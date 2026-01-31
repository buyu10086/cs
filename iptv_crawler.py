import requests
import time
import random
import json
from datetime import datetime, timedelta
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from pathlib import Path

# -------------------------- 全局配置（新增【美化相关配置】，可自定义） --------------------------
# 1. 数据源配置
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/result.m3u",
    "http://wx.thego.cn/ak.m3u
    "https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u",
    "https://raw.githubusercontent.com/xzw832/cmys/refs/heads/main/S_CCTV.txt",
    "https://raw.githubusercontent.com/xzw832/cmys/refs/heads/main/S_weishi.txt",
    "https://raw.githubusercontent.com/YueChan/Live/main/APTV.m3u",
    "http://aktv.top/live.m3u",
    "https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u",
    "https://raw.githubusercontent.com/audyfan/tv/refs/heads/main/live.m3u"
]

# 2. 验证与超时配置
TIMEOUT_VERIFY = 3
TIMEOUT_FETCH = 10
MIN_VALID_CHANNELS = 3
MAX_THREADS_VERIFY = 30
MAX_THREADS_FETCH = 5

# 3. 输出与去重配置
OUTPUT_FILE = "iptv_playlist.m3u8"
REMOVE_DUPLICATE_CHANNELS = True
REMOVE_LOCAL_URLS = True

# 4. 缓存配置
CACHE_FILE = "iptv_verified_cache.json"
CACHE_EXPIRE_HOURS = 24

# 5. 反爬与基础配置
MIN_DELAY = 0.1
MAX_DELAY = 0.5
CHANNEL_SORT_ENABLE = True

# ========== 新增：M3U8美化专属配置（可根据喜好修改） ==========
URL_TRUNCATE_LENGTH = 60  # URL截断长度（保留核心域名+路径，避免超长）
GROUP_SEPARATOR = "#" * 40  # 分组间分隔符（视觉分隔，不影响播放器）
SHOW_BOTTOM_STAT = True  # 是否显示底部汇总统计
CHANNEL_NAME_CLEAN = True  # 是否清理频道名多余空格/特殊字符（标准化）
SOURCE_NUM_PREFIX = "源"  # 多源编号前缀（如“源1”/“第1源”，可改）

# -------------------------- 线程安全数据 --------------------------
channel_sources_map = {}
map_lock = threading.Lock()
verified_urls = set()
url_lock = threading.Lock()

# -------------------------- 工具函数（新增【频道名标准化】函数） --------------------------
def add_random_delay():
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)

def filter_invalid_urls(url):
    if not url or not url.startswith(("http://", "https://")):
        return False
    if REMOVE_LOCAL_URLS and any(host in url.lower() for host in ["localhost", "127.0.0.1", "192.168.", "10.", "172."]):
        return False
    return True

def safe_extract_channel_name(line):
    if not line.startswith("#EXTINF:"):
        return None
    patterns = [
        r',\s*([^,]+)\s*$',
        r'tvg-name="([^"]+)"',
        r'title="([^"]+)"',
        r'[^"]+\s+([^,\s]+)$'
    ]
    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            channel_name = match.group(1).strip()
            if channel_name and not channel_name.isdigit():
                return channel_name
    return "未知频道"

# ========== 新增：频道名标准化清理（美化核心） ==========
def clean_channel_name(name):
    """清理频道名多余空格、特殊符号，实现标准化"""
    if not CHANNEL_NAME_CLEAN or not name:
        return name
    # 过滤多余空格（多个空格变一个）、首尾空格
    name = re.sub(r'\s+', ' ', name).strip()
    # 过滤无用特殊符号（保留中文/英文/数字/常见符号）
    name = re.sub(r'[^\u4e00-\u9fff_a-zA-Z0-9\-\(\)（）·、]', '', name)
    # 统一括号格式（英文()变中文（））
    name = name.replace("(", "（").replace(")", "）")
    return name

# ========== 新增：URL规范截断（美化核心） ==========
def truncate_url(url, length=URL_TRUNCATE_LENGTH):
    """URL截断，超长时末尾加...，保留核心识别部分"""
    if len(url) <= length:
        return url
    return url[:length].strip() + "..."

