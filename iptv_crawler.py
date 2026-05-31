import requests
import re
from urllib.parse import urlparse

# 配置
SOURCE_LIST_FILE = "iptv_sources.txt"
OUTPUT_M3U8 = "iptv_playlist.m3u8"
TIMEOUT = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def github_to_raw(url):
    """把 GitHub 网页链接转为 raw 链接"""
    if "github.com" in url and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    return url

def test_stream_valid(link):
    """简单测试链接是否可连通（非严格播放检测）"""
    try:
        parsed = urlparse(link)
        if not parsed.scheme or not parsed.netloc:
            return False
        resp = requests.head(link, headers=HEADERS, timeout=2)
        return resp.status_code in (200, 206)
    except:
        return False

def guess_channel_name(link):
    """从链接里智能识别频道名"""
    match = re.search(r'([cC][cC][tT][vV][-_]?\d+)', link, re.I)
    if match:
        return match.group(1).upper().replace('_', '').replace('-', '')

    match = re.search(r'([a-zA-Z]+[-_]\d+)', link)
    if match:
        return match.group(1)

    match = re.search(r'([\u4e00-\u9fa5]+)', link)
    if match:
        return match.group(1)[:8]

    return None

def get_links_from_url(url):
    """抓取单个源里的所有 m3u8 直播流"""
    try:
        url = github_to_raw(url)
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        content = resp.text

        pattern = re.compile(r'https?://\S+\.m3u8', re.IGNORECASE)
        return pattern.findall(content)
    except Exception as e:
        print(f"抓取失败 {url[:50]}…: {str(e)[:40]}")
        return []

def main():
    # 读取源列表
    try:
        with open(SOURCE_LIST_FILE, 'r', encoding='utf-8') as f:
            source_urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"错误：未找到 {SOURCE_LIST_FILE}")
        return

    # 批量抓取
    all_links = []
    for u in source_urls:
        print(f"抓取源: {u[:60]}")
        links = get_links_from_url(u)
        all_links.extend(links)

    # 去重
    all_links = list(dict.fromkeys(all_links))
    print(f"\n去重后共 {len(all_links)} 个链接，开始检测有效性…")

    # 过滤有效链接
    valid_links = []
    for link in all_links:
        if test_stream_valid(link):
            valid_links.append(link)
            print(f"有效: {link[:70]}")
        else:
            print(f"无效: {link[:70]}")

    if not valid_links:
        print("没有可用直播源")
        return

    # 生成标准 M3U8
    m3u_lines = ["#EXTM3U"]
    for link in valid_links:
        name = guess_channel_name(link) or f"频道{len(m3u_lines)//2 + 1:02d}"
        m3u_lines.append(f'#EXTINF:-1 tvg-name="{name}",{name}')
        m3u_lines.append(link)

    # 写入文件
    with open(OUTPUT_M3U8, 'w', encoding='utf-8') as f:
        f.write('\n'.join(m3u_lines))

    print(f"\n完成！生成标准 IPTV 播放列表：{OUTPUT_M3U8}")
    print(f"有效源总数：{len(valid_links)}")

if __name__ == "__main__":
    main()
