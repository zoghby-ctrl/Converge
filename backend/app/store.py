"""Small SQLite repository. Every replay step commits a complete revision atomically."""
import json
import os
import sqlite3
from contextlib import contextmanager, nullcontext
from pathlib import Path
from threading import RLock

from .models import Dataset, Incident, Signal

ROOT = Path(__file__).resolve().parents[2]


def default_path():
    runtime_dir = os.environ.get("CONVERGE_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir).expanduser() / "converge.sqlite3"
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local"))) / "Converge" / "runtime" / "converge.sqlite3"


class Store:
    backend = "sqlite"

    def __new__(cls, path=None, *, namespace="replay"):
        if cls is Store and path is None:
            url = os.environ.get("DATABASE_URL", "").strip()
            if url:
                from .postgres_store import PostgresStore
                return object.__new__(PostgresStore)
            if os.environ.get("VERCEL"):
                raise ValueError("DATABASE_URL is required on Vercel")
        return object.__new__(cls)

    def __init__(self, path=None, *, namespace="replay"):
        self.lock = RLock()
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id TEXT PRIMARY KEY, title TEXT NOT NULL, step INTEGER NOT NULL,
                clock TEXT, fixture_json TEXT NOT NULL, excluded_json TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS road_contexts (
                dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
                road_context_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(dataset_id, road_context_id));
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
                source_family TEXT NOT NULL, source_record_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                observed_at TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(dataset_id, idempotency_key), UNIQUE(dataset_id, source_family, source_record_id));
            CREATE INDEX IF NOT EXISTS signals_dataset_time ON signals(dataset_id, observed_at);
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY, signal_id TEXT NOT NULL REFERENCES signals(signal_id) ON DELETE CASCADE,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
                revision INTEGER NOT NULL, active INTEGER NOT NULL, review_state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS incident_revisions (
                incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
                revision INTEGER NOT NULL, previous_revision INTEGER, snapshot TEXT NOT NULL,
                PRIMARY KEY(incident_id, revision));
            CREATE TABLE IF NOT EXISTS incident_members (
                incident_id TEXT NOT NULL, revision INTEGER NOT NULL,
                signal_id TEXT NOT NULL REFERENCES signals(signal_id), capture_group_id TEXT NOT NULL,
                reasons TEXT NOT NULL,
                PRIMARY KEY(incident_id, revision, signal_id),
                FOREIGN KEY(incident_id, revision) REFERENCES incident_revisions(incident_id, revision) ON DELETE CASCADE);
            """)

    def live_store(self):
        return Store(self.path.with_name(self.path.stem + '-text.sqlite3'))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def state(self):
        with self.connection() as db:
            row = db.execute("SELECT * FROM datasets LIMIT 1").fetchone()
            return dict(row) if row else None

    def reset(self, dataset: Dataset):
        with self.connection() as db:
            # Only this dedicated demo database is reset; no operational import surface exists.
            db.execute("DELETE FROM incident_members")
            db.execute("DELETE FROM datasets")
            db.execute("INSERT INTO datasets(dataset_id,title,step,fixture_json) VALUES(?,?,0,?)",
                       (dataset.dataset_id, dataset.title, dataset.model_dump_json()))
            db.executemany("INSERT INTO road_contexts VALUES(?,?,?)",
                           [(dataset.dataset_id, r.road_context_id, r.model_dump_json()) for r in dataset.roads])

    def incidents(self, active_only=True):
        with self.connection() as db:
            rows = db.execute("""SELECT r.snapshot, i.active FROM incidents i JOIN incident_revisions r
                  ON i.incident_id=r.incident_id AND i.revision=r.revision""" +
                  (" WHERE i.active=1" if active_only else "")).fetchall()
        items = [Incident.model_validate_json(r["snapshot"]).model_copy(update={"active": bool(r["active"])}) for r in rows]
        return sorted(items, key=lambda i: (i.status != "candidate", not i.trace["urgent_human_review"],
                                            -i.risk.risk_min, -i.last_observed_at.timestamp(), i.incident_id))

    def get_signal(self, signal_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
            return Signal.model_validate_json(row[0]) if row else None

    def commit_step(self, dataset, clock, step, incidents, excluded, signals, db_connection=None):
        with (nullcontext(db_connection) if db_connection is not None else self.connection()) as db:
            previous = [Incident.model_validate_json(r[0]) for r in db.execute("""SELECT r.snapshot
                        FROM incidents i JOIN incident_revisions r ON i.incident_id=r.incident_id AND i.revision=r.revision
                        WHERE i.active=1""")]
            for s in signals:
                existing = db.execute("SELECT signal_id FROM signals WHERE dataset_id=? AND idempotency_key=?",
                                      (dataset.dataset_id, s.idempotency_key)).fetchone()
                if existing and existing[0] != s.signal_id:
                    raise ValueError("Idempotency key belongs to another signal")
                db.execute("""INSERT INTO signals VALUES(?,?,?,?,?,?,?) ON CONFLICT(signal_id) DO UPDATE SET payload=excluded.payload""",
                           (s.signal_id, s.dataset_id, s.source_family, s.source_record_id, s.idempotency_key,
                            s.observed_at.isoformat(), s.model_dump_json()))
                for e in s.evidence:
                    db.execute("INSERT INTO evidence VALUES(?,?,?) ON CONFLICT(evidence_id) DO NOTHING",
                               (e.evidence_id, s.signal_id, e.model_dump_json()))
            # Stable one-to-one matching by greatest capture Jaccard overlap.
            matches = []
            for index, item in enumerate(incidents):
                current = {g.capture_group_id for g in item.capture_groups}
                for old in previous:
                    old_set = {g.capture_group_id for g in old.capture_groups}
                    overlap = len(current & old_set) / len(current | old_set)
                    if overlap >= 0.5:
                        matches.append((-overlap, old.incident_id, index, old))
            used_new, used_old = set(), set()
            for _, _, index, old in sorted(matches, key=lambda m: (m[0], m[1], m[2])):
                if index in used_new or old.incident_id in used_old:
                    continue
                item = incidents[index]
                item.incident_id, item.revision = old.incident_id, old.revision + 1
                if {g.capture_group_id for g in item.capture_groups} == {g.capture_group_id for g in old.capture_groups}:
                    item.review_state = old.review_state
                item.trace["previous_incident_ids"] = [old.incident_id]
                used_new.add(index)
                used_old.add(old.incident_id)
            db.execute("UPDATE incidents SET active=0")
            for index, item in enumerate(incidents):
                if index not in used_new:
                    collision = db.execute("SELECT 1 FROM incidents WHERE incident_id=?", (item.incident_id,)).fetchone()
                    if collision:
                        item.incident_id += f"-step{step}"
                    item.trace["previous_incident_ids"] = [old.incident_id for old in previous if
                        {g.capture_group_id for g in old.capture_groups} & {g.capture_group_id for g in item.capture_groups}]
                db.execute("""INSERT INTO incidents VALUES(?,?,?,?,?) ON CONFLICT(incident_id) DO UPDATE
                           SET revision=excluded.revision,active=1,review_state=excluded.review_state""",
                           (item.incident_id, dataset.dataset_id, item.revision, 1, item.review_state.value))
                db.execute("INSERT INTO incident_revisions VALUES(?,?,?,?)", (item.incident_id, item.revision,
                           item.revision - 1 if item.revision > 1 else None, item.model_dump_json()))
                for m in item.trace["membership_reasons"]:
                    db.execute("INSERT INTO incident_members VALUES(?,?,?,?,?)", (item.incident_id, item.revision,
                               m["signal_id"], m["capture_group_id"], json.dumps(m)))
            db.execute("UPDATE datasets SET clock=?,step=?,excluded_json=? WHERE dataset_id=?",
                       (clock.isoformat(), step, json.dumps(excluded), dataset.dataset_id))
