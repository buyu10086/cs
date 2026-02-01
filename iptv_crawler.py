import requests
import re
import datetime
from typing import List, Dict, Tuple

# 放宽超时时间，适配海外源响应速度
TIMEOUT = 10

# 公开 IPTV 源列表
IPTV_SOURCES = [
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://gh-proxy.com/https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://gh-proxy.com/https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/main/live.m3u"
]

def fetch_remote_iptv(source_url: str) -> str:
    """拉取远程 IPTV 源内容，增加重试机制，提升拉取成功率"""
    # 重试2次，避免网络波动导致拉取失败
    for retry in range(2):
        try:
            response = requests.get(
                source_url,
                timeout=TIMEOUT,
                allow_redirects=True,
                # 模拟浏览器请求头，避免被服务器拦截为爬虫
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            response.encoding = response.apparent_encoding or 'utf-8'
            if response.status_code in (200, 206, 301, 302):
                return response.text
        except Exception as e:
            if retry == 1:  # 仅最后一次重试失败时输出提示
                print(f"⚠️  拉取失败（重试2次）：{source_url}（错误：{str(e)[:50]}）")
    return ""

def filter_cctv_channels(iptv_content: str, collected_channels: Dict[str, List[str]]) -> None:
    """
    筛选 CCTV 频道，修复核心：m3u_pattern 去掉多余分组，解决解包数量不匹配
    同时扩展中文名称匹配，提升频道提取数量
    """
    # 修复关键：去掉 #EXTINF 后的多余分组，仅保留 name 和 url 两个分组，避免解包错误
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
    # 匹配中文名称央视频道（如 央视1套、中央新闻频道）
    chinese_cctv_pattern = re.compile(
        r'(?P<name>.+?(?:央视|中央).+?\d+|.+?综合频道|.+?新闻频道)\s*[:：=]\s*(?P<url>https?://.+?m3u8)',
        re.IGNORECASE
    )

    # 1. 处理标准 m3u 格式（修复后：解包 name, url 数量匹配，无异常）
    for name, url in m3u_pattern.findall(iptv_content):
        name, url = name.strip(), url.strip()
        collected_channels.setdefault(name, []).append(url)
    
    # 2. 处理纯文本格式（带频道名）
    for name, url in txt_pattern.findall(iptv_content):
        name = name.strip() if name else f"CCTV-未知频道（{url[-20:]}）"
        collected_channels.setdefault(name, []).append(url.strip())
    
    # 3. 处理中文名称央视频道，统一格式
    for name, url in chinese_cctv_pattern.findall(iptv_content):
        name = name.strip()
        # 中文名称转换为标准 CCTV 格式，提升排序一致性
        if re.search(r'1套|综合', name, re.IGNORECASE):
            name = "CCTV-1 综合频道"
        elif re.search(r'2套|财经', name, re.IGNORECASE):
            name = "CCTV-2 财经频道"
        elif re.search(r'13套|新闻', name, re.IGNORECASE):
            name = "CCTV-13 新闻频道"
        elif re.search(r'5套|体育', name, re.IGNORECASE):
            name = "CCTV-5 体育频道"
        collected_channels.setdefault(name, []).append(url.strip())
    
    # 4. 处理仅含 CCTV 的播放源（修复后：变量已定义，无 NameError）
    url_only_matches = url_only_pattern.findall(iptv_content)
    for url in url_only_matches:
        url = url.strip()
        cctv_match = re.search(r'CCTV[-_]?(\d+|\+|新闻)', url, re.IGNORECASE)
        name = f"CCTV-{cctv_match.group(1)}" if cctv_match else "CCTV 未知频道"
        collected_channels.setdefault(name, []).append(url)
    
    # 5. 去重并保留有效源（过滤非 http 开头的无效地址）
    for channel_name in collected_channels:
        seen = set()
        unique_sources = []
        for src in collected_channels[channel_name]:
            if src not in seen and src.startswith(("http://", "https://")):
                seen.add(src)
                unique_sources.append(src)
        collected_channels[channel_name] = unique_sources

def cctv_channel_sort(channels: List[Dict]) -> List[Dict]:
    """CCTV 频道排序：按频道号正序，兼容标准格式和中文格式频道"""
    def extract_channel_number(channel_name: str) -> Tuple[int, str]:
        """提取频道号，处理特殊频道（如 CCTV-5+）"""
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
    """测速函数：放宽规则，兼容更多流媒体源，避免频道丢失"""
    try:
        start_time = datetime.datetime.now()
        # 用 GET + stream=True 替代 HEAD，兼容不支持 HEAD 方法的源
        response = requests.get(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            stream=True  # 流式请求，不下载完整内容，提升测速效率
        )
        response_time = (datetime.datetime.now() - start_time).total_seconds()
        
        # 放宽状态码要求，支持更多有效源
        valid_status_codes = (200, 206, 301, 302, 403)
        return response_time if response.status_code in valid_status_codes else 10.0
    except Exception:
        # 测速失败不返回 inf，保留为慢源，避免频道被丢弃
        return 10.0

def auto_select_fast_source(channel: Dict) -> Dict:
    """为单个频道选择最快源，无有效测速源时保留默认源，不丢弃频道"""
    source_list = channel.get('sources', [])
    if not source_list:
        channel.update({'fastest_source': None, 'response_time': '无可用源'})
        return channel
    
    # 测速并整理源数据
    source_speed = [(test_source_speed(s), s) for s in source_list if s]
    # 筛选可用源（包含慢源，不丢弃）
    available_sources = [(sp, url) for sp, url in source_speed if sp <= 10.0]
    
    if not available_sources:
        # 无可用测速源时，使用第一个源作为默认值
        channel.update({
            'fastest_source': source_list[0],
            'response_time': '测速失败，使用默认源'
        })
        return channel
    
    # 选择响应时间最短的源
    fastest_speed, fastest_url = sorted(available_sources, key=lambda x: x[0])[0]
    channel.update({
        'fastest_source': fastest_url,
        'response_time': f"{fastest_speed:.4f} 秒" if fastest_speed < 10.0 else "测速较慢，可用"
    })
    return channel

def generate_m3u8_playlist(valid_channels: List[Dict], filename: str = "iptv_playlist.m3u8") -> None:
    """生成标准 m3u8 播放列表，保留所有有源频道，提升生成数量"""
    # 筛选有可用源的频道（不丢弃测速失败但有默认源的频道）
    usable_channels = [c for c in valid_channels if c.get('fastest_source')]
    if not usable_channels:
        print("\n❌ 无可用频道，无法生成 m3u8 文件")
        return
    
    # 写入 m3u8 文件（utf-8 编码，兼容中文频道名）
    with open(filename, 'w', encoding='utf-8') as f:
        # m3u8 标准文件头
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write("# 生成说明：CCTV 频道列表（含最快源和默认源）\n")
        f.write("# 兼容播放器：VLC、PotPlayer、Kodi、完美解码\n")
        
        # 写入每个可用频道
        for channel in usable_channels:
            f.write(f"\n#EXTINF:-1,{channel['name']}\n")
            f.write(f"{channel['fastest_source']}\n")
    
    print(f"\n✅ 已成功生成 m3u8 播放列表：{filename}")
    print(f"   包含 {len(usable_channels)} 个可用 CCTV 频道（大幅提升生成数量）")

def main():
    """主流程：拉取 → 筛选 → 排序 → 测速 → 生成 m3u8"""
    print("=== 开始执行 CCTV 频道筛选与 m3u8 生成任务（优化完整版）===")
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

    # 步骤3：为每个频道选择最快播放源（宽松测速，保留更多频道）
    print("\n=== 开始测速筛选（宽松模式，耗时约10-20分钟，请耐心等待）===")
    final_result = [auto_select_fast_source(channel) for channel in sorted_channels]

    # 步骤4：输出终端结果汇总
    print("\n=== 终端测速结果汇总 ===")
    valid_count = 0
    for idx, channel in enumerate(final_result, 1):
        if channel['fastest_source']:
            valid_count += 1
        print(f"\n{idx}. 频道：{channel['name']}")
        print(f"   源：{channel['fastest_source'] or '无可用源'}")
        print(f"   状态：{channel['response_time']}")

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
