import requests
import time
import random
import json
from datetime import datetime, timedelta
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from pathlib import Path  # 新增：处理文件路径更安全

# -------------------------- 全局配置（集中管理，更易修改，补充注释） --------------------------
# 1. 数据源配置
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/mytv-android/China-TV-Live-M3U8/refs/heads/main/webview.m3u"
]

# 2. 验证与超时配置
TIMEOUT_VERIFY = 3  # 单个直播源验证超时时间（缩短，提升效率）
TIMEOUT_FETCH = 10  # 数据源文件抓取超时时间（稍长，保证完整获取）
MIN_VALID_CHANNELS = 3  # 优化：改为有效频道数阈值（更贴合业务逻辑）
MAX_THREADS_VERIFY = 30  # 直播源验证线程数（大量任务，高线程）
MAX_THREADS_FETCH = 5   # 数据源抓取线程数（少量URL，无需高线程，减少资源浪费）

# 3. 输出与去重配置
OUTPUT_FILE = "iptv_playlist.m3u8"
REMOVE_DUPLICATE_CHANNELS = True  # 现在已生效：去除重复频道
REMOVE_LOCAL_URLS = True  # 新增：过滤本地无效URL（localhost/127.0.0.1等）

# 4. 缓存配置
CACHE_FILE = "iptv_verified_cache.json"
CACHE_EXPIRE_HOURS = 24  # 缓存有效期24小时

# 5. 反爬与格式配置
MIN_DELAY = 0.1
MAX_DELAY = 0.5
CHANNEL_SORT_ENABLE = True  # 新增：频道按名称排序，生成文件更整洁

# -------------------------- 线程安全数据（减少全局变量依赖，优化锁逻辑） --------------------------
channel_sources_map = {}
map_lock = threading.Lock()
verified_urls = set()
url_lock = threading.Lock()

# -------------------------- 工具函数优化（编码处理、资源关闭、URL过滤） --------------------------
def add_random_delay():
    """添加随机反爬延迟（不影响整体并行效率）"""
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)

def filter_invalid_urls(url):
    """新增：过滤无效URL（本地地址、空值）"""
    if not url or not url.startswith(("http://", "https://")):
        return False
    if REMOVE_LOCAL_URLS and any(host in url.lower() for host in ["localhost", "127.0.0.1", "192.168.", "10.", "172."]):
        return False
    return True

def safe_extract_channel_name(line):
    """优化：增强频道名提取能力，适配更多M3U格式，提高成功率"""
    if not line.startswith("#EXTINF:"):
        return None
    
    # 正则优化：优先匹配最后一个逗号后内容，再匹配tvg-name，最后匹配title
    patterns = [
        r',\s*([^,]+)\s*$',  # 优先：匹配逗号后内容（最常见格式）
        r'tvg-name="([^"]+)"',  # 备选1：匹配tvg-name属性
        r'title="([^"]+)"',     # 备选2：匹配title属性
        r'[^"]+\s+([^,\s]+)$'   # 备选3：匹配最后一个非空白/非逗号内容
    ]
    
    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            channel_name = match.group(1).strip()
            # 过滤无效频道名
            if channel_name and not channel_name.isdigit():
                return channel_name
    return "未知频道"

