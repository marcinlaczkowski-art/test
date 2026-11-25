"""
STEP 0 (V2): Secure and freeze PUMPFUN_ALPHA_RESEARCH (V1) without modifying a single file.
1. Generates cryptographic SHA-256 manifest of all V1 deliverables, scripts, and data (`V1_MANIFEST_SHA256.json`).
2. Copies frozen V1 model weights & scaler metadata into `PUMPFUN_ALPHA_RESEARCH_V2/cache/v1_frozen_model.json`.
3. Probes `frontend-api-v3.pump.fun` chronological `created_timestamp` pagination depth for P0 dataset rebuild.
"""
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

V1_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH")
V2_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH_V2")
V2_CACHE = V2_DIR / "cache"
V2_CACHE.mkdir(parents=True, exist_ok=True)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    manifest_entries = []
    # Hash all top-level files, src/, dashboard/, and summary cache files in V1
    # (also count raw cache files without re-hashing 2,000 tiny cache JSONs individually if huge, or hash all!)
    all_v1_files = sorted([p for p in V1_DIR.rglob("*") if p.is_file()])
    print(f"Scanning {len(all_v1_files)} files in V1 ({V1_DIR})...")

    for p in all_v1_files:
        rel = p.relative_to(V1_DIR).as_posix()
        st = p.stat()
        manifest_entries.append({
            "relative_path": rel,
            "size_bytes": st.st_size,
            "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "sha256": sha256_file(p),
        })

    manifest = {
        "v1_directory": str(V1_DIR),
        "manifest_created_utc": datetime.now(timezone.utc).isoformat(),
        "total_files": len(manifest_entries),
        "total_bytes": sum(x["size_bytes"] for x in manifest_entries),
        "files": manifest_entries,
    }

    manifest_path = V2_DIR / "V1_MANIFEST_SHA256.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Saved V1 SHA-256 manifest: {manifest_path} ({len(manifest_entries)} files, {manifest['total_bytes']:,} bytes)")

    # Freeze V1 model weights & summary for head-to-head comparison in V2
    v1_sum_path = V1_DIR / "cache" / "analytics_summary.json"
    if v1_sum_path.exists():
        v1_sum = json.loads(v1_sum_path.read_text(encoding="utf-8"))
        frozen_v1 = {
            "model_name": "Pump_Potential_V1_Frozen",
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_sha256": sha256_file(v1_sum_path),
            "v1_weights": v1_sum.get("model_weights", {}),
            "v1_universe_counts": v1_sum.get("universe_counts", {}),
            "v1_backtest_benchmarks": v1_sum.get("backtest_benchmarks_walk_forward", []),
        }
        (V2_CACHE / "v1_frozen_model.json").write_text(json.dumps(frozen_v1, indent=2), encoding="utf-8")
        print("Saved frozen V1 model specification to cache/v1_frozen_model.json")

    # Probe chronological span of created_timestamp on frontend-api-v3.pump.fun
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://pump.fun"}
    for off in [0, 500, 1000, 1450, 2000]:
        url = f"https://frontend-api-v3.pump.fun/coins?offset={off}&limit=5&sort=created_timestamp&order=DESC&includeNsfw=true"
        try:
            req = urllib.request.Request(url, headers=headers)
            data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
            if data:
                ts0 = data[0].get("created_timestamp", 0)
                dt0 = datetime.fromtimestamp(ts0 / 1000.0, tz=timezone.utc).isoformat() if ts0 else "N/A"
                print(f"offset={off:4d} -> count={len(data)}, first_created_utc={dt0}")
            else:
                print(f"offset={off:4d} -> empty []")
        except Exception as e:
            print(f"offset={off:4d} -> ERR {e}")

if __name__ == "__main__":
    main()
