#!/usr/bin/env python3
"""
r/DeepSeek 社区情绪指数 (DSI, DeepSeek Sentiment Index)
参照币圈 Fear & Greed Index (alternative.me) 的多信号加权结构：
0 = 极度愤怒, 100 = 极度乐观; 愤怒指数 = 100 - 乐观指数。

组件与权重：
  1. 社会情绪   Social Sentiment   20%   近3日 赞数加权 正面/(正面+负面) 比
  2. 情绪动量   Sentiment Momentum 20%   近3日 vs 前3日 情绪比的变化（斜率 K=150）
  3. 情绪波动   Volatility         10%   近14日 逐日情绪比标准差（倒置：波动大=恐慌/愤怒）
  4. 退出信号   Exit Signals       30%   近3日 "bye/switch/refund/rugpull" 等离场词密度（倒置）
  5. 互动热度   Engagement         20%   近3日发帖+评论量 vs 14日基线，方向由社会情绪符号决定

校准规则：
  - 3日窗口样本量 < 200 时向 50 收缩（shrinkage），避免早期小样本抖动
  - 区间参照 alternative.me：0-24 极度愤怒 / 25-44 愤怒 / 45-54 中性 / 55-74 乐观 / 75-100 极度乐观

用法: python3 sentiment_index.py [--out index_history.csv]
"""
import json, os, re, sys, math
from collections import defaultdict

DAY = 86400
POS = r"\b(impress\w*|amaz\w*|awesome|great|love\w*|incredible|game.?chang\w*|breakthrough|better than|beats|outperform\w*|mind.?blow\w*|shocked|wow|excellent|finally|recommend|powerful|fast|insane|huge|superior|cheap|good|nice|fair|reasonable|thank\w*|welcome|win|wins|winning|best|solid|worth|enjoy|happy|perfect|fine|okay\b|understand|congrat\w*|golden age|bargain|lucky|liberating|unreal|great job|kudos)"
NEG = r"\b(fail\w*|bad|worse|disappoint\w*|problem\w*|bug\w*|issue\w*|broken|slow|lag\w*|error\w*|censor\w*|refus\w*|limit\w*|crash\w*|frustrat\w*|suck\w*|terrible|hate\w*|garbage|useless|worry\w*|concern\w*|stop|downgrad\w*|degrad\w*|nerf\w*|bann\w*|worsen\w*|unfair|greed\w*|rip\b|bye\b|switch\w*|leave|outrage\w*|angry|upset|sad|regret\w*|lie\w*|shame|scam|mislead\w*)"
EXIT = r"\b(bye\b|goodbye|switch(ing|ed)? to|refund|moved (all|my|away)|move (to|away)|cancel(ed|led)? my|rug.?pull|cooked|killed itself|jump ship|migrat\w*|boycott|good riddance|farewell|was nice while|it was fun)"

pos_re, neg_re, exit_re = re.compile(POS), re.compile(NEG), re.compile(EXIT)

# ---- load data ----------------------------------------------------------
import os as _os
ROOT = _os.environ.get("DSH_DATA_DIR") or _os.path.dirname(_os.path.abspath(__file__))
posts = json.load(open(_os.path.join(ROOT, "posts", "all_posts.json")))
comments = []
for d in ("comments", "comments2"):
    dd = _os.path.join(ROOT, d)
    if not _os.path.isdir(dd): continue
    for fn in os.listdir(dd):
        if fn.endswith(".json"):
            comments += json.load(open(_os.path.join(ROOT, d, fn)))

print(f"items: {len(posts)} posts, {len(comments)} comments", file=sys.stderr)

# per-day aggregates
agg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])  # pos_w, neg_w, exit_w, total_w, n_items

def add(text, score, ts):
    w = max(score, 0) + 1.0
    t = (text or "").lower()
    if not t.strip():
        return
    d = ts // DAY
    p = bool(pos_re.search(t))
    n = bool(neg_re.search(t))
    e = bool(exit_re.search(t))
    a = agg[d]
    a[0] += w if (p and not n) else 0
    a[1] += w if (n and not p) else 0
    a[2] += w if e else 0
    a[3] += w
    a[4] += 1

for p in posts:
    add((p.get("title") or "") + " " + (p.get("selftext") or "")[:600], p["score"], p["created_utc"])
for c in comments:
    add(c.get("body"), c["score"], c["created_utc"])

days = sorted(agg)
print(f"data days: {days[0]}..{days[-1]} ({len(days)} days)", file=sys.stderr)

def gmt(d):
    import time as _t
    return _t.strftime("%Y-%m-%d", _t.gmtime(d * DAY))

# ---- helpers -------------------------------------------------------------
def window(d0, d1):
    """sum agg over [d0, d1] inclusive"""
    pos = neg = exit_ = tot = n = 0.0
    for d in range(d0, d1 + 1):
        if d in agg:
            a = agg[d]
            pos += a[0]; neg += a[1]; exit_ += a[2]; tot += a[3]; n += a[4]
    return pos, neg, exit_, tot, n

def p_ratio_day(d):
    a = agg.get(d)
    if not a or a[0] + a[1] == 0:
        return 0.5
    return a[0] / (a[0] + a[1])

def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))

