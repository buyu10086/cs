import requests
import re
from pathlib import Path

# 配置文件路径
IPTV_SOURCES_PATH = Path("/iptv_sources.txt")
M3U8_SOURCES_PATH = Path("/m3u8_sources.txt")

# 正则表达式匹配 频道名,播放链接 格式（非m3u8）
CHANNEL_LINK_PATTERN = re.compile(r'^([^,]+),([^,]+)$', re.MULTILINE)

def load_remote_source(url):
    """加载远程节目源文件，返回文本内容"""
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except Exception as e:
        print(f"加载远程源失败 {url}: {e}")
        return ""

def parse_iptv_sources():
    """解析iptv_sources.txt中的远程链接，提取非m3u8格式的节目源"""
    parsed_channels = []
    
    # 读取iptv_sources.txt中的远程链接
    if not IPTV_SOURCES_PATH.exists():
        print(f"错误：{IPTV_SOURCES_PATH} 文件不存在")
        return parsed_channels
    
    with open(IPTV_SOURCES_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # 提取所有远程链接（过滤注释和空行）
    remote_urls = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("http://", "https://")):
            remote_urls.append(line)
    
    # 下载并解析每个远程链接的内容
    for url in remote_urls:
        source_text = load_remote_source(url)
        if not source_text:
            continue
        
        # 匹配 频道名,播放链接 格式的行
        matches = CHANNEL_LINK_PATTERN.findall(source_text)
        for channel_name, link in matches:
            # 过滤掉m3u8格式的链接（只保留非m3u8的）
            if not link.endswith(".m3u8"):
                parsed_channels.append(f"{channel_name},{link}")
    
    return parsed_channels

def load_existing_m3u8_sources():
    """加载m3u8_sources.txt中原有的内容（保留注释和原有m3u8链接）"""
    existing_content = []
    if M3U8_SOURCES_PATH.exists():
        with open(M3U8_SOURCES_PATH, "r", encoding="utf-8") as f:
            existing_content = f.readlines()
    # 去除空行和换行符，保留有效内容
    existing_content = [line.rstrip("\n") for line in existing_content if line.strip() or line.startswith("#")]
    return existing_content

def merge_and_write_sources(existing_content, new_channels):
    """合并原有内容和新解析的频道，写入m3u8_sources.txt"""
    # 合并内容：原有内容 + 新解析的非m3u8频道
    merged_content = existing_content.copy()
    
    # 添加分隔注释
    if new_channels:
        merged_content.append("\n# 从iptv_sources解析的非m3u8节目源")
        merged_content.extend(new_channels)
    
    # 写入文件
    with open(M3U8_SOURCES_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(merged_content))
    
    print(f"成功写入：{len(merged_content)} 行内容到 {M3U8_SOURCES_PATH}")
    print(f"其中新增非m3u8节目源：{len(new_channels)} 个")

def main():
    """主流程"""
    # 1. 解析iptv_sources中的非m3u8节目源
    new_channels = parse_iptv_sources()
    
    # 2. 加载原有m3u8_sources内容
    existing_content = load_existing_m3u8_sources()
    
    # 3. 合并并写入
    merge_and_write_sources(existing_content, new_channels)

if __name__ == "__main__":
    main()
