"""Explicit, bounded image evaluation. Never runs on startup or during pytest."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from backend.app.image_contract import (
    NORMALIZATION_VERSION, PROMPT_VERSION, SCHEMA_VERSION, TASK_VERSION,
    ImageExtraction, admission_warnings, evidence_from,
)
from backend.app.image_ingestion import normalize_image
from backend.app.image_perception import ImagePerception
from backend.app.perception import ProcessingError, digest, now
from backend.app.store import ROOT, Store, default_path

FIELDS = ("standing_water", "visible_surface_damage", "passage_obstruction")
FEATURES = {
    "standing_water": "standing_water",
    "visible_surface_damage": "visible_road_damage",
    "passage_obstruction": "passage_obstruction",
}


def validate_manifest(manifest):
    rows = manifest["images"]
    required = {
        "id", "split", "source_group", "path", "sha256", "source_url", "author",
        "license", "content_origin", "placement_origin", "time_origin", "reference_labels",
    }
    seen_ids = set()
    seen_hashes = set()
    source_splits = {}
    split_counts = {"development": 0, "validation": 0}
    category_counts = {}
    for row in rows:
        missing = required - set(row)
        if missing:
            raise ValueError(f"Manifest row {row.get('id')} lacks {sorted(missing)}")
        if row["id"] in seen_ids or row["sha256"] in seen_hashes:
            raise ValueError(f"Duplicate image identity or content: {row['id']}")
        seen_ids.add(row["id"])
        seen_hashes.add(row["sha256"])
        if row["split"] not in split_counts:
            raise ValueError(f"Invalid split: {row['id']}")
        split_counts[row["split"]] += 1
        category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
        source_splits.setdefault(row["source_group"], set()).add(row["split"])
        if len(source_splits[row["source_group"]]) > 1:
            raise ValueError(f"Source group crosses splits: {row['source_group']}")
        if not all(str(row[field]).strip() for field in ("source_group", "source_url", "author", "license")):
            raise ValueError(f"Incomplete source provenance: {row['id']}")
        if row["content_origin"] != "public_source" or row["placement_origin"] != "simulated" or row["time_origin"] != "simulated":
            raise ValueError(f"Unexpected content/placement/time provenance: {row['id']}")
        if set(row["reference_labels"]) != set(FIELDS):
            raise ValueError(f"Incomplete reference labels: {row['id']}")
        path = ROOT / row["path"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError(f"Fixture hash mismatch: {row['id']}")
        with Image.open(path) as image:
            if image.format not in {"JPEG", "PNG"} or max(image.size) > 1280:
                raise ValueError(f"Unexpected fixture format or size: {row['id']}")
            if image.getexif():
                raise ValueError(f"Fixture retains EXIF metadata: {row['id']}")
    return {"total": len(rows), "split_counts": split_counts,
            "category_counts": category_counts, "unique_hashes": len(seen_hashes),
            "independent_human_label_count": sum(bool(row.get("human_labels")) for row in rows)}


def _safe_result(item):
    payload = dict(item)
    metadata = dict(payload.get("image_metadata") or {})
    metadata.pop("stored_path", None)
    metadata.pop("preserved_path", None)
    if metadata:
        payload["image_metadata"] = metadata
    return payload


def _rates(counts):
    counts["precision"] = (
        counts["tp"] / (counts["tp"] + counts["fp"])
        if counts["tp"] + counts["fp"] else None
    )
    counts["recall"] = (
        counts["tp"] / (counts["tp"] + counts["fn"])
        if counts["tp"] + counts["fn"] else None
    )


def evaluate(split, live=False, limit=None, ids=None):
    manifest_path = ROOT / "fixtures" / "images" / "manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    corpus_validation = validate_manifest(manifest)
    examples = [row for row in manifest["images"] if row["split"] == split]
    if ids:
        wanted = set(ids)
        examples = [row for row in examples if row["id"] in wanted]
        missing = wanted - {row["id"] for row in examples}
        if missing:
            raise ValueError(f"IDs are absent from split {split}: {sorted(missing)}")
    if limit:
        examples = examples[:limit]

    store_path = default_path().with_name(default_path().stem + "-text.sqlite3")
    perception = ImagePerception(Store(store_path))
    before = perception.summary()
    metrics = {field: {"tp": 0, "fp": 0, "fn": 0} for field in FIELDS}
    admitted_metrics = {field: {"tp": 0, "fp": 0, "fn": 0} for field in FIELDS}
    reference_counts = {field: {state: 0 for state in
                        ("present", "absent", "uncertain", "not_assessable")}
                        for field in FIELDS}
    predicted_counts = {field: {state: 0 for state in
                        ("present", "absent", "uncertain", "not_assessable")}
                        for field in FIELDS}
    exact_state_correct = field_abstentions = unsupported = failures = 0
    completed_extractions = unusable = cache_hits = fallback_calls = review_required = 0
    results = []

    for row in examples:
        path = ROOT / row["path"]
        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != row["sha256"]:
            raise ValueError(f"Fixture hash mismatch: {row['id']}")
        metadata = normalize_image(raw, store_path.parent)
        expected = row["reference_labels"]
        for field in FIELDS:
            reference_counts[field][expected[field]] += 1
        try:
            if not live:
                with perception.store.connection() as db:
                    found = db.execute(
                        "SELECT 1 FROM extraction_cache WHERE cache_key=?",
                        (perception.cache_key(metadata, perception.settings.primary),),
                    ).fetchone()
                if not found:
                    raise ProcessingError("not_cached", "needs_review")
            item = perception.extract(metadata)
            extraction = ImageExtraction.model_validate(item["extraction"])
            completed_extractions += 1
            cache_hits += item["source"] == "cached"
            fallback_calls += item["fallback_used"]
            unusable += extraction.image_quality == "unusable"
            admitted = [e.model_dump(mode="json") for e in evidence_from(
                extraction, f"eval-{row['id']}", 1)]
            admitted_positive_features = {
                item["feature"] for item in admitted if item["state"] == "positive"
            }
            warnings = admission_warnings(extraction)
            review_required += bool(warnings) or item["review_state"] == "needs_review"
            row_unsupported = 0
            row_admitted_unsupported = 0
            row_exact = 0
            for field in FIELDS:
                predicted = getattr(extraction, field)
                truth = expected[field]
                predicted_counts[field][predicted] += 1
                positive = predicted == "present"
                truth_positive = truth == "present"
                metrics[field]["tp"] += int(positive and truth_positive)
                metrics[field]["fp"] += int(positive and not truth_positive)
                metrics[field]["fn"] += int(not positive and truth_positive)
                admitted_positive = FEATURES[field] in admitted_positive_features
                admitted_metrics[field]["tp"] += int(admitted_positive and truth_positive)
                admitted_metrics[field]["fp"] += int(admitted_positive and not truth_positive)
                admitted_metrics[field]["fn"] += int(not admitted_positive and truth_positive)
                row_unsupported += int(positive and not truth_positive)
                row_admitted_unsupported += int(admitted_positive and not truth_positive)
                row_exact += int(predicted == truth)
                field_abstentions += int(predicted in ("uncertain", "not_assessable"))
            unsupported += row_unsupported
            exact_state_correct += row_exact
            results.append({
                "id": row["id"], "path": row["path"], "sha256": actual_hash,
                "expected": expected, "result": _safe_result(item),
                "admitted_evidence": admitted, "admission_warnings": warnings,
                "unsupported_positive_count": row_unsupported,
                "admitted_unsupported_positive_count": row_admitted_unsupported,
                "exact_state_correct": row_exact,
            })
            print(json.dumps({
                "id": row["id"], "source": item["source"],
                "fallback": item["fallback_used"], "review": item["review_state"],
                "quality": extraction.image_quality, "unsupported": row_unsupported,
                "exact_states": row_exact,
            }), flush=True)
        except ProcessingError as error:
            failures += 1
            for field in FIELDS:
                metrics[field]["fn"] += int(expected[field] == "present")
                admitted_metrics[field]["fn"] += int(expected[field] == "present")
            results.append({"id": row["id"], "path": row["path"], "error": error.code})
            print(json.dumps({"id": row["id"], "error": error.code}), flush=True)
            if error.code in {
                "invalid_api_key", "model_unavailable", "development_usage_limit",
                "api_configuration_rejected",
            }:
                break

    for counts in metrics.values():
        _rates(counts)
    for counts in admitted_metrics.values():
        _rates(counts)
    after = perception.summary()
    delta_keys = (
        "total_api_requests", "primary_calls", "fallback_calls", "input_tokens",
        "output_tokens", "cache_hits", "schema_failure_count", "estimated_spend_usd",
        "image_api_requests", "image_primary_calls", "image_fallback_calls",
        "image_schema_failure_count", "image_cache_hits",
    )
    usage_delta = {key: (after.get(key) or 0) - (before.get(key) or 0) for key in delta_keys}
    total_fields = len(examples) * len(FIELDS)
    report = {
        "split": split, "timestamp": now(),
        "corpus_hash": digest(manifest_text), "manifest_version": manifest["version"],
        "corpus_validation": corpus_validation,
        "task_version": TASK_VERSION, "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION, "normalization_version": NORMALIZATION_VERSION,
        "reasoning": perception.settings.reasoning, "requested": len(examples),
        "completed_results": len(results), "completed_extractions": completed_extractions,
        "processing_failures": failures, "metrics": metrics,
        "admitted_metrics": admitted_metrics,
        "reference_state_counts": reference_counts, "predicted_state_counts": predicted_counts,
        "exact_state_correct": exact_state_correct, "exact_state_total": total_fields,
        "field_abstentions": field_abstentions, "field_abstention_total": total_fields,
        "field_abstention_rate": field_abstentions / total_fields if total_fields else None,
        "unusable_images": unusable, "unsupported_positive_claims": unsupported,
        "review_required_images": review_required,
        "result_cache_hits": cache_hits, "result_fallbacks": fallback_calls,
        "usage_delta": usage_delta, "results": results,
        "metric_basis": (
            "Present precision/recall uses provisional agent reference labels recorded before "
            "runtime model output; exact-state and abstention counts cover all three target fields."
        ),
        "limitation": (
            "Small convenience sample of licensed public images with simulated placement/time. "
            "No independent human labels or municipal field-accuracy claim."
        ),
    }
    suffix = "-cached" if not live else ""
    output = ROOT / "docs" / f"image-evaluation-{split}{suffix}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"},
                     ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "validation"], default="development")
    parser.add_argument("--live", action="store_true",
                        help="Explicitly permit billed API extraction on cache misses")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    evaluate(args.split, args.live, args.limit, args.ids)