# ---- parameters (calibrated) ----------------------------------------------
K_MOMENTUM = 1.2     # momentum slope: 50 + delta*K (social 为 0-100 分制)
K_VOLATILITY = 320.0  # volatility invert slope
K_EXIT = 1500.0       # exit density invert slope (density 3% -> 55分)
CONF_MIN_ITEMS = 30   # 3d window below this -> low confidence
SHRINK_N = 200.0      # 3d window below this n -> shrink index toward 50

rows = []
for d in days:
    # 1. social (3d)
    pos3, neg3, exit3, tot3, n3 = window(d - 2, d)
    social = clamp(100 * pos3 / (pos3 + neg3)) if (pos3 + neg3) > 0 else 50.0
    # 2. momentum (3d vs previous 3d, gentle slope)
    pos_p, neg_p, _, _, _ = window(d - 5, d - 3)
    prev = 100 * pos_p / (pos_p + neg_p) if (pos_p + neg_p) > 0 else 50.0
    momentum = clamp(50 + (social - prev) * K_MOMENTUM)
    # 3. volatility (14d std of daily ratio, inverted)
    ratios = [p_ratio_day(x) for x in range(d - 13, d + 1) if x in agg]
    if len(ratios) >= 3:
        mean = sum(ratios) / len(ratios)
        std = math.sqrt(sum((r - mean) ** 2 for r in ratios) / len(ratios))
        volatility = clamp(100 - std * K_VOLATILITY)
    else:
        volatility = 50.0
    # 4. exit signals (3d density, inverted)
    density = exit3 / tot3 if tot3 > 0 else 0.0
    exit_score = clamp(100 - density * K_EXIT)
    # 5. engagement (3d volume vs 14d baseline, direction-signed)
    vol3_daily = n3 / 3.0
    base_items = sum(agg[x][4] for x in range(d - 13, d + 1) if x in agg)
    base_days = sum(1 for x in range(d - 13, d + 1) if x in agg)
    baseline = base_items / base_days if base_days else vol3_daily
    ratio = vol3_daily / baseline if baseline > 0 else 1.0
    direction = (social - 50) / 50.0
    engagement = clamp(50 + direction * min(50.0, (ratio - 1) * 50.0))
    # composite
    idx = clamp(0.20 * social + 0.20 * momentum + 0.10 * volatility
                + 0.30 * exit_score + 0.20 * engagement)
    # small-sample shrinkage toward neutral 50
    if n3 < SHRINK_N:
        idx = 50 + (idx - 50) * (n3 / SHRINK_N)
    rows.append({
        "date": gmt(d), "day": d,
        "index": round(idx, 1), "anger": round(100 - idx, 1),
        "social": round(social, 1), "momentum": round(momentum, 1),
        "volatility": round(volatility, 1), "exit": round(exit_score, 1),
        "engagement": round(engagement, 1),
        "n_items": n3, "confidence": "high" if n3 >= CONF_MIN_ITEMS else "low",
    })

# ---- zone labeling (alternative.me F&G boundaries) -------------------------
def zone(v):
    if v >= 75: return "极度乐观"
    if v >= 55: return "乐观"
    if v >= 45: return "中性"
    if v >= 25: return "愤怒"
    return "极度愤怒"

def anger_zone(v):
    a = 100 - v
    if a >= 75: return "极度愤怒"
    if a >= 55: return "愤怒"
    if a >= 45: return "一般"
    if a >= 25: return "轻度不满"
    return "平和"

# ---- output ----------------------------------------------------------------
out = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--out" else "index_history.csv"
with open(out, "w") as f:
    f.write("date,index,anger,social,momentum,volatility,exit,engagement,n_items,confidence,zone\n")
    for r in rows:
        f.write(f"{r['date']},{r['index']},{r['anger']},{r['social']},{r['momentum']},{r['volatility']},{r['exit']},{r['engagement']},{r['n_items']},{r['confidence']},{zone(r['index'])}\n")
json.dump(rows, open("index_history.json", "w"), ensure_ascii=False, indent=1)

print(f"\nwrote {out} ({len(rows)} days) and index_history.json\n")
print(f"{'date':<12}{'DSI':>6}{'愤怒':>6}{'social':>8}{'moment':>8}{'vol':>6}{'exit':>6}{'eng':>6}{'n':>5}  区")
for r in rows:
    flag = "" if r["confidence"] == "high" else " *"
    print(f"{r['date']:<12}{r['index']:>6}{r['anger']:>6}{r['social']:>8}{r['momentum']:>8}{r['volatility']:>6}{r['exit']:>6}{r['engagement']:>6}{r['n_items']:>5}  {zone(r['index'])}{flag}")

# key-event checkpoints
print("\n=== 关键事件校验 ===")
events = {"2026-07-31": "V4-Flash 发布", "2026-08-06": "涨价预告", "2026-08-13": "公布涨幅1,114%", "2026-08-16": "新定价生效"}
by_date = {r["date"]: r for r in rows}
for ev, label in events.items():
    r = by_date.get(ev)
    if r:
        print(f"{ev} ({label}): DSI={r['index']}  {zone(r['index'])}  愤怒={r['anger']}")
last = rows[-1]
print(f"\n最新读数 ({last['date']}): DSI 乐观指数 = {last['index']}（{zone(last['index'])}），愤怒指数 = {last['anger']}（{anger_zone(last['anger'])}）")
