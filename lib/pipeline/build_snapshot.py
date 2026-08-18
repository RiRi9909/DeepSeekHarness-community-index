#!/usr/bin/env python3
"""Aggregate pipeline outputs into snapshot.json + self-contained cockpit.html."""
import json, os, re, time
from collections import defaultdict, Counter

ROOT = os.environ.get("DSH_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")

index_rows = json.load(open(os.path.join(ROOT, "index_history.json")))
posts = json.load(open(os.path.join(ROOT, "posts", "all_posts.json")))

comments = []
for d in ("comments", "comments2"):
    dd = os.path.join(ROOT, d)
    if not os.path.isdir(dd):
        continue
    for fn in os.listdir(dd):
        if fn.endswith(".json"):
            pid = fn[:-5]
            for c in json.load(open(os.path.join(ROOT, d, fn))):
                c["_post_id"] = pid
                comments.append(c)

post_by_id = {p["id"]: p for p in posts}
for c in comments:
    c["_post_title"] = post_by_id.get(c.get("_post_id", ""), {}).get("title", "")

POS = r"\b(impress\w*|amaz\w*|awesome|great|love\w*|incredible|game.?chang\w*|breakthrough|better than|beats|outperform\w*|mind.?blow\w*|shocked|wow|excellent|finally|recommend|powerful|fast|insane|huge|superior|cheap|good|nice|fair|reasonable|thank\w*|welcome|win|wins|winning|best|solid|worth|enjoy|happy|perfect|fine|okay\b|understand|congrat\w*|golden age|bargain|lucky|liberating|unreal|great job|kudos)"
NEG = r"\b(fail\w*|bad|worse|disappoint\w*|problem\w*|bug\w*|issue\w*|broken|slow|lag\w*|error\w*|censor\w*|refus\w*|limit\w*|crash\w*|frustrat\w*|suck\w*|terrible|hate\w*|garbage|useless|worry\w*|concern\w*|stop|downgrad\w*|degrad\w*|nerf\w*|bann\w*|worsen\w*|unfair|greed\w*|rip\b|bye\b|switch\w*|leave|outrage\w*|angry|upset|sad|regret\w*|lie\w*|shame|scam|mislead\w*)"

def sentiment(body):
    t = (body or "").lower()
    p = bool(re.search(POS, t)); n = bool(re.search(NEG, t))
    return "pos" if (p and not n) else ("neg" if (n and not p) else "neu")

def bucket_of(title):
    t = (title or "").lower()
    if re.search(r"\b(price|pricing|cost|cheap|expensive|hike|increase|afford|bill)", t): return "pricing"
    if re.search(r"\b(ban|chip|china|ccp|censor|refus|propaganda|usa|america|us |sino)", t): return "geopolitics"
    if re.search(r"\b(v4|flash|0731|release|out|launch|vision|update|opencode|mimo|claude|openai|gpt|luna|opus)", t): return "model"
    return "general"

def zone_of(v):
    if v >= 75: return "极度乐观"
    if v >= 55: return "乐观"
    if v >= 45: return "中性"
    if v >= 25: return "愤怒"
    return "极度愤怒"

series = [{
    "date": r["date"], "dsi": r["index"], "anger": r["anger"],
    "social": r["social"], "momentum": r["momentum"], "volatility": r["volatility"],
    "exit": r["exit"], "engagement": r["engagement"],
    "n": r["n_items"], "conf": r["confidence"], "zone": zone_of(r["index"]),
} for r in index_rows]

latest = series[-1]
prev = series[-2]
avg7 = round(sum(r["dsi"] for r in series[-7:]) / 7, 1)
hi = max(series, key=lambda r: r["dsi"]); lo = min(series, key=lambda r: r["dsi"])

byday = Counter()
for p in posts:
    byday[time.strftime("%Y-%m-%d", time.gmtime(p["created_utc"]))] += 1
vol = [{"date": r["date"], "posts": byday.get(r["date"], 0)} for r in series]

removed = sum(1 for p in posts if p.get("removed_by_category") or p.get("selftext") in ("[removed]", "[deleted]"))
authors_posts = len({p["author"] for p in posts if p["author"] not in ("[deleted]", "[removed]", "AutoModerator")})

