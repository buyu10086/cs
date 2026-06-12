import re
import requests
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 定义文件路径
M3U8_SOURCES_FILE = "m3u8_sources.txt"
IPTV_SOURCES_FILE = "iptv_sources.txt"
OUTPUT_PLAYLIST_FILE = "iptv_playlist.m3u8"

# 匹配CCTV等频道名的正则（可根据实际情况扩展）
CHANNEL_PATTERN = re.compile(r'(cctv\d+|CCTV\d+|卫视|高清)', re.IGNORECASE)
# 匹配有效的播放链接的正则
URL_PATTERN = re.compile(r'https?://[^\s]+', re.IGNORECASE)

# 配置请求重试策略
def requests_retry_session(
    retries=3,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504),
    session=None,
):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def read_m3u8_sources(file_path):
    """读取m3u8_sources.txt，提取频道和m3u8链接"""
    sources = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"警告：文件 {file_path} 不存在，跳过读取")
        return sources
    
    for line in lines:
        line = line.strip()
        # 跳过注释和空行
        if not line or line.startswith('#'):
            continue
        # 提取频道名（从URL中解析）
        if 'cctv' in line.lower() or '卫视' in line:
            channel_match = CHANNEL_PATTERN.search(line)
            if channel_match:
                channel_name = channel_match.group(1).upper()
                sources.append((channel_name, line))
    return sources

def fetch_remote_iptv(url):
    """获取远程IPTV源文件内容（带重试机制）"""
    try:
        session = requests_retry_session()
        response = session.get(url, timeout=15)
        response.encoding = 'utf-8'
        return response.text
    except Exception as e:
        print(f"获取远程IPTV失败 {url}: {e}")
        return ""

def read_iptv_sources(file_path):
    """读取iptv_sources.txt，解析本地/远程IPTV源"""
    sources = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"警告：文件 {file_path} 不存在，跳过读取")
        return sources
    
    for line in lines:
        line = line.strip()
        # 跳过注释和空行
        if not line or line.startswith('#'):
            continue
        
        # 如果是远程URL，先下载内容再解析
        if line.startswith('http'):
            remote_content = fetch_remote_iptv(line)
            if remote_content:
                # 解析远程内容中的频道和链接（支持 频道名,链接 格式）
                for remote_line in remote_content.split('\n'):
                    remote_line = remote_line.strip()
                    if not remote_line or ',' not in remote_line:
                        continue
                    # 分割频道名和链接
                    channel_name, link = remote_line.split(',', 1)
                    channel_name = channel_name.strip()
                    link = link.strip()
                    if channel_name and link:
                        sources.append((channel_name, link))
        else:
            # 本地文件（本示例暂不处理，可根据需求扩展）
            pass
    return sources

def generate_m3u8_playlist(sources, output_file):
    """生成标准的m3u8播放列表"""
    m3u8_header = """#EXTM3U x-tvg-url="https://epg.112114.xyz/pp.xml"
"""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(m3u8_header)
        # 去重（按频道名去重）
        unique_sources = {}
        for channel, link in sources:
            if channel not in unique_sources:
                unique_sources[channel] = link
        
        # 写入每个节目源
        for channel_name, link in unique_sources.items():
            # 标准m3u8格式
            f.write(f"#EXTINF:-1 group-title=\"IPTV直播\" tvg-name=\"{channel_name}\",{channel_name}\n")
            f.write(f"{link}\n\n")
    return unique_sources

def main():
    """主函数：整合所有源并生成m3u8播放列表"""
    # 读取两个源文件
    m3u8_sources = read_m3u8_sources(M3U8_SOURCES_FILE)
    iptv_sources = read_iptv_sources(IPTV_SOURCES_FILE)
    
    # 合并所有源
    all_sources = m3u8_sources + iptv_sources
    
    # 生成m3u8播放列表
    unique_sources = generate_m3u8_playlist(all_sources, OUTPUT_PLAYLIST_FILE)
    print(f"成功生成播放列表：{OUTPUT_PLAYLIST_FILE}")
    print(f"共读取 {len(all_sources)} 个节目源（去重后 {len(unique_sources)} 个）")

if __name__ == "__main__":
    main()
