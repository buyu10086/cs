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
import multiprocessing  # 用于获取CPU核心数，动态调整线程池

# -------------------------- 全局配置（全保留+新增美化/性能配置） --------------------------
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
MAX_THREADS_VERIFY_BASE = 30  # 验证线程基础值
MAX_THREADS_FETCH_BASE = 5   # 抓取线程基础值

# 3. 输出与去重配置
OUTPUT_FILE = "iptv_playlist.m3u8"
REMOVE_DUPLICATE_CHANNELS = True
REMOVE_LOCAL_URLS = True

# 4. 缓存配置
CACHE_FILE = "iptv_verified_cache.json"
CACHE_EXPIRE_HOURS = 24

# 5. 反爬与基础配置
MIN_DELAY = 0.05  # 降低延迟，提升效率（仍防反爬）
MAX_DELAY = 0.2
CHANNEL_SORT_ENABLE = True

# ========== M3U8极致美化专属配置（重点！可自定义） ==========
URL_TRUNCATE_DOMAIN = True  # 智能截断URL（保留域名），而非简单截取
URL_TRUNCATE_LENGTH = 60    # 简单截取长度（URL_TRUNCATE_DOMAIN=False时生效）
GROUP_SEPARATOR = "#" * 50  # 分组分隔符加长，视觉更清晰
SHOW_BOTTOM_STAT = True
CHANNEL_NAME_CLEAN = True
CHANNEL_NAME_STANDARD = True  # 频道名标准化（CCTV1-综合/浙江-卫视）
SOURCE_NUM_PREFIX = "📶源"    # 源前缀加图标，更直观
UPDATE_TIME_MARK = "⏰"       # 更新时刻高亮符号
SPEED_LEVEL_MARK = True      # 速度分级标注（极速/快速/普通）

# ========== 智能选源核心配置 ==========
MAX_SOURCES_PER_CHANNEL = 3
SORT_SOURCE_BY_SPEED = True

# ========== 更新时刻配置 ==========
UPDATE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# -------------------------- 底层优化：正则预编译+全局常量 --------------------------
# 预编译所有正则，避免循环内重复编译
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+)\s*$', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_OTHER_NAME = re.compile(r'[^"]+\s+([^,\s]+)$', re.IGNORECASE)
RE_CLEAN_NAME = re.compile(r'\s+')
RE_INVALID_CHAR = re.compile(r'[^\u4e00-\u9fff_a-zA-Z0-9\-\(\)（）·、]')
RE_CCTV_NORMAL = re.compile(r'CCTV(\d+)(\D.*)?')
RE_WEISHI_NORMAL = re.compile(r'(.+)卫视(\D.*)?')
RE_URL_DOMAIN = re.compile(r'https?://([^/]+)/?(.*)')  # 提取域名的正则
# 速度分级阈值（毫秒）
SPEED_LEVEL_1 = 50    # 极速：<50ms
SPEED_LEVEL_2 = 150   # 快速：50-150ms
# 速度标注
SPEED_MARK_1 = "⚡极速"
SPEED_MARK_2 = "🚀快速"
SPEED_MARK_3 = "▶普通"
SPEED_MARK_CACHE = "💾缓存·极速"

# -------------------------- 全局初始化（性能优化+线程安全） --------------------------
# 1. 日志系统（优化：日志级别可配，减少冗余输出）
def init_logger():
    logger = logging.getLogger("IPTV_Spider")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    # 控制台处理器（精简格式）
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    # 文件处理器（完整格式，保存日志）
    file_handler = logging.FileHandler("iptv_spider.log", encoding="utf-8", mode="a")
    file_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger

logger = init_logger()

# 2. Session连接池优化（核心性能提升：设置连接池参数，避免TCP耗尽）
def init_session():
    session = requests.Session()
    # 连接池配置
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=20,  # 连接池数量
        pool_maxsize=50,      # 每个连接池最大连接数
        max_retries=1         # 重试1次，解决临时网络波动
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # 请求头
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Referer": "https://github.com/",
        "Accept": "*/*",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive"  # 长连接，提升效率
    }
    session.headers.update(DEFAULT_HEADERS)
    return session

# 抓取/验证分离的优化Session
FETCH_SESSION = init_session()
VERIFY_SESSION = init_session()

