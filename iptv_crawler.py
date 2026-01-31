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
import multiprocessing
from typing import Tuple, List, Dict, Optional

# -------------------------- 全局配置（优化自动选源+保留3个源） --------------------------
# 1. 数据源配置（全量卫视频道）
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://raw.githubusercontent.com/Guovin/iptv-api/refs/heads/gd/output/result.m3u",
    "https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u",
    "https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u",
    "https://raw.githubusercontent.com/audyfan/tv/refs/heads/main/live.m3u",
    # 卫视频道专属数据源
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://raw.githubusercontent.com/zhouweitong123/IPTV/main/IPTV/卫视.m3u",
    "https://raw.githubusercontent.com/chenfenping/iptv/main/tv/m3u8/weishi.m3u",
    "https://raw.githubusercontent.com/yangzongzhuan/IPTV/master/m3u/weishi.m3u",
    "https://raw.githubusercontent.com/linkease/iptv/main/playlist/weishi.m3u"
]

# 2. 效率核心配置
TIMEOUT_VERIFY = 3.5
TIMEOUT_FETCH = 12
MIN_VALID_CHANNELS = 1
MAX_THREADS_VERIFY_BASE = 25
MAX_THREADS_FETCH_BASE = 6
MIN_DELAY = 0.15
MAX_DELAY = 0.4
DISABLE_SSL_VERIFY = True
BATCH_PROCESS_SIZE = 50

# 3. 输出与缓存配置
OUTPUT_FILE = "iptv_playlist.m3u8"
CACHE_FILE = "iptv_persist_cache.json"
TEMP_CACHE_SET = set()
CACHE_EXPIRE_HOURS = 24
REMOVE_DUPLICATE_CHANNELS = False
REMOVE_LOCAL_URLS = True

# 4. 自动选源+保留3个源配置（核心优化）
AUTO_SELECT_SOURCE = True  # 开启自动选最优源（默认开启）
TOTAL_SOURCES_PER_CHANNEL = 3  # 每个频道保留3个源（1个最优+2个备用）
SELECT_SPEED_THRESHOLD = 30  # 速度差值阈值（ms），低于此值时优先选.m3u8格式
PREFER_M3U8 = True  # 优先选择.m3u8格式源（稳定性更高）

# 5. 排序+播放端配置
CHANNEL_SORT_ENABLE = True
CCTV_SORT_ENABLE = True
WEISHI_SORT_ENABLE = True
LOCAL_SORT_ENABLE = True
FEATURE_SORT_ENABLE = True
DIGITAL_SORT_ENABLE = True

# 分组配置
GROUP_SECONDARY_CCTV = "📺 央视频道-CCTV1-17"
GROUP_SECONDARY_WEISHI = "📡 卫视频道-一线/地方（全量）"
GROUP_SECONDARY_LOCAL = "🏙️ 地方频道-各省市区"
GROUP_SECONDARY_FEATURE = "🎬 特色频道-电影/体育/少儿"
GROUP_SECONDARY_DIGITAL = "🔢 数字频道-按数字排序"
GROUP_SECONDARY_OTHER = "🌀 其他频道-综合"

# 播放端美化配置
PLAYER_TITLE_PREFIX = True
PLAYER_TITLE_SHOW_SPEED = True  # 显示最优源速度
PLAYER_TITLE_SHOW_NUM = True    # 显示保留源数（3个）
PLAYER_TITLE_SHOW_UPDATE = True
UPDATE_TIME_FORMAT_SHORT = "%m-%d %H:%M"
UPDATE_TIME_FORMAT_FULL = "%Y-%m-%d %H:%M:%S"
GROUP_SEPARATOR = "#" * 50
URL_TRUNCATE_DOMAIN = True
URL_TRUNCATE_LENGTH = 50
SOURCE_NUM_PREFIX = "📶"
SPEED_MARK_CACHE = "💾缓存·极速"
SPEED_MARK_1 = "⚡极速"
SPEED_MARK_2 = "🚀快速"
SPEED_MARK_3 = "▶普通"
SPEED_LEVEL_1 = 50
SPEED_LEVEL_2 = 150

# -------------------------- 排序核心配置 --------------------------
TOP_WEISHI = [
    "湖南卫视", "浙江卫视", "江苏卫视", "东方卫视", "北京卫视", "安徽卫视", "山东卫视", "广东卫视",
    "深圳卫视", "天津卫视", "四川卫视", "湖北卫视", "河南卫视", "江西卫视", "云南卫视", "贵州卫视"
]
ALL_PROVINCE_WEISHI = [
    "北京卫视", "天津卫视", "河北卫视", "山西卫视", "内蒙古卫视", "辽宁卫视", "吉林卫视", "黑龙江卫视",
    "上海卫视", "江苏卫视", "浙江卫视", "安徽卫视", "福建卫视", "江西卫视", "山东卫视", "河南卫视",
    "湖北卫视", "湖南卫视", "广东卫视", "广西卫视", "海南卫视", "重庆卫视", "四川卫视", "贵州卫视",
    "云南卫视", "西藏卫视", "陕西卫视", "甘肃卫视", "青海卫视", "宁夏卫视", "新疆卫视", "台湾卫视",
    "香港卫视", "澳门卫视", "深圳卫视", "厦门卫视", "青岛卫视"
]
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

