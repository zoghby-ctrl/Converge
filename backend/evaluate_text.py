"""Explicit, bounded extraction evaluation. Never runs on server startup or pytest."""
import argparse
import json

from backend.app.perception import Perception, ProcessingError, digest, now
from backend.app.store import ROOT, Store, default_path
from backend.app.text_contract import TextExtraction, evidence_from, PROMPT_VERSION, SCHEMA_VERSION


def evaluate(split, live=False, limit=None):
    path = ROOT / "fixtures" / ("text_development.json" if split == "development" else "text_validation_locked.json")
    examples = json.loads(path.read_text(encoding="utf-8"))
    if limit:
        examples = examples[:limit]
    base = default_path()
    p = Perception(Store(base.with_name(base.stem + "-text.sqlite3")))
    before = p.summary()
    results = []
    metrics = {f: dict(tp=0, fp=0, fn=0) for f in ("standing_water", "road_damage", "passage_obstruction")}
    extraction_metrics = {f: dict(tp=0, fp=0, fn=0) for f in metrics}
    negation_errors = unsupported = failures = abstentions = 0
    for row in examples:
        try:
            if not live:
                with p.store.connection() as db:
                    found = db.execute("SELECT 1 FROM extraction_cache WHERE cache_key=?", (p.cache_key(row["text"], p.settings.primary),)).fetchone()
                if not found:
                    raise ProcessingError("not_cached", "needs_review")
            item = p.extract(row["text"])
            x = TextExtraction.model_validate(item["extraction"])
            actual = evidence_from(x, "eval", 1) if item["review_state"] != "needs_review" else []
            admitted = {e.feature for e in actual if e.state == "positive"}
            abstentions += item["review_state"] == "needs_review"
            row_unsupported = 0
            for field, expected, engine in (("standing_water", "water", "standing_water"), ("road_damage", "damage", "visible_road_damage"), ("passage_obstruction", "obstruction", "passage_obstruction")):
                truth = row[expected] == "present" and row.get("temporal") != "historical"
                positive = engine in admitted
                metrics[field]["tp"] += int(truth and positive)
                metrics[field]["fp"] += int(not truth and positive)
                metrics[field]["fn"] += int(truth and not positive)
                extracted_positive = getattr(x, field) == "present" and x.temporal_status not in ("historical", "uncertain") and not (field == "standing_water" and x.temporal_status == "resolved") and any(s.field == field and s.temporal_status == "current" for s in x.evidence_spans)
                extraction_metrics[field]["tp"] += int(truth and extracted_positive)
                extraction_metrics[field]["fp"] += int(not truth and extracted_positive)
                extraction_metrics[field]["fn"] += int(truth and not extracted_positive)
                unsupported_claim = getattr(x, field) == "present" and row[expected] != "present"
                row_unsupported += unsupported_claim
            unsupported += row_unsupported
            negation_errors += int("negation" in row["tags"] and row_unsupported > 0)
            results.append({"id": row["id"], "text": row["text"], "expected": row, "result": item,
                            "admitted_positive_features": sorted(admitted)})
            print(json.dumps({"id": row["id"], "source": item["source"], "fallback": item["fallback_used"],
                "review": item["review_state"], "unsupported": row_unsupported}), flush=True)
        except ProcessingError as error:
            failures += 1
            for field, expected in (("standing_water", "water"), ("road_damage", "damage"), ("passage_obstruction", "obstruction")):
                metrics[field]["fn"] += int(row[expected] == "present" and row.get("temporal") != "historical")
                extraction_metrics[field]["fn"] += int(row[expected] == "present" and row.get("temporal") != "historical")
            results.append({"id": row["id"], "error": error.code})
            print(json.dumps({"id": row["id"], "error": error.code}), flush=True)
            if error.code in ("invalid_api_key", "model_unavailable", "development_usage_limit", "api_configuration_rejected"):
                break
    for counts in list(metrics.values()) + list(extraction_metrics.values()):
        counts["precision"] = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None
        counts["recall"] = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None
    after = p.summary()
    delta = {key: (after[key] or 0) - (before[key] or 0) for key in (
        "total_api_requests", "primary_calls", "fallback_calls", "input_tokens", "output_tokens", "cache_hits",
        "schema_failure_count", "estimated_spend_usd")}
    report = dict(split=split, timestamp=now(), corpus_hash=digest(path.read_text(encoding="utf-8")),
        prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION, reasoning=p.settings.reasoning,
        requested=len(examples), completed=len(results), processing_failures=failures, abstentions=abstentions,
        metrics=metrics, extraction_metrics=extraction_metrics,
        metric_basis="metrics: current positive evidence admission; extraction_metrics: temporally qualified extracted positives before review gate; abstentions count as false negatives",
        negation_errors=negation_errors, unsupported_positive_claims=unsupported, usage_delta=delta, results=results,
        limitation="Authored small-corpus evaluation, not municipal field accuracy; development and validation are separate.")
    output = ROOT / "docs" / ("text-evaluation-" + split + ("-cached" if not live else "") + ".json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "validation"], default="development")
    parser.add_argument("--live", action="store_true", help="Explicitly permit billed API extraction on cache misses")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    evaluate(args.split, args.live, args.limit)
