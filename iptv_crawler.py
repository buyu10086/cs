import requests
import re
import datetime
from typing import List, Dict, Tuple

# 超时时间设置（单位：秒）
TIMEOUT = 3

# 你的公开 IPTV 源列表
IPTV_SOURCES = [
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/main/live.m3u"
]

def fetch_remote_iptv(source_url: str) -> str:
    try:
        response = requests.get(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True
        )
        response.encoding = response.apparent_encoding or 'utf-8'
        return response.text if response.status_code in (200, 206) else ""
    except Exception as e:
        print(f"⚠️  拉取失败：{source_url}（{str(e)}）")
        return ""

def filter_cctv_channels(iptv_content: str, collected_channels: Dict[str, List[str]]) -> None:
    m3u_pattern = re.compile(r'#EXTINF:.+?,(?P<name>.+?CCTV.+?)\n(?P<url>https?://.+?)\n', re.IGNORECASE)
    txt_pattern = re.compile(r'(?P<name>.*?CCTV.*?)\s*[:：]?\s*(?P<url>https?://.+?m3u8.*?)', re.IGNORECASE)
    url_only_pattern = re.compile(r'(?P<url>https?://.+?CCTV.+?m3u8)', re.IGNORECASE)

    for name, url in m3u_pattern.findall(iptv_content):
        name, url = name.strip(), url.strip()
        collected_channels.setdefault(name, []).append(url)
    for name, url in txt_pattern.findall(iptv_content):
        name = name.strip() if name else f"CCTV-未知频道（{url[-20:]}）"
        collected_channels.setdefault(name, []).append(url.strip())
    for url in url_only_matches:
        cctv_match = re.search(r'CCTV[-_]?(\d+|\+|新闻)', url, re.IGNORECASE)
        name = f"CCTV-{cctv_match.group(1)}" if cctv_match else "CCTV-未知频道"
        collected_channels.setdefault(name, []).append(url.strip())
    # 去重播放源
    for name in collected_channels:
        collected_channels[name] = list(set(collected_channels[name]))

def cctv_channel_sort(channels: List[Dict]) -> List[Dict]:
    def extract_channel_number(channel_name: str) -> Tuple[int, str]:
        match = re.search(r'CCTV[-_]?(\d+)([+]?)', channel_name, re.IGNORECASE)
        if match:
            return (int(match.group(1)), match.group(2))
        if re.search(r'新闻', channel_name, re.IGNORECASE):
            return (100, "新闻")
        if re.search(r'财经', channel_name, re.IGNORECASE):
            return (101, "财经")
        return (999, channel_name)
    return sorted(channels, key=lambda x: extract_channel_number(x['name']))

def test_source_speed(source_url: str) -> float:
    try:
        start_time = datetime.datetime.now()
        response = requests.head(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True
        )
        response_time = (datetime.datetime.now() - start_time).total_seconds()
        return response_time if response.status_code in (200, 206) else float('inf')
    except Exception:
        return float('inf')

def auto_select_fast_source(channel: Dict) -> Dict:
    source_list = channel.get('sources', [])
    if not source_list:
        channel.update({'fastest_source': None, 'response_time': '无可用源'})
        return channel
    source_speed = [(test_source_speed(s), s) for s in source_list if s]
    available = [(sp, url) for sp, url in source_speed if sp != float('inf')]
    if not available:
        channel.update({'fastest_source': None, 'response_time': '无可用源'})
        return channel
    fastest_sp, fastest_url = sorted(available, key=lambda x: x[0])[0]
    channel.update({
        'fastest_source': fastest_url,
        'response_time': f"{fastest_sp:.4f} 秒"
    })
    return channel

def generate_m3u8_playlist(valid_channels: List[Dict], filename: str = "iptv_playlist.m3u8") -> None:
    """生成标准m3u8播放列表文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        # m3u8文件头
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        # 写入每个有效频道
        for channel in valid_channels:
            if not channel.get('fastest_source'):
                continue
            # 写入频道信息（EXTINF为m3u8标准格式）
            f.write(f"#EXTINF:-1,{channel['name']}\n")
            f.write(f"{channel['fastest_source']}\n")
    print(f"\n✅ 已生成m3u8播放列表：{filename}（共 {len([c for c in valid_channels if c['fastest_source']])} 个可用频道）")

def main():
    print("=== 开始拉取远程IPTV源 ===")
    collected_cctv = {}

    for i, source_url in enumerate(IPTV_SOURCES, 1):
        print(f"\n{i}/{len(IPTV_SOURCES)} 拉取中：{source_url}")
        iptv_content = fetch_remote_iptv(source_url)
        if iptv_content:
            filter_cctv_channels(iptv_content, collected_cctv)
            print(f"   已收集 {len(collected_cctv)} 个CCTV频道（去重后）")

    if not collected_cctv:
        print("\n❌ 未筛选到任何CCTV频道")
        return

    cctv_channels = [{'name': n, 'sources': s} for n, s in collected_cctv.items()]
    sorted_channels = cctv_channel_sort(cctv_channels)
    print(f"\n=== 已排序 {len(sorted_channels)} 个频道 ===")

    print("\n=== 测速中，请等待 ===")
    final_result = [auto_select_fast_source(c) for c in sorted_channels]

    print("\n=== 最终结果 ===")
    for idx, c in enumerate(final_result, 1):
        print(f"\n{idx}. {c['name']}")
        print(f"   源：{c['fastest_source'] or '无'}")
        print(f"   响应：{c['response_time']}")

    # 生成m3u8文件
    generate_m3u8_playlist(final_result)

if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("请先安装依赖：pip install requests")
    else:
        main()
