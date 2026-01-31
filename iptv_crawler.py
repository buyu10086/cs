import requests
import time
import random
import json
from datetime import datetime, timedelta
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from pathlib import Path
import logging

# -------------------------- 全局配置（所有配置保留，新增更新时间格式配置） --------------------------
# 1. 数据源配置
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/result.m3u",
    "https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u",
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

# ========== M3U8美化专属配置 ==========
URL_TRUNCATE_LENGTH = 60
GROUP_SEPARATOR = "#" * 40
SHOW_BOTTOM_STAT = True
CHANNEL_NAME_CLEAN = True
SOURCE_NUM_PREFIX = "源"

# ========== 智能选源核心配置 ==========
MAX_SOURCES_PER_CHANNEL = 3  # 每个频道保留最快的3个源
SORT_SOURCE_BY_SPEED = True  # 按速度从快到慢排序

# ========== 新增：M3U8更新时刻配置（可自定义格式） ==========
UPDATE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"  # 更新时间显示格式，可按需修改
# 示例格式：%Y-%m-%d %H:%M → 2026-01-31 20:30；%Y/%m/%d %H:%M:%S → 2026/01/31 20:30:00

# -------------------------- 全局初始化（日志+Session+线程安全） --------------------------
def init_logger():
    logger = logging.getLogger("IPTV_Spider")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    stream_handler = logging.StreamHandler()
    file_handler = logging.FileHandler("iptv_spider.log", encoding="utf-8", mode="a")
    stream_handler.setFormatter(fmt)
    file_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger

logger = init_logger()

# 全局Session（抓取/验证分离）
FETCH_SESSION = requests.Session()
VERIFY_SESSION = requests.Session()
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://github.com/",
    "Accept": "*/*",
    "Cache-Control": "no-cache"
}
FETCH_SESSION.headers.update(DEFAULT_HEADERS)
VERIFY_SESSION.headers.update(DEFAULT_HEADERS)

# 线程安全数据
channel_sources_map = {}  # 格式：{频道名: [(url, 耗时), ...]}
map_lock = threading.Lock()
verified_urls = set()
url_lock = threading.Lock()
temp_verified_results = threading.local()
temp_verified_results.data = []
# 全局更新时间（脚本运行时生成，所有频道统一显示）
GLOBAL_UPDATE_TIME = datetime.now().strftime(UPDATE_TIME_FORMAT)

# -------------------------- 工具函数（全量兼容+优化） --------------------------
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

def clean_channel_name(name):
    if not CHANNEL_NAME_CLEAN or not name:
        return name
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[^\u4e00-\u9fff_a-zA-Z0-9\-\(\)（）·、]', '', name)
    name = replace("(", "（").replace(")", "）")
    return name

def truncate_url(url, length=URL_TRUNCATE_LENGTH):
    if len(url) <= length:
        return url
    return url[:length].strip() + "..."

def normalize_channel_name(name):
    """频道名归一化，实现模糊去重"""
    if not name:
        return "未知频道"
    norm_name = re.sub(r'[^\u4e00-\u9fff0-9a-zA-Z]', '', name).upper()
    # 央视频道归一化映射
    cctv_map = {
        "央视1套": "CCTV1", "中央1套": "CCTV1", "央视2套": "CCTV2", "中央2套": "CCTV2",
        "央视3套": "CCTV3", "中央3套": "CCTV3", "央视4套": "CCTV4", "中央4套": "CCTV4",
        "央视5套": "CCTV5", "中央5套": "CCTV5", "央视6套": "CCTV6", "中央6套": "CCTV6",
        "央视7套": "CCTV7", "中央7套": "CCTV7", "央视8套": "CCTV8", "中央8套": "CCTV8",
        "央视9套": "CCTV9", "中央9套": "CCTV9", "央视10套": "CCTV10", "中央10套": "CCTV10",
        "央视11套": "CCTV11", "中央11套": "CCTV11", "央视12套": "CCTV12", "中央12套": "CCTV12",
        "央视13套": "CCTV13", "中央13套": "CCTV13", "央视14套": "CCTV14", "中央14套": "CCTV14",
        "央视15套": "CCTV15", "中央15套": "CCTV15", "央视16套": "CCTV16", "中央16套": "CCTV16",
        "央视17套": "CCTV17", "中央17套": "CCTV17"
    }
    for key, val in cctv_map.items():
        if key.upper() in norm_name:
            norm_name = val
            break
    return norm_name if norm_name else "未知频道"

