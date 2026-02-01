import requests
import re
from pathlib import Path
from datetime import datetime

# -------------------------- 配置项（已修改输出文件名和之前一致） --------------------------
# 你的6个指定IPTV数据源
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/master/live.m3u"
]

# 输出m3u8文件名（修改为和之前一致：iptv_playlist.m3u8）
OUTPUT_FILE = "iptv_playlist.m3u8"
# EPG节目单地址（提升播放体验）
EPG_URL = "https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 过滤本地链接（避免无效内网地址）
FILTER_LOCAL_URLS = True

# -------------------------- 核心工具函数 --------------------------
def init_session():
    """初始化请求会话，添加通用请求头，忽略SSL验证"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive"
    })
    # 忽略SSL证书验证（避免海外源抓取报错）
    session.verify = False
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    return session

def fetch_source_content(session, url):
    """抓取单个数据源的内容"""
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()  # 抛出请求错误
        # 自动识别编码，避免中文乱码
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text.splitlines()  # 按行分割返回
    except Exception as e:
        print(f"⚠️  抓取失败 {url}：{str(e)[:50]}")
        return []

def filter_valid_lines(lines, processed_urls):
    """过滤有效行，提取#EXTINF和对应的播放链接"""
    valid_entries = []
    current_extinf = None
    local_hosts = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 提取#EXTINF行（频道信息）
        if line.startswith("#EXTINF:"):
            current_extinf = line
            continue

        # 提取对应的播放链接（紧跟#EXTINF行之后）
        if current_extinf and line.startswith(("http://", "https://")):
            # 过滤本地链接
            if FILTER_LOCAL_URLS:
                is_local = any(host in line.lower() for host in local_hosts)
                if is_local:
                    current_extinf = None
                    continue

            # 去重（避免重复URL）
            if line not in processed_urls:
                processed_urls.add(line)
                valid_entries.append((current_extinf, line))
            current_extinf = None

    return valid_entries

def generate_m3u8(entries):
    """生成标准的m3u8播放列表文件（文件名和之前一致）"""
    # 构建m3u8头部
    m3u8_content = [
        f"#EXTM3U x-tvg-url={EPG_URL}",
        f"# IPTV播放列表 - 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# 数据源数量：{len(IPTV_SOURCE_URLS)}个",
        f"# 有效频道数量：{len(entries)}个",
        f"# 兼容播放器：TVBox/Kodi/完美视频/亿家直播"
    ]

    # 添加所有有效频道条目
    for extinf, url in entries:
        m3u8_content.append("")
        m3u8_content.append(extinf)
        m3u8_content.append(url)

    # 写入文件（文件名：iptv_playlist.m3u8）
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(m3u8_content))
        print(f"\n✅ 生成成功！")
        print(f"✅ 文件名：{OUTPUT_FILE}（和之前保持一致）")
        print(f"✅ 有效频道：{len(entries)}个")
    except Exception as e:
        print(f"❌ 写入文件失败：{e}")

# -------------------------- 主程序入口 --------------------------
if __name__ == "__main__":
    print("="*60)
    print("IPTV m3u8播放列表生成工具（文件名和之前一致）")
    print("="*60)

    # 初始化
    session = init_session()
    processed_urls = set()  # 记录已处理的URL，用于去重
    all_valid_entries = []  # 存储所有有效频道条目

    # 批量抓取并处理所有数据源
    for idx, url in enumerate(IPTV_SOURCE_URLS, 1):
        print(f"\n[{idx}/{len(IPTV_SOURCE_URLS)}] 正在抓取：{url.split('/')[-1]}")
        # 抓取数据源内容
        source_lines = fetch_source_content(session, url)
        if not source_lines:
            continue
        # 过滤有效条目
        valid_entries = filter_valid_lines(source_lines, processed_urls)
        all_valid_entries.extend(valid_entries)
        print(f"   提取有效频道：{len(valid_entries)}个")

    # 生成m3u8文件（文件名：iptv_playlist.m3u8）
    if all_valid_entries:
        generate_m3u8(all_valid_entries)
    else:
        print("\n❌ 无有效频道，无法生成m3u8文件")