# 3. 动态线程池：根据CPU核心数自动调整（性能优化）
CPU_CORES = multiprocessing.cpu_count()
MAX_THREADS_VERIFY = min(MAX_THREADS_VERIFY_BASE, CPU_CORES * 5)  # 多核CPU提升线程数
MAX_THREADS_FETCH = min(MAX_THREADS_FETCH_BASE, CPU_CORES * 2)
logger.info(f"性能优化：检测到CPU核心数 {CPU_CORES}，自动调整线程数 → 抓取{MAX_THREADS_FETCH} | 验证{MAX_THREADS_VERIFY}")

# 4. 线程安全数据（内存优化：移除冗余本地存储，简化结构）
channel_sources_map = {}  # {频道名: [(url, 耗时), ...]}
map_lock = threading.Lock()
verified_urls = set()
url_lock = threading.Lock()
# 全局更新时间（一次生成，全局复用）
GLOBAL_UPDATE_TIME = datetime.now().strftime(UPDATE_TIME_FORMAT)
GLOBAL_UPDATE_TIME_DISPLAY = f"{UPDATE_TIME_MARK}{GLOBAL_UPDATE_TIME}"

# -------------------------- 工具函数（效率+美化双优化） --------------------------
def add_random_delay():
    """延迟优化：更短的随机延迟，兼顾反爬和效率"""
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

def filter_invalid_urls(url):
    """URL过滤：逻辑剪枝，合并判断条件"""
    if not url or not url.startswith(("http://", "https://")):
        return False
    if REMOVE_LOCAL_URLS:
        local_hosts = ["localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."]
        if any(host in url.lower() for host in local_hosts):
            return False
    return True

def safe_extract_channel_name(line):
    """频道名提取：使用预编译正则，提升效率"""
    if not line.startswith("#EXTINF:"):
        return None
    for pattern in [RE_CHANNEL_NAME, RE_TVG_NAME, RE_TITLE_NAME, RE_OTHER_NAME]:
        match = pattern.search(line)
        if match:
            channel_name = match.group(1).strip()
            if channel_name and not channel_name.isdigit():
                return channel_name
    return "未知频道"

def clean_channel_name(name):
    """频道名清理：预编译正则，效率提升"""
    if not CHANNEL_NAME_CLEAN or not name:
        return name
    name = RE_CLEAN_NAME.sub(' ', name).strip()
    name = RE_INVALID_CHAR.sub('', name)
    name = name.replace("(", "（").replace(")", "）")
    return name

def standard_channel_name(name):
    """频道名标准化（美化核心：CCTV1-综合/浙江-卫视）"""
    if not CHANNEL_NAME_STANDARD or not name:
        return name
    # CCTV频道标准化
    cctv_match = RE_CCTV_NORMAL.match(name)
    if cctv_match:
        cctv_num = cctv_match.group(1)
        cctv_suffix = cctv_match.group(2) or "综合"
        return f"CCTV{cctv_num}-{cctv_suffix.strip()}"
    # 卫视频道标准化
    weishi_match = RE_WEISHI_NORMAL.match(name)
    if weishi_match:
        ws_area = weishi_match.group(1).strip()
        ws_suffix = weishi_match.group(2) or ""
        return f"{ws_area}-卫视{ws_suffix.strip()}"
    # 地方频道保留原格式
    return name

def get_speed_mark(response_time):
    """速度分级标注（美化：极速/快速/普通，替代纯数字）"""
    if not SPEED_LEVEL_MARK:
        return f"{response_time}ms" if response_time > 0 else "缓存"
    if response_time == 0.0:
        return SPEED_MARK_CACHE
    elif response_time < SPEED_LEVEL_1:
        return f"{SPEED_MARK_1}({response_time}ms)"
    elif response_time < SPEED_LEVEL_2:
        return f"{SPEED_MARK_2}({response_time}ms)"
    else:
        return f"{SPEED_MARK_3}({response_time}ms)"

