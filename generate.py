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


def call_llm(topic, max_retry=2):
    """调用大模型，返回 (title, body)。失败重试 max_retry 次，仍失败才抛异常降级。"""
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

    last_err = None
    for attempt in range(max_retry + 1):
        try:
            resp = requests.post(
                BASE_URL.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=45,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"] or ""
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            obj = json.loads(content)
            return (obj.get("title") or topic["title"]).strip(), (obj.get("body") or "").strip()
        except Exception as e:
            last_err = e
            if attempt < max_retry:
                wait = 2 ** attempt  # 1s, 2s, 4s 指数退避，缓解限流
                print(f"      第{attempt+1}次失败，{wait}s后重试: {str(e)[:50]}")
                time.sleep(wait)
    raise last_err


CLICHE_ENDINGS = ("你怎么看", "你如何看待", "欢迎留言", "欢迎评论", "评论区见", "说说你的看法")


def has_cliche(body):
    return any(x in body[-120:] for x in CLICHE_ENDINGS)


# 降级文素材：多套开头、视角、分析、收尾，按序号错开组合，避免千篇一律
OPENERS = [
    "今天刷屏的「{t}」，来得并不突然。",
    "早上打开{tp}热榜，「{t}」已经挂在显眼的位置。",
    "如果只看标题，「{t}」像是一则普通消息；点开之后才发现没那么简单。",
    "「{t}」这件事，值得单独拿出来说说。",
    "围绕「{t}」的讨论，今天明显热了起来。",
    "又一条冲上热榜的消息：{t}。",
    "「{t}」为什么能引发这么大关注？答案藏在细节里。",
    "热榜每天都在换，但「{t}」这条留了下来。",
    "关于「{t}」，可以先从最朴素的问题问起：到底发生了什么。",
    "把「{t}」放回它发生的语境里，会更清楚它在说什么。",
    "一条「{t}」，把不少人的注意力集中到了一起。",
    "刷到「{t}」时，先别急着划走，它和后文有关。",
]

PERSPECTIVES = [
    "最先值得看的，是当事人自己的说法。当事人的叙述未必完整，却是理解这件事的起点；把它和公开信息对照着看，轮廓才会清晰。",
    "站在旁观者角度，最容易忽略的是时间线。事情往往不是一夜之间发生的，把前因后果按顺序排开，很多「意外」就顺理成章了。",
    "换个行业视角会更有意思。同一件事，从业者看到的是规则和成本，普通读者看到的是结果，两边的落差本身就值得琢磨。",
    "从制度层面看，这类事情通常不是单一原因造成的。它更像多个环节叠加后的结果，追责或改进都要找对那一环。",
    "如果把视角拉到更长的时间尺度，今天的争论也许只是阶段性的。历史里类似的情形不少，结局未必如当下所想。",
    "普通人的感受同样重要。宏大的叙述之外，具体的人怎么被影响，才是判断一件事分量的真正标尺。",
    "媒体怎么呈现也值得留意。同一件事，标题的措辞不同，给人的第一印象就会差很多，这也是信息素养的一部分。",
    "还要看到不确定性：目前的信息未必是全部，任何笃定的结论都该留有余地，等待更多来源交叉印证。",
]

ANALYSES = [
    "这件事真正抛出的疑问是：类似的情况会不会重演？如果会，普通人该提前知道些什么。",
    "比结论更有价值的，是它暴露的流程问题。一个环节被看见，往往意味着其他环节也值得回头检查。",
    "往前一步想，这件事可能带来的改变，比它本身更值得跟踪。政策、行业、舆论，任何一端的调整都值得记一笔。",
    "它也提醒我们，判断一件事不能只靠情绪。把事实、推测、立场分清楚，是信息过载时代最基本的能力。",
    "有意思的是，讨论区的分歧点往往不在事实，而在价值排序。看清这一点，很多争论就没那么难理解了。",
    "往现实里落一落：这类话题最终会变成生活的常识，还是很快被下一条热搜盖过，取决于它有没有真正解决问题。",
    "如果把它和近期的同类事件放在一起，会发现一些共同的模式。识别模式，比记住单个热点更有用。",
    "说到底，公众的关注是一种资源。用在哪里、持续多久，决定了这类事情能不能得到应有的回应。",
]

CLOSERS = [
    "把已知的信息摆在一起，态度可以保留，判断不必急着下。",
    "先记下事实，观点留给时间，这是眼下更稳妥的做法。",
    "等更多信息出来，再回头看今天的说法，或许会有新的感受。",
    "关注但不盲从，大概是面对热点最划算的姿态。",
    "事情还在发展，能确认的部分先确认，不能确认的先记着。",
    "放下手机之后，这件事还值得多想一会儿。",
    "与其站队，不如先弄清它的来龙去脉。",
    "热搜会过去，问题留下来的部分才值得被记住。",
]


def fallback(topic, idx):
    """AI 调用失败时的降级：按序号错开多套模板，拼一篇够长且各有差异的文。"""
    title = topic["title"]
    tp = topic["platform"]
    desc = topic.get("desc") or f"该话题在{tp}热榜受到广泛关注。"
    n = len(OPENERS)
    opener = OPENERS[(idx - 1) % n].format(t=title, tp=tp)
    # 用互不相同的步长取视角/分析，让 15 篇两两组合不重复
    persp = PERSPECTIVES[((idx - 1) * 3 + 1) % len(PERSPECTIVES)]
    anal = ANALYSES[((idx - 1) * 5 + 2) % len(ANALYSES)]
    clos = CLOSERS[((idx - 1) * 7 + 3) % len(CLOSERS)]
    ending = ENDING_QUESTIONS[(idx - 1) % len(ENDING_QUESTIONS)]
    parts = [
        f"{opener}一句\"{title}\"背后，牵动的是{tp}上大量用户的注意力。一个话题能在短时间内冲上热榜，"
        "往往说明它恰好碰到了公众情绪的某个节点：可能是共同的经历，可能是对未知的担忧，"
        "也可能是长期积累的情绪找到了出口。"
        "热榜的榜单每分钟都在刷新，能留下来被反复讨论的，通常不只是事件本身有多大，"
        "更在于它说中了人们心里那个还没来得及说清的疑问。",
        f"从目前公开的信息看，{desc}不过热榜信息更新很快，标题之外的细节仍有待更多来源交叉印证。"
        "在转述和传播中，原始表述容易被压缩、被二次加工，读者看到的版本和最初的报道未必完全一致。",
        f"{persp}这也是为什么，面对刷屏的消息，先弄清它从哪里来、是谁说的、有没有原始出处，比急着表态更重要。",
        "同一件事，站在不同立场的人会有完全不同的感受。当事人、旁观者、从业者、普通网友，各自的关切点并不相同；"
        "把这些视角放在一起，画面才会更完整，也更接近事情本来的样子。"
        "这也是为什么，同样一条消息，在不同人的转述里会呈现完全不同的重点——不是谁在说谎，"
        "而是每个人都在用自己的经验给空白处填上理解。承认这种差异，是讨论能继续下去的前提。",
        f"{anal}热点会过去，但问题未必随之消失。如果一次讨论只留下情绪而没有留下思考，这份关注就有些可惜了。"
        "更实际的追问是：这件事暴露的环节，有没有可能在别的地方重演？如果答案是有，"
        "那么今天多问一句、多核实一步，就不算白忙。",
        f"{clos}把事实和观点分开看：事实部分等权威渠道确认，观点部分允许不同声音并存。{ending}",
    ]
    return title, "\n\n".join(parts)


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
