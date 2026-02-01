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

# -------------------------- 全局配置（核心：取消过度过滤，适配所有数据源） --------------------------
# 1. 数据源配置（保留所有可用源，按优先级排序）
IPTV_SOURCE_URLS = [
    # 重点保障：kakaxi系列源
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    # 其他核心数据源
    "https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    "https://raw.githubusercontent.com/zwc456baby/iptv_alive/refs/heads/master/live.m3u"
]

# 仅保留可用的官方/合规源
OFFICIAL_SOURCES = {
    "CCTV1 综合（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225618/index.m3u8",
    "CCTV5 体育（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225622/index.m3u8",
    "CCTV13 新闻（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225630/index.m3u8",
    "湖南卫视（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225726/index.m3u8",
    "浙江卫视（可用）": "http://117.148.123.202:8080/PLTV/88888888/224/3221225730/index.m3u8",
    "咪咕体育高清（可用）": "https://hls.miguvideo.com/hls/main/0/0/1.m3u8"
}

# 2. 核心优化：取消过度过滤，适配所有数据源格式
TIMEOUT_VERIFY = 6.0  # 延长验证超时，适配慢响应源
TIMEOUT_FETCH = 20    # 延长抓取超时，适配海外/大体积源
MIN_VALID_CHANNELS = 1
MAX_THREADS_VERIFY_BASE = 150  # 增加验证线程，提升效率
MAX_THREADS_FETCH_BASE = 20    # 增加抓取线程，保障多数据源并行
MIN_DELAY = 0.02
MAX_DELAY = 0.08
DISABLE_SSL_VERIFY = True
BATCH_PROCESS_SIZE = 500  # 增大批处理容量

# 3. 输出与缓存配置（取消频道去重，确保所有源频道保留）
OUTPUT_FILE = "iptv_playlist_full.m3u8"
CACHE_FILE = "iptv_persist_cache.json"
TEMP_CACHE_SET = set()
CACHE_EXPIRE_HOURS = 24
REMOVE_DUPLICATE_CHANNELS = False  # 关闭频道去重（仅按URL去重，保留不同频道名）
REMOVE_LOCAL_URLS = True
ENABLE_EMOJI = False
CACHE_MAX_SIZE = 20000  # 大幅增大缓存，容纳所有数据源

# 4. 排序+分组配置（简化分组逻辑，避免归类错误）
CHANNEL_SORT_ENABLE = True
CCTV_SORT_ENABLE = True
WEISHI_SORT_ENABLE = True
LOCAL_SORT_ENABLE = True
FEATURE_SORT_ENABLE = True
DIGITAL_SORT_ENABLE = True
MANUAL_SOURCE_NUM = 5  # 增加备用源数量
OFFICIAL_SOURCE_PRIORITY = True

# 分组配置（按类型分组，不按数据源区分，避免遗漏）
GROUP_OFFICIAL = "官方可用源-央视/卫视/咪咕" if ENABLE_EMOJI else "官方可用源-央视/卫视/咪咕"
GROUP_CCTV = "央视频道-综合" if ENABLE_EMOJI else "央视频道-综合"
GROUP_WEISHI = "卫视频道-一线/地方" if ENABLE_EMOJI else "卫视频道-一线/地方"
GROUP_LOCAL = "地方频道-各省市区" if ENABLE_EMOJI else "地方频道-各省市区"
GROUP_FEATURE = "特色频道-电影/体育/少儿/财经" if ENABLE_EMOJI else "特色频道-电影/体育/少儿/财经"
GROUP_DIGITAL = "数字频道-按数字排序" if ENABLE_EMOJI else "数字频道-按数字排序"
GROUP_OTHER = "其他频道-综合" if ENABLE_EMOJI else "其他频道-综合"