def smart_truncate_url(url):
    """智能URL截断（美化核心：保留域名+关键路径，而非简单截取）"""
    if not url:
        return ""
    if not URL_TRUNCATE_DOMAIN:
        return url[:URL_TRUNCATE_LENGTH] + "..." if len(url) > URL_TRUNCATE_LENGTH else url
    # 智能截断：提取域名 + 后段关键路径
    match = RE_URL_DOMAIN.search(url)
    if not match:
        return url[:URL_TRUNCATE_LENGTH] + "..." if len(url) > URL_TRUNCATE_LENGTH else url
    domain = match.group(1)
    path = match.group(2)
    if len(url) <= URL_TRUNCATE_LENGTH:
        return url
    # 域名+路径前N位+...，保证可读性
    remain_length = URL_TRUNCATE_LENGTH - len(domain) - 3
    path_trunc = path[:remain_length] if remain_length > 0 else ""
    return f"{domain}/{path_trunc}..."

def normalize_channel_name(name):
    """频道名归一化：预编译正则，效率提升"""
    if not name:
        return "未知频道"
    norm_name = RE_INVALID_CHAR.sub('', name).upper()
    # CCTV归一化映射（精简逻辑）
    cctv_map = {f"央视{n}套": f"CCTV{n}" for n in range(1, 18)}
    cctv_map.update({f"中央{n}套": f"CCTV{n}" for n in range(1, 18)})
    for key, val in cctv_map.items():
        if key in norm_name:
            return val
    return norm_name if norm_name else "未知频道"

# -------------------------- 缓存函数（性能优化：流式读写+增量清理） --------------------------
def load_verified_cache():
    """缓存加载：流式读写，避免大文件内存溢出"""
    global verified_urls
    try:
        cache_path = Path(CACHE_FILE)
        if not cache_path.exists():
            logger.info(f"未找到缓存文件 {CACHE_FILE}，首次运行将创建")
            return
        # 流式读取大缓存文件
        with open(cache_path, "r", encoding="utf-8", buffering=1024*1024) as f:
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
        # 增量过滤，仅保留有效URL
        valid_urls_filtered = [url for url in valid_urls if filter_invalid_urls(url)]
        verified_urls = set(valid_urls_filtered)
        logger.info(f"成功加载本地缓存 → 有效源数：{len(verified_urls)} | 缓存时间：{cache_time_str}")
    except json.JSONDecodeError:
        logger.error("缓存文件格式损坏，无法加载，将重新创建")
    except Exception as e:
        logger.error(f"加载缓存失败：{str(e)[:60]}", exc_info=False)