BUCKET_META = {
    "pricing": {"title": "定价与涨价", "en": "Pricing",
                "summary": "最大话题。表态者中愤怒 55–60% vs 理解 40–45%：被指\"rug pull\"，cache 涨约 10 倍是核心痛点；辩护方认为仍远便宜于 Claude、算力受限情有可原。替代目标热度：Luna > MiMo > Qwen。"},
    "model": {"title": "模型本身", "en": "Model",
              "summary": "V4-Flash 获压倒性好评（表态者中 94% 正面）：性价比与编码能力被盛赞（介于 Sonnet 与 Opus 4.8 之间）；缺点集中在幻觉、创意写作弱、无原生视觉。涨价焦虑是唯一大面积阴影。"},
    "geopolitics": {"title": "地缘与审查", "en": "Geopolitics",
                    "summary": "亲开源、反硅谷垄断主导，对美国禁模/芯片管制压倒性反对与嘲讽；审查批评存在但被点踩。氛围本质是护盘 DeepSeek 而非单纯政治站队，梗文化浓。"},
    "general": {"title": "日常使用", "en": "Daily",
                "summary": "重度编码/Agent 社区：晒 token、调 cache、比 harness。抱怨长对话退化、harness 回传 thinking 浪费 token、官方沟通混乱；招聘诈骗甄别与\"AI 挚友\"话题常驻。"},
}
buckets = defaultdict(list)
for c in comments:
    buckets[bucket_of(c["_post_title"])].append(c)

themes = []
for key in ("pricing", "model", "geopolitics", "general"):
    cs = buckets.get(key, [])
    wpos = wneg = wneu = 0.0
    for c in cs:
        w = max(c.get("score"), 0) + 1
        s = sentiment(c.get("body"))
        if s == "pos": wpos += w
        elif s == "neg": wneg += w
        else: wneu += w
    tot = wpos + wneg + wneu or 1
    quotes, seen = [], set()
    for c in sorted(cs, key=lambda x: -x["score"]):
        b = (c.get("body") or "").replace("\n", " ").strip()
        if 30 <= len(b) <= 200 and b not in seen and c["score"] >= 2:
            seen.add(b)
            quotes.append({"q": b, "s": c["score"], "post": c["_post_title"][:60]})
        if len(quotes) >= 3: break
    themes.append({
        "key": key, "title": BUCKET_META[key]["title"], "en": BUCKET_META[key]["en"],
        "count": len(cs), "summary": BUCKET_META[key]["summary"],
        "pos": round(100 * wpos / tot, 1), "neg": round(100 * wneg / tot, 1), "neu": round(100 * wneu / tot, 1),
        "quotes": quotes,
    })

wall, seen = [], set()
for c in sorted(comments, key=lambda x: -x["score"]):
    b = (c.get("body") or "").replace("\n", " ").strip()
    if 40 <= len(b) <= 220 and b not in seen and c["score"] >= 8:
        seen.add(b)
        wall.append({"q": b, "s": c["score"], "post": c["_post_title"][:70], "sent": sentiment(b)})
    if len(wall) >= 9: break

events = [
    {"date": "07-24", "dsi": 57.5, "title": "旧模型名停用", "en": "deepseek-chat / reasoner retired",
     "desc": "deepseek-chat、deepseek-reasoner 两个旧 API 别名停用，开发者被迫改代码换模型名。"},
    {"date": "07-31", "dsi": 90.3, "title": "V4-Flash 发布", "en": "V4-Flash release",
     "desc": "\"dirt cheap\" 定价引爆狂欢，DSI 冲上全周期顶点 90.3（极度乐观）。"},
    {"date": "08-06", "dsi": 35.1, "title": "涨价预告", "en": "Price hike announced",
     "desc": "官方宣布 API 将\"显著\"涨价，DSI 单日暴跌至 35.1（愤怒）。"},
    {"date": "08-13", "dsi": 38.2, "title": "公布涨幅 1,114%", "en": "Hike details: up to 1,114%",
     "desc": "cache 命中价涨约 10 倍，\"Bye bye Deepseek\" 刷屏，愤怒峰值。"},
    {"date": "08-16", "dsi": 61.3, "title": "新定价生效", "en": "New pricing effective",
     "desc": "峰谷分时定价落地，\"still a bargain\" 辩护派回升，指数反弹至乐观区。"},
]

