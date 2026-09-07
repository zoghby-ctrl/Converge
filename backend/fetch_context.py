"""Explicit provider acquisition, separate from offline app execution.

Fetches only the two fixed demo requests, with time/size bounds. Writes an isolated
new directory; never overwrites the locked bundle. No credentials or AI calls.
"""
import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .app.context import OSM_URL, WEATHER_URL


def fetch_snapshot(output: Path, client=None):
    output.mkdir(parents=True, exist_ok=False)
    info = {}
    with (httpx.Client(timeout=20, follow_redirects=False) if client is None else client) as session:
        for key, name, provider, product, url, limit in (
            ("roads", "osm-map.xml.gz", "OpenStreetMap", "OSM API 0.6 bounded map", OSM_URL, 10_000_000),
            ("weather", "open-meteo-era5.json", "Open-Meteo", "ERA5", WEATHER_URL, 100_000)):
            with session.stream("GET", url) as response:
                response.raise_for_status()
                raw = bytearray()
                for block in response.iter_bytes():
                    raw.extend(block)
                    if len(raw) > limit:
                        raise ValueError("Provider response exceeds bounded snapshot size")
            acquired = datetime.now(timezone.utc).isoformat()
            raw = bytes(raw)
            (output / name).write_bytes(gzip.compress(raw, mtime=0) if name.endswith(".gz") else raw)
            source = {"provider": provider, "product": product, "request_url": url, "acquired_at": acquired,
                "raw_ref": name, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "notes": "Authentic provider bytes. Acquisition is not historical as-issued availability."}
            if key == "weather":
                data = json.loads(raw)
                source.update(grid_center=[data["longitude"], data["latitude"]], resolution_degrees=0.25)
            info[key] = {"raw_ref": name, "raw_sha256": source["raw_sha256"], "source": source}
    (output / "manifest.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New acquisition directory; existing paths are refused")
    args = parser.parse_args()
    try:
        fetch_snapshot(args.output)
    except (httpx.HTTPError, ValueError, OSError, KeyError):
        raise SystemExit("Context acquisition failed; locked offline bundle was not changed. Review/remove the partial output before retrying.") from None
    print("Provider snapshots acquired. Review before replacing the offline context bundle.")
