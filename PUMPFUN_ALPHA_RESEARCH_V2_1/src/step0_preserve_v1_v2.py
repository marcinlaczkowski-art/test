"""
STEP 0 (V2.1): Verify and preserve both V1 (`PUMPFUN_ALPHA_RESEARCH`) and V2 (`PUMPFUN_ALPHA_RESEARCH_V2`)
without modifying or deleting a single file. Generates cryptographic SHA-256 version manifest.
"""
import hashlib
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

V1_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH")
V2_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH_V2")
V2_1_DIR = Path(r"C:\Users\annal\.gemini\antigravity\scratch\PUMPFUN_ALPHA_RESEARCH_V2_1")

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def scan_dir_deliverables(root: Path) -> list:
    entries = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            # Hash all deliverables, code, tests, logs, xlsx, csv, md, html, and model files
            if not rel.startswith("cache/candles/") and not rel.startswith("cache/trades/") and not rel.startswith("cache/raw/"):
                entries.append({
                    "relative_path": rel,
                    "size_bytes": p.stat().st_size,
                    "sha256": sha256_file(p),
                })
    return entries

def main():
    v1_entries = scan_dir_deliverables(V1_DIR)
    v2_entries = scan_dir_deliverables(V2_DIR)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "v1_root": str(V1_DIR),
        "v2_root": str(V2_DIR),
        "v2_1_root": str(V2_1_DIR),
        "v1_hashed_deliverables_count": len(v1_entries),
        "v2_hashed_deliverables_count": len(v2_entries),
        "v1_files": v1_entries,
        "v2_files": v2_entries,
    }
    out_p = V2_1_DIR / "VERSION_MANIFEST_V1_V2_SHA256.json"
    out_p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Saved {out_p}: V1={len(v1_entries)} deliverables, V2={len(v2_entries)} deliverables.")

    # Copy frozen V1 and V2 model specs into V2.1 cache for head-to-head comparison
    models_cache = V2_1_DIR / "cache" / "frozen_baselines"
    models_cache.mkdir(parents=True, exist_ok=True)
    shutil.copy2(V2_DIR / "cache" / "v1_frozen_model.json", models_cache / "v1_frozen_model.json")
    shutil.copy2(V2_DIR / "cache" / "models" / "v2_frozen_model.json", models_cache / "v2_frozen_model.json")
    print("Copied frozen V1 and V2 model specifications into V2.1 cache/frozen_baselines/.")

if __name__ == "__main__":
    main()