# -------------------------- 缓存函数（增量更新+无效清理） --------------------------
def load_verified_cache():
    global verified_urls
    try:
        cache_path = Path(CACHE_FILE)
        if not cache_path.exists():
            logger.info(f"未找到缓存文件 {CACHE_FILE}，首次运行将创建")
            return
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        cache_time_str = cache_data.get("cache_time", "")
        valid_urls = cache_data.get("verified_urls", [])
        if not cache_time_str or not valid_urls:
            logger.warning("缓存文件无有效数据，跳过加载")
            return
        try:
            cache_time = datetime.strptime(cache_time_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.warning("缓存时间格式错误，跳过加载")
            return
        if datetime.now() > cache_time + timedelta(hours=CACHE_EXPIRE_HOURS):
            logger.warning(f"缓存已过期（超过{CACHE_EXPIRE_HOURS}小时），跳过加载")
            return
        valid_urls_filtered = [url for url in valid_urls if filter_invalid_urls(url)]
        verified_urls = set(valid_urls_filtered)
        logger.info(f"成功加载本地缓存，共 {len(verified_urls)} 个有效已验证源（缓存时间：{cache_time_str}）")
    except json.JSONDecodeError:
        logger.error("缓存文件格式损坏，无法加载")
    except Exception as e:
        logger.error(f"加载缓存失败：{str(e)[:50]}", exc_info=False)

def save_verified_cache():
    try:
        cache_path = Path(CACHE_FILE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        valid_verified_urls = [url for url in verified_urls if filter_invalid_urls(url)]
        cache_data = {
            "cache_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "verified_urls": valid_verified_urls
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.info(f"成功保存缓存到 {CACHE_FILE}，共 {len(valid_verified_urls)} 个有效源（已清理无效缓存）")
    except Exception as e:
        logger.error(f"保存缓存失败：{str(e)[:50]}", exc_info=False)

# -------------------------- 数据源抓取函数（流式读取+Session复用） --------------------------
def fetch_single_source(url, idx):
    add_random_delay()
    try:
        with FETCH_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as response:
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            valid_lines = []
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                line_strip = line.strip()
                if line_strip and not line_strip.startswith("//"):
                    valid_lines.append(line_strip)
        logger.info(f"数据源 {idx+1} 抓取成功，有效行 {len(valid_lines)}")
        return True, valid_lines
    except requests.exceptions.Timeout:
        logger.error(f"数据源 {idx+1} 抓取超时（超过{TIMEOUT_FETCH}秒）")
    except requests.exceptions.HTTPError as e:
        logger.error(f"数据源 {idx+1} HTTP错误：{str(e)[:50]}")
    except requests.exceptions.ConnectionError:
        logger.error(f"数据源 {idx+1} 连接失败，可能网络/源失效")
    except Exception as e:
        logger.error(f"数据源 {idx+1} 抓取失败：{str(e)[:50]}", exc_info=False)
    return False, []

def fetch_raw_iptv_data_parallel(url_list):
    all_lines = []
    valid_source_count = 0
    fetch_threads = min(MAX_THREADS_FETCH, len(url_list))
    logger.info(f"开始并行抓取数据源，线程数：{fetch_threads}，待抓取源数：{len(url_list)}")
    with ThreadPoolExecutor(max_workers=fetch_threads) as executor:
        future_to_idx = {executor.submit(fetch_single_source, url, idx): idx for idx, url in enumerate(url_list)}
        for future in as_completed(future_to_idx):
            success, lines = future.result()
            if success and lines:
                all_lines.extend(lines)
                valid_source_count += 1
    logger.info(f"并行抓取完成：尝试 {len(url_list)} 源，可用 {valid_source_count} 源，总有效行：{len(all_lines)}")
    return all_lines

# -------------------------- 源验证函数（精细化验证+记录响应耗时） --------------------------
def verify_single_source(url, channel_name):
    if not filter_invalid_urls(url):
        return None, None, None
    add_random_delay()
    if url in verified_urls:
        return channel_name, url, 0.0  # 缓存源耗时标记为0（最快）
    # 精细化超时配置
    connect_timeout = 1
    read_timeout = TIMEOUT_VERIFY - connect_timeout if TIMEOUT_VERIFY - connect_timeout > 0 else 1
    valid_stream_suffix = (".m3u8", ".ts", ".flv", ".rtmp", ".rtsp")
    valid_content_types = ["video/", "application/x-mpegurl", "audio/", "application/octet-stream"]
    
    try:
        # 核心：记录请求开始时间，计算实际响应耗时
        start_time = time.time()
        with VERIFY_SESSION.get(
            url,
            timeout=(connect_timeout, read_timeout),
            allow_redirects=True,
            stream=True,
            headers={"Range": "bytes=0-1024"}
        ) as response:
            # 计算耗时（保留3位小数，转毫秒更直观）
            response_time = round((time.time() - start_time) * 1000, 3)
            
            # 三重验证：状态码+响应头+流格式
            if response.status_code not in [200, 206, 301, 302, 307, 308]:
                return None, None, None
            content_type = response.headers.get("Content-Type", "").lower()
            if not any(ct in content_type for ct in valid_content_types):
                return None, None, None
            final_url = response.url.lower()
            if not final_url.endswith(valid_stream_suffix):
                return None, None, None
            # m3u8文件头额外验证
            if final_url.endswith(".m3u8"):
                stream_data = response.content[:1024].decode("utf-8", errors="ignore")
                if "#EXTM3U" not in stream_data:
                    return None, None, None
            
            # 验证通过，加入缓存
            with url_lock:
                verified_urls.add(url)
            temp_verified_results.data.append((channel_name, url, response_time))
            return channel_name, url, response_time
    except Exception:
        return None, None, None

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

# -------------------------- 核心：智能选源+美化M3U8+更新时刻标注 --------------------------
def generate_m3u8_parallel(raw_lines):
    # 带更新时刻的头部
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# ================================= IPTV直播源信息 =================================
# 生成时间    ：{GLOBAL_UPDATE_TIME}
# 缓存状态    ：{"已加载本地缓存（有效期24小时）" if len(verified_urls) > 0 else "未加载缓存（首次运行/缓存过期）"}
# 生效配置    ：频道去重={REMOVE_DUPLICATE_CHANNELS} | 本地URL过滤={REMOVE_LOCAL_URLS} | 频道排序={CHANNEL_SORT_ENABLE}
# 验证规则    ：超时{TIMEOUT_VERIFY}秒 | 精细化验证（状态码+流格式+文件头）
# 智能选源    ：每个频道保留最快{MAX_SOURCES_PER_CHANNEL}个源 | 排序规则={SORT_SOURCE_BY_SPEED and '从快到慢' or '原顺序'}
# 播放器兼容  ：支持所有标准M3U8播放器（Kodi/完美视频/TVBox等）
# ================================================================================
"""
    valid_lines = [m3u8_header]
    total_valid_source = 0

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
    if not task_list:
        logger.error("未提取到待验证的源，无法生成M3U8")
        return False
    logger.info(f"待验证源总数：{len(task_list)}（已去重+过滤无效URL+复用本地缓存）")

    # 动态线程池验证+测速
    verify_threads = max(5, min(len(task_list)//2, 50))
    logger.info(f"开始并行验证源+测速，动态线程数：{verify_threads}")
    with ThreadPoolExecutor(max_workers=verify_threads) as executor:
        future_to_task = {executor.submit(verify_single_source, url, chan): (url, chan) for url, chan in task_list}
        success_count = 0
        fail_count = 0
        for future in as_completed(future_to_task):
            chan_name, valid_url, response_time = future.result()
            if chan_name and valid_url:
                success_count += 1
                # 存入带耗时的源数据
                with map_lock:
                    if chan_name not in channel_sources_map:
                        channel_sources_map[chan_name] = []
                    # 去重相同URL（避免同一频道多个相同源）
                    if not any(item[0] == valid_url for item in channel_sources_map[chan_name]):
                        channel_sources_map[chan_name].append((valid_url, response_time))
            else:
                fail_count += 1
    logger.info(f"源验证+测速完成：成功 {success_count} 个，失败 {fail_count} 个，验证成功率：{success_count/(success_count+fail_count)*100:.1f}%")

    # 频道模糊去重
    if REMOVE_DUPLICATE_CHANNELS:
        dedup_map = {}
        norm_name_map = {}
        for chan_name, sources in channel_sources_map.items():
            if not sources:
                continue
            norm_name = normalize_channel_name(chan_name)
            # 保留源数最多的频道（保证备用源充足）
            if norm_name not in norm_name_map or len(sources) > len(norm_name_map[norm_name][1]):
                norm_name_map[norm_name] = (chan_name, sources)
        for norm_name, (orig_name, sources) in norm_name_map.items():
            dedup_map[orig_name] = sources
        channel_sources_map.clear()
        channel_sources_map.update(dedup_map)
        logger.info(f"频道模糊去重完成，剩余有效频道 {len(channel_sources_map)} 个")

    # 核心：智能选源逻辑（按速度筛选+排序）
    smart_selected_map = {}
    total_selected_source = 0
    for chan_name, sources in channel_sources_map.items():
        if not sources:
            continue
        # 1. 按响应耗时排序（0=缓存源，最快排最前）
        if SORT_SOURCE_BY_SPEED:
            sorted_sources = sorted(sources, key=lambda x: x[1])
        else:
            sorted_sources = sources
        # 2. 保留最快的N个源（MAX_SOURCES_PER_CHANNEL）
        selected_sources = sorted_sources[:MAX_SOURCES_PER_CHANNEL]
        smart_selected_map[chan_name] = selected_sources
        total_selected_source += len(selected_sources)
    # 替换为智能选源后的结果
    channel_sources_map = smart_selected_map
    logger.info(f"智能选源完成：每个频道保留最快{MAX_SOURCES_PER_CHANNEL}个源，最终筛选出 {total_selected_source} 个优质源")

    # 分组整理
    grouped_channels = {"📺 央视频道": [], "📡 卫视频道": [], "🏙️ 地方频道": [], "🎬 其他频道": []}
    for channel_name, sources in channel_sources_map.items():
        if not sources:
            continue
        clean_name = clean_channel_name(channel_name)
        group = get_channel_group(clean_name)
        grouped_channels[group].append((clean_name, sources))

    # 系统信息分组（新增更新时刻标注）
    valid_lines.append(f"\n# 📢 系统信息（共1项）")
    valid_lines.append(f"#EXTINF:-1 group-title='📢 系统信息',直播源生成统计【更新于：{GLOBAL_UPDATE_TIME}】")
    valid_lines.append(f"# 有效频道数：{len(channel_sources_map)} 个 | 优质源总数：{total_selected_source} 个 | 验证成功率：{success_count/(success_count+fail_count)*100:.1f}%")
    valid_lines.append(f"# 智能选源：每个频道保留最快{MAX_SOURCES_PER_CHANNEL}个源，播放器建议优先选择第一个源（最快）")
    valid_lines.append(f"# 源更新时刻：{GLOBAL_UPDATE_TIME} | 缓存源标记为【缓存·最快】")
    valid_lines.append("#")

    # 美化分组输出：【核心】在每个频道播放段标注更新时刻
    for group_name, channels in grouped_channels.items():
        if not channels:
            continue
        if CHANNEL_SORT_ENABLE:
            channels.sort(key=lambda x: x[0])
        valid_lines.append(f"\n{GROUP_SEPARATOR}")
        valid_lines.append(f"# {group_name}（共{len(channels)}个频道 | 源更新于：{GLOBAL_UPDATE_TIME}）")
        valid_lines.append(GROUP_SEPARATOR)
        for channel_name, sources in channels:
            source_count = len(sources)
            # 频道标题栏标注更新时刻
            valid_lines.append(f"\n#EXTINF:-1 group-title='{group_name}',{channel_name}（{source_count}个优质源·从快到慢·更新于：{GLOBAL_UPDATE_TIME}）")
            # 输出带耗时+更新时刻的源（注释标注，不影响播放）
            for idx, (url, response_time) in enumerate(sources, 1):
                trunc_url = truncate_url(url)
                # 耗时标注：缓存源显示【缓存·最快】，其他显示具体毫秒
                speed_note = "【缓存·最快】" if response_time == 0.0 else f"【{response_time}ms】"
                # 源行注释添加更新时刻
                valid_lines.append(f"# {SOURCE_NUM_PREFIX}{idx} {speed_note} | 源更新于：{GLOBAL_UPDATE_TIME}：{trunc_url}")
                valid_lines.append(url)
                logger.debug(f"优质源：[{group_name}] [{channel_name}] - {SOURCE_NUM_PREFIX}{idx} {speed_note}：{trunc_url}")

    # 底部汇总统计（强化更新时刻显示）
    if SHOW_BOTTOM_STAT and len(channel_sources_map) >= MIN_VALID_CHANNELS:
        valid_lines.append(f"\n{GROUP_SEPARATOR}")
        bottom_stat = f"""# ================================= 汇总统计 =================================
# 源更新时刻  ：{GLOBAL_UPDATE_TIME}
# 总有效频道  ：{len(channel_sources_map)} 个
# 优质源总数  ：{total_selected_source} 个
# 验证成功率  ：{success_count/(success_count+fail_count)*100:.1f}%
# 分组明细    ：央视频道{len(grouped_channels['📺 央视频道'])}个 | 卫视频道{len(grouped_channels['📡 卫视频道'])}个 | 地方频道{len(grouped_channels['🏙️ 地方频道'])}个 | 其他频道{len(grouped_channels['🎬 其他频道'])}个
# 智能选源    ：每个频道保留最快{MAX_SOURCES_PER_CHANNEL}个源，缓存源标记为【缓存·最快】
# 缓存说明    ：已保存{len(verified_urls)}个有效源到本地缓存，下次运行无需重复验证
# 播放器提示  ：所有源均更新于{GLOBAL_UPDATE_TIME}，卡顿请切换后续备用源
# ================================================================================"""
        valid_lines.append(bottom_stat)

    # 容错逻辑
    valid_channel_count = len(channel_sources_map)
    if valid_channel_count < MIN_VALID_CHANNELS:
        logger.warning(f"有效频道({valid_channel_count})低于阈值({MIN_VALID_CHANNELS})，生成基础提醒文件")
        output_path = Path(OUTPUT_FILE)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        error_content = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# ================================= IPTV直播源信息 =================================
# 生成时间    ：{GLOBAL_UPDATE_TIME}
# 生成状态    ：有效频道数不足（仅{valid_channel_count}个），建议稍后重试
# 重试建议    ：检查网络/等待数据源更新/降低MIN_VALID_CHANNELS阈值
# 验证统计    ：共验证{len(task_list)}个源，成功{success_count}个，成功率{success_count/(success_count+fail_count)*100:.1f}%
# ================================================================================

# 📢 系统信息（共1项）
#EXTINF:-1 group-title='📢 系统信息',生成失败提醒【更新于：{GLOBAL_UPDATE_TIME}】
# 有效频道数低于阈值{MIN_VALID_CHANNELS}，请稍后重新运行脚本
#"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(error_content)
        return False

    # 写入最终美化版M3U8
    try:
        output_path = Path(OUTPUT_FILE)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(valid_lines))
    except Exception as e:
        logger.error(f"写入输出文件失败：{str(e)[:50]}", exc_info=False)
        return False

    # 最终统计（含更新时刻）
    logger.info(f"\n📊 最终生成统计（智能选源+更新时刻版）：")
    logger.info(f"   源更新时刻：{GLOBAL_UPDATE_TIME}")
    logger.info(f"   待验证源：{len(task_list)} 个 | 验证成功：{success_count} 个 | 验证成功率：{success_count/(success_count+fail_count)*100:.1f}%")
    logger.info(f"   有效频道：{valid_channel_count} 个 | 优质源总数：{total_selected_source} 个 | 平均每频道：{total_selected_source/valid_channel_count:.1f} 个源")
    for group_name, channels in grouped_channels.items():
        if channels:
            logger.info(f"   {group_name}：{len(channels)} 个频道")
    logger.info(f"✅ 更新时刻版M3U8生成完成：{OUTPUT_FILE}（绝对路径：{Path(OUTPUT_FILE).absolute()}）")
    return True

# -------------------------- 主程序（全流程整合） --------------------------
if __name__ == "__main__":
    start_time = time.time()
    logger.info("="*70)
    logger.info("  并行化IPTV源抓取（更新时刻标注+智能选源+精细化验证）FINAL终极版  ")
    logger.info("="*70)
    logger.info(f"脚本启动，M3U8更新时刻将标记为：{GLOBAL_UPDATE_TIME}")
    # 核心流程：加载缓存 → 抓取数据 → 智能选源+生成M3U8 → 保存缓存
    load_verified_cache()
    raw_data = fetch_raw_iptv_data_parallel(IPTV_SOURCE_URLS)
    if raw_data:
        generate_m3u8_parallel(raw_data)
    else:
        logger.error("未抓取到任何原始数据，无法生成M3U8文件")
    save_verified_cache()
    # 总运行时间统计
    total_time = time.time() - start_time
    logger.info("="*70)
    logger.info(f"运行完成，总耗时：{total_time:.2f} 秒（约 {total_time/60:.1f} 分钟）")
    logger.info(f"日志文件：iptv_spider.log | 缓存文件：{CACHE_FILE} | 输出文件：{OUTPUT_FILE}")
    logger.info(f"核心提示：本次生成的M3U8所有源统一标注更新时刻 → {GLOBAL_UPDATE_TIME}")
    logger.info(f"使用提示：播放器导入后，可在频道标题/注释中查看源更新时间，优先选择第一个最快源")
    logger.info("="*70)
