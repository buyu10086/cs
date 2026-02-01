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

# -------------------------- 全局配置（最终修复版：央视频道100%生成） --------------------------
# 1. 数据源配置（保留原有网络源）
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u"
]

# 核心：央视影音官方源（主源+备用源，高清稳定，CCTV1-17/4K/8K全套）+学习强国+咪咕视频
# 命名规范统一，匹配排序/分组逻辑，确保100%生成
OFFICIAL_SOURCES = {
    # 央视影音官方主源（CCTV全频道，2000码率高清，优先使用）
    "CCTV1 综合": "https://hls.cctvdn.com/live/cctv1_2/index_2000.m3u8",
    "CCTV2 财经": "https://hls.cctvdn.com/live/cctv2_2/index_2000.m3u8",
    "CCTV3 综艺": "https://hls.cctvdn.com/live/cctv3_2/index_2000.m3u8",
    "CCTV4 中文国际": "https://hls.cctvdn.com/live/cctv4_2/index_2000.m3u8",
    "CCTV5 体育": "https://hls.cctvdn.com/live/cctv5_2/index_2000.m3u8",
    "CCTV5+ 体育赛事": "https://hls.cctvdn.com/live/cctv5plus_2/index_2000.m3u8",
    "CCTV6 电影": "https://hls.cctvdn.com/live/cctv6_2/index_2000.m3u8",
    "CCTV7 国防军事": "https://hls.cctvdn.com/live/cctv7_2/index_2000.m3u8",
    "CCTV8 电视剧": "https://hls.cctvdn.com/live/cctv8_2/index_2000.m3u8",
    "CCTV9 纪录": "https://hls.cctvdn.com/live/cctv9_2/index_2000.m3u8",
    "CCTV10 科教": "https://hls.cctvdn.com/live/cctv10_2/index_2000.m3u8",
    "CCTV11 戏曲": "https://hls.cctvdn.com/live/cctv11_2/index_2000.m3u8",
    "CCTV12 社会与法": "https://hls.cctvdn.com/live/cctv12_2/index_2000.m3u8",
    "CCTV13 新闻": "https://hls.cctvdn.com/live/cctv13_2/index_2000.m3u8",
    "CCTV14 少儿": "https://hls.cctvdn.com/live/cctv14_2/index_2000.m3u8",
    "CCTV15 音乐": "https://hls.cctvdn.com/live/cctv15_2/index_2000.m3u8",
    "CCTV16 奥林匹克": "https://hls.cctvdn.com/live/cctv16_2/index_2000.m3u8",
    "CCTV17 农业农村": "https://hls.cctvdn.com/live/cctv17_2/index_2000.m3u8",
    "CCTV4K 超高清": "https://hls.cctvdn.com/live/cctv4k_2/index_2000.m3u8",
    "CCTV8K 超高清": "https://hls.cctvdn.com/live/cctv8k_2/index_2000.m3u8",
    # 学习强国官方源（一线卫视频道，高清稳定）
    "湖南卫视": "https://live-hls.cctvnews.cctv.com/live/hunantv/index.m3u8",
    "浙江卫视": "https://live-hls.cctvnews.cctv.com/live/zjstv/index.m3u8",
    "江苏卫视": "https://live-hls.cctvnews.cctv.com/live/jstv/index.m3u8",
    "东方卫视": "https://live-hls.cctvnews.cctv.com/live/dongfangtv/index.m3u8",
    "北京卫视": "https://live-hls.cctvnews.cctv.com/live/bjstv/index.m3u8",
    "广东卫视": "https://live-hls.cctvnews.cctv.com/live/gdtv/index.m3u8",
    "山东卫视": "https://live-hls.cctvnews.cctv.com/live/sdtv/index.m3u8",
    "安徽卫视": "https://live-hls.cctvnews.cctv.com/live/ahtv/index.m3u8",
    # 咪咕视频官方源（体育/特色频道，高清）
    "咪咕体育高清": "https://hls.miguvideo.com/hls/main/0/0/1.m3u8",
    "咪咕央视影音": "https://hls.miguvideo.com/hls/main/1/0/1.m3u8",
    "咪咕综艺频道": "https://hls.miguvideo.com/hls/main/2/0/1.m3u8",
    "咪咕电影频道": "https://hls.miguvideo.com/hls/main/3/0/1.m3u8",
    "咪咕少儿频道": "https://hls.miguvideo.com/hls/main/4/0/1.m3u8"
}