# -------------------------- 缓存函数优化（健壮性提升，减少异常） --------------------------
def load_verified_cache():
    """加载本地已验证源的缓存（带过期判断，优化异常处理）"""
    global verified_urls
    try:
        cache_path = Path(CACHE_FILE)
        if not cache_path.exists():
            print(f"ℹ️  未找到缓存文件 {CACHE_FILE}，将在运行后创建")
            return
        
        # 安全读取文件，指定编码
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        # 验证缓存时间戳格式
        cache_time_str = cache_data.get("cache_time", "")
        if not cache_time_str:
            print("⚠️  缓存文件无有效时间戳，跳过加载")
            return
        
        try:
            cache_time = datetime.strptime(cache_time_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            print("⚠️  缓存时间戳格式错误，跳过加载")
            return
        
        # 判断缓存是否过期
        expire_time = cache_time + timedelta(hours=CACHE_EXPIRE_HOURS)
        current_time = datetime.now()
        if current_time > expire_time:
            print(f"⚠️  缓存已过期（超过{CACHE_EXPIRE_HOURS}小时），跳过加载")
            return
        
        # 加载有效缓存，去重
        valid_urls = cache_data.get("verified_urls", [])
        verified_urls = set(filter(filter_invalid_urls, valid_urls))  # 新增：过滤缓存中的无效URL
        print(f"✅ 成功加载本地缓存，共 {len(verified_urls)} 个有效已验证源（缓存时间：{cache_time_str}）")
    
    except json.JSONDecodeError:
        print(f"⚠️  缓存文件格式损坏，无法加载")
    except Exception as e:
        print(f"⚠️  加载缓存失败：{str(e)[:50]}")

def save_verified_cache():
    """保存当前已验证源到本地缓存（优化路径处理，确保目录存在）"""
    try:
        cache_path = Path(CACHE_FILE)
        # 新增：创建缓存文件所在目录（如果不存在）
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        cache_data = {
            "cache_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "verified_urls": list(verified_urls)
        }
        
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 成功保存缓存到 {CACHE_FILE}，共 {len(verified_urls)} 个已验证源")
    except Exception as e:
        print(f"❌ 保存缓存失败：{str(e)[:50]}")

# -------------------------- 数据源抓取优化（编码处理、线程数优化、资源安全） --------------------------
def fetch_single_source(url, idx):
    """并行抓取单个数据源，返回(是否成功, 有效行列表)（优化编码+资源处理）"""
    add_random_delay()
    
    try:
        response = requests.get(
            url,
            timeout=TIMEOUT_FETCH,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://github.com/",
                "Accept": "*/*"
            },
            stream=False  # 小文件直接获取，无需流式
        )
        response.raise_for_status()
        
        # 优化：自动检测编码，解决乱码问题
        response.encoding = response.apparent_encoding or "utf-8"
        lines = response.text.splitlines()
        
        # 过滤无效行：空行、//注释行、纯空格行
        valid_lines = []
        for line in lines:
            line_strip = line.strip()
            if line_strip and not line_strip.startswith("//"):
                valid_lines.append(line_strip)
        
        print(f"✅ 数据源 {idx+1} 抓取成功，有效行 {len(valid_lines)}")
        return True, valid_lines
    
    except requests.exceptions.Timeout:
        print(f"❌ 数据源 {idx+1} 抓取超时（超过{TIMEOUT_FETCH}秒）")
    except requests.exceptions.HTTPError as e:
        print(f"❌ 数据源 {idx+1} HTTP错误：{str(e)[:50]}")
    except requests.exceptions.ConnectionError:
        print(f"❌ 数据源 {idx+1} 连接失败")
    except Exception as e:
        print(f"❌ 数据源 {idx+1} 抓取失败：{str(e)[:50]}")
    
    return False, []

def fetch_raw_iptv_data_parallel(url_list):
    """并行抓取所有数据源（优化线程数，减少资源浪费）"""
    all_lines = []
    valid_source_count = 0
    # 优化：抓取阶段线程数适配URL数量（最多5个），无需30线程
    fetch_threads = min(MAX_THREADS_FETCH, len(url_list))
    
    with ThreadPoolExecutor(max_workers=fetch_threads) as executor:
        future_to_idx = {executor.submit(fetch_single_source, url, idx): idx for idx, url in enumerate(url_list)}
        for future in as_completed(future_to_idx):
            success, lines = future.result()
            if success and lines:
                all_lines.extend(lines)
                valid_source_count += 1
    
    print(f"\n📊 并行抓取完成：尝试 {len(url_list)} 源，可用 {valid_source_count} 源")
    return all_lines

# -------------------------- 源验证优化（缩小锁范围、提前去重、资源关闭） --------------------------
def verify_single_source(url, channel_name):
    """验证单个源是否可用，返回(频道名, 有效url)（优化锁范围，提升并行效率）"""
    # 前置过滤：无效URL直接返回
    if not filter_invalid_urls(url):
        return None, None
    
    add_random_delay()
    
    # 优化：查询set无需加锁（set查询线程安全），仅修改时加锁，减少锁竞争
    if url in verified_urls:
        return channel_name, url
    
    try:
        # 优化：stream=True时关闭响应，避免资源泄露
        with requests.get(
            url,
            timeout=TIMEOUT_VERIFY,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
            stream=True
        ) as response:
            # 仅验证状态码，不下载内容
            valid_status_codes = [200, 206, 301, 302, 307, 308]
            if response.status_code in valid_status_codes:
                # 仅修改verified_urls时加锁，缩小锁范围
                with url_lock:
                    verified_urls.add(url)
                return channel_name, url
    except:
        pass
    
    return None, None

def get_channel_group(channel_name):
    """频道分组逻辑（保留原有功能，格式优化）"""
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

