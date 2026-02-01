import requests
import re
import datetime
from typing import List, Dict, Tuple

# 超时时间设置（单位：秒）
TIMEOUT = 3

# 公开 IPTV 源列表（你提供的链接）
IPTV_SOURCES = [
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/main/live.m3u"
]

def fetch_remote_iptv(source_url: str) -> str:
    """拉取远程 IPTV 源内容，支持 txt/m3u 格式，失败返回空字符串"""
    try:
        response = requests.get(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True
        )
        # 自动识别编码，避免中文乱码
        response.encoding = response.apparent_encoding or 'utf-8'
        return response.text if response.status_code in (200, 206) else ""
    except Exception as e:
        print(f"⚠️  拉取失败：{source_url}（错误信息：{str(e)[:50]}）")
        return ""

def filter_cctv_channels(iptv_content: str, collected_channels: Dict[str, List[str]]) -> None:
    """从 IPTV 内容中筛选 CCTV 频道，自动去重，修复 url_only_matches 未定义问题"""
    # 3种格式匹配正则
    m3u_pattern = re.compile(r'#EXTINF:.+?,(?P<name>.+?CCTV.+?)\n(?P<url>https?://.+?)\n', re.IGNORECASE)
    txt_pattern = re.compile(r'(?P<name>.*?CCTV.*?)\s*[:：]?\s*(?P<url>https?://.+?m3u8.*?)', re.IGNORECASE)
    url_only_pattern = re.compile(r'(?P<url>https?://.+?CCTV.+?m3u8)', re.IGNORECASE)

    # 1. 处理 m3u 格式（带 EXTINF 标识）
    for name, url in m3u_pattern.findall(iptv_content):
        name, url = name.strip(), url.strip()
        collected_channels.setdefault(name, []).append(url)
    
    # 2. 处理纯文本格式（频道名 + 播放源 对应格式）
    for name, url in txt_pattern.findall(iptv_content):
        name = name.strip() if name else f"CCTV-未知频道（{url[-20:]}）"
        collected_channels.setdefault(name, []).append(url.strip())
    
    # 3. 处理仅含 CCTV 的播放源（仅 url）- 修复核心：先执行匹配赋值，再使用变量
    url_only_matches = url_only_pattern.findall(iptv_content)  # 补充这行，解决 NameError
    for url in url_only_matches:
        url = url.strip()
        # 从 url 中提取简易频道名
        cctv_match = re.search(r'CCTV[-_]?(\d+|\+|新闻)', url, re.IGNORECASE)
        name = f"CCTV-{cctv_match.group(1)}" if cctv_match else "CCTV 未知频道"
        collected_channels.setdefault(name, []).append(url)
    
    # 4. 播放源去重（避免同一频道重复添加相同源）
    for channel_name in collected_channels:
        collected_channels[channel_name] = list(set(collected_channels[channel_name]))

def cctv_channel_sort(channels: List[Dict]) -> List[Dict]:
    """CCTV 频道排序：按频道号正序，支持数字频道和常见非数字频道"""
    def extract_channel_number(channel_name: str) -> Tuple[int, str]:
        """提取频道号，处理特殊格式（如 CCTV-5+、CCTV_1）"""
        match = re.search(r'CCTV[-_]?(\d+)([+]?)', channel_name, re.IGNORECASE)
        if match:
            return (int(match.group(1)), match.group(2))
        # 非数字频道排序优先级
        if re.search(r'新闻', channel_name, re.IGNORECASE):
            return (100, "新闻")
        if re.search(r'财经', channel_name, re.IGNORECASE):
            return (101, "财经")
        if re.search(r'体育', channel_name, re.IGNORECASE):
            return (102, "体育")
        # 其他未知频道放末尾
        return (999, channel_name)
    
    return sorted(channels, key=lambda x: extract_channel_number(x['name']))

def test_source_speed(source_url: str) -> float:
    """测试播放源响应速度，可用返回响应时间，不可用返回极大值"""
    try:
        start_time = datetime.datetime.now()
        response = requests.head(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True
        )
        response_time = (datetime.datetime.now() - start_time).total_seconds()
        # 兼容流媒体常见状态码 200 和 206
        return response_time if response.status_code in (200, 206) else float('inf')
    except Exception:
        return float('inf')

