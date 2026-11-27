#!/usr/bin/env python3
"""Write frozen_manifest.json after the draw (PROTOCOL §4)."""
import hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
HERE = Path(__file__).parent; STUDY = HERE.parent / "variant_study"
sys.path.insert(0, str(HERE)); from pilot_run import FROZEN  # noqa: E402
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "--", *[str(HERE / f) for f in FROZEN], str(STUDY / "run.py"), str(STUDY / "profiles.json")], capture_output=True, text=True, check=True).stdout.strip()
if dirty: sys.exit("REFUSING to freeze: uncommitted frozen files:\n" + dirty)
man = {"commit": commit, "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "sha256": {f: sha(HERE / f) for f in FROZEN}, "harness_sha256": {n: sha(STUDY / n) for n in ("run.py", "profiles.json")}}
(HERE / "frozen_manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
print("frozen at commit", commit[:10], "with", len(man["sha256"]), "files")
