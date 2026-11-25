"""临时探测：在 Actions 境外环境测试各平台能否抓到真实封面图。跑完即删。"""
import json, re, requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

def get_og_image(url):
    r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    html = r.text
    pats = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)',
    ]
    for p in pats:
        m = re.search(p, html, re.I)
        if m:
            return m.group(1)
    return None

def bilibili_cover(url):
    m = re.search(r'(BV[0-9A-Za-z]{10})', url)
    if not m:
        return None
    try:
        d = requests.get(f"https://api.bilibili.com/x/web-interface/view?bvid={m.group(1)}",
                         headers=HEADERS, timeout=12).json()
        return (d.get("data") or {}).get("pic")
    except Exception:
        return None

def main():
    items = json.load(open("hot.json", encoding="utf-8"))["items"]
    hit = 0
    for it in items:
        pf, url = it["platform"], it["url"]
        img = None
        src = "-"
        if pf == "B站":
            img, src = bilibili_cover(url), "bili-api"
        if not img:
            try:
                img, src = get_og_image(url), "og:image"
            except Exception as e:
                src = f"err:{type(e).__name__}"
        ok = "-"
        if img:
            if img.startswith("//"):
                img = "https:" + img
            try:
                rr = requests.get(img, headers=HEADERS, timeout=15, stream=True)
                ct = rr.headers.get("Content-Type", "")
                size = int(rr.headers.get("Content-Length") or 0)
                ok = "OK" if "image" in ct and size > 8000 else f"BAD({ct[:12]},{size})"
                if ok == "OK":
                    hit += 1
            except Exception as e:
                ok = f"dl-err:{type(e).__name__}"
        print(f"[{pf}] {it['title'][:16]:<18} | {src:<12} | {ok:<14} | {str(img)[:70]}", flush=True)
    print(f"\n=== 真实图可抓: {hit}/{len(items)} ===", flush=True)

if __name__ == "__main__":
    main()
