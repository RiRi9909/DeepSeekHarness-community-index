#!/usr/bin/env python3
"""Fetch r/DeepSeek posts from Arctic Shift (Pushshift successor mirror)."""
import json, time, urllib.request, urllib.parse, sys, os

BASE = "https://arctic-shift.photon-reddit.com/api/posts/search"
ROOT = os.environ.get("DSH_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "posts")
UA = "Mozilla/5.0 (research script; sentiment analysis)"
HEADERS = {"User-Agent": UA}

DAYS_BACK = int(sys.argv[1]) if len(sys.argv) > 1 else 45
CUTOFF = time.time() - DAYS_BACK * 86400

def fetch(params):
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

os.makedirs(OUT, exist_ok=True)
seen = {}
posts_path = os.path.join(OUT, "all_posts.json")
if os.path.exists(posts_path):
    try:
        for p in json.load(open(posts_path)):
            seen[p["id"]] = p
    except Exception:
        pass
existing_newest = max((p["created_utc"] for p in seen.values()), default=0)
TARGET = max(CUTOFF, existing_newest - 2 * 86400)  # 2-day overlap for updated threads
print(f"existing posts: {len(seen)}, target cutoff: {time.strftime('%Y-%m-%d', time.gmtime(TARGET))}", file=sys.stderr)
cursor = None
batch = 0
_errs = 0
aborted = False
while True:
    params = {"subreddit": "DeepSeek", "limit": 100, "sort": "desc"}
    if cursor is not None:
        params["before"] = cursor
    try:
        data = fetch(params)
    except Exception as e:
        errors = getattr(sys.modules[__name__], "_errs", 0) + 1
        sys.modules[__name__]._errs = errors
        print(f"ERROR: {e} (consecutive failures: {errors})", file=sys.stderr)
        if errors >= 8:
            print("too many consecutive failures — keeping partial data", file=sys.stderr)
            aborted = True
            break
        time.sleep(8)
        continue
    posts = data.get("data", [])
    if not posts:
        break
    batch += 1
    oldest = min(p["created_utc"] for p in posts)
    for p in posts:
        seen[p["id"]] = p
    print(f"batch {batch}: {len(posts)} posts, oldest={time.strftime('%Y-%m-%d', time.gmtime(oldest))}", file=sys.stderr)
    if oldest < TARGET or batch >= 25:
        break
    cursor = oldest
    time.sleep(1.2)

if aborted:
    print("WARNING: pagination aborted early; writing partial dataset", file=sys.stderr)
all_posts = list(seen.values())
all_posts.sort(key=lambda p: p["created_utc"], reverse=True)
with open(os.path.join(OUT, "all_posts.json"), "w") as f:
    json.dump(all_posts, f)
print(f"TOTAL posts collected: {len(all_posts)}")
