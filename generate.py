# -*- coding: utf-8 -*-
"""把热点改写成适合头条/公众号发表的短美文，输出 data/posts.json
兼容任意 OpenAI 格式的国产大模型：DeepSeek / 通义 / 智谱 / 硅基流动等。
API Key 从环境变量 LLM_API_KEY 读取，绝不写进代码。
"""
import json
import os
import re
import time
from datetime import datetime

import requests

# ---------- 可配置：换厂商只改这 3 行 ----------
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("LLM_MODEL", "deepseek-flash")
API_KEY = os.getenv("LLM_API_KEY", "")

SYSTEM_PROMPT = """你是资深自媒体编辑，为今日头条和微信公众号写短评美文。
规则：
1. 只依据给定热点信息写作，不编造事实、数据、引语；不确定的写"据报道/网传"。
2. 不做政治敏感评判，不站队、不煽动，聚焦事件本身的看点或生活启发。
3. 每篇输出严格为 JSON：{"title": "...", "body": "..."}
   - title：20-30字，有信息量，不标题党、不用震惊体。
   - body：300-500字，3-4自然段，开头点题、中间分析、结尾给读者一句思考或互动提问。
4. 语言口语化、有温度，段落之间用 \n\n 分隔。只输出 JSON，不要代码块标记。"""


def call_llm(topic):
    """调用大模型，返回 (title, body)。失败抛异常由上层降级处理。"""
    user = (
        f"热点标题：{topic['title']}\n"
        f"来源平台：{topic['platform']}\n"
        f"补充信息：{topic.get('desc') or '无'}\n\n"
        "请据此写一篇适合头条/公众号发表的短评美文。"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.8,
        "max_tokens": 1200,
        "stream": False,
    }
    # 部分模型默认开启思考模式，这里关闭以省钱提速；不支持的厂商会忽略该字段
    payload["thinking"] = {"type": "disabled"}

    resp = requests.post(
        BASE_URL.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"] or ""
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    obj = json.loads(content)
    return (obj.get("title") or topic["title"]).strip(), (obj.get("body") or "").strip()


def fallback(topic):
    """AI 调用失败时的降级：用原始信息拼一篇可用简介，保证当天不断更。"""
    title = topic["title"]
    desc = topic.get("desc") or f"该话题当前在{topic['platform']}热榜受到广泛关注。"
    body = (
        f"近日，\"{title}\"成为{topic['platform']}热议话题。\n\n"
        f"{desc}\n\n"
        "热点背后往往折射出公众的共同关切。我们梳理事实、理性看待，"
        "不盲从、不跟风，等更多信息披露后再下结论。你如何看待这件事？欢迎留言交流。"
    )
    return title, body


def main():
    if not API_KEY:
        print("[warn] 未设置 LLM_API_KEY，将全部使用降级简介。")
    hot_path = "hot.json" if os.path.exists("hot.json") else "data/hot.json"
    with open(hot_path, encoding="utf-8") as f:
        hot = json.load(f)

    posts, failed = [], 0
    for i, topic in enumerate(hot["items"], 1):
        try:
            if not API_KEY:
                raise RuntimeError("no api key")
            title, body = call_llm(topic)
            print(f"  [{i}/10] AI 生成成功")
        except Exception as e:
            failed += 1
            title, body = fallback(topic)
            print(f"  [{i}/10] 降级处理: {str(e)[:60]}")
        posts.append({
            "title": title,
            "body": body,
            "source_title": topic["title"],
            "url": topic.get("url", ""),
            "platform": topic["platform"],
        })
        time.sleep(0.5)

    result = {
        "updated_at": hot["updated_at"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "posts": posts,
    }
    def save(path):
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    save("posts.json")
    save("data/posts.json")
    print(f"[ok] 生成 {len(posts)} 篇（降级 {failed} 篇）-> posts.json")


if __name__ == "__main__":
    main()
