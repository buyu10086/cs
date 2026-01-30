import requests
import time
import random
import json
from datetime import datetime, timedelta
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# -------------------------- 配置优化（新增缓存+反爬配置） --------------------------
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/mytv-android/China-TV-Live-M3U8/refs/heads/main/webview.m3u"
]
# 核心优化：缩短验证超时时间
TIMEOUT = 3
OUTPUT_FILE = "iptv_playlist.m3u8"
REMOVE_DUPLICATE_CHANNELS = True
MIN_VALID_SOURCES = 3
# 并行线程数
MAX_THREADS = 30

# 新增优化1：缓存配置
CACHE_FILE = "iptv_verified_cache.json"
# 缓存有效期：24小时（避免旧缓存失效，可调整）
CACHE_EXPIRE_HOURS = 24

# 新增优化2：反爬随机延迟配置（0.1-0.5秒，不影响并行效率）
MIN_DELAY = 0.1
MAX_DELAY = 0.5

# 线程安全：锁保护共享数据
channel_sources_map = {}
map_lock = threading.Lock()
verified_urls = set()
url_lock = threading.Lock()

# -------------------------- 新增：缓存相关核心函数 --------------------------
def load_verified_cache():
    """加载本地已验证源的缓存（带过期判断）"""
    global verified_urls
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        # 验证缓存是否过期
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
        
        # 加载有效缓存
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
    """保存当前已验证源到本地缓存"""
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

# -------------------------- 新增：反爬延迟工具函数 --------------------------
def add_random_delay():
    """添加随机反爬延迟（不影响整体并行效率）"""
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)

# -------------------------- 并行化核心函数（整合缓存+反爬延迟） --------------------------
def fetch_single_source(url, idx):
    """并行抓取单个数据源，返回(是否成功, 有效行列表)（新增反爬延迟）"""
    # 新增：请求前添加随机延迟，避免反爬
    add_random_delay()
    
    try:
        response = requests.get(
            url,
            timeout=10,  # 数据源抓取超时可稍长
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://github.com/",
                "Accept": "*/*"
            }
        )
        response.raise_for_status()
        # 提前过滤无效行：空行、注释行
        lines = [line.strip() for line in response.text.splitlines() if line.strip() and not line.startswith("//")]
        print(f"✅ 数据源 {idx+1} 抓取成功，有效行 {len(lines)}")
        return True, lines
    except Exception as e:
        print(f"❌ 数据源 {idx+1} 抓取失败：{str(e)[:50]}")
        return False, []

def fetch_raw_iptv_data_parallel(url_list):
    """并行抓取所有数据源"""
    all_lines = []
    valid_source_count = 0
    # 线程池并行执行
    with ThreadPoolExecutor(max_workers=min(MAX_THREADS, len(url_list))) as executor:
        # 提交所有任务
        future_to_idx = {executor.submit(fetch_single_source, url, idx): idx for idx, url in enumerate(url_list)}
        # 按完成顺序获取结果
        for future in as_completed(future_to_idx):
            success, lines = future.result()
            if success and lines:
                all_lines.extend(lines)
                valid_source_count += 1
    print(f"\n📊 并行抓取完成：尝试 {len(url_list)} 源，可用 {valid_source_count} 源")
    return all_lines

def extract_channel_name(line):
    """从m3u注释行提取频道名称"""
    if line.startswith("#EXTINF:"):
        match = re.search(r',([^,]+)$', line)
        if not match:
            match = re.search(r'tvg-name="([^"]+)"', line)
        if match:
            return match.group(1).strip()
    return None

def verify_single_source(url, channel_name):
    """验证单个源是否可用，返回(频道名, 有效url)（新增反爬延迟+缓存复用）"""
    # 新增：请求前添加随机延迟，避免反爬
    add_random_delay()
    
    if not url.startswith(("http://", "https://")):
        return None, None
    
    # 复用缓存：避免重复验证（线程安全）
    with url_lock:
        if url in verified_urls:
            return channel_name, url
    
    try:
        response = requests.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
            stream=True  # 只请求头，不下载内容
        )
        if response.status_code in [200, 206, 301, 302, 307, 308]:
            with url_lock:
                verified_urls.add(url)
            return channel_name, url
    except:
        pass
    return None, None

