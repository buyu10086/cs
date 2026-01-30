import requests
import time
import random
import json
from datetime import datetime, timedelta
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# -------------------------- 配置优化 --------------------------
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/TianmuTNT/iptv/refs/heads/main/iptv.m3u",
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/mytv-android/China-TV-Live-M3U8/refs/heads/main/webview.m3u"
]
TIMEOUT = 3
OUTPUT_FILE = "iptv_playlist.m3u8"
REMOVE_DUPLICATE_CHANNELS = True
MIN_VALID_SOURCES = 3
MAX_THREADS = 30

# 缓存配置
CACHE_FILE = "iptv_verified_cache.json"
CACHE_EXPIRE_HOURS = 24

# 反爬随机延迟
MIN_DELAY = 0.1
MAX_DELAY = 0.5

# 线程安全锁
channel_sources_map = {}
map_lock = threading.Lock()
verified_urls = set()
url_lock = threading.Lock()

# -------------------------- 缓存相关函数 --------------------------
def load_verified_cache():
    global verified_urls
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        cache_time_str = cache_data.get("cache_time", "")
        if not cache_time_str:
            print("⚠️  缓存文件无时间戳，跳过加载")
            return
        
        cache_time = datetime.strptime(cache_time_str, '%Y-%m-%d %H:%M:%S')
        expire_time = cache_time + timedelta(hours=CACHE_EXPIRE_HOURS)
        current_time = datetime.now()
        
        if current_time > expire_time:
            print(f"⚠️  缓存已过期（超过{CACHE_EXPIRE_HOURS}小时），跳过加载")
            return
        
        valid_urls = cache_data.get("verified_urls", [])
        verified_urls = set(valid_urls)
        print(f"✅ 成功加载本地缓存，共 {len(verified_urls)} 个已验证源（缓存时间：{cache_time_str}）")
    
    except FileNotFoundError:
        print(f"ℹ️  未找到缓存文件 {CACHE_FILE}，将在运行后创建")
    except json.JSONDecodeError:
        print(f"⚠️  缓存文件格式错误，无法加载")
    except Exception as e:
        print(f"⚠️  加载缓存失败：{str(e)[:50]}")

def save_verified_cache():
    try:
        cache_data = {
            "cache_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "verified_urls": list(verified_urls)
        }
        
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 成功保存缓存到 {CACHE_FILE}，共 {len(verified_urls)} 个已验证源")
    except Exception as e:
        print(f"❌ 保存缓存失败：{str(e)[:50]}")

# -------------------------- 反爬延迟函数 --------------------------
def add_random_delay():
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)

# -------------------------- 并行抓取数据源 --------------------------
def fetch_single_source(url, idx):
    add_random_delay()
    try:
        response = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://github.com/",
                "Accept": "*/*"
            }
        )
        response.raise_for_status()
        lines = [line.strip() for line in response.text.splitlines() if line.strip() and not line.startswith("//")]
        print(f"✅ 数据源 {idx+1} 抓取成功，有效行 {len(lines)}")
        return True, lines
    except Exception as e:
        print(f"❌ 数据源 {idx+1} 抓取失败：{str(e)[:50]}")
        return False, []

def fetch_raw_iptv_data_parallel(url_list):
    all_lines = []
    valid_source_count = 0
    with ThreadPoolExecutor(max_workers=min(MAX_THREADS, len(url_list))) as executor:
        future_to_idx = {executor.submit(fetch_single_source, url, idx): idx for idx, url in enumerate(url_list)}
        for future in as_completed(future_to_idx):
            success, lines = future.result()
            if success and lines:
                all_lines.extend(lines)
                valid_source_count += 1
    print(f"\n📊 并行抓取完成：尝试 {len(url_list)} 源，可用 {valid_source_count} 源")
    return all_lines

# -------------------------- 频道名称提取 --------------------------
def extract_channel_name(line):
    if line.startswith("#EXTINF:"):
        match = re.search(r',([^,]+)$', line)
        if not match:
            match = re.search(r'tvg-name="([^"]+)"', line)
        if match:
            return match.group(1).strip()
    return None

# -------------------------- 源验证 --------------------------
def verify_single_source(url, channel_name):
    add_random_delay()
    if not url.startswith(("http://", "https://")):
        return None, None
    
    with url_lock:
        if url in verified_urls:
            return channel_name, url
    
    try:
        response = requests.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
            stream=True
        )
        if response.status_code in [200, 206, 301, 302, 307, 308]:
            with url_lock:
                verified_urls.add(url)
            return channel_name, url
    except:
        pass
    return None, None

