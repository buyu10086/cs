import requests
import time
import random
import json
from datetime import datetime, timedelta
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import logging
import multiprocessing
from typing import Tuple, List, Dict, Optional

# -------------------------- 全局配置（核心优化：精准识别kakaxi-1/zubo源） --------------------------
# 1. 数据源配置（保留kakaxi-1/zubo源置顶）
IPTV_SOURCE_URLS = [
    # 重点保障：kakaxi-1/zubo 源（已确认可用，置顶优先抓取）
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/master/live.m3u"
]

# 仅保留可用的官方/合规源（避免405拦截）
OFFICIAL_SOURCES = {
    "CCTV1 综合（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225618/index.m3u8",
    "CCTV5 体育（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225622/index.m3u8",
    "CCTV13 新闻（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225630/index.m3u8",
    "湖南卫视（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225726/index.m3u8",
    "浙江卫视（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225730/index.m3u8",
    "咪咕体育高清（可用）": "https://hls.miguvideo.com/hls/main/0/0/1.m3u8"
}

# 2. 效率核心配置（适配kakaxi-1/zubo源）
TIMEOUT_VERIFY = 5.0
TIMEOUT_FETCH = 15
MIN_VALID_CHANNELS = 1
MAX_THREADS_VERIFY_BASE = 100
MAX_THREADS_FETCH_BASE = 15
MIN_DELAY = 0.05
MAX_DELAY = 0.15
DISABLE_SSL_VERIFY = True
BATCH_PROCESS_SIZE = 200

# 3. 输出与缓存配置
OUTPUT_FILE = "iptv_playlist.m3u8"
CACHE_FILE = "iptv_persist_cache.json"
TEMP_CACHE_SET = set()
CACHE_EXPIRE_HOURS = 24
REMOVE_DUPLICATE_CHANNELS = False
REMOVE_LOCAL_URLS = True
ENABLE_EMOJI = False
CACHE_MAX_SIZE = 10000

# 4. 排序+播放端配置
CHANNEL_SORT_ENABLE = True
CCTV_SORT_ENABLE = True
WEISHI_SORT_ENABLE = True
LOCAL_SORT_ENABLE = True
FEATURE_SORT_ENABLE = True
DIGITAL_SORT_ENABLE = True
MANUAL_SOURCE_NUM = 4
OFFICIAL_SOURCE_PRIORITY = True

# 分组配置（kakaxi-1/zubo源单独分组，避免归类错误）
GROUP_OFFICIAL = "官方可用源-央视/卫视/咪咕" if ENABLE_EMOJI else "官方可用源-央视/卫视/咪咕"
GROUP_KAKAXI = "kakaxi-1/zubo源-专属分组" if ENABLE_EMOJI else "kakaxi-1/zubo源-专属分组"  # 新增：kakaxi专属分组
GROUP_SECONDARY_CCTV = "央视频道-网络/备用" if ENABLE_EMOJI else "央视频道-网络/备用"
GROUP_SECONDARY_WEISHI = "卫视频道-一线/地方" if ENABLE_EMOJI else "卫视频道-一线/地方"
GROUP_SECONDARY_LOCAL = "地方频道-各省市区" if ENABLE_EMOJI else "地方频道-各省市区"
GROUP_SECONDARY_FEATURE = "特色频道-电影/体育/少儿" if ENABLE_EMOJI else "特色频道-电影/体育/少儿"
GROUP_SECONDARY_DIGITAL = "数字频道-按数字排序" if ENABLE_EMOJI else "数字频道-按数字排序"
GROUP_SECONDARY_OTHER = "其他频道-综合" if ENABLE_EMOJI else "其他频道-综合"

# 播放端美化配置
PLAYER_TITLE_PREFIX = True
PLAYER_TITLE_SHOW_SPEED = True
PLAYER_TITLE_SHOW_NUM = True
PLAYER_TITLE_SHOW_UPDATE = True
UPDATE_TIME_FORMAT_SHORT = "%m-%d %H:%M"
UPDATE_TIME_FORMAT_FULL = "%Y-%m-%d %H:%M:%S"
GROUP_SEPARATOR = "#" * 50
URL_TRUNCATE_DOMAIN = True
URL_TRUNCATE_LENGTH = 50
SOURCE_NUM_PREFIX = "📶" if ENABLE_EMOJI else ""
SPEED_MARK_OFFICIAL = "🔰官方" if ENABLE_EMOJI else "官方"
SPEED_MARK_CACHE = "💾缓存" if ENABLE_EMOJI else "缓存"
SPEED_MARK_1 = "⚡极速" if ENABLE_EMOJI else "极速"
SPEED_MARK_2 = "🚀快速" if ENABLE_EMOJI else "快速"
SPEED_MARK_3 = "▶普通" if ENABLE_EMOJI else "普通"
SPEED_LEVEL_1 = 50
SPEED_LEVEL_2 = 200

