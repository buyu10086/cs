import requests
import re
import datetime
from typing import List, Dict, Tuple

# 超时时间设置（单位：秒），响应时间越短，认为源越快
TIMEOUT = 3

# 你的公开 IPTV 源列表（从你提供的链接整理）
IPTV_SOURCES = [
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/master/live.m3u"
]

def fetch_remote_iptv(source_url: str) -> str:
    """
    拉取远程 IPTV 源的内容（支持 txt 和 m3u 格式）
    失败则返回空字符串
    """
    try:
        response = requests.get(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True
        )
        # 编码自动识别，避免中文乱码
        response.encoding = response.apparent_encoding or 'utf-8'
        return response.text if response.status_code in (200, 206) else ""
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
            requests.exceptions.RequestException):
        print(f"⚠️  拉取失败：{source_url}")
        return ""

def filter_cctv_channels(iptv_content: str, collected_channels: Dict[str, List[str]]) -> None:
    """
    从 IPTV 内容中筛选 CCTV 频道，去重并收集播放源
    支持 m3u 格式（#EXTINF 开头）和纯文本格式
    """
    # 正则1：匹配 m3u 格式（#EXTINF:...,[频道名]\n[播放源]）
    m3u_pattern = re.compile(r'#EXTINF:.+?,(?P<name>.+?CCTV.+?)\n(?P<url>https?://.+?)\n', re.IGNORECASE)
    # 正则2：匹配纯文本格式（含 CCTV 的播放源，同时尝试提取频道名）
    txt_pattern = re.compile(r'(?P<name>.*?CCTV.*?)\s*[:：]?\s*(?P<url>https?://.+?m3u8.*?)', re.IGNORECASE)
    # 正则3：匹配单独的 CCTV 播放源（仅 url 含 CCTV）
    url_only_pattern = re.compile(r'(?P<url>https?://.+?CCTV.+?m3u8)', re.IGNORECASE)

    # 1. 处理 m3u 格式
    m3u_matches = m3u_pattern.findall(iptv_content)
    for name, url in m3u_matches:
        name = name.strip()
        url = url.strip()
        if name not in collected_channels:
            collected_channels[name] = []
        if url not in collected_channels[name]:
            collected_channels[name].append(url)

    # 2. 处理纯文本格式（带频道名）
    txt_matches = txt_pattern.findall(iptv_content)
    for name, url in txt_matches:
        name = name.strip() if name else f"未知CCTV频道（{url[-20:]}）"
        url = url.strip()
        if name not in collected_channels:
            collected_channels[name] = []
        if url not in collected_channels[name]:
            collected_channels[name].append(url)

    # 3. 处理仅含 CCTV 的播放源（补充默认频道名）
    url_only_matches = url_only_pattern.findall(iptv_content)
    for url in url_only_matches:
        url = url.strip()
        # 从 url 中提取简易频道名
        cctv_match = re.search(r'CCTV[-_]?(\d+|\+|新闻)', url, re.IGNORECASE)
        name = f"CCTV-{cctv_match.group(1)}" if cctv_match else "CCTV 未知频道"
        if name not in collected_channels:
            collected_channels[name] = []
        if url not in collected_channels[name]:
            collected_channels[name].append(url)

def cctv_channel_sort(channels: List[Dict]) -> List[Dict]:
    """
    CCTV频道排序：按频道号正序排列（如CCTV-1 < CCTV-2 < CCTV-13 < CCTV-5+）
    """
    def extract_channel_number(channel_name: str) -> Tuple[int, str]:
        """提取频道号，处理特殊频道（如CCTV-5+）"""
        # 正则匹配频道号（数字部分 + 可能的后缀）
        match = re.search(r'CCTV[-_]?(\d+)([+]?)', channel_name, re.IGNORECASE)
        if match:
            number = int(match.group(1))
            suffix = match.group(2)  # 处理5+、16+这类后缀
            return (number, suffix)
        # 匹配非数字频道（如CCTV-新闻）
        if re.search(r'新闻', channel_name, re.IGNORECASE):
            return (100, "新闻")
        if re.search(r'财经', channel_name, re.IGNORECASE):
            return (101, "财经")
        # 其他非数字频道放在末尾
        return (999, channel_name)
    
    # 按提取的频道号进行排序
    return sorted(channels, key=lambda x: extract_channel_number(x['name']))

