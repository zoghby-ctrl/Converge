"""Image upload jobs and their boundary to the existing observation engine.

The module deliberately owns image bytes and image extraction metadata only.  It
does not calculate risk, incident membership, or model decisions.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .engine import run_engine
from pydantic import Field

from .models import Contract, Dataset, ImageObservationMetadata, Provenance, RoadContext, Signal
from .perception import ProcessingError, now
from .image_contract import (
    ImageExtraction, admission_warnings, evidence_from as image_evidence_from,
)
from .image_ingestion import ImageIngestionError, MAX_UPLOAD_BYTES, normalize_image
from .image_contract import PROMPT_VERSION, SCHEMA_VERSION, TASK_VERSION


class ImageCorrection(Contract):
    extraction: ImageExtraction
    reviewer: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=400)
    expected_revision: int = Field(ge=0)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def signal_for_client(signal):
    """Return a Signal without disclosing its server-side filesystem path."""
    if signal is None:
        return None
    payload = signal.model_dump(mode="json", exclude={"image_path"})
    if signal.source_family == "image" and signal.image_path:
        payload["image_url"] = f"/api/v1/signals/{signal.signal_id}/image"
    return payload


def _hamming(left: str, right: str) -> int | None:
    if not left or not right or len(left) != len(right):
        return None
    try:
        return sum(a != b for a, b in zip(bin(int(left, 16))[2:].zfill(len(left) * 4),
                                          bin(int(right, 16))[2:].zfill(len(right) * 4)))
    except ValueError:
        return None


class ImageObservations:
    def __init__(self, observations):
        self.observations = observations
        self.store = observations.store
        self.perception = None
        try:
            from .image_perception import ImagePerception
            self.perception = ImagePerception(self.store, observations.perception.settings,
                                              observations.perception.client)
        except ImportError:  # adapter may be installed after the app module is loaded
            self.perception = None
        from .upload_storage import UploadStorage
        self.storage = UploadStorage.from_env(self.store)
        if self.store.backend == "sqlite":
            self._initialize_sqlite()

    def _initialize_sqlite(self):
        with self.store.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS image_jobs(
                signal_id TEXT PRIMARY KEY, original_json TEXT NOT NULL,
                status TEXT NOT NULL, error_code TEXT, revision INTEGER NOT NULL DEFAULT 0,
                linked_text_signal_id TEXT, raw_hash TEXT NOT NULL, stored_path TEXT NOT NULL,
                normalization_json TEXT NOT NULL, perceptual_hash TEXT);
            """)
            # Shared revision table is intentionally used for both modalities.
            db.execute("UPDATE image_jobs SET status='needs_review',error_code='interrupted_restart' "
                       "WHERE status IN ('pending','analyzing')")

    def _dataset(self):
        return self.observations.dataset()

    def _metadata(self, payload):
        if isinstance(payload, ImageObservationMetadata):
            return payload
        try:
            return ImageObservationMetadata.model_validate(payload)
        except Exception as error:
            raise HTTPException(422, "Invalid image metadata") from error

    def _normalise(self, content: bytes):
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "image_too_large")
        try:
            result = normalize_image(content, self.store.path.parent)
        except ImageIngestionError as error:
            raise HTTPException(413 if error.code == "image_too_large" else 422, error.code) from None
        except (ValueError, OSError):
            raise HTTPException(422, "invalid_image") from None
        result = _dump(result)
        if not isinstance(result, dict) or not result.get("raw_hash") or not result.get("stored_path"):
            raise HTTPException(422, "Image normalizer returned incomplete metadata")
        return result

    @staticmethod
    def _stored_path(value, root):
        candidate = Path(str(value))
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve(strict=False)
            base = root.resolve(strict=False)
            image_base = (base / "images").resolve(strict=False)
            if os.path.commonpath([str(resolved), str(image_base)]) != str(image_base):
                raise ValueError
        except (ValueError, OSError):
            raise HTTPException(422, "Invalid image storage reference") from None
        return resolved

    def _near_duplicate(self, perceptual_hash):
        if not perceptual_hash:
            return None
        with self.store.connection() as db:
            rows = db.execute("SELECT signal_id,perceptual_hash FROM image_jobs WHERE perceptual_hash IS NOT NULL").fetchall()
        for row in rows:
            distance = _hamming(perceptual_hash, row["perceptual_hash"])
            if distance is not None and distance <= 4:
                return row["signal_id"]
        return None

    def submit(self, payload, content: bytes):
        metadata = self._metadata(payload)
        metadata_json = metadata.model_dump(mode="json")
        raw_hash = _sha256(content)
        # Check idempotency before decoding or writing files. A reused key must
        # represent the same bytes and the same operator-owned metadata.
        with self.observations.lock:
            with self.store.connection() as db:
                for row in db.execute("SELECT signal_id,original_json,linked_text_signal_id FROM image_jobs"):
                    previous = json.loads(row["original_json"])
                    if previous.get("idempotency_key") != metadata.idempotency_key:
                        continue
                    previous_metadata = {key: previous.get(key) for key in ImageObservationMetadata.model_fields}
                    if previous.get("raw_hash") != raw_hash or previous_metadata != metadata_json:
                        raise HTTPException(409, "Idempotency key has different input")
                    return row["signal_id"], False, row["linked_text_signal_id"]
        normalized = self._normalise(content)
        raw_hash = str(normalized.get("raw_hash") or raw_hash)
        path = self._stored_path(normalized["stored_path"], self.store.path.parent)
        normalized["stored_path"] = str(path)
        if self.storage:
            self.storage.persist(normalized)
        image_key = "image:" + metadata.idempotency_key
        with self.observations.lock:
            dataset = self._dataset()
            with self.store.connection() as db:
                for row in db.execute("SELECT signal_id,original_json,linked_text_signal_id FROM image_jobs"):
                    previous = json.loads(row["original_json"])
                    if previous.get("idempotency_key") == metadata.idempotency_key:
                        previous_metadata = {key: previous.get(key) for key in ImageObservationMetadata.model_fields}
                        if previous.get("raw_hash") != raw_hash or previous_metadata != metadata_json:
                            raise HTTPException(409, "Idempotency key has different input")
                        return row["signal_id"], False, row["linked_text_signal_id"]
                if len(dataset.signals) >= 500:
                    raise HTTPException(409, "Local observation capacity (500) reached")
                sid = "image-" + uuid4().hex
                received = datetime.now(timezone.utc)
                near = self._near_duplicate(normalized.get("perceptual_hash"))
                provenance = Provenance(
                    content_origin=metadata.content_origin,
                    placement_origin=metadata.placement_origin,
                    time_origin=metadata.time_origin,
                    source_ref=metadata.source_ref or sid,
                    author_category="operator image",
                    license=metadata.license,
                    annotation_method="ai_image",
                    reviewer=metadata.operator)
                signal = Signal(signal_id=sid, dataset_id=dataset.dataset_id,
                    idempotency_key=image_key, source_record_id=sid, source_family="image",
                    capture_group_id=metadata.capture_group_id, copy_lineage=metadata.copy_lineage,
                    independence="uncertain" if near else metadata.independence,
                    text=None, image_path=str(path), exact_image_hash=raw_hash,
                    lat=metadata.lat, lon=metadata.lon, location_accuracy_m=metadata.location_accuracy_m,
                    location_method="submission coordinates", road_context_id=metadata.road_context_id,
                    observed_at=metadata.observed_at, received_at=received, available_at=received,
                    provenance=provenance, evidence=[])
                from .context import attach_operator_road
                sourced = attach_operator_road(dataset, signal)
                if signal.road_context_id is not None and not sourced and not any(r.road_context_id == metadata.road_context_id for r in dataset.roads):
                    dataset.roads.append(RoadContext(road_context_id=metadata.road_context_id,
                        name=metadata.road_context_id, road_class=None,
                        coordinates=[(metadata.lon, metadata.lat), (metadata.lon, metadata.lat)],
                        provenance=provenance.model_copy(update={"annotation_method": "manual_structured"})))
                original = metadata_json
                original.update(kind="image", image_url=f"/api/v1/signals/{sid}/image", raw_hash=raw_hash,
                                normalization={k: v for k, v in normalized.items()
                                               if k not in {"stored_path", "preserved_path"}},
                                duplicate_review_required=bool(near), near_duplicate_of=near)
                linked_text = None
                if metadata.text and metadata.text.strip():
                    from .text_contract import NewObservation
                    text_payload = {key: value for key, value in metadata.model_dump(mode="json").items()
                                    if key in {"text", "lat", "lon", "observed_at", "location_accuracy_m",
                                               "road_context_id", "capture_group_id", "independence",
                                               "copy_lineage", "operator", "idempotency_key", "content_origin"}}
                    paired_key = hashlib.sha256(
                        f"paired-text:{metadata.idempotency_key}".encode("utf-8")).hexdigest()
                    text_payload.update(text=metadata.text, idempotency_key=paired_key,
                                        content_origin="synthetic" if metadata.content_origin == "synthetic" else "collected")
                    text_req = NewObservation.model_validate(text_payload)
                    linked_text, _ = self.observations._submit_text_locked(text_req, db, dataset,
                                                                            link_image=sid)
                    original["linked_text_signal_id"] = linked_text
                db.execute("INSERT INTO image_jobs VALUES(?,?,?,?,?,?,?,?,?,?)", (sid, json.dumps(original),
                    "pending", None, 0, linked_text, raw_hash, str(path), json.dumps(normalized),
                    normalized.get("perceptual_hash")))
                dataset.signals.append(signal)
                db.execute("UPDATE datasets SET fixture_json=?", (dataset.model_dump_json(),))
                db.execute("INSERT INTO signals VALUES(?,?,?,?,?,?,?)", (sid, dataset.dataset_id, "image", sid,
                    image_key, metadata.observed_at.isoformat(), signal.model_dump_json()))
                return sid, True, linked_text

    def get(self, sid):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM image_jobs WHERE signal_id=?", (sid,)).fetchone()
            if not row:
                return None
            revisions = [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM extraction_revisions WHERE signal_id=? ORDER BY revision", (sid,))]
        for revision in revisions:
            image_metadata = revision.get("image_metadata")
            if isinstance(image_metadata, dict):
                image_metadata.pop("stored_path", None)
                image_metadata.pop("preserved_path", None)
        incidents = [i for i in self.store.incidents() if sid in i.signal_ids]
        state = self.store.state()
        exclusions = [e for e in json.loads(state["excluded_json"]) if e["signal_id"] == sid]
        original = json.loads(row["original_json"])
        if isinstance(original.get("normalization"), dict):
            original["normalization"].pop("stored_path", None)
            original["normalization"].pop("preserved_path", None)
        return {"signal_id": sid, "kind": "image", "original": original,
            "status": row["status"], "error_code": row["error_code"], "revision": row["revision"],
            "revisions": revisions, "latest": revisions[-1] if revisions else None,
            "incidents": incidents, "excluded": exclusions,
            "linked_text_signal_id": row["linked_text_signal_id"],
            "disposition": "candidate" if any(i.status == "candidate" for i in incidents) else
                "watch" if incidents else "not_admitted"}

    def image_path(self, sid):
        with self.store.connection() as db:
            row = db.execute("SELECT stored_path FROM image_jobs WHERE signal_id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "Image signal not found")
        path = self._stored_path(row[0], self.store.path.parent)
        if self.storage:
            self.storage.restore(path)
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not path.is_file():
            raise HTTPException(404, "Image file not found")
        return path

    def process(self, sid, deeper=False):
        with self.observations.lock:
            job = self.get(sid)
            if not job:
                return
            with self.store.connection() as db:
                db.execute("UPDATE image_jobs SET status='analyzing',error_code=NULL WHERE signal_id=?", (sid,))
                row = db.execute("SELECT stored_path,normalization_json FROM image_jobs WHERE signal_id=?", (sid,)).fetchone()
            if self.perception is None:
                try:
                    from .image_perception import ImagePerception
                    self.perception = ImagePerception(self.store, self.observations.perception.settings,
                                                      self.observations.perception.client)
                except ImportError:
                    self._fail(sid, "image_adapter_unavailable")
                    return
        try:
            metadata = json.loads(row["normalization_json"])
            if self.storage:
                self.storage.restore(Path(metadata["stored_path"]))
            result = self.perception.extract(metadata, deeper=deeper)
            with self.observations.lock:
                self.accept(sid, result)
        except ProcessingError as error:
            self._fail(sid, error.code, error.state)
        except Exception:
            # Keep provider responses and image contents out of logs and API errors.
            self._fail(sid, "local_processing_error")

    def _fail(self, sid, code, state="failed"):
        with self.store.connection() as db:
            db.execute("UPDATE image_jobs SET status=?,error_code=? WHERE signal_id=?", (state, code, sid))

    def accept(self, sid, result):
        job = self.get(sid)
        payload = dict(result) if isinstance(result, dict) else {"extraction": result}
        extraction = ImageExtraction.model_validate(payload.get("extraction", payload))
        revision = job["revision"] + 1
        recorded = {**payload, "extraction": extraction.model_dump(mode="json"), "signal_id": sid, "revision": revision,
                    "recorded_at": now(), "task_version": payload.get("task_version", TASK_VERSION),
                    "prompt_version": payload.get("prompt_version", PROMPT_VERSION),
                    "schema_version": payload.get("schema_version", SCHEMA_VERSION)}
        dataset = self._dataset()
        signal = next(s for s in dataset.signals if s.signal_id == sid)
        reviewed = payload.get("source") == "manual"
        warnings = [] if reviewed else admission_warnings(extraction)
        recorded["admission_warnings"] = warnings
        recorded["review_state"] = (
            "needs_review" if warnings or payload.get("review_state") == "needs_review"
            else payload.get("review_state", "unreviewed")
        )
        signal.evidence = image_evidence_from(extraction, sid, revision, reviewed)
        signal.provenance.annotation_method = "human_reviewed" if reviewed else "ai_image"
        if reviewed:
            signal.provenance.reviewer = payload.get("reviewer", signal.provenance.reviewer)
        clock = datetime.now(timezone.utc)
        incidents, excluded, signals = run_engine(dataset, clock)
        step = self.store.state()["step"] + 1
        with self.store.connection() as db:
            db.execute("INSERT INTO extraction_revisions VALUES(?,?,?)", (sid, revision, json.dumps(recorded)))
            db.execute("UPDATE image_jobs SET status=?,error_code=NULL,revision=? WHERE signal_id=?",
                       ("needs_review" if recorded["review_state"] == "needs_review" else "processed", revision, sid))
            db.execute("UPDATE datasets SET fixture_json=?", (dataset.model_dump_json(),))
            self.store.commit_step(dataset, clock, step, incidents, excluded, signals, db_connection=db)

    def review(self, sid, request):
        with self.observations.lock:
            job = self.get(sid)
            self.observations.guard_revision(job, request.expected_revision)
            extraction = ImageExtraction.model_validate(request.extraction)
            self.accept(sid, {"extraction": extraction, "source": "manual", "provider": "human",
                "model": None, "model_identifier": None, "prompt_version": PROMPT_VERSION,
                "schema_version": SCHEMA_VERSION, "task_version": TASK_VERSION, "processed_at": now(),
                "raw_response_reference": None, "fallback_used": False, "fallback_reason": None,
                "review_state": "human_reviewed", "reviewer": request.reviewer,
                "review_reason": request.reason})
            return self.get(sid)