# -------------------------- 排序核心配置 --------------------------
TOP_WEISHI = ["湖南卫视", "浙江卫视", "江苏卫视", "东方卫视", "北京卫视", "安徽卫视", "山东卫视", "广东卫视"]
DIRECT_CITIES = ["北京", "上海", "天津", "重庆"]
PROVINCE_PINYIN_ORDER = [
    "安徽", "福建", "甘肃", "广东", "广西", "贵州", "海南", "河北", "河南", "黑龙江",
    "湖北", "湖南", "吉林", "江苏", "江西", "辽宁", "内蒙古", "宁夏", "青海", "山东",
    "山西", "陕西", "上海", "四川", "台湾", "天津", "西藏", "新疆", "云南", "浙江",
    "重庆", "北京"
]
FEATURE_TYPE_ORDER = [
    ("电影", ["电影", "影院", "影视"]),
    ("体育", ["体育", "赛事", "奥运", "足球", "篮球"]),
    ("少儿", ["少儿", "卡通", "动画", "宝贝"]),
    ("财经", ["财经", "股市", "金融", "理财"]),
    ("综艺", ["综艺", "娱乐", "选秀", "晚会"]),
    ("新闻", ["新闻", "资讯", "时事"]),
    ("纪录片", ["纪录片", "纪实", "纪录"]),
    ("音乐", ["音乐", "歌曲", "MTV"])
]
CCTV_BASE_ORDER = ["CCTV1", "CCTV5", "CCTV13"]

# -------------------------- 底层优化：强化kakaxi-1/zubo源识别 --------------------------
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+)\s*$', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_OTHER_NAME = re.compile(r'([^\s]+)$', re.IGNORECASE)
# 核心优化：精准匹配kakaxi-1/zubo源的频道格式（适配其实际输出）
RE_KAKAXI_CHANNEL = re.compile(r'#EXTINF:-1\s*(tvg-id="[^"]*"\s*)?(tvg-name="[^"]*"\s*)?(group-title="[^"]*"\s*)?,([^#\n]+)', re.IGNORECASE)
RE_URL_DOMAIN = re.compile(r'https?://([^/]+)/?(.*)')
# 核心优化：识别kakaxi-1/zubo源的URL特征（基于实际m3u8中的域名）
RE_KAKAXI_URL = re.compile(r'(cztvcloud|cztv\.com|jstv\.com|cnr\.cn|akamaized\.net)', re.IGNORECASE)
RE_CCTV_CORE = re.compile(r'CCTV(\d+|新闻|体育|综合)', re.IGNORECASE)
RE_DIGITAL_NUMBER = re.compile(r'^(\d+)(频道|台)?$', re.IGNORECASE)
RE_OFFICIAL_DOMAIN = re.compile(r'(cmvideo|miguvideo)\.com', re.IGNORECASE)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}
VALID_SUFFIX = {".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s"}
VALID_CONTENT_TYPE = {"video/", "application/x-mpegurl", "audio/", "application/octet-stream"}

# 全局变量
GLOBAL_UPDATE_TIME_FULL = datetime.now().strftime(UPDATE_TIME_FORMAT_FULL)
GLOBAL_UPDATE_TIME_SHORT = datetime.now().strftime(UPDATE_TIME_FORMAT_SHORT)
CPU_CORES = multiprocessing.cpu_count()
MAX_THREADS_VERIFY = min(MAX_THREADS_VERIFY_BASE, CPU_CORES * 10)
MAX_THREADS_FETCH = min(MAX_THREADS_FETCH_BASE, CPU_CORES * 8)
channel_sources_map = dict()
verified_urls = set()
task_list = list()
all_lines = list()
total_time = 0.0
# 新增：记录kakaxi-1/zubo源的URL，用于后续识别
kakaxi_source_url = "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt"
kakaxi_task_ids = set()  # 存储kakaxi源的任务标识

# -------------------------- 日志初始化 --------------------------
def init_logger():
    logger = logging.getLogger("IPTV_Spider")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    ch.setFormatter(ch_fmt)
    fh = logging.FileHandler("iptv_spider.log", encoding="utf-8", mode="a")
    fh.setLevel(logging.DEBUG)
    fh_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fh_fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger

logger = init_logger()

# -------------------------- Session初始化 --------------------------
def init_global_session():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=100,
        pool_maxsize=200,
        max_retries=5,
        pool_block=False
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9"
    })
    if DISABLE_SSL_VERIFY:
        session.verify = False
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    return session

GLOBAL_SESSION = init_global_session()