def auto_select_fast_source(channel: Dict) -> Dict:
    """为单个频道选择最快的可用播放源"""
    source_list = channel.get('sources', [])
    if not source_list:
        channel.update({'fastest_source': None, 'response_time': '无可用源'})
        return channel
    
    # 测速并筛选可用源
    source_speed = [(test_source_speed(s), s) for s in source_list if s]
    available_sources = [(sp, url) for sp, url in source_speed if sp != float('inf')]
    
    if not available_sources:
        channel.update({'fastest_source': None, 'response_time': '无可用源'})
        return channel
    
    # 选择响应时间最短的源
    fastest_speed, fastest_url = sorted(available_sources, key=lambda x: x[0])[0]
    channel.update({
        'fastest_source': fastest_url,
        'response_time': f"{fastest_speed:.4f} 秒"
    })
    return channel

def generate_m3u8_playlist(valid_channels: List[Dict], filename: str = "iptv_playlist.m3u8") -> None:
    """生成标准 m3u8 播放列表文件，可直接用 VLC 等播放器打开"""
    # 筛选有可用播放源的频道
    usable_channels = [c for c in valid_channels if c.get('fastest_source')]
    if not usable_channels:
        print("\n❌ 无可用频道，无法生成 m3u8 文件")
        return
    
    # 写入 m3u8 文件
    with open(filename, 'w', encoding='utf-8') as f:
        # m3u8 标准文件头
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write("# 生成说明：CCTV 频道最快播放源列表，兼容 VLC/PotPlayer 等播放器\n")
        
        # 写入每个可用频道
        for channel in usable_channels:
            f.write(f"\n#EXTINF:-1,{channel['name']}\n")
            f.write(f"{channel['fastest_source']}\n")
    
    print(f"\n✅ 已成功生成 m3u8 播放列表：{filename}")
    print(f"   包含 {len(usable_channels)} 个可用 CCTV 频道，可直接用播放器打开")

def main():
    """主流程：拉取源 → 筛选 CCTV → 排序 → 测速 → 生成 m3u8"""
    print("=== 开始执行 CCTV 频道筛选与 m3u8 生成任务 ===")
    collected_cctv = {}

    # 步骤1：拉取所有远程 IPTV 源并筛选 CCTV
    for i, source_url in enumerate(IPTV_SOURCES, 1):
        print(f"\n{i}/{len(IPTV_SOURCES)} 正在拉取：{source_url}")
        iptv_content = fetch_remote_iptv(source_url)
        if iptv_content:
            filter_cctv_channels(iptv_content, collected_cctv)
            print(f"   拉取成功，当前累计 {len(collected_cctv)} 个去重 CCTV 频道")

    # 无频道数据直接退出
    if not collected_cctv:
        print("\n❌ 未筛选到任何 CCTV 频道，任务终止")
        return

    # 步骤2：转换数据格式并排序
    cctv_channels = [{'name': n, 'sources': s} for n, s in collected_cctv.items()]
    sorted_channels = cctv_channel_sort(cctv_channels)
    print(f"\n=== 频道排序完成，共 {len(sorted_channels)} 个 CCTV 频道 ===")

    # 步骤3：为每个频道选择最快播放源（测速）
    print("\n=== 开始测速筛选最快播放源（耗时较长，请耐心等待）===")
    final_result = [auto_select_fast_source(channel) for channel in sorted_channels]

    # 步骤4：输出终端结果
    print("\n=== 终端测速结果汇总 ===")
    valid_count = 0
    for idx, channel in enumerate(final_result, 1):
        if channel['fastest_source']:
            valid_count += 1
        print(f"\n{idx}. 频道：{channel['name']}")
        print(f"   最快源：{channel['fastest_source'] or '无可用源'}")
        print(f"   响应时间：{channel['response_time']}")

    # 步骤5：生成 m3u8 播放文件
    generate_m3u8_playlist(final_result)
    print("\n=== 任务全部完成 ===")

if __name__ == "__main__":
    # 检查依赖是否安装
    try:
        import requests
    except ImportError:
        print("❌ 缺少依赖 requests，请先执行安装命令：pip install requests")
    else:
        main()