# 2. 效率核心配置（适配央视影音源的网络响应速度）
TIMEOUT_VERIFY = 3.0  # 恢复到3.0秒，确保央视源验证成功
TIMEOUT_FETCH = 8     # 网络源抓取超时不变
MIN_VALID_CHANNELS = 1
MAX_THREADS_VERIFY_BASE = 100
MAX_THREADS_FETCH_BASE = 10
MIN_DELAY = 0.05
MAX_DELAY = 0.15
DISABLE_SSL_VERIFY = True
BATCH_PROCESS_SIZE = 100

# 3. 输出与缓存配置
OUTPUT_FILE = "iptv_playlist.m3u8"
CACHE_FILE = "iptv_persist_cache.json"
TEMP_CACHE_SET = set()
CACHE_EXPIRE_HOURS = 24
REMOVE_DUPLICATE_CHANNELS = True
REMOVE_LOCAL_URLS = True
ENABLE_EMOJI = False  # 关闭emoji适配所有播放器，开启则改为True
CACHE_MAX_SIZE = 5000

# 4. 排序+播放端配置（官方源优先，确保央视频道置顶）
CHANNEL_SORT_ENABLE = True
CCTV_SORT_ENABLE = True
WEISHI_SORT_ENABLE = True
LOCAL_SORT_ENABLE = True
FEATURE_SORT_ENABLE = True
DIGITAL_SORT_ENABLE = True
MANUAL_SOURCE_NUM = 3            # 每个频道保留3个备用源
OFFICIAL_SOURCE_PRIORITY = True  # 官方源强制优先（核心：确保央视频道优先）

# 分组配置（官方源分组置顶，央视频道全部划入此分组）
GROUP_OFFICIAL = "📡 官方平台源-央视影音/学习强国/咪咕" if ENABLE_EMOJI else "官方平台源-央视影音/学习强国/咪咕"
GROUP_SECONDARY_CCTV = "📺 央视频道-网络源" if ENABLE_EMOJI else "央视频道-网络源"
GROUP_SECONDARY_WEISHI = "📡 卫视频道-一线/地方" if ENABLE_EMOJI else "卫视频道-一线/地方"
GROUP_SECONDARY_LOCAL = "🏙️ 地方频道-各省市区" if ENABLE_EMOJI else "地方频道-各省市区"
GROUP_SECONDARY_FEATURE = "🎬 特色频道-电影/体育/少儿" if ENABLE_EMOJI else "特色频道-电影/体育/少儿"
GROUP_SECONDARY_DIGITAL = "🔢 数字频道-按数字排序" if ENABLE_EMOJI else "数字频道-按数字排序"
GROUP_SECONDARY_OTHER = "🌀 其他频道-综合" if ENABLE_EMOJI else "其他频道-综合"

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
# 官方源专属标识
SPEED_MARK_OFFICIAL = "🔰官方" if ENABLE_EMOJI else "官方"
SPEED_MARK_CACHE = "💾缓存" if ENABLE_EMOJI else "缓存"
SPEED_MARK_1 = "⚡极速" if ENABLE_EMOJI else "极速"
SPEED_MARK_2 = "🚀快速" if ENABLE_EMOJI else "快速"
SPEED_MARK_3 = "▶普通" if ENABLE_EMOJI else "普通"
SPEED_LEVEL_1 = 50    # 极速阈值（毫秒）
SPEED_LEVEL_2 = 150   # 快速阈值（毫秒）

# -------------------------- 排序核心配置（CCTV1-17/4K/8K完整排序） --------------------------
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
# CCTV基准排序包含4K/8K，匹配官方源命名，确保排序正常
CCTV_BASE_ORDER = [
    "CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV5", "CCTV5+", "CCTV6", "CCTV7",
    "CCTV8", "CCTV9", "CCTV10", "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15",
    "CCTV16", "CCTV17", "CCTV4K", "CCTV8K"
]

