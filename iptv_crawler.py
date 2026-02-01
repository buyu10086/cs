import requests
import re
from pathlib import Path
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -------------------------- 配置项（优化：添加GH代理，适配kakaxi源） --------------------------
# 你的6个指定IPTV数据源（kakaxi源添加ghproxy代理，避免访问失败；保持文件名不变）
IPTV_SOURCE_URLS = [
    # kakaxi源添加国内代理（ghproxy），确保国内可访问
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    # 其他核心数据源（部分添加代理，提升国内访问成功率）
    "https://gh-proxy.com/https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/master/live.m3u"
]

# 输出m3u8文件名（保持和之前一致：iptv_playlist.m3u8）
OUTPUT_FILE = "iptv_playlist.m3u8"
# EPG节目单地址（提升播放体验）
EPG_URL = "https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 过滤本地链接（避免无效内网地址）
FILTER_LOCAL_URLS = True
# 请求重试次数（解决偶尔网络波动）
REQUEST_RETRY_TIMES = 3

# -------------------------- 核心工具函数（优化：放宽过滤规则，适配kakaxi源格式） --------------------------
def init_session():
    """初始化请求会话，添加通用请求头、SSL忽略、重试机制"""
    session = requests.Session()
    
    # 添加请求头，模拟浏览器访问
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive"
    })
    
    # 配置重试机制（连接失败、超时自动重试）
    retry_strategy = Retry(
        total=REQUEST_RETRY_TIMES,
        backoff_factor=1,  # 重试间隔：1s, 2s, 4s...
        status_forcelist=[429, 500, 502, 503, 504]  # 这些状态码触发重试
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 忽略SSL证书验证（避免海外源/代理源抓取报错）
    session.verify = False
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    
    return session

def fetch_source_content(session, url):
    """抓取单个数据源的内容"""
    try:
        response = session.get(url, timeout=40)  # 延长超时，适配代理源
        response.raise_for_status()  # 抛出HTTP请求错误（4xx/5xx）
        
        # 自动识别编码，避免中文乱码（适配kakaxi源的中文频道名）
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text.splitlines()  # 按行分割返回，方便后续处理
    except Exception as e:
        print(f"⚠️  抓取失败 {url}：{str(e)[:50]}")
        return []

def filter_valid_lines(lines, processed_urls):
    """
    优化：放宽过滤规则，适配kakaxi源的特殊格式
    不再强制要求#EXTINF和链接紧跟，支持间隔空白/注释行，避免误过滤
    """
    valid_entries = []
    current_extinf = None
    local_hosts = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 1. 提取#EXTINF行（频道信息），保留当前有效EXTINF，不强制立即绑定链接
        if line.startswith("#EXTINF:"):
            current_extinf = line
            continue

        # 2. 跳过注释行（不重置current_extinf），适配kakaxi源中的注释间隔
        if line.startswith("#") and not line.startswith("#EXTINF:"):
            continue

        # 3. 提取对应的播放链接（只要有未绑定的current_extinf，就进行绑定）
        if current_extinf and line.startswith(("http://", "https://")):
            # 过滤本地链接，剔除无效内网地址
            if FILTER_LOCAL_URLS:
                is_local = any(host in line.lower() for host in local_hosts)
                if is_local:
                    current_extinf = None
                    continue

            # 去重（避免重复URL，减少无效频道）
            if line not in processed_urls:
                processed_urls.add(line)
                valid_entries.append((current_extinf, line))

            # 绑定成功后重置，准备下一个频道
            current_extinf = None

    return valid_entries

def generate_m3u8(entries):
    """生成标准的m3u8播放列表文件（文件名保持iptv_playlist.m3u8）"""
    # 构建m3u8头部，保留完整信息（符合m3u8标准格式）
    m3u8_content = [
        f"#EXTM3U x-tvg-url={EPG_URL}",
        f"# IPTV播放列表 - 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# 数据源数量：{len(IPTV_SOURCE_URLS)}个（含kakaxi系列源，已添加国内代理）",
        f"# 有效频道数量：{len(entries)}个",
        f"# 兼容播放器：TVBox/Kodi/完美视频/亿家直播"
    ]

    # 添加所有有效频道条目（保持标准m3u8格式，空行分隔提升可读性）
    for extinf, url in entries:
        m3u8_content.append("")
        m3u8_content.append(extinf)
        m3u8_content.append(url)

    # 写入文件（文件名：iptv_playlist.m3u8，覆盖旧文件，utf-8编码确保中文正常显示）
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(m3u8_content))
        print(f"\n✅ 生成成功！")
        print(f"✅ 文件名：{OUTPUT_FILE}（和之前保持一致）")
        print(f"✅ 有效频道：{len(entries)}个（含kakaxi系列源频道）")
    except Exception as e:
        print(f"❌ 写入文件失败：{e}")

# -------------------------- 主程序入口 --------------------------
if __name__ == "__main__":
    print("="*60)
    print("IPTV m3u8播放列表生成工具（适配kakaxi源，文件名一致）")
    print("="*60)

    # 初始化资源
    session = init_session()
    processed_urls = set()  # 记录已处理的URL，用于去重（避免重复频道）
    all_valid_entries = []  # 存储所有有效频道条目

    # 批量抓取并处理所有数据源（含kakaxi源，带进度提示）
    for idx, url in enumerate(IPTV_SOURCE_URLS, 1):
        source_name = url.split("/")[-1]
        if "kakaxi" in url:
            source_name += "（kakaxi源，已代理）"
        print(f"\n[{idx}/{len(IPTV_SOURCE_URLS)}] 正在抓取：{source_name}")
        
        # 抓取数据源内容
        source_lines = fetch_source_content(session, url)
        if not source_lines:
            continue
        
        # 过滤有效条目（适配kakaxi格式，不丢失频道）
        valid_entries = filter_valid_lines(source_lines, processed_urls)
        all_valid_entries.extend(valid_entries)
        print(f"   提取有效频道：{len(valid_entries)}个")

    # 生成最终的m3u8文件
    if all_valid_entries:
        generate_m3u8(all_valid_entries)
    else:
        print("\n❌ 无有效频道，无法生成m3u8文件")