# -------------------------- M3U8生成优化（生效去重、排序、目录处理） --------------------------
def generate_m3u8_parallel(raw_lines):
    """并行验证源+生成m3u8文件（优化去重、排序、容错）"""
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 更新时间：{update_time}
# 支持多源切换+频道分组+本地缓存优化+自动去重+无效URL过滤
"""
    valid_lines = [m3u8_header]
    valid_lines.append(f"#EXTINF:-1 group-title='📢 系统信息',📅 直播源更新时间：{update_time}")
    valid_lines.append("#")

    # 第一步：提取所有待验证的(频道名, url)对，提前去重避免重复任务
    task_list = []
    temp_channel = None
    seen_urls = set()  # 临时去重，避免重复验证同一个URL
    
    for line in raw_lines:
        line_strip = line.strip()
        if not line_strip:
            continue
        
        if line_strip.startswith("#EXTINF:"):
            temp_channel = safe_extract_channel_name(line_strip)
        elif filter_invalid_urls(line_strip) and temp_channel:
            # 去重：同一个URL不重复加入任务列表
            if line_strip not in seen_urls:
                seen_urls.add(line_strip)
                task_list.append((line_strip, temp_channel))
            temp_channel = None
    
    print(f"\n🔍 待验证源总数：{len(task_list)}（已去重+过滤无效URL+复用本地缓存）")

    # 第二步：并行验证所有源
    total_valid = 0
    with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
        future_to_task = {executor.submit(verify_single_source, url, chan): (url, chan) for url, chan in task_list}
        for future in as_completed(future_to_task):
            chan_name, valid_url = future.result()
            if chan_name and valid_url:
                total_valid += 1
                # 线程安全更新频道-源映射，同时去重（同一个频道的重复URL）
                with map_lock:
                    if chan_name not in channel_sources_map:
                        channel_sources_map[chan_name] = []
                    if valid_url not in channel_sources_map[chan_name]:
                        channel_sources_map[chan_name].append(valid_url)

    # 第三步：频道去重（生效REMOVE_DUPLICATE_CHANNELS配置）
    if REMOVE_DUPLICATE_CHANNELS:
        # 去重逻辑：保留源数量最多的频道（同名频道合并）
        dedup_map = {}
        for chan_name, sources in channel_sources_map.items():
            if chan_name not in dedup_map or len(sources) > len(dedup_map[chan_name]):
                dedup_map[chan_name] = sources
        channel_sources_map.clear()
        channel_sources_map.update(dedup_map)
        print(f"\n✨ 频道去重完成，剩余有效频道 {len(channel_sources_map)} 个")

    # 第四步：按分组生成文件，支持频道排序
    grouped_channels = {"📺 央视频道": [], "📡 卫视频道": [], "🏙️ 地方频道": [], "🎬 其他频道": []}
    
    for channel_name, sources in channel_sources_map.items():
        if sources:
            group = get_channel_group(channel_name)
            grouped_channels[group].append((channel_name, sources))

    # 优化：频道按名称排序，生成文件更整洁
    for group_name, channels in grouped_channels.items():
        if not channels:
            continue
        # 排序开关生效
        if CHANNEL_SORT_ENABLE:
            channels.sort(key=lambda x: x[0])  # 按频道名称字母序排序
        valid_lines.append(f"\n# {group_name}")
        for channel_name, sources in channels:
            valid_lines.append(f"#EXTINF:-1 group-title='{group_name}',{channel_name}（{len(sources)}个源）")
            for idx, url in enumerate(sources, 1):
                # 新增：源标注序号，方便识别切换
                valid_lines.append(f"# 源{idx}：{url[:60]}...")
                valid_lines.append(url)
                print(f"📺 [{group_name}] [{channel_name}] - 有效源{idx}：{url[:50]}...")

    # 第五步：容错逻辑优化（判断有效频道数，更贴合业务）
    valid_channel_count = len(channel_sources_map)
    if valid_channel_count < MIN_VALID_CHANNELS:
        print(f"\n⚠️  有效频道({valid_channel_count})低于阈值({MIN_VALID_CHANNELS})，生成基础文件")
        output_path = Path(OUTPUT_FILE)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"""#EXTM3U
# 更新时间：{update_time}
#EXTINF:-1 group-title='📢 系统信息',📅 直播源更新时间：{update_time}
#EXTINF:-1 group-title='📢 系统信息',⚠️  有效频道较少，建议稍后重试
#""")
        return False

    # 第六步：写入最终文件（优化路径处理，确保目录存在）
    try:
        output_path = Path(OUTPUT_FILE)
        # 新增：创建输出文件所在目录（如果不存在）
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(valid_lines))
    except Exception as e:
        print(f"❌ 写入输出文件失败：{str(e)[:50]}")
        return False

    # 第七步：输出最终统计
    print(f"\n📊 最终统计：验证 {len(task_list)} 源，有效 {total_valid} 源，有效频道 {valid_channel_count} 个")
    for group_name, channels in grouped_channels.items():
        print(f"   📋 {group_name}：{len(channels)} 频道")
    print(f"✅ 生成完成：{OUTPUT_FILE}（路径：{Path(OUTPUT_FILE).absolute()}）")
    return True

# -------------------------- 主程序（保持原有流程，优化输出） --------------------------
if __name__ == "__main__":
    start_time = time.time()
    print("========== 并行化IPTV源抓取（缓存+反爬+去重优化版） ==========")
    
    # 加载本地缓存
    load_verified_cache()
    
    # 抓取原始数据
    raw_data = fetch_raw_iptv_data_parallel(IPTV_SOURCE_URLS)
    
    # 生成M3U8文件
    if raw_data:
        generate_m3u8_parallel(raw_data)
    else:
        print("\n❌ 未抓取到任何原始数据，无法生成M3U8文件")
    
    # 保存缓存到本地
    save_verified_cache()
    
    # 计算总耗时
    total_time = time.time() - start_time
    print(f"\n⏱️  总运行时间：{total_time:.2f} 秒（约 {total_time/60:.1f} 分钟）")
    print("========== 抓取完成，缓存已保存，下次运行将更快 ==========")
