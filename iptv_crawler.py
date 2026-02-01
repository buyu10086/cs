import requests
import re
import datetime
from typing import List, Dict, Tuple

# 放宽超时时间，适配官方源响应
TIMEOUT = 10

# 新增官方/合法公开源，提升稳定性与合法性
IPTV_SOURCES = [
    # 合法公开授权源（优先选择）
    "https://gh-proxy.com/https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",  # iptv-org 合法授权源
    "https://gh-proxy.com/https://raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/cctv.m3u",  # 整理后的央视合法源
    
    # 原有稳定源（筛选合法内容）
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/main/live.m3u"
]

def fetch_remote_iptv(source_url: str) -> str:
    for retry in range(2):
        try:
            response = requests.get(
                source_url,
                timeout=TIMEOUT,
                allow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            response.encoding = response.apparent_encoding or 'utf-8'
            if response.status_code in (200, 206, 301, 302):
                return response.text
        except Exception as e:
            if retry == 1:
                print(f"⚠️  拉取失败：{source_url}（错误：{str(e)[:50]}）")
    return ""

def filter_cctv_channels(iptv_content: str, collected_channels: Dict[str, List[str]]) -> None:
    m3u_pattern = re.compile(
        r'#EXTINF:.+?,(?P<name>.+?(?:CCTV|央视|中央).+?)\s*\n?(?P<url>https?://.+?)(?:\s|\n|#|$)',
        re.IGNORECASE | re.DOTALL
    )
    txt_pattern = re.compile(
        r'(?P<name>.+?(?:CCTV|央视|中央).+?)\s*[:：=]\s*(?P<url>https?://.+?m3u8)',
        re.IGNORECASE
    )
    url_only_pattern = re.compile(
        r'(?P<url>https?://.+?(?:CCTV|cctv).+?m3u8)',
        re.IGNORECASE
    )
    chinese_cctv_pattern = re.compile(
        r'(?P<name>.+?(?:央视|中央).+?\d+|.+?综合频道|.+?新闻频道)\s*[:：=]\s*(?P<url>https?://.+?m3u8)',
        re.IGNORECASE
    )

    for name, url in m3u_pattern.findall(iptv_content):
        name, url = name.strip(), url.strip()
        collected_channels.setdefault(name, []).append(url)
    
    for name, url in txt_pattern.findall(iptv_content):
        name = name.strip() if name else f"CCTV-未知频道（{url[-20:]}）"
        collected_channels.setdefault(name, []).append(url.strip())
    
    for name, url in chinese_cctv_pattern.findall(iptv_content):
        name = name.strip()
        if re.search(r'1套|综合', name, re.IGNORECASE):
            name = "CCTV-1 综合频道"
        elif re.search(r'2套|财经', name, re.IGNORECASE):
            name = "CCTV-2 财经频道"
        elif re.search(r'13套|新闻', name, re.IGNORECASE):
            name = "CCTV-13 新闻频道"
        elif re.search(r'5套|体育', name, re.IGNORECASE):
            name = "CCTV-5 体育频道"
        collected_channels.setdefault(name, []).append(url.strip())
    
    url_only_matches = url_only_pattern.findall(iptv_content)
    for url in url_only_matches:
        url = url.strip()
        cctv_match = re.search(r'CCTV[-_]?(\d+|\+|新闻)', url, re.IGNORECASE)
        name = f"CCTV-{cctv_match.group(1)}" if cctv_match else "CCTV 未知频道"
        collected_channels.setdefault(name, []).append(url)
    
    for channel_name in collected_channels:
        seen = set()
        unique_sources = []
        for src in collected_channels[channel_name]:
            if src not in seen and src.startswith(("http://", "https://")):
                seen.add(src)
                unique_sources.append(src)
        collected_channels[channel_name] = unique_sources

def cctv_channel_sort(channels: List[Dict]) -> List[Dict]:
    def extract_channel_number(channel_name: str) -> Tuple[int, str]:
        match = re.search(r'CCTV[-_]?(\d+)([+]?)', channel_name, re.IGNORECASE)
        if match:
            return (int(match.group(1)), match.group(2))
        if re.search(r'新闻', channel_name, re.IGNORECASE):
            return (100, "新闻")
        if re.search(r'财经', channel_name, re.IGNORECASE):
            return (101, "财经")
        if re.search(r'体育', channel_name, re.IGNORECASE):
            return (102, "体育")
        return (999, channel_name)
    return sorted(channels, key=lambda x: extract_channel_number(x['name']))

def test_source_speed(source_url: str) -> float:
    try:
        start_time = datetime.datetime.now()
        response = requests.get(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            stream=True
        )
        response_time = (datetime.datetime.now() - start_time).total_seconds()
        valid_status_codes = (200, 206, 301, 302, 403)
        return response_time if response.status_code in valid_status_codes else 10.0
    except Exception:
        return 10.0

def auto_select_fast_source(channel: Dict) -> Dict:
    source_list = channel.get('sources', [])
    if not source_list:
        channel.update({'fastest_source': None, 'response_time': '无可用源'})
        return channel
    source_speed = [(test_source_speed(s), s) for s in source_list if s]
    available_sources = [(sp, url) for sp, url in source_speed if sp <= 10.0]
    if not available_sources:
        channel.update({
            'fastest_source': source_list[0],
            'response_time': '测速失败，使用默认源'
        })
        return channel
    fastest_speed, fastest_url = sorted(available_sources, key=lambda x: x[0])[0]
    channel.update({
        'fastest_source': fastest_url,
        'response_time': f"{fastest_speed:.4f} 秒" if fastest_speed < 10.0 else "测速较慢，可用"
    })
    return channel

def generate_m3u8_playlist(valid_channels: List[Dict], filename: str = "iptv_playlist.m3u8") -> None:
    usable_channels = [c for c in valid_channels if c.get('fastest_source')]
    if not usable_channels:
        print("\n❌ 无可用频道，无法生成 m3u8 文件")
        return
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write("# 生成说明：合法公开CCTV频道列表（仅用于个人学习交流）\n")
        f.write("# 兼容播放器：VLC、PotPlayer\n")
        for channel in usable_channels:
            f.write(f"\n#EXTINF:-1,{channel['name']}\n")
            f.write(f"{channel['fastest_source']}\n")
    print(f"\n✅ 已生成 m3u8 播放列表：{filename}")
    print(f"   包含 {len(usable_channels)} 个合法 CCTV 频道")

def main():
    print("=== 开始执行 CCTV 频道筛选（含官方合法源）===")
    collected_cctv = {}
    for i, source_url in enumerate(IPTV_SOURCES, 1):
        print(f"\n{i}/{len(IPTV_SOURCES)} 正在拉取：{source_url}")
        iptv_content = fetch_remote_iptv(source_url)
        if iptv_content:
            filter_cctv_channels(iptv_content, collected_cctv)
            print(f"   拉取成功，当前累计 {len(collected_cctv)} 个 CCTV 频道")
    if not collected_cctv:
        print("\n❌ 未筛选到任何 CCTV 频道，任务终止")
        return
    cctv_channels = [{'name': n, 'sources': s} for n, s in collected_cctv.items()]
    sorted_channels = cctv_channel_sort(cctv_channels)
    print(f"\n=== 频道排序完成，共 {len(sorted_channels)} 个 CCTV 频道 ===")
    print("\n=== 开始测速筛选（宽松模式）===")
    final_result = [auto_select_fast_source(channel) for channel in sorted_channels]
    print("\n=== 终端结果汇总 ===")
    valid_count = 0
    for idx, channel in enumerate(final_result, 1):
        if channel['fastest_source']:
            valid_count += 1
        print(f"\n{idx}. 频道：{channel['name']}")
        print(f"   源：{channel['fastest_source'] or '无可用源'}")
        print(f"   状态：{channel['response_time']}")
    generate_m3u8_playlist(final_result)
    print("\n=== 任务完成 ===")

if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("❌ 请先安装依赖：pip install requests")
    else:
        main()