# -------------------------- 自定义频道分组（核心修改） --------------------------
def get_channel_group(channel_name):
    """修改为自定义分类：央视频道、卫视频道、数字频道、北京频道、河南省级、其他频道"""
    if not channel_name:
        return "🎬 其他频道"
    
    # 1. 央视频道
    cctv_keywords = ["CCTV", "央视", "中央", "央视频", "CCTV-", "中视"]
    if any(keyword in channel_name for keyword in cctv_keywords):
        return "📺 央视频道"
    
    # 2. 卫视频道
    if "卫视" in channel_name:
        return "📡 卫视频道"
    
    # 3. 数字频道
    digital_keywords = ["数字", "付费", "高清", "4K", "影视频道", "综艺频道"]
    if any(keyword in channel_name for keyword in digital_keywords):
        return "🔢 数字频道"
    
    # 4. 北京频道
    if "北京" in channel_name and "卫视" not in channel_name:
        return "🏙️ 北京频道"
    
    # 5. 河南省级
    if "河南" in channel_name and "卫视" not in channel_name:
        return "🌏 河南省级"
    
    # 其他
    return "🎬 其他频道"

# -------------------------- 生成M3U8（核心修改：分类中增加更新时间） --------------------------
def generate_m3u8_parallel(raw_lines):
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # 北京时刻（系统时区默认东八区）
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 北京时刻更新时间：{update_time}
# 支持多源切换+自定义频道分组
"""
    valid_lines = [m3u8_header]
    # 增加“更新时间”作为特殊条目（对应界面的“更新时间”分类）
    valid_lines.append(f"#EXTINF:-1 group-title='📢 系统信息',📅 北京时刻更新时间：{update_time}")
    valid_lines.append("#")

    # 提取待验证的(频道名, url)对
    task_list = []
    temp_channel = None
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            temp_channel = extract_channel_name(line)
        elif line.startswith(("http://", "https://")) and temp_channel:
            task_list.append((line, temp_channel))
            temp_channel = None
    print(f"\n🔍 待验证源总数：{len(task_list)}（已复用本地缓存）")

    # 并行验证源
    total_valid = 0
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_task = {executor.submit(verify_single_source, url, chan): (url, chan) for url, chan in task_list}
        for future in as_completed(future_to_task):
            chan_name, valid_url = future.result()
            if chan_name and valid_url:
                total_valid += 1
                with map_lock:
                    if chan_name not in channel_sources_map:
                        channel_sources_map[chan_name] = []
                    if valid_url not in channel_sources_map[chan_name]:
                        channel_sources_map[chan_name].append(valid_url)

    # 自定义分类顺序（与界面一致：更新时间、央视频道、卫视频道、数字频道、北京频道、河南省级、其他）
    group_order = [
        "📢 系统信息",
        "📺 央视频道",
        "📡 卫视频道",
        "🔢 数字频道",
        "🏙️ 北京频道",
        "🌏 河南省级",
        "🎬 其他频道"
    ]
    grouped_channels = {group: [] for group in group_order}

    # 按分类整理频道
    for channel_name, sources in channel_sources_map.items():
        if sources:
            group = get_channel_group(channel_name)
            grouped_channels[group].append((channel_name, sources))

    # 生成分类内容（包含更新时间）
    for group_name in group_order:
        channels = grouped_channels[group_name]
        if not channels and group_name != "📢 系统信息":  # 跳过空分类（除了系统信息）
            continue
        valid_lines.append(f"\n# {group_name}")
        for channel_name, sources in channels:
            valid_lines.append(f"#EXTINF:-1 group-title='{group_name}',{channel_name}（{len(sources)}个源）")
            for url in sources:
                valid_lines.append(url)
                print(f"📺 [{group_name}] [{channel_name}] - 有效源：{url[:50]}...")

    # 容错逻辑
    if total_valid < MIN_VALID_SOURCES:
        print(f"\n⚠️  有效源({total_valid})低于阈值({MIN_VALID_SOURCES})，生成基础文件")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(f"""#EXTM3U
# 北京时刻更新时间：{update_time}
#EXTINF:-1 group-title='📢 系统信息',📅 北京时刻更新时间：{update_time}
#
#EXTINF:-1 group-title='📢 系统信息',⚠️  有效源较少，建议稍后重试
#""")
        return False

    # 写入文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_lines))

    print(f"\n📊 最终统计：验证 {len(task_list)} 源，有效 {total_valid} 源，有效频道 {len(channel_sources_map)} 个")
    for group_name in group_order:
        if grouped_channels[group_name]:
            print(f"   📋 {group_name}：{len(grouped_channels[group_name])} 频道")
    print(f"✅ 生成完成：{OUTPUT_FILE}（北京时刻更新：{update_time}）")
    return True

if __name__ == "__main__":
    start_time = time.time()
    print("========== 并行化IPTV源抓取（自定义分类+北京时刻） ==========")
    
    load_verified_cache()
    raw_data = fetch_raw_iptv_data_parallel(IPTV_SOURCE_URLS)
    if raw_data:
        generate_m3u8_parallel(raw_data)
    
    save_verified_cache()
    
    total_time = time.time() - start_time
    print(f"\n⏱️  总运行时间：{total_time:.2f} 秒")
    print("========== 抓取完成，缓存已保存 ==========")
