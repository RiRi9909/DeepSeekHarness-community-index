#!/usr/bin/env python3
"""Orchestrator: fetch -> index -> snapshot (called by the DSH host plugin)."""
import os, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--out" else os.environ.get("DSH_DATA_DIR", BASE)
os.makedirs(OUT, exist_ok=True)
env = dict(os.environ, DSH_DATA_DIR=OUT)

STEPS = ["fetch_posts.py", "fetch_comments.py", "sentiment_index.py", "build_snapshot.py"]
for script in STEPS:
    print(f"[pipeline] {script}", flush=True)
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(BASE, script)],
            cwd=OUT, env=env,
            capture_output=True, text=True, timeout=900,
        )
    except subprocess.TimeoutExpired:
        print(f"[pipeline] {script} timed out", file=sys.stderr)
        sys.exit(1)
    if r.returncode != 0:
        print(f"[pipeline] {script} failed:", file=sys.stderr)
        print((r.stderr or r.stdout or "")[-1200:], file=sys.stderr)
        sys.exit(1)
print("[pipeline] done", flush=True)