# 播放端配置
PLAYER_TITLE_PREFIX = True
PLAYER_TITLE_SHOW_SPEED = True
PLAYER_TITLE_SHOW_NUM = True
PLAYER_TITLE_SHOW_UPDATE = True
UPDATE_TIME_FORMAT_SHORT = "%m-%d %H:%M"
UPDATE_TIME_FORMAT_FULL = "%Y-%m-%d %H:%M:%S"
URL_TRUNCATE_DOMAIN = False  # 不截断URL，确保播放正常
URL_TRUNCATE_LENGTH = 150
SOURCE_NUM_PREFIX = "" if ENABLE_EMOJI else ""
SPEED_MARK_OFFICIAL = "官方" if ENABLE_EMOJI else "官方"
SPEED_MARK_CACHE = "缓存" if ENABLE_EMOJI else "缓存"
SPEED_MARK_1 = "极速" if ENABLE_EMOJI else "极速"
SPEED_MARK_2 = "快速" if ENABLE_EMOJI else "快速"
SPEED_MARK_3 = "普通" if ENABLE_EMOJI else "普通"
SPEED_LEVEL_1 = 100
SPEED_LEVEL_2 = 300

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
    ("电影", ["电影", "影院", "影视", "剧场"]),
    ("体育", ["体育", "赛事", "奥运", "足球", "篮球", "排球"]),
    ("少儿", ["少儿", "卡通", "动画", "宝贝", "动漫"]),
    ("财经", ["财经", "股市", "金融", "理财", "第一财经"]),
    ("新闻", ["新闻", "资讯", "时事"]),
    ("纪录片", ["纪录片", "纪实", "纪录"]),
    ("音乐", ["音乐", "歌曲", "MTV", "音乐现场"])
]
CCTV_BASE_ORDER = [
    "CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV5", "CCTV5+", "CCTV6", "CCTV7",
    "CCTV8", "CCTV9", "CCTV10", "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15",
    "CCTV16", "CCTV17", "CCTV4K", "CCTV8K"
]

# -------------------------- 底层优化：统一提取规则，适配所有数据源格式 --------------------------
# 兼容所有数据源的频道名提取正则（覆盖常见格式）
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+?)(?=\s*#|$)', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_EXTINF_FULL = re.compile(r'#EXTINF:-1\s*(?:tvg-id="[^"]*"\s*)?(?:tvg-name="[^"]*"\s*)?(?:group-title="[^"]*"\s*)?,([^#\n]+)', re.IGNORECASE)
RE_CCTV_CORE = re.compile(r'CCTV(\d+|5\+|4K|8K|新闻|少儿|音乐|体育|综合)', re.IGNORECASE)
RE_DIGITAL_NUMBER = re.compile(r'^(\d+)(频道|台|套)?$', re.IGNORECASE)
RE_OFFICIAL_DOMAIN = re.compile(r'(cmvideo|miguvideo|cctvdn|cctvnews)\.com', re.IGNORECASE)
RE_VALID_URL = re.compile(r'https?://.+?\.(m3u8|ts|flv|rtmp|rtsp)', re.IGNORECASE)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}
VALID_SUFFIX = {".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s", ".m3u"}
VALID_CONTENT_TYPE = {"video/", "application/x-mpegurl", "audio/", "application/octet-stream", "application/vnd.apple.mpegurl"}

# 全局变量
GLOBAL_UPDATE_TIME_FULL = datetime.now().strftime(UPDATE_TIME_FORMAT_FULL)
GLOBAL_UPDATE_TIME_SHORT = datetime.now().strftime(UPDATE_TIME_FORMAT_SHORT)
CPU_CORES = multiprocessing.cpu_count()
MAX_THREADS_VERIFY = min(MAX_THREADS_VERIFY_BASE, CPU_CORES * 15)
MAX_THREADS_FETCH = min(MAX_THREADS_FETCH_BASE, CPU_CORES * 10)
channel_sources_map = dict()
verified_urls = set()
task_list = list()
all_lines = list()
total_time = 0.0
# 记录各数据源的URL，用于统计
SOURCE_STAT = {url: {"fetch_lines": 0, "success_channels": 0} for url in IPTV_SOURCE_URLS}