# -------------------------- 缓存函数 --------------------------
def load_verified_cache():
    global verified_urls
    try:
        cache_path = Path(CACHE_FILE)
        if not cache_path.exists():
            print(f"ℹ️  未找到缓存文件 {CACHE_FILE}，将在运行后创建")
            return
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        cache_time_str = cache_data.get("cache_time", "")
        if not cache_time_str:
            print("⚠️  缓存文件无有效时间戳，跳过加载")
            return
        try:
            cache_time = datetime.strptime(cache_time_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            print("⚠️  缓存时间戳格式错误，跳过加载")
            return
        expire_time = cache_time + timedelta(hours=CACHE_EXPIRE_HOURS)
        current_time = datetime.now()
        if current_time > expire_time:
            print(f"⚠️  缓存已过期（超过{CACHE_EXPIRE_HOURS}小时），跳过加载")
            return
        valid_urls = cache_data.get("verified_urls", [])
        verified_urls = set(filter(filter_invalid_urls, valid_urls))
        print(f"✅ 成功加载本地缓存，共 {len(verified_urls)} 个有效已验证源（缓存时间：{cache_time_str}）")
    except json.JSONDecodeError:
        print(f"⚠️  缓存文件格式损坏，无法加载")
    except Exception as e:
        print(f"⚠️  加载缓存失败：{str(e)[:50]}")

def save_verified_cache():
    try:
        cache_path = Path(CACHE_FILE)
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

# -------------------------- 数据源抓取函数 --------------------------
def fetch_single_source(url, idx):
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
            stream=False
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        lines = response.text.splitlines()
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
    all_lines = []
    valid_source_count = 0
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

# -------------------------- 源验证函数 --------------------------
def verify_single_source(url, channel_name):
    if not filter_invalid_urls(url):
        return None, None
    add_random_delay()
    if url in verified_urls:
        return channel_name, url
    try:
        with requests.get(
            url,
            timeout=TIMEOUT_VERIFY,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
            stream=True
        ) as response:
            valid_status_codes = [200, 206, 301, 302, 307, 308]
            if response.status_code in valid_status_codes:
                with url_lock:
                    verified_urls.add(url)
                return channel_name, url
    except:
        pass
    return None, None

def get_channel_group(channel_name):
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

# -------------------------- 核心：美化后的M3U8生成函数 --------------------------
def generate_m3u8_parallel(raw_lines):
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # ========== 美化1：顶部元信息增强（详细、结构化，不影响播放器） ==========
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# ================================= IPTV直播源信息 =================================
# 生成时间    ：{update_time}
# 缓存状态    ：{"已加载本地缓存（有效期24小时）" if len(verified_urls) > 0 else "未加载缓存（首次运行/缓存过期）"}
# 生效配置    ：频道去重={REMOVE_DUPLICATE_CHANNELS} | 本地URL过滤={REMOVE_LOCAL_URLS} | 频道排序={CHANNEL_SORT_ENABLE}
# 验证规则    ：超时{TIMEOUT_VERIFY}秒 | 仅保留HTTP/HTTPS有效链接
# 播放器兼容  ：支持所有标准M3U8播放器（Kodi/完美视频/TVBox等）
# ================================================================================
"""
    valid_lines = [m3u8_header]
    total_valid_source = 0  # 统计总有效源数（用于底部汇总）

    # 提取待验证任务
    task_list = []
    temp_channel = None
    seen_urls = set()
    for line in raw_lines:
        line_strip = line.strip()
        if not line_strip:
            continue
        if line_strip.startswith("#EXTINF:"):
            temp_channel = safe_extract_channel_name(line_strip)
        elif filter_invalid_urls(line_strip) and temp_channel:
            if line_strip not in seen_urls:
                seen_urls.add(line_strip)
                task_list.append((line_strip, temp_channel))
            temp_channel = None
    print(f"\n🔍 待验证源总数：{len(task_list)}（已去重+过滤无效URL+复用本地缓存）")

    # 并行验证源
    with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
        future_to_task = {executor.submit(verify_single_source, url, chan): (url, chan) for url, chan in task_list}
        for future in as_completed(future_to_task):
            chan_name, valid_url = future.result()
            if chan_name and valid_url:
                with map_lock:
                    if chan_name not in channel_sources_map:
                        channel_sources_map[chan_name] = []
                    if valid_url not in channel_sources_map[chan_name]:
                        channel_sources_map[chan_name].append(valid_url)

    # 频道去重
    if REMOVE_DUPLICATE_CHANNELS:
        dedup_map = {}
        for chan_name, sources in channel_sources_map.items():
            if chan_name not in dedup_map or len(sources) > len(dedup_map[chan_name]):
                dedup_map[chan_name] = sources
        channel_sources_map.clear()
        channel_sources_map.update(dedup_map)
        print(f"\n✨ 频道去重完成，剩余有效频道 {len(channel_sources_map)} 个")

    # 分组整理
    grouped_channels = {"📺 央视频道": [], "📡 卫视频道": [], "🏙️ 地方频道": [], "🎬 其他频道": []}
    for channel_name, sources in channel_sources_map.items():
        if not sources:
            continue
        clean_name = clean_channel_name(channel_name)  # 标准化频道名
        group = get_channel_group(clean_name)
        grouped_channels[group].append((clean_name, sources))
        total_valid_source += len(sources)  # 累计总有效源数

    # ========== 美化2：系统信息独立分组（醒目，和直播频道分隔） ==========
    valid_lines.append(f"\n# 📢 系统信息（共1项）")
    valid_lines.append(f"#EXTINF:-1 group-title='📢 系统信息',直播源生成统计")
    valid_lines.append(f"# 有效频道数：{len(channel_sources_map)} 个 | 总有效源数：{total_valid_source} 个")
    valid_lines.append("#")  # 空行占位，不影响播放器

    # ========== 美化3：分组可视化（分隔符+数量统计+有序排序） ==========
    for group_name, channels in grouped_channels.items():
        if not channels:
            continue
        # 分组排序
        if CHANNEL_SORT_ENABLE:
            channels.sort(key=lambda x: x[0])
        # 分组头：分隔符+分组名+频道数
        valid_lines.append(f"\n{GROUP_SEPARATOR}")
        valid_lines.append(f"# {group_name}（共{len(channels)}个频道）")
        valid_lines.append(GROUP_SEPARATOR)
        
        # ========== 美化4：频道标准化+多源有序标注（核心美化） ==========
        for channel_name, sources in channels:
            source_count = len(sources)
            # 频道行：标准化名称+源数标注（播放器可正常识别频道名）
            valid_lines.append(f"\n#EXTINF:-1 group-title='{group_name}',{channel_name}（{source_count}个有效源）")
            # 多源：有序编号+URL截断+注释标注（视觉整洁，方便识别）
            for idx, url in enumerate(sources, 1):
                trunc_url = truncate_url(url)
                valid_lines.append(f"# {SOURCE_NUM_PREFIX}{idx}：{trunc_url}")
                valid_lines.append(url)  # 原始URL（播放器核心识别，必须保留）
                print(f"📺 [{group_name}] [{channel_name}] - {SOURCE_NUM_PREFIX}{idx}：{trunc_url}")

    # ========== 美化5：底部汇总统计（可选，结构化信息）【已修复：三重引号包裹多行f-string】 ==========
    if SHOW_BOTTOM_STAT and len(channel_sources_map) >= MIN_VALID_CHANNELS:
        valid_lines.append(f"\n{GROUP_SEPARATOR}")
        # 修复核心：用三重引号包裹多行f-string，支持换行且语法合法
        bottom_stat = f"""# ================================= 汇总统计 =================================
# 生成时间    ：{update_time}
# 总有效频道  ：{len(channel_sources_map)} 个
# 总有效源数  ：{total_valid_source} 个
# 分组明细    ：央视频道{len(grouped_channels['📺 央视频道'])}个 | 卫视频道{len(grouped_channels['📡 卫视频道'])}个 | 地方频道{len(grouped_channels['🏙️ 地方频道'])}个 | 其他频道{len(grouped_channels['🎬 其他频道'])}个
# 缓存说明    ：已保存{len(verified_urls)}个有效源到本地缓存，下次运行无需重复验证
# ================================================================================"""
        valid_lines.append(bottom_stat)

    # 容错逻辑（优化，保留美化格式）
    valid_channel_count = len(channel_sources_map)
    if valid_channel_count < MIN_VALID_CHANNELS:
        print(f"\n⚠️  有效频道({valid_channel_count})低于阈值({MIN_VALID_CHANNELS})，生成基础美化文件")
        output_path = Path(OUTPUT_FILE)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        error_content = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# ================================= IPTV直播源信息 =================================
# 生成时间    ：{update_time}
# 生成状态    ：有效频道数不足（仅{valid_channel_count}个），建议稍后重试
# 重试建议    ：检查网络/等待数据源更新/降低MIN_VALID_CHANNELS阈值
# ================================================================================

# 📢 系统信息（共1项）
#EXTINF:-1 group-title='📢 系统信息',生成失败提醒
# 有效频道数低于阈值{MIN_VALID_CHANNELS}，请稍后重新运行脚本
#"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(error_content)
        return False

    # 写入美化后的M3U8文件
    try:
        output_path = Path(OUTPUT_FILE)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(valid_lines))
    except Exception as e:
        print(f"❌ 写入输出文件失败：{str(e)[:50]}")
        return False

    # 最终统计
    print(f"\n📊 最终统计：验证 {len(task_list)} 源，有效 {total_valid_source} 源，有效频道 {valid_channel_count} 个")
    for group_name, channels in grouped_channels.items():
        print(f"   📋 {group_name}：{len(channels)} 频道")
    print(f"✅ 美化版M3U8生成完成：{OUTPUT_FILE}（路径：{Path(OUTPUT_FILE).absolute()}）")
    return True

# -------------------------- 主程序 --------------------------
if __name__ == "__main__":
    start_time = time.time()
    print("========== 并行化IPTV源抓取（缓存+反爬+美化输出版） ==========")
    load_verified_cache()
    raw_data = fetch_raw_iptv_data_parallel(IPTV_SOURCE_URLS)
    if raw_data:
        generate_m3u8_parallel(raw_data)
    else:
        print("\n❌ 未抓取到任何原始数据，无法生成M3U8文件")
    save_verified_cache()
    total_time = time.time() - start_time
    print(f"\n⏱️  总运行时间：{total_time:.2f} 秒（约 {total_time/60:.1f} 分钟）")
    print("========== 抓取完成，缓存已保存，美化版M3U8生成成功 ==========")
