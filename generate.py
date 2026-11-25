# -*- coding: utf-8 -*-
"""把热点改写成适合头条/公众号发表的短美文，输出 posts.json。
兼容任意 OpenAI 格式的国产大模型：DeepSeek / 通义 / 智谱 / 硅基流动等。
API Key 从环境变量 LLM_API_KEY 读取，绝不写进代码。
每篇配一张按平台色+关键词生成的 SVG 封面图（存 covers/，不依赖外部图床）。
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

SYSTEM_PROMPT = """你是资深自媒体编辑，为今日头条和微信公众号写热点短评美文。
规则：
1. 只依据给定热点信息写作，不编造事实、数据、引语；不确定的写"据报道/网传"。
2. 不做政治敏感评判，不站队、不煽动，聚焦事件本身的看点或生活启发。
3. 每篇输出严格为 JSON：{"title": "...", "body": "..."}
   - title：20-30字，有信息量，不标题党、不用震惊体。
   - body：700-1000字，5-7自然段，段落之间用 \n\n 分隔：
     ①开头点题：一句话说清事情 what/why；
     ②背景铺垫：交代来龙去脉，2段；
     ③多方视角：不同立场怎么看，1-2段；
     ④深度分析：影响与趋势，1-2段；
     ⑤收尾：点题升华，并用一句有新意的互动提问结尾。
4. 结尾互动提问禁止用"你怎么看""欢迎留言""你如何看待"这类套话，
   要贴合本篇主题、具体且有代入感，每篇都不一样。
