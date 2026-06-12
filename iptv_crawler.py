import re
import requests
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ========== 配置区 - 可自行修改 ==========
M3U8_SOURCES_FILE = "m3u8_sources.txt"
IPTV_SOURCES_FILE = "iptv_sources.txt"
OUTPUT_PLAYLIST_FILE = "iptv_playlist.m3u8"
# 黑名单：过滤失效域名、违规协议、无效链接
BLACK_DOMAIN = {"vip.lzcdn2.com", "vip1.lz-cdn1.com"}  # 报错CDN域名
BLACK_PROTOCOL = {"p2p", "rtmp", "udp"}               # 不支持的协议
# 正则规则
CHANNEL_PATTERN = re.compile(r'(cctv\d+|CCTV\d+|卫视|电台|新闻)', re.IGNORECASE)
URL_PATTERN = re.compile(r'https?://[^\s]+', re.IGNORECASE)

# 请求重试配置
def requests_retry_session(retries=3, backoff_factor=0.3):
    session = requests.Session()
    retry = Retry(total=retries, read=retries, connect=retries, status_forcelist=(500, 502, 504))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https", adapter)
    return session

def is_valid_url(link):
    """校验链接：过滤黑名单协议、域名"""
    link_lower = link.lower()
    # 过滤协议
    for proto in BLACK_PROTOCOL:
        if link_lower.startswith(f"{proto}://") or link_lower.startswith(f"{proto}/"):
            return False
    # 过滤黑名单域名
    try:
        domain = urlparse(link).netloc
        if domain in BLACK_DOMAIN:
            return False
    except:
        return False
    return True

def read_m3u8_sources(file_path):
    sources = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f.readlines():
            line = line.strip()
            if not line or line.startswith('#') or not is_valid_url(line):
                continue
            channel_match = CHANNEL_PATTERN.search(line)
            channel_name = channel_match.group(1).upper() if channel_match else "未知频道"
            sources.append((channel_name, line))
    return sources

def fetch_remote_iptv(url):
    try:
        session = requests_retry_session()
        response = session.get(url, timeout=15)
        response.encoding = 'utf-8'
        return response.text
    except Exception as e:
        print(f"远程源获取失败 {url}: {e}")
        return ""

def read_iptv_sources(file_path):
    sources = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f.readlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 远程文本源（如zo.gt.tc）
            if line.startswith(("http://", "https://")):
                remote_content = fetch_remote_iptv(line)
                if not remote_content:
                    continue
                for remote_line in remote_content.split('\n'):
                    remote_line = remote_line.strip()
                    if ',' not in remote_line or not remote_line:
                        continue
                    channel_name, link = remote_line.split(',', 1)
                    channel_name = channel_name.strip()
                    link = link.strip()
                    # 二次校验链接有效性
                    if channel_name and link and is_valid_url(link):
                        sources.append((channel_name, link))
    return sources

def generate_m3u8_playlist(sources):
    # 标准M3U8头部 + EPG
    header = """#EXTM3U x-tvg-url="https://epg.112114.xyz/pp.xml"
# 分组说明：IPTV直播 | 广播电台 | 影视点播
"""
    unique_sources = {}
    for name, link in sources:
        if name not in unique_sources:
            unique_sources[name] = link

    # 分类写入：直播 / 电台 / 点播
    live_list = []
    radio_list = []
    video_list = []
    for name, link in unique_sources.items():
        if "电台" in name or "调频" in name:
            radio_list.append((name, link))
        elif ".mp4" in link.lower() or "影视" in name or "电影" in name:
            video_list.append((name, link))
        else:
            live_list.append((name, link))

    with open(OUTPUT_PLAYLIST_FILE, 'w', encoding='utf-8') as f:
        f.write(header)
        # 1. 直播频道
        f.write("#EXTINF:-1 group-title=\"IPTV直播\",=== 央视/卫视直播 ===\n")
        for name, link in live_list:
            f.write(f"#EXTINF:-1 group-title=\"IPTV直播\" tvg-name=\"{name}\",{name}\n{link}\n\n")
        # 2. 广播电台
        f.write("#EXTINF:-1 group-title=\"广播电台\",=== 音频电台 ===\n")
        for name, link in radio_list:
            f.write(f"#EXTINF:-1 group-title=\"广播电台\" tvg-name=\"{name}\",{name}\n{link}\n\n")
        # 3. 影视点播
        f.write("#EXTINF:-1 group-title=\"影视点播\",=== 影视点播 ===\n")
        for name, link in video_list:
            f.write(f"#EXTINF:-1 group-title=\"影视点播\" tvg-name=\"{name}\",{name}\n{link}\n\n")

def main():
    print("开始读取源文件并过滤无效链接...")
    m3u8_src = read_m3u8_sources(M3U8_SOURCES_FILE)
    iptv_src = read_iptv_sources(IPTV_SOURCES_FILE)
    all_src = m3u8_src + iptv_src
    generate_m3u8_playlist(all_src)
    print(f"生成完成！总链接数：{len(all_src)}，去重后有效链接：{len(dict(all_src))}")
    print(f"输出文件：{OUTPUT_PLAYLIST_FILE}")

if __name__ == "__main__":
    main()