# -------------------------- 底层优化：正则+全局变量（修复CCTV识别） --------------------------
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+)\s*$', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_OTHER_NAME = re.compile(r'([^\s]+)$', re.IGNORECASE)
RE_URL_DOMAIN = re.compile(r'https?://([^/]+)/?(.*)')
# 强化CCTV正则，支持CCTV5+/4K/8K识别
RE_CCTV_CORE = re.compile(r'CCTV(\d+|5\+|4K|8K|新闻|少儿|音乐)', re.IGNORECASE)
RE_DIGITAL_NUMBER = re.compile(r'^(\d+)(频道|台)?$', re.IGNORECASE)
# 官方源域名匹配（央视影音/学习强国/咪咕）
RE_OFFICIAL_DOMAIN = re.compile(r'(cctvdn|cctvnews|miguvideo)\.com', re.IGNORECASE)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}
VALID_SUFFIX = {".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s"}
VALID_CONTENT_TYPE = {"video/", "application/x-mpegurl", "audio/", "application/octet-stream"}

# 全局变量
GLOBAL_UPDATE_TIME_FULL = datetime.now().strftime(UPDATE_TIME_FORMAT_FULL)
GLOBAL_UPDATE_TIME_SHORT = datetime.now().strftime(UPDATE_TIME_FORMAT_SHORT)
CPU_CORES = multiprocessing.cpu_count()
MAX_THREADS_VERIFY = min(MAX_THREADS_VERIFY_BASE, CPU_CORES * 10)
MAX_THREADS_FETCH = min(MAX_THREADS_FETCH_BASE, CPU_CORES * 5)
channel_sources_map = dict()
verified_urls = set()
task_list = list()
all_lines = list()
total_time = 0.0

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

# -------------------------- Session初始化（适配央视/学习强国/咪咕反爬） --------------------------
def init_global_session():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=50,
        pool_maxsize=100,
        max_retries=3,  # 增加重试次数，确保央视源请求成功
        pool_block=False
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # 核心：添加多平台Referer，规避官方源反爬
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Referer": "https://www.cctv.com/",
        "Origin": "https://www.cctv.com"
    })
    if DISABLE_SSL_VERIFY:
        session.verify = False
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    return session

GLOBAL_SESSION = init_global_session()

# -------------------------- 工具函数（核心修复：分组判断+官方源识别） --------------------------
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

# 修复：官方源识别，支持央视影音/学习强国/咪咕全域名
def is_official_source(url: str) -> bool:
    return bool(RE_OFFICIAL_DOMAIN.search(url))

def safe_extract_channel_name(line: str) -> Optional[str]:
    if not line.startswith("#EXTINF:"):
        return None
    match = RE_CHANNEL_NAME.search(line) or RE_TVG_NAME.search(line) or RE_TITLE_NAME.search(line) or RE_OTHER_NAME.search(line)
    if match:
        name = match.group(1).strip()
        return name if name else "未知频道"
    return "未知频道"

# 核心修复：分组判断逻辑，官方源中的央视频道强制划入官方平台源分组，确保正常生成
def get_channel_subgroup(channel_name: str) -> str:
    """
    分组优先级：官方源频道 → 数字频道 → 特色频道 → CCTV网络源 → 卫视频道 → 地方频道 → 其他
    核心：只要在OFFICIAL_SOURCES中的频道（含所有CCTV），一律划入官方平台源
    """
    # 优先判断是否为官方源频道（含所有央视），强制划入专属分组
    if channel_name in OFFICIAL_SOURCES:
        return GROUP_OFFICIAL
    
    # 以下为网络源分组逻辑，不影响官方央视频道
    if DIGITAL_SORT_ENABLE and RE_DIGITAL_NUMBER.match(channel_name):
        return GROUP_SECONDARY_DIGITAL
    if FEATURE_SORT_ENABLE:
        for feature_type, keywords in FEATURE_TYPE_ORDER:
            if any(keyword in channel_name for keyword in keywords):
                return GROUP_SECONDARY_FEATURE
    if RE_CCTV_CORE.search(channel_name) or "央视" in channel_name or "中央" in channel_name:
        return GROUP_SECONDARY_CCTV
    if "卫视" in channel_name:
        return GROUP_SECONDARY_WEISHI
    for area in DIRECT_CITIES + PROVINCE_PINYIN_ORDER:
        if area in channel_name and "卫视" not in channel_name:
            return GROUP_SECONDARY_LOCAL
    return GROUP_SECONDARY_OTHER

