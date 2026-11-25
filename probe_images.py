"""临时探测 v2：测试搜索引擎图片 + B站API 能否拿到真实新闻图。跑完即删。"""
import json, re, html, requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
H = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}

def bing_images(q):
    try:
        r = requests.get("https://www.bing.com/images/search", params={"q": q, "form": "HDRSC2"},
                         headers=H, timeout=15)
        urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', r.text)
        return [html.unescape(u) for u in urls[:3]]
    except Exception as e:
        return [f"ERR:{type(e).__name__}"]

def baidu_images(q):
    try:
        r = requests.get("https://image.baidu.com/search/index",
                         params={"tn": "baiduimage", "word": q}, headers=H, timeout=15)
        urls = re.findall(r'"objURL":"(.*?)"', r.text)
        if not urls:
            urls = re.findall(r'"middleURL":"(.*?)"', r.text)
        return [u.replace("\\/", "/") for u in urls[:3]]
    except Exception as e:
        return [f"ERR:{type(e).__name__}"]

def bilibili_cover(url):
    m = re.search(r'(BV[0-9A-Za-z]{10})', url)
    if not m:
        return f"NO-BV:{url[:40]}"
    try:
        r = requests.get(f"https://api.bilibili.com/x/web-interface/view?bvid={m.group(1)}",
                         headers=H, timeout=12)
        d = r.json()
        return (d.get("data") or {}).get("pic") or f"API-code:{d.get('code')}"
    except Exception as e:
        return f"ERR:{type(e).__name__}"

def check_img(u):
    if not u or u.startswith("ERR") or u.startswith("NO-") or u.startswith("API-"):
        return u
    try:
        r = requests.get(u, headers=H, timeout=12, stream=True)
        ct = r.headers.get("Content-Type", "")
        size = int(r.headers.get("Content-Length") or 0)
        return "OK" if "image" in ct and size > 15000 else f"BAD({ct[:10]},{size})"
    except Exception as e:
        return f"DL-ERR:{type(e).__name__}"

def main():
    items = json.load(open("hot.json", encoding="utf-8"))["items"]
    for it in items[:6]:
        q = it["title"][:20]
        bing = bing_images(q)
        baidu = baidu_images(q)
        print(f"\n[{it['platform']}] {q}", flush=True)
        print(f"  bing[0]: {check_img(bing[0]) if bing else 'EMPTY'} | {str(bing[0])[:70] if bing else ''}", flush=True)
        print(f"  baidu[0]: {check_img(baidu[0]) if baidu else 'EMPTY'} | {str(baidu[0])[:70] if baidu else ''}", flush=True)
        if it["platform"] == "B站":
            bv = bilibili_cover(it["url"])
            print(f"  bili-api: {check_img(bv)} | {str(bv)[:70]}", flush=True)
    print("\n=== done ===", flush=True)

if __name__ == "__main__":
    main()
