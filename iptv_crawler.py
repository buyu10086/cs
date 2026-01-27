import requests
import time
from datetime import datetime
import re

# -------------------------- 2026年最新可用源配置 --------------------------
IPTV_SOURCE_URLS = [
    "https://ghproxy.cc/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/hujingguang/ChinaIPTV/main/cnTV_AutoUpdate.m3u8"
]
TIMEOUT = 10
OUTPUT_FILE = "iptv_playlist.m3u8"
# 关闭单源去重（改为收集多源），保留频道名称去重（避免重复频道条目）
REMOVE_DUPLICATE_CHANNELS = True
MIN_VALID_SOURCES = 3
# ---------------------------------------------------------------------------

# 核心修改：存储「频道名:源列表」，支持多源
channel_sources_map = {}
verified_urls = set()

def fetch_raw_iptv_data(url_list):
    """抓取多个源的原始IPTV数据并合并（容错：跳过失效源）"""
    all_lines = []
    valid_source_count = 0
    
    for idx, url in enumerate(url_list):
        print(f"\n📥 正在抓取数据源 {idx+1}/{len(url_list)}: {url}")
        try:
            response = requests.get(
                url, 
                timeout=20,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://github.com/",
                    "Accept": "*/*"
                }
            )
            response.raise_for_status()
            lines = response.text.splitlines()
            lines = [line.strip() for line in lines if line.strip() and not line.startswith("//")]
            if lines:
                all_lines.extend(lines)
                valid_source_count += 1
                print(f"✅ 数据源 {idx+1} 抓取成功，共 {len(lines)} 行有效数据")
            else:
                print(f"⚠️  数据源 {idx+1} 抓取成功，但无有效数据")
                
        except requests.exceptions.HTTPError as e:
            print(f"❌ 数据源 {idx+1} HTTP错误：{e}")
        except requests.exceptions.Timeout:
            print(f"❌ 数据源 {idx+1} 抓取超时（已延长超时时间）")
        except requests.exceptions.ConnectionError:
            print(f"❌ 数据源 {idx+1} 连接失败（跳过）")
        except Exception as e:
            print(f"❌ 数据源 {idx+1} 抓取失败：{str(e)[:100]}")
            continue
    
    print(f"\n📊 数据源抓取完成：共尝试 {len(url_list)} 个源，可用 {valid_source_count} 个")
    return all_lines

def extract_channel_name(line):
    """从m3u注释行提取频道名称（兼容多种格式）"""
    if line.startswith("#EXTINF:"):
        match = re.search(r',([^,]+)$', line)
        if not match:
            match = re.search(r'tvg-name="([^"]+)"', line)
        if match:
            return match.group(1).strip()
    return None

def is_source_available(url):
    """验证直播源是否可用（放宽条件，确保多源都能被检测）"""
    if not url.startswith(("http://", "https://")):
        return False
    if url in verified_urls:
        return True
    try:
        response = requests.get(
            url, 
            timeout=TIMEOUT, 
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            stream=True
        )
        if response.status_code in [200, 206, 301, 302, 307, 308]:
            verified_urls.add(url)
            return True
        return False
    except:
        return False

def generate_m3u8(raw_lines):
    """生成支持多源切换的m3u8文件（同一个频道保留所有有效源）"""
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 更新时间：{update_time}
# 支持多源切换：同一个频道可选择不同播放源
"""
    valid_lines = [m3u8_header]
    
    # 电视可见的更新时间虚拟频道
    valid_lines.append(f"#EXTINF:-1 group-title='📢 系统信息',📅 直播源更新时间：{update_time}")
    valid_lines.append("#")
    
    temp_channel = None
    total_checked = 0
    total_valid = 0
    
    # -------------------------- 核心修改1：收集多源 --------------------------
    # 第一步：遍历所有源，为每个频道收集所有有效源
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        
        if line.startswith("#EXTINF:"):
            temp_channel = extract_channel_name(line)
        elif line.startswith(("http://", "https://")) and temp_channel:
            total_checked += 1
            # 央视源优先验证通过
            is_cctv = any(keyword in temp_channel for keyword in ["CCTV", "央视", "中央", "CCTV-", "央视频"])
            if is_source_available(line) or (is_cctv and total_valid < 30):
                total_valid += 1
                # 为频道添加源（不存在则创建列表，存在则追加）
                if temp_channel not in channel_sources_map:
                    channel_sources_map[temp_channel] = []
                # 避免同一个源重复添加
                if line not in channel_sources_map[temp_channel]:
                    channel_sources_map[temp_channel].append(line)
                    print(f"✅ 为 [{temp_channel}] 新增源 [{len(channel_sources_map[temp_channel])}]：{line[:50]}...")
            temp_channel = None
    
    # -------------------------- 核心修改2：生成多源格式 --------------------------
    # 第二步：遍历收集的频道-源列表，生成多源格式的m3u8
    for channel_name, sources in channel_sources_map.items():
        if not sources:
            continue
        
        # 写入频道名称行（只写一次）
        valid_lines.append(f"#EXTINF:-1 group-title='{'' if 'CCTV' in channel_name else '卫视/地方台'}',{channel_name}（{len(sources)}个源）")
        # 写入该频道的所有有效源（播放端会识别为多源）
        for idx, source_url in enumerate(sources):
            valid_lines.append(source_url)
            print(f"📺 频道 [{channel_name}] - 源 {idx+1}：{source_url[:50]}...")
    
    # 容错逻辑
    if total_valid < MIN_VALID_SOURCES:
        print(f"\n⚠️  有效源数量({total_valid})低于最小值({MIN_VALID_SOURCES})，生成基础文件")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            empty_content = f"""#EXTM3U
# 更新时间：{update_time}
#EXTINF:-1 group-title='📢 系统信息',📅 直播源更新时间：{update_time}
#
#EXTINF:-1 group-title='📢 系统信息',⚠️  当前有效源较少，建议稍后重试
#
"""
            f.write(empty_content)
        return False
    
    # 写入最终文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_lines))
    
    print(f"\n📊 最终统计：共检测 {total_checked} 个源，有效源 {total_valid} 个，有效频道 {len(channel_sources_map)} 个")
    print(f"✅ 多源版文件生成完成：{OUTPUT_FILE}")
    print(f"🕒 更新时间：{update_time}")
    return True

if __name__ == "__main__":
    print("========== 开始抓取IPTV源（支持多源切换） ==========")
    raw_data = fetch_raw_iptv_data(IPTV_SOURCE_URLS)
    
    if not raw_data:
        print("❌ 未获取到任何IPTV数据，保留历史文件")
        exit(0)
    
    generate_m3u8(raw_data)
    print("========== 抓取完成，播放端支持多源切换 ==========")