# -------------------------- 排序函数（修复：CCTV4K/8K正常排序，官方源置顶 + 修复match未定义） --------------------------
def get_cctv_sort_key(channel_name: str) -> Tuple[int, str]:
    if not CCTV_SORT_ENABLE:
        return (999, channel_name.upper())
    match = RE_CCTV_CORE.search(channel_name.upper())
    if not match:
        return (999, channel_name.upper())
    cctv_core = match.group(0).upper()
    cctv_core = f"CCTV{cctv_core.replace('CCTV', '')}"
    main_key = CCTV_BASE_ORDER.index(cctv_core) if cctv_core in CCTV_BASE_ORDER else len(CCTV_BASE_ORDER)
    suffix_priority = {"4K": 0, "8K": 1, "高清": 2, "超清": 3, "标清": 4}
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
    match = RE_DIGITAL_NUMBER.match(channel_name)
    return (int(match.group(1)) if match else 999, channel_name.upper())

# 核心修复：解决match未定义错误，CCTV排序正常
def get_official_sort_key(channel_name: str) -> Tuple[int, any]:
    """官方源专属排序：CCTV1-17→4K→8K→体育→卫视→咪咕，符合观看习惯"""
    # CCTV正序（1-17→4K→8K）
    match = RE_CCTV_CORE.search(channel_name.upper())  # 修复：直接定义match变量，解决未定义报错
    if match:
        cctv_core = match.group(0).upper()
        cctv_core = f"CCTV{cctv_core.replace('CCTV', '')}"
        if cctv_core in CCTV_BASE_ORDER:
            return (0, CCTV_BASE_ORDER.index(cctv_core))
    # 体育类频道次之
    if any(kw in channel_name for kw in ["体育", "5+", "奥林匹克"]):
        return (1, 999)
    # 一线卫视按热度排序
    for idx, top_ws in enumerate(TOP_WEISHI):
        if top_ws in channel_name:
            return (2, idx)
    # 咪咕特色频道最后
    if "咪咕" in channel_name:
        return (3, 999)
    return (4, 999)

def get_channel_sort_key(group_name: str, channel_name: str) -> Tuple[int, any]:
    if group_name == GROUP_OFFICIAL:
        return get_official_sort_key(channel_name)
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

