#!/usr/bin/env python3
"""Fetch comments for top r/DeepSeek posts from Arctic Shift."""
import json, time, urllib.request, urllib.parse, sys, os, random

BASE = "https://arctic-shift.photon-reddit.com/api/comments/search"
ROOT = os.environ.get("DSH_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "comments")
UA = "Mozilla/5.0 (research script; sentiment analysis)"
HEADERS = {"User-Agent": UA}

with open(os.path.join(ROOT, "posts", "all_posts.json")) as f:
    posts = json.load(f)

by_c = sorted(posts, key=lambda p: p["num_comments"], reverse=True)[:25]
by_s = sorted(posts, key=lambda p: p["score"], reverse=True)[:15]
chosen = {p["id"]: p for p in by_c + by_s}

# mid-tier random sample for breadth
existing_top = set(chosen)
cands = [p for p in posts if p["id"] not in existing_top and 20 <= p["score"] <= 150 and p["num_comments"] >= 8]
random.seed(42)
sample = random.sample(cands, min(40, len(cands)))
for p in sample:
    chosen[p["id"]] = p

os.makedirs(OUT, exist_ok=True)

def fetch(pid):
    params = {"link_id": pid, "limit": 100, "sort": "desc"}
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

ok = 0
for pid in chosen:
    path = os.path.join(OUT, f"{pid}.json")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        ok += 1
        continue
    for attempt in range(3):
        try:
            data = fetch(pid)
            with open(path, "w") as f:
                json.dump(data.get("data", []), f)
            ok += 1
            break
        except Exception as e:
            print(f"{pid} attempt {attempt}: {e}", file=sys.stderr)
            time.sleep(3 + attempt * 2)
    time.sleep(0.8)

print(f"comments fetched/kept: {ok}/{len(chosen)}", file=sys.stderr)