5. 语言口语化、有温度、有细节；信息密度高，不空喊口号。
6. 只输出 JSON，不要代码块标记。"""

# 结尾互动提问的轮换池：AI 未给出新意提问时按序号取用，保证不重复
ENDING_QUESTIONS = [
    "如果这件事发生在你身边，你的第一反应会是什么？",
    "你觉得三年后再回头看，人们会怎么评价今天这个决定？",
    "换成你是当事人，你会做出同样的选择吗？为什么？",
    "这条消息里，最让你意外的是哪个细节？",
    "你身边有人正在经历类似的事吗？他们是怎么处理的？",
    "如果只能给这件事提一条建议，你会说什么？",
    "你更关心它带来的变化，还是它暴露出的问题？",
    "把它和你熟悉的一件事放在一起看，你会发现什么共同点？",
    "你愿意为这个观点点个赞，还是想反过来驳一句？",
    "下一个追问，你最希望媒体替你弄清楚哪一个？",
    "如果给这件事起个小标题，你会用哪五个字？",
    "你第一次听说它时，是相信还是怀疑？后来变了吗？",
    "你觉得普通人能从这里带走的一条经验是什么？",
    "这件事里，有没有哪个瞬间让你觉得「原来如此」？",
    "如果让你讲给完全不了解的人听，你会从哪句讲起？",
]

# 平台色：用于封面图，取各平台主色
PLATFORM_COLORS = {
    "微博": "#e6162d", "知乎": "#0066ff", "头条": "#f04142",
    "抖音": "#161823", "百度": "#2932e1", "小红书": "#ff2442",
    "B站": "#fb7299", "掘金": "#2e69ff", "36氪": "#4285f4",
    "新浪": "#e61414", "IT之家": "#0078d4", "澎湃": "#1a1a1a",
}

# 关键词 -> 配色主题（背景渐变 + 图形），让不同题材的封面"有特征"
# 每条为 (背景色1, 背景色2, 主题字)
TOPIC_THEMES = [
    ("#1f2d3d", "#2c5364", "科技"), ("#3a1c71", "#d76d77", "社会"),
    ("#0f3443", "#34e89e", "财经"), ("#42275a", "#734b6d", "文化"),
    ("#232526", "#414345", "时政"), ("#1a2980", "#26d0ce", "国际"),
    ("#5f2c82", "#49a09d", "生活"), ("#8e2de2", "#4a00e0", "体育"),
    ("#c31432", "#240b36", "突发"), ("#134e5e", "#71b280", "民生"),
]


def pick_theme(text):
    """按标题关键词挑主题，返回 (c1, c2, label)。"""
    groups = [
        (["芯片", "AI", "人工智能", "科技", "手机", "发射", "航天", "机器人", "模型", "算力"], 0),
        (["被查", "通报", "事故", "判决", "警方", "调查", "立案"], 1),
        (["股", "经济", "房价", "基金", "涨", "跌", "公司", "裁员", "上市", "楼市"], 2),
        (["电影", "电视剧", "演唱会", "演员", "导演", "书", "音乐", "综艺", "文物"], 3),
        (["政策", "会议", "国务院", "部委", "人大", "政协", "部署"], 4),
        (["美国", "特朗普", "俄", "乌克兰", "以色列", "日本", "欧盟", "关税", "外交"], 5),
        (["旅游", "养生", "健康", "天气", "菜", "美食", "假期", "高铁", "出行"], 6),
        (["比赛", "夺冠", "球队", "奥运", "世界杯", "球员", "教练"], 7),
        (["地震", "火灾", "暴雨", "台风", "失联", "空难", "紧急"], 8),
        (["医保", "社保", "教育", "高考", "就业", "养老", "育儿", "医院", "学校"], 9),
    ]
    for words, idx in groups:
        if any(w in text for w in words):
            return TOPIC_THEMES[idx]
    # 无命中时用标题字符和取模，保证同题材也各不相同
    return TOPIC_THEMES[sum(ord(c) for c in text) % len(TOPIC_THEMES)]


def make_cover(title, platform, idx):
    """生成 SVG 封面图字符串：平台主色徽标 + 题材渐变 + 大字标题。"""
    c1, c2, label = pick_theme(title)
    accent = PLATFORM_COLORS.get(platform, "#c0392b")
    # 标题折行：每行约 11 个汉字
    t = re.sub(r"\s+", " ", title).strip()
    lines = [t[i:i + 11] for i in range(0, len(t), 11)][:4]
    if len(t) > 44:
        lines[-1] = lines[-1][:10] + "…"
    y0 = 250 - (len(lines) - 1) * 31
    title_svg = "".join(
        f'<text x="60" y="{y0 + i * 62}" fill="#fff" font-size="42" '
        f'font-weight="700" font-family="PingFang SC,Microsoft YaHei,sans-serif">'
        f'{esc_xml(line)}</text>'
        for i, line in enumerate(lines)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="500" viewBox="0 0 900 500">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>
    </linearGradient>
  </defs>
  <rect width="900" height="500" fill="url(#g)"/>
  <circle cx="790" cy="90" r="150" fill="{accent}" opacity="0.28"/>
  <circle cx="820" cy="420" r="90" fill="#fff" opacity="0.06"/>
  <rect x="60" y="52" width="10" height="44" rx="5" fill="{accent}"/>
  <text x="86" y="84" fill="#fff" font-size="26" opacity="0.9" font-family="PingFang SC,Microsoft YaHei,sans-serif">{esc_xml(label)} · {esc_xml(platform)}</text>
  {title_svg}
  <text x="60" y="452" fill="#fff" font-size="22" opacity="0.6" font-family="PingFang SC,Microsoft YaHei,sans-serif">每日热点美文 · NO.{idx:02d}</text>
</svg>'''


def esc_xml(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def call_llm(topic):
    """调用大模型，返回 (title, body)。失败抛异常由上层降级处理。"""
    user = (
        f"热点标题：{topic['title']}\n"
        f"来源平台：{topic['platform']}\n"
        f"补充信息：{topic.get('desc') or '无'}\n\n"
        "请据此写一篇 700-1000 字、5-7 自然段的头条/公众号短评美文，"
        "结尾用一个贴合本篇、不落俗套的互动提问。"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.9,
        "max_tokens": 2200,
        "stream": False,
    }
    # 部分模型默认开启思考模式，这里关闭以省钱提速；不支持的厂商会忽略该字段
    payload["thinking"] = {"type": "disabled"}

    resp = requests.post(
        BASE_URL.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"] or ""
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    obj = json.loads(content)
    return (obj.get("title") or topic["title"]).strip(), (obj.get("body") or "").strip()


CLICHE_ENDINGS = ("你怎么看", "你如何看待", "欢迎留言", "欢迎评论", "评论区见", "说说你的看法")


def has_cliche(body):
    return any(x in body[-120:] for x in CLICHE_ENDINGS)


def fallback(topic, idx):
    """AI 调用失败时的降级：用原始信息拼一篇够长的可用文，保证当天不断更。"""
    title = topic["title"]
    desc = topic.get("desc") or f"该话题当前在{topic['platform']}热榜受到广泛关注。"
    ending = ENDING_QUESTIONS[idx % len(ENDING_QUESTIONS)]
    parts = [
        f"近日，\"{title}\"成为{topic['platform']}热议话题，短时间内冲上热榜，引发大量关注。"
        "一个话题能在一天之内刷屏，往往说明它恰好踩中了公众情绪的某个节点：可能是共同的经历，"
        "可能是对未知的担忧，也可能是对某种长期积累情绪的一次集中释放。",
        f"从目前公开的信息看，{desc}"
        "不过热榜信息更新很快，标题之外的细节仍有待更多来源交叉印证。"
        "在转述和传播的过程中，原始表述容易被压缩、被二次加工，读者看到的版本和最初的报道未必完全一致。",
        "这类话题之所以能迅速发酵，往往不只是事情本身足够吸睛，更因为它触碰了大众普遍关心的那根神经。"
        "信息在传播中会被不断加工，细节可能被放大，也可能被忽略。"
        "因此，面对刷屏的消息，先弄清消息从哪里来、是谁说的、有没有原始出处，比急着表态更重要。",
        "看待热点，最忌讳的是只凭一个标题就下结论。同一件事，站在不同立场的人会有完全不同的感受，"
        "而这些差异本身，就是理解社会的一面镜子。"
        "当事人、旁观者、从业者、普通网友，各自的关切点并不相同，把几种视角放在一起，画面才会更完整。",
        "更值得追问的是，这件事暴露出的深层问题是什么，它会不会推动某些改变，"
        "以及我们能否从中提炼出对日常生活有用的判断标准。"
        "热点会过去，但问题未必随之消失；如果一次讨论只留下情绪而没有留下思考，那这份关注就有些可惜了。",
        "对普通人来说，最实际的做法是把事实和观点分开看：事实部分等权威渠道确认，观点部分允许不同声音并存。"
        "在更多信息披露之前，保持关注但不急于站队，或许是更稳妥的态度。"
        f"{ending}",
    ]
    body = "\n\n".join(parts)
    return title, body


def main():
    if not API_KEY:
        print("[warn] 未设置 LLM_API_KEY，将全部使用降级简介。")
    hot_path = "hot.json" if os.path.exists("hot.json") else "data/hot.json"
    with open(hot_path, encoding="utf-8") as f:
        hot = json.load(f)

    os.makedirs("covers", exist_ok=True)
    posts, failed = [], 0
    for i, topic in enumerate(hot["items"], 1):
        try:
            if not API_KEY:
                raise RuntimeError("no api key")
            title, body = call_llm(topic)
            print(f"  [{i}/{len(hot['items'])}] AI 生成成功 {len(body)}字")
        except Exception as e:
            failed += 1
            title, body = fallback(topic, i)
            print(f"  [{i}/{len(hot['items'])}] 降级处理: {str(e)[:60]}")

        # 结尾如果还是套话，替换成轮换提问
        if has_cliche(body):
            cut = max(body.rfind("\n\n"), body.rfind("。"))
            body = body[:cut].rstrip("。，, ") + "。" + ENDING_QUESTIONS[(i - 1) % len(ENDING_QUESTIONS)]
            print(f"      结尾套话已替换为轮换提问")

        cover_path = f"covers/{i:02d}.svg"
        with open(cover_path, "w", encoding="utf-8") as f:
            f.write(make_cover(title, topic["platform"], i))

        posts.append({
            "title": title,
            "body": body,
            "source_title": topic["title"],
            "url": topic.get("url", ""),
            "platform": topic["platform"],
            "cover": cover_path,
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
    print(f"[ok] 生成 {len(posts)} 篇（降级 {failed} 篇）+ {len(posts)} 张封面 -> posts.json / covers/")


if __name__ == "__main__":
    main()