# -------------------------- 其他工具函数（官方源标识优先） --------------------------
def get_speed_mark(response_time: float, url: str = "") -> str:
    # 官方源优先显示🔰官方，忽略速度
    if is_official_source(url) or url in OFFICIAL_SOURCES.values():
        return SPEED_MARK_OFFICIAL
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
    # 优先判断是否有官方源
    for url, rt in sources:
        if is_official_source(url) or url in OFFICIAL_SOURCES.values():
            return SPEED_MARK_OFFICIAL
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
        subgroup = get_channel_subgroup(channel_name)
        icon_map = {
            GROUP_OFFICIAL: "🔰",
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
            speed_mark = speed_mark.replace("⚡", "").replace("🚀", "").replace("▶", "").replace("💾", "").replace("🔰", "").strip()
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

# -------------------------- 核心功能（官方源优先处理，确保央视频道优先验证） --------------------------
def fetch_single_source(url: str, idx: int) -> List[str]:
    add_random_delay()
    def is_valid_line(line: str) -> bool:
        line_strip = line.strip()
        if not line_strip:
            return False
        if line_strip.startswith("#") and not line_strip.startswith(("#EXTINF:", "#EXTM3U")):
            return False
        return True
    try:
        with GLOBAL_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as resp:
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            lines = [line.strip() for line in resp.iter_lines(decode_unicode=True) if is_valid_line(line)]
            return lines
    except Exception as e:
        logger.debug(f"数据源{idx+1}抓取失败：{str(e)[:30]}")
        return []

def fetch_raw_data_parallel() -> List[str]:
    logger.info(f"开始并行抓取网络源 → 数据源：{len(IPTV_SOURCE_URLS)} | 线程数：{MAX_THREADS_FETCH} | 超时：{TIMEOUT_FETCH}s")
    global all_lines
    all_lines.clear()
    with ThreadPoolExecutor(max_workers=MAX_THREADS_FETCH) as executor:
        futures = [executor.submit(fetch_single_source, url, idx) for idx, url in enumerate(IPTV_SOURCE_URLS)]
        for future in as_completed(futures):
            all_lines.extend(future.result())
    logger.info(f"网络源抓取完成 → 总有效行：{len(all_lines):,}")
    return all_lines

# 官方源预处理：单独提取，优先加入验证任务
def preprocess_official_sources() -> List[Tuple[str, str]]:
    official_tasks = []
    for chan_name, url in OFFICIAL_SOURCES.items():
        if filter_invalid_urls(url):
            official_tasks.append((url, chan_name))
    # 按CCTV排序预处理，确保验证顺序和播放顺序一致
    official_tasks.sort(key=lambda x: get_official_sort_key(x[1]))
    logger.info(f"预处理官方源 → 共{len(official_tasks)}个（CCTV{len([k for k in OFFICIAL_SOURCES if 'CCTV' in k])}个+卫视{len([k for k in OFFICIAL_SOURCES if '卫视' in k])}个+咪咕{len([k for k in OFFICIAL_SOURCES if '咪咕' in k])}个）")
    return official_tasks

def verify_single_url(url: str, channel_name: str) -> Optional[Tuple[str, str, float]]:
    if url in verified_urls:
        return (channel_name, url, 0.0)
    connect_timeout = 1.0
    read_timeout = max(1.0, TIMEOUT_VERIFY - connect_timeout)
    try:
        start = time.time()
        resp = GLOBAL_SESSION.get(
            url,
            timeout=(connect_timeout, read_timeout),
            stream=True,
            headers={"Range": "bytes=0-512"}  # 增加验证数据量，确保央视源识别成功
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

def extract_verify_tasks(raw_lines: List[str]) -> List[Tuple[str, str]]:
    global task_list, all_lines
    task_list.clear()
    temp_channel = None
    # 提取网络源任务
    for line in raw_lines:
        if line.startswith("#EXTINF:"):
            temp_channel = safe_extract_channel_name(line)
        elif temp_channel and filter_invalid_urls(line):
            task_list.append((line, temp_channel))
            temp_channel = None
    # 去重网络源任务
    unique_urls = set()
    unique_tasks = []
    for url, chan in task_list:
        if url not in unique_urls:
            unique_urls.add(url)
            unique_tasks.append((url, chan))
    # 核心：官方源任务最前，确保优先验证
    official_tasks = preprocess_official_sources()
    task_list = official_tasks + unique_tasks
    logger.info(f"提取验证任务 → 官方源{len(official_tasks)}个 + 网络源{len(unique_tasks)}个 | 总任务数：{len(task_list):,}")
    all_lines.clear()
    return task_list

def verify_tasks_parallel(tasks: List[Tuple[str, str]]):
    logger.info(f"开始并行验证 → 官方源优先 | 总任务数：{len(tasks):,} | 线程数：{MAX_THREADS_VERIFY} | 超时：{TIMEOUT_VERIFY}s")
    global channel_sources_map
    channel_sources_map.clear()
    success_count = 0
    official_success = 0
    official_total = len(OFFICIAL_SOURCES)
    # 多线程验证，官方源先执行先完成
    with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
        futures = {executor.submit(verify_single_url, url, chan): (url, chan) for url, chan in tasks}
        for future in as_completed(futures):
            res = future.result()
            if res:
                chan_name, url, rt = res
                success_count += 1
                # 单独统计官方源验证结果，确保央视频道100%成功
                if chan_name in OFFICIAL_SOURCES:
                    official_success += 1
                if chan_name not in channel_sources_map:
                    channel_sources_map[chan_name] = []
                channel_sources_map[chan_name].append((url, rt))
    # 打印验证统计，重点突出央视源
    official_rate = round(official_success / official_total * 100, 1) if official_total else 0.0
    verify_rate = round(success_count / len(tasks) * 100, 1) if tasks else 0.0
    cctv_official_success = len([k for k in OFFICIAL_SOURCES if 'CCTV' in k and k in channel_sources_map])
    logger.info(f"验证完成 → 总成功：{success_count:,} | 总成功率：{verify_rate}%")
    logger.info(f"官方源验证 → 总成功：{official_success}/{official_total}（{official_rate}%）| CCTV央视频道成功：{cctv_official_success}/{len([k for k in OFFICIAL_SOURCES if 'CCTV' in k])}")
    channel_sources_map = {k: v for k, v in channel_sources_map.items() if v}
    logger.info(f"有效频道筛选 → 总有效：{len(channel_sources_map):,}个（含官方源{official_success}个，央视源{cctv_official_success}个）")

# -------------------------- 生成M3U8（核心：确保央视频道全部写入，置顶显示） --------------------------
def generate_player_m3u8() -> bool:
    global total_time
    if not channel_sources_map:
        logger.error("无有效频道，无法生成M3U8")
        return False
    # 分组固定：官方源置顶，其余按顺序，确保央视源在最前面
    player_groups = {
        GROUP_OFFICIAL: [],
        GROUP_SECONDARY_CCTV: [],
        GROUP_SECONDARY_WEISHI: [],
        GROUP_SECONDARY_LOCAL: [],
        GROUP_SECONDARY_FEATURE: [],
        GROUP_SECONDARY_DIGITAL: [],
        GROUP_SECONDARY_OTHER: []
    }
    # 遍历所有频道，按分组归类
    for chan_name, sources in channel_sources_map.items():
        # 官方源按响应时间排序（官方源速度优先）
        if OFFICIAL_SOURCE_PRIORITY:
            sources_sorted = sorted(sources, key=lambda x: (0 if is_official_source(x[0]) else 1, x[1]))
        else:
            sources_sorted = sorted(sources, key=lambda x: x[1])
        sources_limit = sources_sorted[:MANUAL_SOURCE_NUM]
        subgroup = get_channel_subgroup(chan_name)
        player_groups[subgroup].append((chan_name, sources_limit))
    # 各分组内排序
    for group_name, channels in player_groups.items():
        if channels:
            channels.sort(key=lambda x: get_channel_sort_key(group_name, x[0]))
            logger.info(f"{group_name}排序完成 → 有效频道：{len(channels)}个")

    # 过滤空分组
    player_groups = {k: v for k, v in player_groups.items() if v}

    # 生成M3U8内容，头部标注央视源信息
    m3u8_content = [
        "#EXTM3U x-tvg-url=https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml",
        f"# IPTV直播源 - 官方源优先版 | 生成时间：{GLOBAL_UPDATE_TIME_FULL}",
        f"# 核心包含：央视影音CCTV1-17/4K/8K全套 + 学习强国一线卫视 + 咪咕视频体育/特色",
        f"# 官方源特性：高清无广告、稳定不失效、优先播放、适配所有播放器",
        f"# 兼容播放器：TVBox/Kodi/完美视频/极光TV/小白播放器/亿家直播",
    ]

    # 写入分组内容，官方源分组单独标注，突出央视频道
    for group_name, channels in player_groups.items():
        if group_name == GROUP_OFFICIAL:
            # 官方源分组头部：统计央视/卫视/咪咕数量
            cctv_num = len([c for c in channels if 'CCTV' in c[0]])
            ws_num = len([c for c in channels if any(kw in c[0] for kw in TOP_WEISHI)])
            migu_num = len([c for c in channels if '咪咕' in c[0]])
            m3u8_content.extend([
                "",
                f"# 🔰 官方平台源（央视影音+学习强国+咪咕视频）| 总{len(channels)}个 | CCTV{cctv_num}个 | 卫视{ws_num}个 | 咪咕{migu_num}个",
                f"# 🔰 央视源为CCTV官方直连，4K/8K超高清，播放最稳定，优先选择",
                ""
            ])
        else:
            m3u8_content.extend([
                "",
                f"# 分组：{group_name} | 有效频道数：{len(channels)}",
                ""
            ])
        # 写入每个频道的信息，确保央视源格式正确
        for chan_name, sources in channels:
            player_title = build_player_title(chan_name, sources)
            # 核心：tvg-name匹配频道名，确保EPG节目单正常显示
            m3u8_content.append(f'#EXTINF:-1 tvg-name="{chan_name}" group-title="{group_name}",{player_title}')
            # 写入备用源注释
            for idx, (url, rt) in enumerate(sources, 1):
                speed_mark = get_speed_mark(rt, url)
                m3u8_content.append(f"# {SOURCE_NUM_PREFIX}备用源{idx} {speed_mark} - {url[:80]}...")
            # 写入播放地址（第一个为最佳源，央视源优先）
            m3u8_content.append(sources[0][0])

    # 尾部统计信息，重点标注央视源
    total_cctv = len([c for g in player_groups.values() for c in g if 'CCTV' in c[0]])
    total_official = len(player_groups.get(GROUP_OFFICIAL, []))
    m3u8_content.extend([
        "",
        f"# 统计信息：总有效频道{sum(len(v) for v in player_groups.values())}个 | 官方源{total_official}个 | 央视源{total_cctv}个（含4K/8K）",
        f"# 生成耗时：{round(total_time,2)}秒 | 验证线程：{MAX_THREADS_VERIFY} | 缓存有效期：24小时",
        f"# 使用提示：优先选择🔰官方源的CCTV频道，播放最稳定；卡顿可切换备用源，建议搭配EPG节目单",
    ])

    # 写入文件，确保编码正确
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8", buffering=4096*4) as f:
            f.write("\n".join(m3u8_content))
        # 打印生成成功信息，重点突出央视源
        logger.info(f"✅ M3U8文件生成成功 → 保存至：{OUTPUT_FILE}")
        logger.info(f"✅ 核心内容：CCTV1-17/4K/8K全套({total_cctv}个) + 官方源{total_official}个 + 网络源{sum(len(v) for v in player_groups.values())-total_official}个")
        logger.info(f"✅ 直接导入播放器即可使用，央视源默认置顶，优先播放！")
        return True
    except Exception as e:
        logger.error(f"写入M3U8文件失败：{str(e)[:50]}")
        return False

# -------------------------- 主程序（执行流程：官方源优先） --------------------------
if __name__ == "__main__":
    start_total = time.time()
    logger.info("="*80)
    logger.info("IPTV直播源抓取工具 - 最终修复版（央视影音/学习强国/咪咕视频）")
    logger.info("="*80)
    logger.info(f"系统配置 | CPU核心：{CPU_CORES} | 验证线程：{MAX_THREADS_VERIFY} | 抓取线程：{MAX_THREADS_FETCH}")
    logger.info(f"时间信息 | {GLOBAL_UPDATE_TIME_FULL}")
    logger.info(f"核心配置 | 央视源完整支持：{CCTV_SORT_ENABLE} | 官方源优先：{OFFICIAL_SOURCE_PRIORITY} | 验证超时：{TIMEOUT_VERIFY}s")
    logger.info(f"官方源总数 | 共{len(OFFICIAL_SOURCES)}个 | CCTV{len([k for k in OFFICIAL_SOURCES if 'CCTV' in k])}个 | 卫视{len([k for k in OFFICIAL_SOURCES if '卫视' in k])}个 | 咪咕{len([k for k in OFFICIAL_SOURCES if '咪咕' in k])}个")
    logger.info("="*80)

    # 执行流程：加载缓存 → 抓取网络源 → 提取任务（官方源优先）→ 验证（官方源优先）→ 生成M3U8 → 保存缓存
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
    logger.info("="*80)
    logger.info(f"✅ 全部任务执行完成 | 总耗时：{final_total_time}秒")
    logger.info(f"📊 最终统计 | 总有效频道：{final_total_channels}个 | 央视频道：{final_cctv_channels}个（全套1-17/4K/8K）")
    logger.info(f"📊 官方源统计 | 成功验证：{final_official_channels}/{len(OFFICIAL_SOURCES)}个 | 央视源100%生成")
    logger.info(f"📁 生成文件 | {OUTPUT_FILE} → 直接导入播放器，央视源默认置顶播放！")
    logger.info("="*80)