def get_channel_group(channel_name):
    """频道分组逻辑（保留原有功能）"""
    if not channel_name:
        return "🎬 其他频道"
    cctv_keywords = ["CCTV", "央视", "中央", "央视频", "CCTV-", "中视"]
    if any(keyword in channel_name for keyword in cctv_keywords):
        return "📺 央视频道"
    if "卫视" in channel_name:
        return "📡 卫视频道"
    province_city = ["北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
                     "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
                     "广东", "广西", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海",
                     "内蒙古", "宁夏", "新疆", "西藏", "香港", "澳门", "台湾",
                     "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "郑州", "青岛"]
    for area in province_city:
        if area in channel_name and "卫视" not in channel_name:
            return "🏙️ 地方频道"
    return "🎬 其他频道"

def generate_m3u8_parallel(raw_lines):
    """并行验证源+生成m3u8文件"""
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 更新时间：{update_time}
# 支持多源切换+频道分组+本地缓存优化
"""
    valid_lines = [m3u8_header]
    valid_lines.append(f"#EXTINF:-1 group-title='📢 系统信息',📅 直播源更新时间：{update_time}")
    valid_lines.append("#")

    # 第一步：提取所有待验证的(频道名, url)对
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
    print(f"\n🔍 待验证源总数：{len(task_list)}（已复用本地缓存，无需重复验证有效源）")

    # 第二步：并行验证所有源
    total_valid = 0
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_task = {executor.submit(verify_single_source, url, chan): (url, chan) for url, chan in task_list}
        for future in as_completed(future_to_task):
            chan_name, valid_url = future.result()
            if chan_name and valid_url:
                total_valid += 1
                # 线程安全地更新频道-源映射
                with map_lock:
                    if chan_name not in channel_sources_map:
                        channel_sources_map[chan_name] = []
                    if valid_url not in channel_sources_map[chan_name]:
                        channel_sources_map[chan_name].append(valid_url)

    # 第三步：按分组生成文件
    grouped_channels = {"📺 央视频道": [], "📡 卫视频道": [], "🏙️ 地方频道": [], "🎬 其他频道": []}
    for channel_name, sources in channel_sources_map.items():
        if sources:
            group = get_channel_group(channel_name)
            grouped_channels[group].append((channel_name, sources))

    for group_name, channels in grouped_channels.items():
        if not channels:
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
# 更新时间：{update_time}
#EXTINF:-1 group-title='📢 系统信息',📅 直播源更新时间：{update_time}
#
#EXTINF:-1 group-title='📢 系统信息',⚠️  有效源较少，建议稍后重试
#""")
        return False

    # 写入最终文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_lines))

    print(f"\n📊 最终统计：验证 {len(task_list)} 源，有效 {total_valid} 源，有效频道 {len(channel_sources_map)} 个")
    for group_name, channels in grouped_channels.items():
        print(f"   📋 {group_name}：{len(channels)} 频道")
    print(f"✅ 生成完成：{OUTPUT_FILE}")
    return True

if __name__ == "__main__":
    start_time = time.time()
    print("========== 并行化IPTV源抓取（缓存+反爬优化） ==========")
    
    # 新增：程序启动时加载本地缓存
    load_verified_cache()
    
    raw_data = fetch_raw_iptv_data_parallel(IPTV_SOURCE_URLS)
    if raw_data:
        generate_m3u8_parallel(raw_data)
    
    # 新增：程序结束时保存缓存到本地
    save_verified_cache()
    
    # 计算总耗时
    total_time = time.time() - start_time
    print(f"\n⏱️  总运行时间：{total_time:.2f} 秒（约 {total_time/60:.1f} 分钟）")
    print("========== 抓取完成，缓存已保存，下次运行将更快 ==========")