methodology = {
    "components": [
        {"name": "社会情绪", "en": "Social Sentiment", "w": 20, "val": latest["social"],
         "desc": "近 3 日赞数加权的正面词/负面词比（≈F&G 的社媒情绪）。"},
        {"name": "情绪动量", "en": "Sentiment Momentum", "w": 20, "val": latest["momentum"],
         "desc": "近 3 日 vs 前 3 日情绪的变化（≈F&G 的动量）。"},
        {"name": "情绪波动", "en": "Volatility", "w": 10, "val": latest["volatility"],
         "desc": "近 14 日逐日情绪比标准差，倒置：波动越大越恐慌（≈F&G 的波动率）。"},
        {"name": "退出信号", "en": "Exit Signals", "w": 30, "val": latest["exit"],
         "desc": "\"bye / switch to / refund / rug pull\" 离场词密度，倒置。Reddit 版的\"恐慌抛售\"。"},
        {"name": "互动热度", "en": "Engagement", "w": 20, "val": latest["engagement"],
         "desc": "近 3 日发帖+评论量 vs 14 日基线，方向由情绪符号决定（≈F&G 的量能）。"},
    ],
    "zones": [
        {"lo": 0, "hi": 24, "label": "极度愤怒", "en": "Extreme Anger"},
        {"lo": 25, "hi": 44, "label": "愤怒", "en": "Anger"},
        {"lo": 45, "hi": 54, "label": "中性", "en": "Neutral"},
        {"lo": 55, "hi": 74, "label": "乐观", "en": "Optimism"},
        {"lo": 75, "hi": 100, "label": "极度乐观", "en": "Euphoria"},
    ],
}

generated_at = int(time.time() * 1000)
data = {
    "meta": {
        "title": "r/DeepSeek 社区情绪驾驶舱",
        "subtitle": "Community Sentiment Cockpit",
        "window": f"{series[0]['date']} ~ {series[-1]['date']}",
        "generated": time.strftime("%Y-%m-%d", time.gmtime(generated_at / 1000)),
        "reference": "参照 Crypto Fear & Greed Index（alternative.me）",
    },
    "current": {
        "dsi": latest["dsi"], "anger": latest["anger"], "zone": latest["zone"],
        "delta": round(latest["dsi"] - prev["dsi"], 1),
        "avg7": avg7,
        "hi": {"v": hi["dsi"], "date": hi["date"]},
        "lo": {"v": lo["dsi"], "date": lo["date"]},
        "n": latest["n"],
    },
    "stats": {
        "posts": len(posts), "comments": len(comments), "days": len(series),
        "authorsPosts": authors_posts,
        "removedRate": round(100 * removed / max(1, len(posts)), 1),
    },
    "series": series,
    "volume": vol,
    "themes": themes,
    "wall": wall,
    "events": events,
    "methodology": methodology,
}

# snapshot.json
snapshot = {
    "generatedAt": generated_at,
    "dsi": latest["dsi"],
    "anger": latest["anger"],
    "zone": latest["zone"],
    "window": f"{series[0]['date']} ~ {series[-1]['date']}",
}
json.dump(snapshot, open(os.path.join(ROOT, "snapshot.json"), "w"), ensure_ascii=False)

# cockpit.html (self-contained)
inline = "<script>window.DASH_DATA = " + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";</script>"
src_html = open(TPL, encoding="utf-8").read()
if '<script src="data.js"></script>' in src_html:
    built = src_html.replace('<script src="data.js"></script>', inline)
else:
    built = src_html
with open(os.path.join(ROOT, "cockpit.html"), "w", encoding="utf-8") as f:
    f.write(built)

print(f"snapshot: DSI {latest['dsi']} ({latest['zone']}) anger {latest['anger']} window {series[0]['date']}~{series[-1]['date']}")
print(f"written snapshot.json + cockpit.html ({len(built)} bytes)")