def save_verified_cache():
    """缓存保存：流式写入，增量清理，减少内存占用"""
    try:
        cache_path = Path(CACHE_FILE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # 增量清理，仅保留当前有效URL
        valid_verified_urls = [url for url in verified_urls if filter_invalid_urls(url)]
        cache_data = {
            "cache_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "verified_urls": valid_verified_urls
        }
        # 流式写入大缓存文件
        with open(cache_path, "w", encoding="utf-8", buffering=1024*1024) as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.info(f"成功保存缓存 → {CACHE_FILE} | 有效源数：{len(valid_verified_urls)}（已清理无效缓存）")
    except Exception as e:
        logger.error(f"保存缓存失败：{str(e)[:60]}", exc_info=False)

# -------------------------- 数据源抓取（性能：流式+Session池 | 效率：逻辑剪枝） --------------------------
def fetch_single_source(url, idx):
    add_random_delay()
    try:
        with FETCH_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as response:
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            valid_lines = []
            # 流式读取，边读边处理，内存优化
            for line in response.iter_lines(decode_unicode=True, chunk_size=1024):
                if not line:
                    continue
                line_strip = line.strip()
                if line_strip and not line_strip.startswith(("//", "#EXTM3U")):  # 剪枝：跳过无用头
                    valid_lines.append(line_strip)
        logger.info(f"数据源 {idx+1:2d} 抓取成功 → 有效行：{len(valid_lines):,}")
        return True, valid_lines
    except requests.exceptions.Timeout:
        logger.error(f"数据源 {idx+1:2d} 抓取失败 → 超时（>{TIMEOUT_FETCH}秒）")
    except requests.exceptions.HTTPError as e:
        logger.error(f"数据源 {idx+1:2d} 抓取失败 → HTTP错误：{e.response.status_code}")
    except requests.exceptions.ConnectionError:
        logger.error(f"数据源 {idx+1:2d} 抓取失败 → 连接拒绝/网络异常")
    except Exception as e:
        logger.error(f"数据源 {idx+1:2d} 抓取失败 → 未知错误：{str(e)[:50]}", exc_info=False)
    return False, []

def fetch_raw_iptv_data_parallel(url_list):
    all_lines = []
    valid_source_count = 0
    logger.info(f"开始并行抓取数据源 → 总源数：{len(url_list)} | 线程数：{MAX_THREADS_FETCH}")
    with ThreadPoolExecutor(max_workers=MAX_THREADS_FETCH) as executor:
        future_to_idx = {executor.submit(fetch_single_source, url, idx): idx for idx, url in enumerate(url_list)}
        for future in as_completed(future_to_idx):
            success, lines = future.result()
            if success and lines:
                all_lines.extend(lines)
                valid_source_count += 1
    logger.info(f"并行抓取完成 → 可用源数：{valid_source_count}/{len(url_list)} | 总有效行：{len(all_lines):,}")
    return all_lines

# -------------------------- 源验证（性能：Session池+逻辑剪枝 | 测速：精准计时） --------------------------
def verify_single_source(url, channel_name):
    if not filter_invalid_urls(url):
        return None, None, None
    add_random_delay()
    # 缓存命中，直接返回（耗时0）
    if url in verified_urls:
        return channel_name, url, 0.0
    # 精细化超时：连接1s，读取剩余时间，总超时不变
    connect_timeout = 1
    read_timeout = max(1, TIMEOUT_VERIFY - connect_timeout)
    valid_stream_suffix = (".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s")
    valid_content_types = ["video/", "application/x-mpegurl", "audio/", "application/octet-stream", "video/mp4"]
    
    try:
        start_time = time.time()
        with VERIFY_SESSION.get(
            url,
            timeout=(connect_timeout, read_timeout),
            allow_redirects=True,
            stream=True,
            headers={"Range": "bytes=0-1024"},  # 仅读前1024字节，提升效率
            verify=False  # 跳过SSL验证，解决部分证书问题，提升效率
        ) as response:
            # 精准计算响应耗时（毫秒，保留3位）
            response_time = round((time.time() - start_time) * 1000, 3)
            # 逻辑剪枝：合并状态码判断
            if response.status_code not in [200, 206, 301, 302, 307, 308]:
                return None, None, None
            # 响应头验证
            content_type = response.headers.get("Content-Type", "").lower()
            if not any(ct in content_type for ct in valid_content_types):
                return None, None, None
            # 最终URL格式验证
            final_url = response.url.lower()
            if not final_url.endswith(valid_stream_suffix):
                return None, None, None
            # M3U8文件头验证（仅对m3u8格式）
            if final_url.endswith(".m3u8"):
                stream_data = response.content[:1024].decode("utf-8", errors="ignore")
                if "#EXTM3U" not in stream_data:
                    return None, None, None
            # 验证通过，加入缓存（加锁保证线程安全）
            with url_lock:
                verified_urls.add(url)
            return channel_name, url, response_time
    except Exception:
        # 静默失败，不打印冗余日志（提升效率）
        return None, None, None

def get_channel_group(channel_name):
    """频道分组：逻辑剪枝，提升效率"""
    if not channel_name:
        return "🎬 其他频道"
    if any(k in channel_name for k in ["CCTV", "央视", "中央", "央视频"]):
        return "📺 央视频道"
    if "卫视" in channel_name:
        return "📡 卫视频道"
    # 地方频道关键词（精简）
    province_city = ["北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
                     "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
                     "广东", "广西", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海",
                     "内蒙古", "宁夏", "新疆", "西藏", "香港", "澳门", "台湾"]
    for area in province_city:
        if area in channel_name and "卫视" not in channel_name:
            return "🏙️ 地方频道"
    return "🎬 其他频道"

# -------------------------- 核心：智能选源+极致美化M3U8生成 --------------------------
def generate_m3u8_parallel(raw_lines):
    # 极致美化：分层头部，信息更清晰
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
{GROUP_SEPARATOR}
# 📺 IPTV直播源播放列表 - 智能选源版
# {GLOBAL_UPDATE_TIME_DISPLAY} 生成 | 验证超时：{TIMEOUT_VERIFY}秒 | 每个频道保留{MAX_SOURCES_PER_CHANNEL}个最快源
# 🚀 性能优化：CPU多核自适应 | Session连接池 | 正则预编译 | 流式读写
# ✨ 美化特性：频道标准化 | 速度分级标注 | 智能URL截断 | 结构分层可视化
# 🎯 播放器兼容：Kodi/TVBox/完美视频/极光TV/小米电视/当贝市场所有M3U8播放器
{GROUP_SEPARATOR}
"""
    valid_lines = [m3u8_header]
    total_selected_source = 0

    # 提取待验证任务（逻辑剪枝，减少循环）
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
        logger.error("未提取到待验证的源，无法生成M3U8文件")
        return False
    logger.info(f"待验证源总数 → {len(task_list):,}（已去重+过滤无效URL+复用本地缓存）")

    # 并行验证+测速（动态线程池）
    logger.info(f"开始并行验证+测速 → 线程数：{MAX_THREADS_VERIFY} | 速度分级：{SPEED_MARK_1}/{SPEED_MARK_2}/{SPEED_MARK_3}")
    with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
        future_to_task = {executor.submit(verify_single_source, url, chan): (url, chan) for url, chan in task_list}
        success_count = 0
        fail_count = 0
        for future in as_completed(future_to_task):
            chan_name, valid_url, response_time = future.result()
            if chan_name and valid_url and response_time >= 0:
                success_count += 1
                # 线程安全存入数据，去重相同URL
                with map_lock:
                    if chan_name not in channel_sources_map:
                        channel_sources_map[chan_name] = []
                    if not any(item[0] == valid_url for item in channel_sources_map[chan_name]):
                        channel_sources_map[chan_name].append((valid_url, response_time))
            else:
                fail_count += 1
    # 计算验证成功率（避免除零）
    verify_rate = success_count / (success_count + fail_count) * 100 if (success_count + fail_count) > 0 else 0.0
    logger.info(f"验证+测速完成 → 成功：{success_count:,} | 失败：{fail_count:,} | 成功率：{verify_rate:.1f}%")

    # 频道模糊去重（归一化）
    if REMOVE_DUPLICATE_CHANNELS:
        dedup_map = {}
        norm_name_map = {}
        for chan_name, sources in channel_sources_map.items():
            if not sources:
                continue
            norm_name = normalize_channel_name(chan_name)
            # 保留源数最多的频道，保证备用源充足
            if norm_name not in norm_name_map or len(sources) > len(norm_name_map[norm_name][1]):
                norm_name_map[norm_name] = (chan_name, sources)
        # 还原为原频道名
        for norm_name, (orig_name, sources) in norm_name_map.items():
            dedup_map[orig_name] = sources
        channel_sources_map.clear()
        channel_sources_map.update(dedup_map)
        logger.info(f"频道模糊去重完成 → 剩余有效频道：{len(channel_sources_map):,} 个")

    # 智能选源核心逻辑：按速度排序+保留最快N个
    smart_selected_map = {}
    for chan_name, sources in channel_sources_map.items():
        if not sources:
            continue
        # 按速度排序（0ms缓存源最快）
        if SORT_SOURCE_BY_SPEED:
            sorted_sources = sorted(sources, key=lambda x: x[1])
        else:
            sorted_sources = sources
        # 保留最快的N个源
        selected_sources = sorted_sources[:MAX_SOURCES_PER_CHANNEL]
        smart_selected_map[chan_name] = selected_sources
        total_selected_source += len(selected_sources)
    channel_sources_map = smart_selected_map
    logger.info(f"智能选源完成 → 优质源总数：{total_selected_source:,} | 平均每频道：{total_selected_source/len(channel_sources_map):.1f} 个")

    # 频道分组+标准化（美化核心）
    grouped_channels = {"📺 央视频道": [], "📡 卫视频道": [], "🏙️ 地方频道": [], "🎬 其他频道": []}
    for channel_name, sources in channel_sources_map.items():
        if not sources:
            continue
        # 清理+标准化频道名
        clean_name = clean_channel_name(channel_name)
        std_name = standard_channel_name(clean_name)
        # 获取分组
        group = get_channel_group(std_name)
        grouped_channels[group].append((std_name, sources))

    # 极致美化：系统信息段（高亮更新时刻）
    valid_lines.append(f"\n# 📢 系统信息 | {GLOBAL_UPDATE_TIME_DISPLAY}")
    valid_lines.append(f"#EXTINF:-1 group-title='📢 系统信息',IPTV源统计【{GLOBAL_UPDATE_TIME_DISPLAY}】")
    valid_lines.append(f"# 有效频道：{len(channel_sources_map):,} 个 | 优质源：{total_selected_source:,} 个 | 验证成功率：{verify_rate:.1f}%")
    valid_lines.append(f"# 智能选源：每个频道保留最快{MAX_SOURCES_PER_CHANNEL}个源 | 速度分级：{SPEED_MARK_1}/{SPEED_MARK_2}/{SPEED_MARK_3}")
    valid_lines.append(f"# 使用提示：播放器优先选择{SOURCE_NUM_PREFIX}1（最快），卡顿请切换后续备用源")
    valid_lines.append(f"{GROUP_SEPARATOR}\n")

    # 极致美化：分组输出（图标+缩进+速度标注+更新时刻）
    for group_name, channels in grouped_channels.items():
        if not channels:
            continue
        # 排序频道，保证展示顺序固定
        if CHANNEL_SORT_ENABLE:
            channels.sort(key=lambda x: x[0])
        # 分组标题（美化：频道数+更新时刻）
        valid_lines.append(f"# {group_name}（共{len(channels)}个频道）| {GLOBAL_UPDATE_TIME_DISPLAY}")
        valid_lines.append(GROUP_SEPARATOR)
        # 遍历每个频道
        for channel_name, sources in channels:
            source_count = len(sources)
            # 频道标题（美化：标准化+源数+更新时刻，播放器直接可见）
            valid_lines.append(f"\n#EXTINF:-1 group-title='{group_name}',{channel_name}（{source_count}个优质源）{GLOBAL_UPDATE_TIME_DISPLAY}")
            # 遍历每个源（美化：速度分级+智能URL截断+图标前缀）
            for idx, (url, response_time) in enumerate(sources, 1):
                speed_mark = get_speed_mark(response_time)
                trunc_url = smart_truncate_url(url)
                # 源注释（美化：缩进+图标+速度+更新时刻）
                valid_lines.append(f"#  {SOURCE_NUM_PREFIX}{idx} {speed_mark} | {GLOBAL_UPDATE_TIME_DISPLAY}：{trunc_url}")
                # 原始URL（播放器唯一识别，不修改）
                valid_lines.append(url)
        # 分组之间空行，结构更清晰
        valid_lines.append(f"\n{GROUP_SEPARATOR}\n")

    # 极致美化：底部可视化统计（字符统计图+详细信息）
    if SHOW_BOTTOM_STAT and len(channel_sources_map) >= MIN_VALID_CHANNELS:
        # 字符统计图（直观展示频道分布）
        stat_chart = ""
        for g_name, g_chans in grouped_channels.items():
            if g_chans:
                chan_num = len(g_chans)
                # 按比例生成统计条（最大20个★）
                stat_bar = "★" * min(chan_num // 2, 20) if chan_num > 0 else ""
                stat_chart += f"# {g_name}：{chan_num:2d}个 {stat_bar}\n"
        # 底部统计内容
        bottom_stat = f"""
{GROUP_SEPARATOR}
# 📊 播放列表汇总统计 | {GLOBAL_UPDATE_TIME_DISPLAY}
{stat_chart}# 🎯 核心指标：有效频道{len(channel_sources_map):,}个 | 优质源{total_selected_source:,}个 | 验证成功率{verify_rate:.1f}%
# ⚡ 性能指标：验证超时{TIMEOUT_VERIFY}秒 | 线程数{MAX_THREADS_VERIFY}（CPU{CPU_CORES}核自适应）
# 💾 缓存指标：本地缓存有效源{len(verified_urls):,}个 | 缓存有效期{CACHE_EXPIRE_HOURS}小时
# 📌 播放器提示：所有源已按速度排序，优先选择{SOURCE_NUM_PREFIX}1，失效请重新运行脚本生成
# 📅 更新提示：建议每6-12小时重新运行脚本，保证源的新鲜度和有效性
{GROUP_SEPARATOR}
"""
        valid_lines.append(bottom_stat)

    # 容错逻辑：有效频道数低于阈值，生成提醒文件
    valid_channel_count = len(channel_sources_map)
    if valid_channel_count < MIN_VALID_CHANNELS:
        logger.warning(f"有效频道数{valid_channel_count}低于阈值{MIN_VALID_CHANNELS}，生成基础提醒文件")
        error_content = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
{GROUP_SEPARATOR}
# ❌ IPTV播放列表生成失败 | {GLOBAL_UPDATE_TIME_DISPLAY}
# 失败原因：有效频道数不足（仅{valid_channel_count}个），低于阈值{MIN_VALID_CHANNELS}个
# 重试建议：1. 检查网络是否能访问GitHub 2. 增大TIMEOUT_VERIFY阈值 3. 稍后重新运行脚本
# 验证统计：共验证{len(task_list):,}个源 | 成功{success_count:,}个 | 成功率{verify_rate:.1f}%
{GROUP_SEPARATOR}
#EXTINF:-1 group-title='📢 错误信息',生成失败【{GLOBAL_UPDATE_TIME_DISPLAY}】
# 有效频道数不足，请按上述建议重试！
"""
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(error_content)
        return False

    # 写入极致美化版M3U8文件（流式写入，内存优化）
    try:
        output_path = Path(OUTPUT_FILE)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8", buffering=1024*1024) as f:
            f.write("\n".join(valid_lines))
    except Exception as e:
        logger.error(f"写入M3U8文件失败：{str(e)[:60]}", exc_info=False)
        return False

    # 最终统计（可视化）
    logger.info(f"\n📊 最终生成统计 {GLOBAL_UPDATE_TIME_DISPLAY}")
    logger.info(f"   📺 频道分布：央视频道{len(grouped_channels['📺 央视频道'])} | 卫视频道{len(grouped_channels['📡 卫视频道'])}")
    logger.info(f"   🏙️ 地方频道{len(grouped_channels['🏙️ 地方频道'])} | 其他频道{len(grouped_channels['🎬 其他频道'])}")
    logger.info(f"   🎯 核心指标：有效频道{valid_channel_count:,}个 | 优质源{total_selected_source:,}个 | 验证成功率{verify_rate:.1f}%")
    logger.info(f"   💾 缓存指标：本地缓存{len(verified_urls):,}个有效源 | 下次运行免重复验证")
    logger.info(f"   ✅ 极致美化版M3U8生成完成 → {OUTPUT_FILE}（绝对路径：{output_path.absolute()}）")
    return True

# -------------------------- 主程序（全流程整合+性能统计） --------------------------
if __name__ == "__main__":
    # 程序启动时间
    start_time = time.time()
    logger.info("="*80)
    logger.info("    IPTV直播源抓取工具 - 极致性能+极致美化版 V3.0    ")
    logger.info("="*80)
    logger.info(f"程序启动 → {GLOBAL_UPDATE_TIME_DISPLAY} | CPU核心数：{CPU_CORES} | Python版本：{requests.__version__}")
    logger.info("="*80)

    # 核心流程：加载缓存 → 抓取数据 → 智能选源+美化生成 → 保存缓存
    load_verified_cache()
    raw_data = fetch_raw_iptv_data_parallel(IPTV_SOURCE_URLS)
    if raw_data:
        generate_m3u8_parallel(raw_data)
    else:
        logger.error("未抓取到任何原始数据，程序终止")
    save_verified_cache()

    # 程序运行总耗时
    total_time = time.time() - start_time
    minutes = int(total_time // 60)
    seconds = round(total_time % 60, 2)
    logger.info("="*80)
    logger.info(f"程序运行完成 → 总耗时：{minutes}分{seconds}秒（{total_time:.2f}秒）")
    logger.info(f"生成文件 → 播放列表：{OUTPUT_FILE} | 运行日志：iptv_spider.log | 验证缓存：{CACHE_FILE}")
    logger.info(f"使用提示 → 播放器直接导入{OUTPUT_FILE}，优先选择{SOURCE_NUM_PREFIX}1（最快），卡顿切换后续源")
    logger.info(f"更新提示 → 建议通过计划任务/crontab每6-12小时自动运行，保证源新鲜")
    logger.info("="*80)