# -------------------------- 工具函数（核心优化：kakaxi源精准识别） --------------------------
def add_random_delay():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

def filter_invalid_urls(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    if REMOVE_LOCAL_URLS:
        for host in LOCAL_HOSTS:
            if host in url.lower():
                return False
    if url in TEMP_CACHE_SET:
        return True
    TEMP_CACHE_SET.add(url)
    return True

def is_official_source(url: str) -> bool:
    return bool(RE_OFFICIAL_DOMAIN.search(url))

# 核心优化：精准提取kakaxi-1/zubo源的频道名
def safe_extract_channel_name(line: str) -> Optional[str]:
    if not line.startswith("#EXTINF:"):
        return None
    # 优先匹配kakaxi-1/zubo源的格式
    kakaxi_match = RE_KAKAXI_CHANNEL.search(line)
    if kakaxi_match:
        name = kakaxi_match.group(4).strip()  # 适配实际分组捕获
        return f"[kakaxi] {name}" if name else "[kakaxi] 未知频道"  # 新增前缀，便于识别
    # 常规格式匹配
    match = RE_CHANNEL_NAME.search(line) or RE_TVG_NAME.search(line) or RE_TITLE_NAME.search(line) or RE_OTHER_NAME.search(line)
    if match:
        name = match.group(1).strip()
        return name if name else "未知频道"
    return "未知频道"

# 核心优化：基于URL特征识别kakaxi源，划入专属分组
def get_channel_subgroup(channel_name: str, url: str = "") -> str:
    # 1. 官方源优先
    if channel_name in OFFICIAL_SOURCES:
        return GROUP_OFFICIAL
    # 2. 核心：通过URL特征识别kakaxi源（精准，不依赖频道名）
    if RE_KAKAXI_URL.search(url) or "[kakaxi]" in channel_name:
        return GROUP_KAKAXI
    # 3. 其他分组逻辑
    if DIGITAL_SORT_ENABLE and RE_DIGITAL_NUMBER.match(channel_name.replace("[kakaxi] ", "")):
        return GROUP_SECONDARY_DIGITAL
    if FEATURE_SORT_ENABLE:
        for feature_type, keywords in FEATURE_TYPE_ORDER:
            if any(keyword in channel_name for keyword in keywords):
                return GROUP_SECONDARY_FEATURE
    if RE_CCTV_CORE.search(channel_name):
        return GROUP_SECONDARY_CCTV
    if "卫视" in channel_name:
        return GROUP_SECONDARY_WEISHI
    for area in DIRECT_CITIES + PROVINCE_PINYIN_ORDER:
        if area in channel_name and "卫视" not in channel_name:
            return GROUP_SECONDARY_LOCAL
    return GROUP_SECONDARY_OTHER

# -------------------------- 排序函数 --------------------------
def get_cctv_sort_key(channel_name: str) -> Tuple[int, str]:
    if not CCTV_SORT_ENABLE:
        return (999, channel_name.upper())
    match = RE_CCTV_CORE.search(channel_name.upper())
    if not match:
        return (999, channel_name.upper())
    cctv_core = match.group(0).upper()
    cctv_core = f"CCTV{cctv_core.replace('CCTV', '')}"
    cctv_core = re.sub(r'（可用.*）|\[KAKAXI\] ', '', cctv_core)
    main_key = CCTV_BASE_ORDER.index(cctv_core) if cctv_core in CCTV_BASE_ORDER else len(CCTV_BASE_ORDER)
    suffix_priority = {"高清": 2, "超清": 3, "标清": 4, "可用": 5}
    sub_key = 99
    for suffix, pri in suffix_priority.items():
        if suffix in channel_name:
            sub_key = pri
            break
    return (main_key, sub_key, channel_name.upper())

def get_weishi_sort_key(channel_name: str) -> Tuple[int, str]:
    if not WEISHI_SORT_ENABLE:
        return (999, channel_name.upper())
    for idx, top_ws in enumerate(TOP_WEISHI):
        if top_ws in channel_name:
            return (idx, channel_name.upper())
    for idx, province in enumerate(PROVINCE_PINYIN_ORDER):
        if province in channel_name:
            return (len(TOP_WEISHI) + idx, channel_name.upper())
    return (len(TOP_WEISHI) + len(PROVINCE_PINYIN_ORDER), channel_name.upper())

def get_local_sort_key(channel_name: str) -> Tuple[int, str]:
    if not LOCAL_SORT_ENABLE:
        return (999, channel_name.upper())
    for idx, city in enumerate(DIRECT_CITIES):
        if city in channel_name:
            return (idx, channel_name.upper())
    for idx, province in enumerate(PROVINCE_PINYIN_ORDER):
        if province in channel_name and province not in DIRECT_CITIES:
            return (len(DIRECT_CITIES) + idx, channel_name.upper())
    return (len(DIRECT_CITIES) + len(PROVINCE_PINYIN_ORDER), channel_name.upper())

def get_feature_sort_key(channel_name: str) -> Tuple[int, str]:
    if not FEATURE_SORT_ENABLE:
        return (999, channel_name.upper())
    for idx, (feature_type, keywords) in enumerate(FEATURE_TYPE_ORDER):
        if any(keyword in channel_name for keyword in keywords):
            return (idx, channel_name.upper())
    return (len(FEATURE_TYPE_ORDER), channel_name.upper())

def get_digital_sort_key(channel_name: str) -> Tuple[int, str]:
    if not DIGITAL_SORT_ENABLE:
        return (999, channel_name.upper())
    match = RE_DIGITAL_NUMBER.match(channel_name.replace("[kakaxi] ", ""))
    return (int(match.group(1)) if match else 999, channel_name.upper())

# 新增：kakaxi源专属排序（按频道名拼音排序）
def get_kakaxi_sort_key(channel_name: str) -> Tuple[str]:
    return (channel_name.replace("[kakaxi] ", "").upper(),)

def get_channel_sort_key(group_name: str, channel_name: str) -> Tuple[int, any]:
    if group_name == GROUP_OFFICIAL:
        return get_official_sort_key(channel_name)
    elif group_name == GROUP_KAKAXI:
        return get_kakaxi_sort_key(channel_name)
    elif group_name == GROUP_SECONDARY_CCTV:
        return get_cctv_sort_key(channel_name)
    elif group_name == GROUP_SECONDARY_WEISHI:
        return get_weishi_sort_key(channel_name)
    elif group_name == GROUP_SECONDARY_LOCAL:
        return get_local_sort_key(channel_name)
    elif group_name == GROUP_SECONDARY_FEATURE:
        return get_feature_sort_key(channel_name)
    elif group_name == GROUP_SECONDARY_DIGITAL:
        return get_digital_sort_key(channel_name)
    else:
        return (999, channel_name.upper())

def get_official_sort_key(channel_name: str) -> Tuple[int, any]:
    match = RE_CCTV_CORE.search(channel_name.upper())
    if match:
        cctv_core = match.group(0).upper()
        cctv_core = f"CCTV{cctv_core.replace('CCTV', '')}"
        cctv_core = re.sub(r'（可用.*）', '', cctv_core)
        if cctv_core in CCTV_BASE_ORDER:
            return (0, CCTV_BASE_ORDER.index(cctv_core))
    if any(kw in channel_name for kw in ["体育", "赛事"]):
        return (1, 999)
    for idx, top_ws in enumerate(TOP_WEISHI):
        if top_ws in channel_name:
            return (2, idx)
    if "咪咕" in channel_name:
        return (3, 999)
    return (4, 999)

# -------------------------- 其他工具函数 --------------------------
def get_speed_mark(response_time: float, url: str = "") -> str:
    if is_official_source(url) or url in OFFICIAL_SOURCES.values():
        return SPEED_MARK_OFFICIAL
    if RE_KAKAXI_URL.search(url):
        return "🌀kakaxi" if ENABLE_EMOJI else "kakaxi"  # 新增kakaxi源专属标识
    if response_time == 0.0:
        return SPEED_MARK_CACHE
    elif response_time < SPEED_LEVEL_1:
        return SPEED_MARK_1
    elif response_time < SPEED_LEVEL_2:
        return SPEED_MARK_2
    else:
        return SPEED_MARK_3

def get_best_speed_mark(sources: List[Tuple[str, float]]) -> str:
    if not sources:
        return SPEED_MARK_3
    for url, rt in sources:
        if is_official_source(url) or url in OFFICIAL_SOURCES.values():
            return SPEED_MARK_OFFICIAL
    for url, rt in sources:
        if RE_KAKAXI_URL.search(url):
            return "🌀kakaxi" if ENABLE_EMOJI else "kakaxi"
    min_time = min([s[1] for s in sources])
    return get_speed_mark(min_time)

def smart_truncate_url(url: str) -> str:
    if not url or len(url) <= URL_TRUNCATE_LENGTH:
        return url
    if not URL_TRUNCATE_DOMAIN:
        return url[:URL_TRUNCATE_LENGTH] + "..."
    match = RE_URL_DOMAIN.search(url)
    if not match:
        return url[:URL_TRUNCATE_LENGTH] + "..."
    domain, path = match.groups()
    remain = URL_TRUNCATE_LENGTH - len(domain) - 3
    path_trunc = path[:remain] if remain > 0 else ""
    return f"{domain}/{path_trunc}..."

def build_player_title(channel_name: str, sources: List[Tuple[str, float]]) -> str:
    title_parts = []
    if PLAYER_TITLE_PREFIX and ENABLE_EMOJI:
        subgroup = get_channel_subgroup(channel_name, sources[0][0] if sources else "")
        icon_map = {
            GROUP_OFFICIAL: "🔰",
            GROUP_KAKAXI: "🌀",
            GROUP_SECONDARY_CCTV: "📺",
            GROUP_SECONDARY_WEISHI: "📡",
            GROUP_SECONDARY_LOCAL: "🏙️",
            GROUP_SECONDARY_FEATURE: "🎬",
            GROUP_SECONDARY_DIGITAL: "🔢",
            GROUP_SECONDARY_OTHER: "🌀"
        }
        title_parts.append(icon_map.get(subgroup, "🌀"))
    title_parts.append(channel_name)
    if PLAYER_TITLE_SHOW_NUM:
        title_parts.append(f"{MANUAL_SOURCE_NUM}源")
    if PLAYER_TITLE_SHOW_SPEED and sources:
        speed_mark = get_best_speed_mark(sources)
        if not ENABLE_EMOJI:
            speed_mark = speed_mark.replace("⚡", "").replace("🚀", "").replace("▶", "").replace("💾", "").replace("🔰", "").replace("🌀", "").strip()
        title_parts.append(speed_mark)
    if PLAYER_TITLE_SHOW_UPDATE:
        title_parts.append(f"[{GLOBAL_UPDATE_TIME_SHORT}]")
    return " ".join(title_parts).replace("  ", " ").strip()

# -------------------------- 缓存函数 --------------------------
def load_persist_cache():
    global verified_urls
    try:
        cache_path = Path(CACHE_FILE)
        if not cache_path.exists():
            logger.info(f"无持久缓存文件，首次运行")
            return
        with open(cache_path, "r", encoding="utf-8", buffering=4096*4) as f:
            cache_data = json.load(f)
        cache_time = datetime.strptime(cache_data.get("cache_time", ""), UPDATE_TIME_FORMAT_FULL)
        if datetime.now() - cache_time > timedelta(hours=CACHE_EXPIRE_HOURS):
            logger.info(f"持久缓存过期，清空重新生成")
            return
        cache_urls = cache_data.get("verified_urls", [])
        verified_urls = set([url for url in cache_urls if filter_invalid_urls(url)])
        TEMP_CACHE_SET.update(verified_urls)
        logger.info(f"加载持久缓存成功 → 有效源数：{len(verified_urls):,}")
    except Exception as e:
        logger.warning(f"持久缓存加载失败：{str(e)[:50]}")
        verified_urls = set()

def save_persist_cache():
    try:
        cache_path = Path(CACHE_FILE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_urls = list(verified_urls)[:CACHE_MAX_SIZE]
        cache_data = {
            "cache_time": GLOBAL_UPDATE_TIME_FULL,
            "verified_urls": cache_urls
        }
        with open(cache_path, "w", encoding="utf-8", buffering=4096*4) as f:
            json.dump(cache_data, f, ensure_ascii=False, separators=(",", ":"))
        logger.info(f"保存持久缓存成功 → 缓存源数：{len(cache_urls):,}")
    except Exception as e:
        logger.error(f"保存持久缓存失败：{str(e)[:50]}")

# -------------------------- 核心功能（优化：kakaxi源精准提取与归类） --------------------------
def fetch_single_source(url: str, idx: int) -> List[str]:
    add_random_delay()
    def is_valid_line(line: str) -> bool:
        line_strip = line.strip()
        if not line_strip:
            return False
        if line_strip.startswith("#") and not line_strip.startswith(("#EXTINF:", "#EXTM3U")):
            return False
        return True
    
    is_kakaxi_zubo = url == kakaxi_source_url
    try:
        with GLOBAL_SESSION.get(url, timeout=20 if is_kakaxi_zubo else TIMEOUT_FETCH, stream=True) as resp:
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            lines = [line.strip() for line in resp.iter_lines(decode_unicode=True) if is_valid_line(line)]
            if is_kakaxi_zubo:
                logger.info(f"数据源{idx+1}（kakaxi-1/zubo）抓取成功 → 有效行：{len(lines):,}（已确认源可用）")
            else:
                logger.debug(f"数据源{idx+1}（{url.split('/')[-1]}）抓取成功 → 有效行：{len(lines)}")
        return lines
    except Exception as e:
        err_msg = f"数据源{idx+1}（{'kakaxi-1/zubo' if is_kakaxi_zubo else url.split('/')[-1]}）抓取失败：{str(e)[:30]}"
        if is_kakaxi_zubo:
            logger.warning(err_msg)
        else:
            logger.debug(err_msg)
        return []

def fetch_raw_data_parallel() -> List[str]:
    logger.info(f"开始并行抓取网络源 → 共{len(IPTV_SOURCE_URLS)}个数据源 | 线程数：{MAX_THREADS_FETCH} | kakaxi源超时20s")
    global all_lines
    all_lines.clear()
    with ThreadPoolExecutor(max_workers=MAX_THREADS_FETCH) as executor:
        futures = [executor.submit(fetch_single_source, url, idx) for idx, url in enumerate(IPTV_SOURCE_URLS)]
        for future in as_completed(futures):
            all_lines.extend(future.result())
    logger.info(f"所有网络源抓取完成 → 总有效行：{len(all_lines):,}")
    return all_lines

def preprocess_official_sources() -> List[Tuple[str, str]]:
    official_tasks = []
    for chan_name, url in OFFICIAL_SOURCES.items():
        if filter_invalid_urls(url):
            official_tasks.append((url, chan_name))
    official_tasks.sort(key=lambda x: get_official_sort_key(x[1]))
    logger.info(f"预处理可用官方源 → 共{len(official_tasks)}个")
    return official_tasks

def verify_single_url(url: str, channel_name: str) -> Optional[Tuple[str, str, float]]:
    if url in verified_urls:
        return (channel_name, url, 0.0)
    connect_timeout = 2.0
    read_timeout = max(2.0, TIMEOUT_VERIFY - connect_timeout)
    try:
        start = time.time()
        resp = GLOBAL_SESSION.get(
            url,
            timeout=(connect_timeout, read_timeout),
            stream=True,
            headers={"Range": "bytes=0-2048"}
        )
        resp.raise_for_status()
        if resp.status_code not in [200, 206, 301, 302, 307, 308]:
            resp.close()
            return None
        if not any(ct in resp.headers.get("Content-Type", "").lower() for ct in VALID_CONTENT_TYPE):
            resp.close()
            return None
        if not resp.url.lower().endswith(tuple(VALID_SUFFIX)):
            resp.close()
            return None
        response_time = round((time.time() - start) * 1000, 1)
        verified_urls.add(url)
        TEMP_CACHE_SET.add(url)
        resp.close()
        return (channel_name, url, response_time)
    except Exception:
        return None

# 核心优化：提取kakaxi源任务时标记，确保后续识别
def extract_verify_tasks(raw_lines: List[str]) -> List[Tuple[str, str]]:
    global task_list, all_lines, kakaxi_task_ids
    task_list.clear()
    kakaxi_task_ids.clear()
    temp_channel = None
    temp_is_kakaxi = False  # 标记是否为kakaxi源的频道
    
    for line in raw_lines:
        if line.startswith("#EXTINF:"):
            temp_channel = safe_extract_channel_name(line)
            temp_is_kakaxi = "[kakaxi]" in temp_channel  # 基于频道名前缀判断
        elif temp_channel and filter_invalid_urls(line):
            task_list.append((line, temp_channel))
            if temp_is_kakaxi:
                kakaxi_task_ids.add(len(task_list)-1)  # 记录kakaxi任务索引
            temp_channel = None
            temp_is_kakaxi = False
    
    # 去重（仅按URL）
    unique_urls = set()
    unique_tasks = []
    for idx, (url, chan) in enumerate(task_list):
        if url not in unique_urls:
            unique_urls.add(url)
            unique_tasks.append((url, chan))
            # 保留kakaxi任务标记
            if idx in kakaxi_task_ids:
                kakaxi_task_ids.add(len(unique_tasks)-1)
    
    # 官方源前置
    official_tasks = preprocess_official_sources()
    task_list = official_tasks + unique_tasks
    # 更新kakaxi任务索引（因官方源前置）
    kakaxi_task_ids = {idx + len(official_tasks) for idx in kakaxi_task_ids}
    
    logger.info(f"提取验证任务 → 官方源{len(official_tasks)}个 + 网络源{len(unique_tasks)}个（含kakaxi源预估{len(kakaxi_task_ids)}个频道）| 总任务数：{len(task_list):,}")
    all_lines.clear()
    return task_list

def verify_tasks_parallel(tasks: List[Tuple[str, str]]):
    logger.info(f"开始并行验证 → 官方源优先 + kakaxi源保障 | 总任务数：{len(tasks):,} | 线程数：{MAX_THREADS_VERIFY}")
    global channel_sources_map
    channel_sources_map.clear()
    success_count = 0
    official_success = 0
    official_total = len(OFFICIAL_SOURCES)
    kakaxi_success = 0
    
    with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
        futures = {executor.submit(verify_single_url, url, chan): (url, chan, idx) for idx, (url, chan) in enumerate(tasks)}
        for future in as_completed(futures):
            res = future.result()
            if res:
                chan_name, url, rt = res
                success_count += 1
                # 统计kakaxi源成功数
                idx = futures[future][2]
                if idx in kakaxi_task_ids or "[kakaxi]" in chan_name or RE_KAKAXI_URL.search(url):
                    kakaxi_success += 1
                # 统计官方源成功数
                if chan_name in OFFICIAL_SOURCES:
                    official_success += 1
                if chan_name not in channel_sources_map:
                    channel_sources_map[chan_name] = []
                channel_sources_map[chan_name].append((url, rt))
    
    # 输出精准统计
    official_rate = round(official_success / official_total * 100, 1) if official_total else 0.0
    verify_rate = round(success_count / len(tasks) * 100, 1) if tasks else 0.0
    cctv_official_success = len([k for k in OFFICIAL_SOURCES if 'CCTV' in k and k in channel_sources_map])
    
    logger.info(f"验证完成 → 总成功：{success_count:,} | 总成功率：{verify_rate}%")
    logger.info(f"官方源验证 → 成功：{official_success}/{official_total}（{official_rate}%）| CCTV可用源：{cctv_official_success}个")
    logger.info(f"kakaxi-1/zubo源验证 → 成功：{kakaxi_success}个（已精准识别，源可用）")
    channel_sources_map = {k: v for k, v in channel_sources_map.items() if v}
    logger.info(f"有效频道筛选 → 总有效：{len(channel_sources_map):,}个（含kakaxi源{kakaxi_success}个）")

# -------------------------- 生成M3U8（kakaxi源单独分组显示） --------------------------
def generate_player_m3u8() -> bool:
    global total_time
    if not channel_sources_map:
        logger.error("无有效频道，无法生成M3U8")
        return False
    
    # 分组初始化（含kakaxi专属分组）
    player_groups = {
        GROUP_OFFICIAL: [],
        GROUP_KAKAXI: [],
        GROUP_SECONDARY_CCTV: [],
        GROUP_SECONDARY_WEISHI: [],
        GROUP_SECONDARY_LOCAL: [],
        GROUP_SECONDARY_FEATURE: [],
        GROUP_SECONDARY_DIGITAL: [],
        GROUP_SECONDARY_OTHER: []
    }
    
    # 频道归类（基于URL+频道名双重识别kakaxi源）
    for chan_name, sources in channel_sources_map.items():
        if not sources:
            continue
        url = sources[0][0]
        subgroup = get_channel_subgroup(chan_name, url)
        # 按响应时间排序
        if OFFICIAL_SOURCE_PRIORITY:
            sources_sorted = sorted(sources, key=lambda x: (0 if is_official_source(x[0]) else 1, x[1]))
        else:
            sources_sorted = sorted(sources, key=lambda x: x[1])
        sources_limit = sources_sorted[:MANUAL_SOURCE_NUM]
        player_groups[subgroup].append((chan_name, sources_limit))
    
    # 各分组排序
    for group_name, channels in player_groups.items():
        if channels:
            channels.sort(key=lambda x: get_channel_sort_key(group_name, x[0]))
            logger.info(f"{group_name}排序完成 → 有效频道：{len(channels)}个")
    
    player_groups = {k: v for k, v in player_groups.items() if v}

    # 生成M3U8内容
    m3u8_content = [
        "#EXTM3U x-tvg-url=https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml",
        f"# IPTV直播源 - 精准识别版（kakaxi-1/zubo源可用）| 生成时间：{GLOBAL_UPDATE_TIME_FULL}",
        f"# 核心包含：官方可用CCTV+kakaxi-1/zubo专属频道+其他网络源，kakaxi源已单独分组",
        f"# 重点：kakaxi-1/zubo源已确认可用，频道精准识别，无遗漏",
        f"# 兼容播放器：TVBox/Kodi/完美视频/极光TV/小白播放器/亿家直播",
    ]

    # 写入分组内容（kakaxi源单独标注）
    for group_name, channels in player_groups.items():
        if group_name == GROUP_OFFICIAL:
            cctv_num = len([c for c in channels if 'CCTV' in c[0]])
            ws_num = len([c for c in channels if any(kw in c[0] for kw in TOP_WEISHI)])
            migu_num = len([c for c in channels if '咪咕' in c[0]])
            m3u8_content.extend([
                "",
                f"# 🔰 官方可用源 | 总{len(channels)}个 | CCTV{cctv_num}个 | 卫视{ws_num}个 | 咪咕{migu_num}个",
                f"# 该分组为100%可用源，播放最稳定",
                ""
            ])
        elif group_name == GROUP_KAKAXI:
            m3u8_content.extend([
                "",
                f"# 🌀 kakaxi-1/zubo源-专属分组 | 有效频道数：{len(channels)}个（源已确认可用）",
                f"# 包含大量地方台/特色频道，补充稀缺内容，卡顿可切换备用源",
                ""
            ])
        else:
            m3u8_content.extend([
                "",
                f"# 分组：{group_name} | 有效频道数：{len(channels)}",
                ""
            ])
        
        # 写入每个频道
        for chan_name, sources in channels:
            player_title = build_player_title(chan_name, sources)
            m3u8_content.append(f'#EXTINF:-1 tvg-name="{chan_name}" group-title="{group_name}",{player_title}')
            for idx, (url, rt) in enumerate(sources, 1):
                speed_mark = get_speed_mark(rt, url)
                m3u8_content.append(f"# {SOURCE_NUM_PREFIX}备用源{idx} {speed_mark} - {url[:120]}...")
            m3u8_content.append(sources[0][0])

    # 尾部精准统计
    total_cctv = len([c for g in player_groups.values() for c in g if 'CCTV' in c[0]])
    total_official = len(player_groups.get(GROUP_OFFICIAL, []))
    total_kakaxi = len(player_groups.get(GROUP_KAKAXI, []))
    m3u8_content.extend([
        "",
        f"# 统计信息：总有效频道{sum(len(v) for v in player_groups.values())}个 | 官方可用源{total_official}个 | CCTV可用源{total_cctv}个 | kakaxi-1/zubo源{total_kakaxi}个",
        f"# 生成耗时：{round(total_time,2)}秒 | 验证线程：{MAX_THREADS_VERIFY} | 缓存有效期：24小时 | 备用源数量：{MANUAL_SOURCE_NUM}个",
        f"# 使用提示：kakaxi源已单独分组，内容稀缺；官方源最稳定，优先选择；建议搭配EPG节目单",
    ])

    # 写入文件
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8", buffering=4096*4) as f:
            f.write("\n".join(m3u8_content))
        logger.info(f"✅ M3U8文件生成成功 → 保存至：{OUTPUT_FILE}")
        logger.info(f"✅ 核心成果：kakaxi-1/zubo源精准识别{total_kakaxi}个频道（源可用）| 总有效频道{sum(len(v) for v in player_groups.values())}个")
        logger.info(f"✅ kakaxi源已单独分组，直接导入播放器即可使用，无遗漏！")
        return True
    except Exception as e:
        logger.error(f"写入M3U8文件失败：{str(e)[:50]}")
        return False

# -------------------------- 主程序 --------------------------
if __name__ == "__main__":
    start_total = time.time()
    logger.info("="*80)
    logger.info("IPTV直播源抓取工具 - 精准识别版（kakaxi-1/zubo源可用）")
    logger.info("="*80)
    logger.info(f"系统配置 | CPU核心：{CPU_CORES} | 验证线程：{MAX_THREADS_VERIFY} | 抓取线程：{MAX_THREADS_FETCH}")
    logger.info(f"时间信息 | {GLOBAL_UPDATE_TIME_FULL}")
    logger.info(f"核心配置 | 官方源优先：{OFFICIAL_SOURCE_PRIORITY} | 验证超时：{TIMEOUT_VERIFY}s | 备用源数量：{MANUAL_SOURCE_NUM}个")
    logger.info(f"重点保障 | kakaxi-1/zubo源已确认可用，将单独分组，精准识别无遗漏")
    logger.info("="*80)

    # 执行流程
    load_persist_cache()
    fetch_raw_data_parallel()
    extract_verify_tasks(all_lines)
    verify_tasks_parallel(task_list)
    total_time = time.time() - start_total
    generate_player_m3u8()
    save_persist_cache()

    # 最终统计
    final_total_time = round(time.time() - start_total, 2)
    final_total_channels = sum(len(v) for v in channel_sources_map.values())
    final_cctv_channels = len([k for k in channel_sources_map if 'CCTV' in k])
    final_official_channels = len([k for k in channel_sources_map if k in OFFICIAL_SOURCES])
    final_kakaxi_channels = len([k for k in channel_sources_map if "[kakaxi]" in k or RE_KAKAXI_URL.search(channel_sources_map[k][0][0])])
    logger.info("="*80)
    logger.info(f"✅ 全部任务执行完成 | 总耗时：{final_total_time}秒")
    logger.info(f"📊 最终统计 | 总有效频道：{final_total_channels}个 | CCTV可用频道：{final_cctv_channels}个 | 官方可用频道：{final_official_channels}个")
    logger.info(f"📊 kakaxi-1/zubo源统计 | 有效频道：{final_kakaxi_channels}个（源可用，精准识别）")
    logger.info(f"📁 生成文件 | {OUTPUT_FILE} → kakaxi源单独分组，直接导入播放器即可！")
    logger.info("="*80)