# -------------------------- 底层优化：正则+全局变量 --------------------------
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+)\s*$', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_OTHER_NAME = re.compile(r'([^\s]+)$', re.IGNORECASE)
RE_URL_DOMAIN = re.compile(r'https?://([^/]+)/?(.*)')
RE_CCTV_NUMBER = re.compile(r'CCTV(\d+)', re.IGNORECASE)
RE_DIGITAL_NUMBER = re.compile(r'^(\d+)(频道|台)?$', re.IGNORECASE)
RE_WEISHI_SUFFIX = re.compile(r'(卫视|卫视频道|卫视HD|卫视高清|卫视-高清)', re.IGNORECASE)
RE_M3U8_SUFFIX = re.compile(r'\.m3u8$', re.IGNORECASE)  # 匹配.m3u8格式
LOCAL_HOSTS = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}
VALID_SUFFIX = {".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s", ".mp4"}
VALID_CONTENT_TYPE = {"video/", "application/x-mpegurl", "audio/", "application/octet-stream", "video/mp4"}

# 全局变量
GLOBAL_UPDATE_TIME_FULL = datetime.now().strftime(UPDATE_TIME_FORMAT_FULL)
GLOBAL_UPDATE_TIME_SHORT = datetime.now().strftime(UPDATE_TIME_FORMAT_SHORT)
CPU_CORES = multiprocessing.cpu_count()
MAX_THREADS_VERIFY = min(MAX_THREADS_VERIFY_BASE, CPU_CORES * 4)
MAX_THREADS_FETCH = min(MAX_THREADS_FETCH_BASE, CPU_CORES * 2)
channel_sources_map = dict()
verified_urls = set()
task_list = list()
all_lines = list()

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
        pool_connections=25,
        pool_maxsize=60,
        max_retries=3,
        pool_block=False
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache"
    })
    if DISABLE_SSL_VERIFY:
        session.verify = False
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    return session

GLOBAL_SESSION = init_global_session()

# -------------------------- 工具函数（核心：自动选最优源+保留3个源） --------------------------
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

def safe_extract_channel_name(line: str) -> Optional[str]:
    if not line.startswith("#EXTINF:"):
        return None
    match = RE_CHANNEL_NAME.search(line) or RE_TVG_NAME.search(line) or RE_TITLE_NAME.search(line) or RE_OTHER_NAME.search(line)
    if match:
        name = match.group(1).strip()
        return name if name else "未知频道"
    return "未知频道"

def is_weishi_channel(channel_name: str) -> bool:
    if not channel_name:
        return False
    if RE_WEISHI_SUFFIX.search(channel_name):
        return True
    for weishi in ALL_PROVINCE_WEISHI:
        if weishi in channel_name and "卫视" in channel_name:
            return True
    for province in PROVINCE_PINYIN_ORDER:
        if province in channel_name and any(suffix in channel_name for suffix in ["卫视", "卫视频道"]):
            return True
    return False

def get_channel_subgroup(channel_name: str) -> str:
    if DIGITAL_SORT_ENABLE and RE_DIGITAL_NUMBER.match(channel_name):
        return GROUP_SECONDARY_DIGITAL
    if is_weishi_channel(channel_name):
        return GROUP_SECONDARY_WEISHI
    if FEATURE_SORT_ENABLE:
        for feature_type, keywords in FEATURE_TYPE_ORDER:
            if any(keyword in channel_name for keyword in keywords):
                return GROUP_SECONDARY_FEATURE
    if "CCTV" in channel_name or "央视" in channel_name or "中央" in channel_name:
        return GROUP_SECONDARY_CCTV
    for area in DIRECT_CITIES + PROVINCE_PINYIN_ORDER:
        if area in channel_name and not is_weishi_channel(channel_name):
            return GROUP_SECONDARY_LOCAL
    return GROUP_SECONDARY_OTHER

def select_best_sources(sources: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
    """核心优化：自动选择1个最优源+2个备用源，共3个源"""
    if not sources:
        return []
    # 1. 按响应时间升序排序（最快在前）
    sorted_sources = sorted(sources, key=lambda x: x[1])
    # 2. 自动选最优源（缓存源优先→速度优先→格式优先）
    best_sources = []
    if AUTO_SELECT_SOURCE:
        # 缓存源直接作为最优源
        cache_source = next((s for s in sorted_sources if s[1] == 0.0), None)
        if cache_source:
            best_sources.append(cache_source)
            # 从剩余源中选2个备用源
            remaining_sources = [s for s in sorted_sources if s != cache_source]
        else:
            # 无缓存源，按速度+格式选择最优源
            primary_source = sorted_sources[0]
            # 速度相近时优先选.m3u8格式
            if PREFER_M3U8 and len(sorted_sources) >= 2:
                first_speed = sorted_sources[0][1]
                second_speed = sorted_sources[1][1]
                if (second_speed - first_speed) <= SELECT_SPEED_THRESHOLD and RE_M3U8_SUFFIX.search(sorted_sources[1][0]):
                    primary_source = sorted_sources[1]
            best_sources.append(primary_source)
            # 从剩余源中选2个备用源（排除已选的最优源）
            remaining_sources = [s for s in sorted_sources if s[0] != primary_source[0]]
        # 选择2个备用源（按速度排序）
        backup_sources = remaining_sources[:TOTAL_SOURCES_PER_CHANNEL - 1
        ]