def test_source_speed(source_url: str) -> float:
    """
    测试播放源的响应速度，返回响应时间（单位：秒）
    若源不可用（超时、连接失败、状态码非200/206），返回一个极大值
    """
    try:
        start_time = datetime.datetime.now()
        # 只请求头部信息（不下载完整内容，提高测速效率）
        response = requests.head(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True  # 允许重定向，兼容部分跳转源
        )
        end_time = datetime.datetime.now()
        response_time = (end_time - start_time).total_seconds()
        
        # 放宽状态码要求，兼容 200（成功）和 206（分段传输，流媒体常见）
        return response_time if response.status_code in (200, 206) else float('inf')
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
            requests.exceptions.RequestException):
        # 各种异常情况，认为源不可用，返回极大值
        return float('inf')

def auto_select_fast_source(channel: Dict) -> Dict:
    """
    为单个CCTV频道自动选择最快的可用播放源
    """
    source_list = channel.get('sources', [])
    if not source_list:
        channel['fastest_source'] = None
        channel['response_time'] = None
        return channel
    
    # 对每个源进行测速，生成（响应时间，源地址）的列表（跳过空值）
    source_speed = []
    for source in source_list:
        if not source:
            continue
        speed = test_source_speed(source)
        source_speed.append((speed, source))
    
    # 筛选出可用源（响应时间不是极大值），并按响应时间升序排序
    available_sources = [(speed, url) for speed, url in source_speed if speed != float('inf')]
    if not available_sources:
        channel['fastest_source'] = None
        channel['response_time'] = '无可用源'
        return channel
    
    # 选择响应时间最短的源
    fastest_speed, fastest_url = sorted(available_sources, key=lambda x: x[0])[0]
    channel['fastest_source'] = fastest_url
    channel['response_time'] = f"{fastest_speed:.4f} 秒"
    
    return channel

def main():
    """主函数：拉取远程源 → 筛选CCTV → 排序 → 选择快速源"""
    print("=== 开始拉取远程 IPTV 源（请稍候）===")
    # 用于收集去重后的 CCTV 频道（key：频道名，value：播放源列表）
    collected_cctv = {}

    # 步骤1：遍历所有远程 IPTV 源，拉取并筛选 CCTV 频道
    for i, source_url in enumerate(IPTV_SOURCES, 1):
        print(f"\n{i}/{len(IPTV_SOURCES)} 拉取中：{source_url}")
        iptv_content = fetch_remote_iptv(source_url)
        if not iptv_content:
            continue
        # 筛选 CCTV 频道并收集
        filter_cctv_channels(iptv_content, collected_cctv)
        print(f"   已收集到 {len(collected_cctv)} 个不同的 CCTV 频道（去重后）")

    # 步骤2：转换为脚本所需的频道数据格式
    cctv_channels = [
        {'name': name, 'sources': sources}
        for name, sources in collected_cctv.items()
    ]
    if not cctv_channels:
        print("\n❌ 未筛选到任何 CCTV 频道，请检查 IPTV 源是否有效")
        return

    # 步骤3：CCTV 频道排序
    sorted_channels = cctv_channel_sort(cctv_channels)
    print(f"\n=== 已完成 CCTV 频道排序（共 {len(sorted_channels)} 个频道）===")

    # 步骤4：为每个排序后的频道选择最快播放源
    print("\n=== 正在自动检测最优播放源（测速中，耗时较长，请耐心等待）===")
    final_result = [auto_select_fast_source(channel) for channel in sorted_channels]

    # 步骤5：输出最终结果
    print("\n=== 最终结果（排序后 + 快速源）===")
    valid_count = 0
    for idx, channel in enumerate(final_result, 1):
        if channel['fastest_source']:
            valid_count += 1
        print(f"\n{idx}. 频道名称：{channel['name']}")
        print(f"   最快播放源：{channel['fastest_source'] or '无可用播放源'}")
        print(f"   响应时间：{channel['response_time']}")
    
    print(f"\n=== 检测完成：共 {valid_count}/{len(final_result)} 个频道拥有可用播放源 ===")

if __name__ == "__main__":
    # 安装依赖提示（若未安装requests）
    try:
        import requests
    except ImportError:
        print("请先安装requests依赖：pip install requests")
    else:
        main()
