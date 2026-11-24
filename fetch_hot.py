# -*- coding: utf-8 -*-
"""抓取全网热榜，去重后取 10 条，输出 data/hot.json"""
import json
import os
import re
import time
import requests
from datetime import datetime

API = "https://uapis.cn/api/v1/misc/hotboard"
PLATFORMS = ["weibo", "zhihu", "toutiao", "douyin", "baidu"]
PLATFORM_CN = {
    "weibo": "微博", "zhihu": "知乎", "toutiao": "头条",
    "douyin": "抖音", "baidu": "百度",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HotDigest/1.0)"}


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def norm(title):
    """用于去重的归一化标题"""
    return re.sub(r"[\W_]+", "", title).lower()[:24]


def fetch_one(platform, retry=2):
    for i in range(retry + 1):
        try:
            r = requests.get(API, params={"type": platform},
                             headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            items = data.get("list") or []
            out = []
            for it in items:
                title = clean(it.get("title"))
                if not title:
                    continue
                info = (it.get("extra") or {}).get("info") or []
                desc = ""
                for s in info:
                    if isinstance(s, str) and len(s) > len(title) + 4:
                        desc = clean(s)
                        break
                out.append({
                    "title": title,
                    "url": it.get("url") or "",
                    "desc": desc[:180],
                    "platform": PLATFORM_CN.get(platform, platform),
                    "hot": str(it.get("hot_value") or ""),
                })
            return out
        except Exception as e:
            if i == retry:
                print(f"[warn] {platform} 抓取失败: {e}")
                return []
            time.sleep(1.5 * (i + 1))
    return []


def main():
    all_items, seen = [], set()
    # 轮转取，保证平台均衡：每轮每平台取 1 条
    pools = {p: fetch_one(p) for p in PLATFORMS}
    for round_i in range(15):
        for p in PLATFORMS:
            pool = pools.get(p, [])
            if round_i >= len(pool):
                continue
            item = pool[round_i]
            key = norm(item["title"])
            if key and key not in seen:
                seen.add(key)
                all_items.append(item)
            if len(all_items) >= 10:
                break
        if len(all_items) >= 10:
            break

    result = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "items": all_items[:10],
    }
    def save(path):
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    save("hot.json")
    save("data/hot.json")
    print(f"[ok] 抓取到 {len(all_items[:10])} 条热点 -> hot.json")
    for i, it in enumerate(result["items"], 1):
        print(f"  {i:>2}. [{it['platform']}] {it['title']}")


if __name__ == "__main__":
    main()