# -------------------------- 日志初始化 --------------------------
def init_logger():
    logger = logging.getLogger("IPTV_Spider")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    ch.setFormatter(ch_fmt)
    fh = logging.FileHandler("iptv_spider_full.log", encoding="utf-8", mode="a")
    fh.setLevel(logging.DEBUG)
    fh_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fh_fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger

logger = init_logger()

# -------------------------- Session初始化（适配所有数据源反爬） --------------------------
def init_global_session():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=200,
        pool_maxsize=400,
        max_retries=5,
        pool_block=False
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # 通用请求头，适配所有数据源
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache"
    })
    if DISABLE_SSL_VERIFY:
        session.verify = False
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    return session

GLOBAL_SESSION = init_global_session()

# -------------------------- 工具函数（核心：统一提取规则，适配所有数据源） --------------------------
def add_random_delay():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

def filter_invalid_urls(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    if REMOVE_LOCAL_URLS:
        for host in LOCAL_HOSTS:
            if host in url.lower():
                return False
    # 仅过滤重复URL，不过滤任何有效链接
    if url in TEMP_CACHE_SET:
        return True
    TEMP_CACHE_SET.add(url)
    return True

def is_official_source(url: str) -> bool:
    return bool(RE_OFFICIAL_DOMAIN.search(url))

# 核心优化：统一频道名提取规则，覆盖所有数据源格式
def safe_extract_channel_name(line: str) -> Optional[str]:
    if not line.startswith("#EXTINF:"):
        return None
    # 顺序：tvg-name → 完整EXTINF匹配 → 逗号后内容 → 标题 → 兜底
    match = RE_TVG_NAME.search(line) or RE_EXTINF_FULL.search(line) or RE_CHANNEL_NAME.search(line) or RE_TITLE_NAME.search(line)
    if match:
        name = match.group(1).strip()
        # 过滤无效频道名
        if name and not name.isdigit() and len(name) <= 50:
            return name
    return "未知频道"

# 简化分组逻辑，避免归类错误（所有数据源统一按内容分组）
def get_channel_subgroup(channel_name: str) -> str:
    if channel_name in OFFICIAL_SOURCES:
        return GROUP_OFFICIAL
    if RE_CCTV_CORE.search(channel_name) or "央视" in channel_name or "中央" in channel_name:
        return GROUP_CCTV
    if "卫视" in channel_name:
        return GROUP_WEISHI
    if DIGITAL_SORT_ENABLE and RE_DIGITAL_NUMBER.match(channel_name):
        return GROUP_DIGITAL
    if FEATURE_SORT_ENABLE:
        for feature_type, keywords in FEATURE_TYPE_ORDER:
            if any(keyword in channel_name for keyword in keywords):
                return GROUP_FEATURE
    for area in DIRECT_CITIES + PROVINCE_PINYIN_ORDER:
        if area in channel_name and "卫视" not in channel_name and "央视" not in channel_name:
            return GROUP_LOCAL
    return GROUP_OTHER

# -------------------------- 排序函数（适配所有频道类型） --------------------------
def get_cctv_sort_key(channel_name: str) -> Tuple[int, str]:
    if not CCTV_SORT_ENABLE:
        return (999, channel_name.upper())
    match = RE_CCTV_CORE.search(channel_name.upper())
    if not match:
        return (999, channel_name.upper())
    cctv_core = match.group(0).upper()
    cctv_core = f"CCTV{cctv_core.replace('CCTV', '')}"
    cctv_core = re.sub(r'（.*）|（.*）', '', cctv_core)
    main_key = CCTV_BASE_ORDER.index(cctv_core) if cctv_core in CCTV_BASE_ORDER else len(CCTV_BASE_ORDER)
    suffix_priority = {"8K": 0, "4K": 1, "超清": 2, "高清": 3, "标清": 4}
    sub_key = 99
    for suffix, pri in suffix_priority.items():
        if suffix in channel_name:
            sub_key = pri
            break
    return (main_key,
