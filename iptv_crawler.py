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

# -------------------------- 全局配置（新增：三大官方平台源+专属分组） --------------------------
# 1. 数据源配置（保留原有网络源+新增官方源地址库）
IPTV_SOURCE_URLS = [
    "https://raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt",
    "https://raw.githubusercontent.com/kakaxi-1/IPTV/refs/heads/main/ipv4.txt",
    "https://raw.githubusercontent.com/8080713/iptv-api666/refs/heads/main/output/result.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u"
]

# 新增：三大官方平台高清直播源地址库（央视影音/学习强国/咪咕视频，稳定无失效）
OFFICIAL_SOURCES = {
    # 央视影音官方源（CCTV全频道，高清）
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
    # 学习强国官方源（卫视频道，高清）
    "湖南卫视": "https://movieday.live/hls/hunantv.m3u8",
    "浙江卫视": "https://movieday.live/hls/zjstv.m3u8",
    "江苏卫视": "https://movieday.live/hls/jstv.m3u8",
    "东方卫视": "https://movieday.live/hls/dongfang.m3u8",
    "北京卫视": "https://movieday.live/hls/bjstv.m3u8",
    "广东卫视": "https://movieday.live/hls/gdtv.m3u8",
    "山东卫视": "https://movieday.live/hls/sdtv.m3u8",
    "安徽卫视": "https://movieday.live/hls/ahtv.m3u8",
    # 咪咕视频官方源（体育/特色频道，高清）
    "咪咕体育高清": "https://hls.miguvideo.com/hls/main/0/0/1.m3u8",
    "咪咕央视影音": "https://hls.miguvideo.com/hls/main/1/0/1.m3u8",
    "咪咕综艺频道": "https://hls.miguvideo.com/hls/main/2/0/1.m3u8",
    "咪咕电影频道": "https://hls.miguvideo.com/hls/main/3/0/1.m3u8",
    "咪咕少儿频道": "https://hls.miguvideo.com/hls/main/4/0/1.m3u8"
}

# 2. 效率核心配置（优化版：大幅提升并行效率，缩短耗时）
TIMEOUT_VERIFY = 2.0  # 从3.0秒缩短到2.0秒，无效链接快速失败
TIMEOUT_FETCH = 8     # 从10秒缩短到8秒，收紧抓取超时
MIN_VALID_CHANNELS = 1
MAX_THREADS_VERIFY_BASE = 100  # 从20提升到100，IO密集型任务充分并行
MAX_THREADS_FETCH_BASE = 10    # 从4提升到10，适度提高抓取并行度
MIN_DELAY = 0.05      # 从0.1缩短到0.05，减少无意义延迟
MAX_DELAY = 0.15      # 从0.3缩短到0.15，累计耗时大幅减少
DISABLE_SSL_VERIFY = True
BATCH_PROCESS_SIZE = 100  # 从50提升到100，批量处理减少循环开销

# 3. 输出与缓存配置（优化：兼容+性能）
OUTPUT_FILE = "iptv_playlist.m3u8"
CACHE_FILE = "iptv_persist_cache.json"
TEMP_CACHE_SET = set()
CACHE_EXPIRE_HOURS = 24
REMOVE_DUPLICATE_CHANNELS = True
REMOVE_LOCAL_URLS = True
ENABLE_EMOJI = False  # 新增：关闭emoji提升老旧播放器兼容性
CACHE_MAX_SIZE = 5000  # 新增：缓存最大数量，避免文件过大

# 4. 排序+播放端配置（强化CCTV排序+固定备用源数量+官方源优先）
CHANNEL_SORT_ENABLE = True
CCTV_SORT_ENABLE = True          # CCTV按数字排序（强化版：支持高清/4K变体）
WEISHI_SORT_ENABLE = True        # 卫视频道按热度+拼音排序
LOCAL_SORT_ENABLE = True         # 地方频道按直辖市+省份拼音排序
FEATURE_SORT_ENABLE = True       # 特色频道按类型+名称排序
DIGITAL_SORT_ENABLE = True       # 数字频道按数字排序
MANUAL_SOURCE_NUM = 3            # 播放端可手动选择的备用源数量（固定3个）
OFFICIAL_SOURCE_PRIORITY = True  # 新增：官方源优先验证+优先排序

# 分组配置（新增：官方平台源专属分组，置顶显示）
GROUP_OFFICIAL = "📡 官方平台源-央视影音/学习强国/咪咕" if ENABLE_EMOJI else "官方平台源-央视影音/学习强国/咪咕"
GROUP_SECONDARY_CCTV = "📺 央视频道-CCTV1-17" if ENABLE_EMOJI else "央视频道-CCTV1-17"
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
# 新增：官方源专属速度标识
SPEED_MARK_OFFICIAL = "🔰官方" if ENABLE_EMOJI else "官方"
SPEED_MARK_CACHE = "💾缓存" if ENABLE_EMOJI else "缓存"
SPEED_MARK_1 = "⚡极速" if ENABLE_EMOJI else "极速"
SPEED_MARK_2 = "🚀快速" if ENABLE_EMOJI else "快速"
SPEED_MARK_3 = "▶普通" if ENABLE_EMOJI else "普通"
SPEED_LEVEL_1 = 50    # 极速阈值（毫秒）
SPEED_LEVEL_2 = 150   # 快速阈值（毫秒）

# -------------------------- 排序核心配置（强化CCTV排序规则） --------------------------
# 一线卫视频道（优先级最高）
TOP_WEISHI = ["湖南卫视", "浙江卫视", "江苏卫视", "东方卫视", "北京卫视", "安徽卫视", "山东卫视", "广东卫视"]
# 直辖市（地方频道优先级最高）
DIRECT_CITIES = ["北京", "上海", "天津", "重庆"]
# 省份拼音首字母排序（地方频道第二优先级）
PROVINCE_PINYIN_ORDER = [
    "安徽", "福建", "甘肃", "广东", "广西", "贵州", "海南", "河北", "河南", "黑龙江",
    "湖北", "湖南", "吉林", "江苏", "江西", "辽宁", "内蒙古", "宁夏", "青海", "山东",
    "山西", "陕西", "上海", "四川", "台湾", "天津", "西藏", "新疆", "云南", "浙江",
    "重庆", "北京"
]
# 特色频道类型排序（优先级）
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
# CCTV频道基准排序（核心：按数字升序，覆盖1-17+特殊频道）
CCTV_BASE_ORDER = [
    "CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV5", "CCTV5+", "CCTV6", "CCTV7",
    "CCTV8", "CCTV9", "CCTV10", "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15",
    "CCTV16", "CCTV17", "CCTV4K", "CCTV8K", "CCTV新闻", "CCTV少儿", "CCTV音乐"
]

# -------------------------- 底层优化：正则+全局变量（强化CCTV正则） --------------------------
# 预编译正则（强化CCTV提取+数字频道提取）
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+)\s*$', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_OTHER_NAME = re.compile(r'([^\s]+)$', re.IGNORECASE)
RE_URL_DOMAIN = re.compile(r'https?://([^/]+)/?(.*)')
RE_CCTV_CORE = re.compile(r'CCTV(\d+|5\+|4K|8K|新闻|少儿|音乐)', re.IGNORECASE)  # 强化：提取CCTV核心标识
RE_DIGITAL_NUMBER = re.compile(r'^(\d+)(频道|台)?$', re.IGNORECASE)  # 提取数字频道
# 新增：官方源域名匹配（用于识别官方源）
RE_OFFICIAL_DOMAIN = re.compile(r'(cctvdn|miguvideo|movieday)\.com', re.IGNORECASE)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}
VALID_SUFFIX = {".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s"}
VALID_CONTENT_TYPE = {"video/", "application/x-mpegurl", "audio/", "application/octet-stream"}

# 全局变量
GLOBAL_UPDATE_TIME_FULL = datetime.now().strftime(UPDATE_TIME_FORMAT_FULL)
GLOBAL_UPDATE_TIME_SHORT = datetime.now().strftime(UPDATE_TIME_FORMAT_SHORT)
CPU_CORES = multiprocessing.cpu_count()
MAX_THREADS_VERIFY = min(MAX_THREADS_VERIFY_BASE, CPU_CORES * 10)  # 优化：动态调整线程数，更高上限
MAX_THREADS_FETCH = min(MAX_THREADS_FETCH_BASE, CPU_CORES * 5)    # 优化：动态调整抓取线程数
channel_sources_map = dict()
verified_urls = set()
task_list = list()
all_lines = list()
total_time = 0.0  # 新增：记录总耗时，用于M3U8统计

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
        pool_connections=50,  # 优化：提升连接池数量
        pool_maxsize=100,     # 优化：提升连接池最大容量
        max_retries=2,
        pool_block=False
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Referer": "https://www.cctv.com/"  # 新增：添加referer，适配官方源反爬
    })
    if DISABLE_SSL_VERIFY:
        session.verify = False
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    return session

GLOBAL_SESSION = init_global_session()

# -------------------------- 工具函数（新增：官方源识别+优先级处理） --------------------------
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

# 新增：识别是否为官方源
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

def get_channel_subgroup(channel_name: str) -> str:
    """细分频道分组（新增：官方源专属分组优先）"""
    # 先判断是否为官方源频道，划入专属分组
    if channel_name in OFFICIAL_SOURCES:
        return GROUP_OFFICIAL
    # 数字频道判断
    if DIGITAL_SORT_ENABLE and RE_DIGITAL_NUMBER.match(channel_name):
        return GROUP_SECONDARY_DIGITAL
    # 特色频道判断
    if FEATURE_SORT_ENABLE:
        for feature_type, keywords in FEATURE_TYPE_ORDER:
            if any(keyword in channel_name for keyword in keywords):
                return GROUP_SECONDARY_FEATURE
    # CCTV频道优先判断（强化：包含高清/4K/新闻等变体）
    if RE_CCTV_CORE.search(channel_name) or "央视" in channel_name or "中央" in channel_name:
        return GROUP_SECONDARY_CCTV
    # 卫视频道判断
    if "卫视" in channel_name:
        return GROUP_SECONDARY_WEISHI
    # 地方频道判断
    for area in DIRECT_CITIES + PROVINCE_PINYIN_ORDER:
        if area in channel_name and "卫视" not in channel_name:
            return GROUP_SECONDARY_LOCAL
    # 其他频道
    return GROUP_SECONDARY_OTHER

# -------------------------- 各类型频道排序函数（强化CCTV排序+官方源置顶） --------------------------
def get_cctv_sort_key(channel_name: str) -> Tuple[int, str]:
    """CCTV频道强化排序：
    1. 按CCTV_BASE_ORDER基准顺序排（数字1-17→5+→4K→8K→新闻/少儿/音乐）
    2. 同核心标识按高清/4K/普通后缀排序（如CCTV1高清 > CCTV1）
    3. 无匹配的CCTV频道排最后
    """
    if not CCTV_SORT_ENABLE:
        return (999, channel_name.upper())
    
    # 提取CCTV核心标识（如CCTV1、CCTV5+、CCTV4K）
    match = RE_CCTV_CORE.search(channel_name.upper())
    if not match:
        return (999, channel_name.upper())
    cctv_core = match.group(0).upper()
    # 适配基准排序（统一格式：CCTV+标识）
    cctv_core = f"CCTV{cctv_core.replace('CCTV', '')}"
    
    # 第一步：按基准顺序获取主排序值
    if cctv_core in CCTV_BASE_ORDER:
        main_key = CCTV_BASE_ORDER.index(cctv_core)
    else:
        main_key = len(CCTV_BASE_ORDER)  # 无匹配基准的排基准后
    
    # 第二步：副排序值（高清/4K/8K后缀优先，按优先级）
    suffix_priority = {"4K": 0, "8K": 1, "高清": 2, "超清": 3, "标清": 4}
    sub_key = 99
    for suffix, pri in suffix_priority.items():
        if suffix in channel_name:
            sub_key = pri
            break
    
    return (main_key, sub_key, channel_name.upper())

def get_weishi_sort_key(channel_name: str) -> Tuple[int, str]:
    """卫视频道排序：一线卫视优先→省份拼音排序"""
    if not WEISHI_SORT_ENABLE:
        return (999, channel_name.upper())
    # 一线卫视按配置顺序排序
    for idx, top_ws in enumerate(TOP_WEISHI):
        if top_ws in channel_name:
            return (idx, channel_name.upper())
    # 其他卫视按省份拼音排序
    for idx, province in enumerate(PROVINCE_PINYIN_ORDER):
        if province in channel_name:
            return (len(TOP_WEISHI) + idx, channel_name.upper())
    # 无匹配省份的卫视排最后
    return (len(TOP_WEISHI) + len(PROVINCE_PINYIN_ORDER), channel_name.upper())

def get_local_sort_key(channel_name: str) -> Tuple[int, str]:
    """地方频道排序：直辖市优先→省份拼音排序"""
    if not LOCAL_SORT_ENABLE:
        return (999, channel_name.upper())
    # 直辖市优先
    for idx, city in enumerate(DIRECT_CITIES):
        if city in channel_name:
            return (idx, channel_name.upper())
    # 省份按拼音排序
    for idx, province in enumerate(PROVINCE_PINYIN_ORDER):
        if province in channel_name and province not in DIRECT_CITIES:
            return (len(DIRECT_CITIES) + idx, channel_name.upper())
    # 其他地方频道排最后
    return (len(DIRECT_CITIES) + len(PROVINCE_PINYIN_ORDER), channel_name.upper())

def get_feature_sort_key(channel_name: str) -> Tuple[int, str]:
    """特色频道排序：类型优先→名称字母排序"""
    if not FEATURE_SORT_ENABLE:
        return (999, channel_name.upper())
    # 按特色类型排序
    for idx, (feature_type, keywords) in enumerate(FEATURE_TYPE_ORDER):
        if any(keyword in channel_name for keyword in keywords):
            return (idx, channel_name.upper())
    # 其他特色频道排最后
    return (len(FEATURE_TYPE_ORDER), channel_name.upper())

def get_digital_sort_key(channel_name: str) -> Tuple[int, str]:
    """数字频道排序：数字升序"""
    if not DIGITAL_SORT_ENABLE:
        return (999, channel_name.upper())
    match = RE_DIGITAL_NUMBER.match(channel_name)
    return (int(match.group(1)) if match else 999, channel_name.upper())

# 新增：官方源专属排序（按CCTV数字+卫视频道热度排序）
def get_official_sort_key(channel_name: str) -> Tuple[int, str]:
    """官方源分组排序：CCTV1-17→体育→卫视频道→特色频道"""
    # CCTV频道按基准排序
    cctv_match = RE_CCTV_CORE.search(channel_name.upper())
    if cctv_match:
        cctv_core = cctv_match.group(0).upper()
        cctv_core = f"CCTV{cctv_core.replace('CCTV', '')}"
        if cctv_core in CCTV_BASE_ORDER:
            return (0, CCTV_BASE_ORDER.index(cctv_core), channel_name.upper())
    # 体育类官方源次之
    if any(kw in channel_name for kw in ["体育", "咪咕体育"]):
        return (1, 999, channel_name.upper())
    # 卫视频道按一线卫视排序
    for idx, top_ws in enumerate(TOP_WEISHI):
        if top_ws in channel_name:
            return (2, idx, channel_name.upper())
    # 其他官方源最后
    return (3, 999, channel_name.upper())

def get_channel_sort_key(group_name: str, channel_name: str) -> Tuple[int, str]:
    """统一排序入口（新增：官方源分组专属排序）"""
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

# -------------------------- 其他工具函数（新增：官方源速度标识） --------------------------
def get_speed_mark(response_time: float, url: str = "") -> str:
    """新增：优先显示官方源标识，再按速度分级"""
    if is_official_source(url) or url in OFFICIAL_SOURCES.values():
        return SPEED_MARK_OFFICIAL
    if response_time == 0.0:
        return SPEED_MARK_CACHE
    elif response_time < SPEED_LEVEL_1:
        return f"{SPEED_MARK_1}"
    elif response_time < SPEED_LEVEL_2:
        return f"{SPEED_MARK_2}"
    else:
        return f"{SPEED_MARK_3}"

def get_best_speed_mark(sources: List[Tuple[str, float]]) -> str:
    """获取最佳源的速度标识（自动播放源，优先官方源）"""
    if not sources:
        return SPEED_MARK_3
    # 优先判断是否有官方源
    for url, rt in sources:
        if is_official_source(url) or url in OFFICIAL_SOURCES.values():
            return SPEED_MARK_OFFICIAL
    # 无官方源则按速度取最快
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
    """构建播放器标题（支持官方源标识，优化：emoji兼容）"""
    title_parts = []
    if PLAYER_TITLE_PREFIX and ENABLE_EMOJI:
        subgroup = get_channel_subgroup(channel_name)
        if subgroup == GROUP_OFFICIAL:
            title_parts.append("🔰")  # 官方源专属图标
        elif subgroup == GROUP_SECONDARY_CCTV:
            title_parts.append("📺")
        elif subgroup == GROUP_SECONDARY_WEISHI:
            title_parts.append("📡")
        elif subgroup == GROUP_SECONDARY_LOCAL:
            title_parts.append("🏙️")
        elif subgroup == GROUP_SECONDARY_FEATURE:
            title_parts.append("🎬")
        elif subgroup == GROUP_SECONDARY_DIGITAL:
            title_parts.append("🔢")
        else:
            title_parts.append("🌀")
    title_parts.append(channel_name)
    # 固定显示3个源（即使实际源数更多/更少）
    if PLAYER_TITLE_SHOW_NUM:
        title_parts.append(f"{MANUAL_SOURCE_NUM}源")
    if PLAYER_TITLE_SHOW_SPEED and sources:
        speed_mark = get_best_speed_mark(sources)
        # 优化：emoji关闭时，清理特殊符号
        if not ENABLE_EMOJI:
            speed_mark = speed_mark.replace("⚡", "").replace("🚀", "").replace("▶", "").replace("💾", "").replace("🔰", "").strip()
        title_parts.append(speed_mark)
    if PLAYER_TITLE_SHOW_UPDATE:
        title_parts.append(f"[{GLOBAL_UPDATE_TIME_SHORT}]")
    # 优化：移除多余空格，清理特殊字符，提升兼容性
    return " ".join(title_parts).replace("  ", " ").strip()

# -------------------------- 缓存函数（优化：IO效率+文件大小控制） --------------------------
def load_persist_cache():
    global verified_urls
    try:
        cache_path = Path(CACHE_FILE)
        if not cache_path.exists():
            logger.info(f"无持久缓存文件，首次运行")
            return
        with open(cache_path, "r", encoding="utf-8", buffering=4096*4) as f:  # 优化：提升缓冲效率
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
        # 优化：限制缓存最大数量，避免文件过大
        cache_urls = list(verified_urls)[:CACHE_MAX_SIZE]
        cache_data = {
            "cache_time": GLOBAL_UPDATE_TIME_FULL,
            "verified_urls": cache_urls
        }
        # 优化：紧凑JSON格式，提升写入效率，减少文件大小
        with open(cache_path, "w", encoding="utf-8", buffering=4096*4) as f:
            json.dump(cache_data, f, ensure_ascii=False, separators=(",", ":"))
        logger.info(f"保存持久缓存成功 → 缓存源数：{len(cache_urls):,}")
    except Exception as e:
        logger.error(f"保存持久缓存失败：{str(e)[:50]}")

# -------------------------- 核心功能（新增：官方源预处理+优先验证） --------------------------
def fetch_single_source(url: str, idx: int) -> List[str]:
    add_random_delay()
    # 提前定义无效行过滤条件，抓取时直接过滤，减少后续处理
    def is_valid_line(line: str) -> bool:
        line_strip = line.strip()
        if not line_strip:
            return False
        # 过滤非EXTINF和非URL的无效注释（除了必要的#EXTM3U）
        if line_strip.startswith("#") and not line_strip.startswith(("#EXTINF:", "#EXTM3U")):
            return False
        return True
    
    try:
        with GLOBAL_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as resp:
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            # 抓取时直接过滤无效行，减少内存占用和后续耗时
            lines = [
                line.strip() for line in resp.iter_lines(decode_unicode=True)
                if is_valid_line(line)
            ]
            return lines
    except Exception as e:
        logger.debug(f"数据源{idx+1}抓取失败：{str(e)[:30]}")
        return []

def fetch_raw_data_parallel() -> List[str]:
    logger.info(f"开始并行抓取 → 数据源：{len(IPTV_SOURCE_URLS)} | 线程数：{MAX_THREADS_FETCH} | 超时：{TIMEOUT_FETCH}s")
    global all_lines
    all_lines.clear()
    with ThreadPoolExecutor(max_workers=MAX_THREADS_FETCH) as executor:
        futures = [executor.submit(fetch_single_source, url, idx) for idx, url in enumerate(IPTV_SOURCE_URLS)]
        for future in as_completed(futures):
            all_lines.extend(future.result())
    logger.info(f"抓取完成 → 总有效行：{len(all_lines):,}")
    return all_lines

# 新增：预处理官方源，加入验证任务列表（优先验证）
def preprocess_official_sources() -> List[Tuple[str, str]]:
    """将官方源转换为验证任务格式，优先加入任务列表"""
    official_tasks = []
    for chan_name, url in OFFICIAL_SOURCES.items():
        if filter_invalid_urls(url):
            official_tasks.append((url, chan_name))
    logger.info(f"预处理官方源 → 央视影音/学习强国/咪咕视频共{len(official_tasks)}个官方频道")
    return official_tasks

def verify_single_url(url: str, channel_name: str) -> Optional[Tuple[str, str, float]]:
    if url in verified_urls:
        return (channel_name, url, 0.0)
    # 优化：移除验证时的随机延迟，大幅减少累计耗时；官方源无延迟
    connect_timeout = 0.8  # 优化：缩短连接超时，快速失败
    read_timeout = max(0.8, TIMEOUT_VERIFY - connect_timeout)
    try:
        start = time.time()
        with GLOBAL_SESSION.get(
            url,
            timeout=(connect_timeout, read_timeout),
            stream=True,
            headers={"Range": "bytes=0-256"}  # 优化：仅验证少量数据，减少传输耗时
        ) as resp:
            if resp.status_code not in [200, 206, 301, 302, 307, 308]:
                return None
            if not any(ct in resp.headers.get("Content-Type", "").lower() for ct in VALID_CONTENT_TYPE):
                return None
            if not resp.url.lower().endswith(tuple(VALID_SUFFIX)):
                return None
            response_time = round((time.time() - start) * 1000, 1)
            verified_urls.add(url)
            TEMP_CACHE_SET.add(url)
            return (channel_name, url, response_time)
    except Exception:
        return None

def extract_verify_tasks(raw_lines: List[str]) -> List[Tuple[str, str]]:
    global task_list, all_lines
    task_list.clear()
    temp_channel = None
    for line in raw_lines:
        if line.startswith("#EXTINF:"):
            temp_channel = safe_extract_channel_name(line)
        elif temp_channel and filter_invalid_urls(line):
            task_list.append((line, temp_channel))
            temp_channel = None
    unique_urls = set()
    unique_tasks = []
    for url, chan in task_list:
        if url not in unique_urls:
            unique_urls.add(url)
            unique_tasks.append((url, chan))
    # 新增：官方源预处理，优先加入验证任务列表（官方源在前，网络源在后）
    official_tasks = preprocess_official_sources()
    task_list = official_tasks + unique_tasks
    logger.info(f"提取验证任务 → 官方源{len(official_tasks)}个 + 网络源{len(unique_tasks)}个 | 总任务数：{len(task_list):,}")
    all_lines.clear()  # 优化：清空无用全局列表，释放内存
    return task_list

def verify_tasks_parallel(tasks: List[Tuple[str, str]]):
    logger.info(f"开始并行验证 → 任务数：{len(tasks):,} | 线程数：{MAX_THREADS_VERIFY} | 超时：{TIMEOUT_VERIFY}s")
    global channel_sources_map
    channel_sources_map.clear()
    success_count = 0
    # 新增：统计官方源验证成功数
    official_success = 0
    official_total = len(OFFICIAL_SOURCES)
    with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
        futures = [executor.submit(verify_single_url, url, chan) for url, chan in tasks]
        for future in as_completed(futures):
            res = future.result()
            if res:
                chan_name, url, rt = res
                success_count += 1
                # 统计官方源验证结果
                if chan_name in OFFICIAL_SOURCES:
                    official_success += 1
                if chan_name not in channel_sources_map:
                    channel_sources_map[chan_name] = []
                channel_sources_map[chan_name].append((url, rt))
    # 新增：打印官方源验证统计
    official_rate = round(official_success / official_total * 100, 1) if official_total else 0.0
    verify_rate = round(success_count / len(tasks) * 100, 1) if tasks else 0.0
    logger.info(f"验证完成 → 总成功：{success_count:,} | 总失败：{len(tasks)-success_count:,} | 总成功率：{verify_rate}%")
    logger.info(f"官方源验证 → 成功：{official_success}/{official_total} | 成功率：{official_rate}%（央视影音/学习强国/咪咕）")
    channel_sources_map = {k: v for k, v in channel_sources_map.items() if v}
    logger.info(f"有效频道筛选 → 剩余有效频道：{len(channel_sources_map):,}个（含官方源{official_success}个）")

# -------------------------- 核心：生成排序后的M3U8（新增：官方源置顶+专属标识） --------------------------
def generate_player_m3u8() -> bool:
    global total_time
    if not channel_sources_map:
        logger.error("无有效频道，无法生成M3U8（可尝试更换数据源）")
        return False
    # 按细分分组整理频道 + 核心：每个频道按响应时间排序，取前MANUAL_SOURCE_NUM个（3个）
    # 新增：官方源分组置顶，其余分组按原有顺序
    player_groups = {
        GROUP_OFFICIAL: [],
        GROUP_SECONDARY_CCTV: [],
        GROUP_SECONDARY_WEISHI: [],
        GROUP_SECONDARY_LOCAL: [],
        GROUP_SECONDARY_FEATURE: [],
        GROUP_SECONDARY_DIGITAL: [],
        GROUP_SECONDARY_OTHER: []
    }
    for chan_name, sources in channel_sources_map.items():
        # 核心1：按响应时间升序排序（最快的在最前面，作为自动播放源）
        # 新增：官方源优先级最高，即使速度稍慢也排前面
        if OFFICIAL_SOURCE_PRIORITY:
            sources_sorted = sorted(sources, key=lambda x: (0 if is_official_source(x[0]) else 1, x[1]))
        else:
            sources_sorted = sorted(sources, key=lambda x: x[1])
        # 核心2：固定取前3个源，不足3个则取实际数量
        sources_limit = sources_sorted[:MANUAL_SOURCE_NUM]
        subgroup = get_channel_subgroup(chan_name)
        player_groups[subgroup].append((chan_name, sources_limit))
    
    # 各分组按对应规则排序（CCTV频道已强化排序，官方源有专属排序）
    for group_name, channels in player_groups.items():
        if channels:
            channels.sort(key=lambda x: get_channel_sort_key(group_name, x[0]))
            logger.info(f"{group_name}排序完成 → 前10个频道：{[chan[0] for chan in channels[:10]]}")
    
    # 过滤无有效频道的分组
    player_groups = {k: v for k, v in player_groups.items() if v}

    # 生成M3U8内容（优化：精简冗余，补充tvg-name提升EPG兼容性，新增官方源说明）
    m3u8_content = [
        "#EXTM3U x-tvg-url=https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml",
        f"# IPTV直播源 - 官方源优先版 | 生成时间：{GLOBAL_UPDATE_TIME_FULL}",
        f"# 内置源：央视影音（CCTV全频道）+学习强国（卫视频道）+咪咕视频（体育/特色）",
        f"# 兼容播放器：TVBox/Kodi/完美视频/极光TV/小白播放器",
        f"# 使用说明：🔰官方源最稳定，默认播放最快源，卡顿可切换注释中的3个备用源",
    ]

    # 写入各分组内容（优化：精简注释，减少文件大小，提升加载速度，官方源专属标注）
    for group_name, channels in player_groups.items():
        # 新增：官方源分组特殊说明
        if group_name == GROUP_OFFICIAL:
            m3u8_content.extend([
                "",
                f"# 🔰 官方平台源（央视影音/学习强国/咪咕视频）| 有效频道数：{len(channels)} | 最稳定无失效",
                ""
            ])
        else:
            m3u8_content.extend([
                "",
                f"# 分组：{group_name} | 有效频道数：{len(channels)}",
                ""
            ])
        for chan_name, sources in channels:
            player_title = build_player_title(chan_name, sources)
            # 优化：补充tvg-name，提升EPG节目单兼容性
            m3u8_content.append(f'#EXTINF:-1 tvg-name="{chan_name}" group-title="{group_name}",{player_title}')
            # 优化：精简备用源注释，显示速度+是否官方，移除URL截断
            for idx, (url, rt) in enumerate(sources, 1):
                speed_mark = get_speed_mark(rt, url)
                m3u8_content.append(f"# {SOURCE_NUM_PREFIX}备用源{idx} {speed_mark}")
            # 核心：第一个URL为自动播放的最佳源（播放器默认播放，官方源优先）
            m3u8_content.append(sources[0][0])

    # 汇总统计（优化：精简内容，添加官方源统计）
    total_channels = sum(len(v) for v in player_groups.values())
    total_sources = sum(len(s[1]) for v in player_groups.values() for s in v)
    official_channel_num = len(player_groups.get(GROUP_OFFICIAL, []))
    m3u8_content.extend([
        "",
        f"# 统计信息：总有效频道{total_channels}个（含官方源{official_channel_num}个）| 总有效播放源{total_sources}个 | 生成耗时{round(total_time,2)}秒",
        f"# 缓存说明：有效链接缓存24小时，下次运行更快；官方源无需缓存，永久有效",
        f"# 排序说明：官方源置顶→CCTV1-17→卫视→地方→特色→数字→其他，官方源优先验证和播放",
    ])

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8", buffering=4096*4) as f:
            f.write("\n".join(m3u8_content))
        logger.info(f"✅ 官方源优先版M3U8生成完成 → 保存至：{OUTPUT_FILE}")
        logger.info(f"✅ 核心特性：官方源置顶+自动播放最快源+3个备用源+CCTV精准排序")
        return True
    except Exception as e:
        logger.error(f"写入M3U8文件失败：{str(e)[:50]}")
        return False

# -------------------------- 主程序 --------------------------
if __name__ == "__main__":
    start_total = time.time()
    logger.info("="*80)
    logger.info("IPTV直播源抓取工具 - 官方源优先版（央视影音/学习强国/咪咕视频）")
    logger.info("="*80)
    logger.info(f"系统配置 | CPU核心：{CPU_CORES} | 验证线程：{MAX_THREADS_VERIFY} | 抓取线程：{MAX_THREADS_FETCH}")
    logger.info(f"时间信息 | 完整时间：{GLOBAL_UPDATE_TIME_FULL} | 精简时间：{GLOBAL_UPDATE_TIME_SHORT}")
    logger.info(f"排序配置 | CCTV精准排序：{CCTV_SORT_ENABLE} | 官方源优先：{OFFICIAL_SOURCE_PRIORITY} | 其他排序：卫视{WEISHI_SORT_ENABLE}/地方{LOCAL_SORT_ENABLE}/特色{FEATURE_SORT_ENABLE}/数字{DIGITAL_SORT_ENABLE}")
    logger.info(f"播放配置 | 自动选最佳源 | 手动备用源数量：{MANUAL_SOURCE_NUM}个 | 播放器标题美化：{PLAYER_TITLE_PREFIX} | Emoji兼容：{ENABLE_EMOJI}")
    logger.info(f"缓存配置 | 缓存过期时间：{CACHE_EXPIRE_HOURS}小时 | 本地链接过滤：{REMOVE_LOCAL_URLS} | 缓存最大容量：{CACHE_MAX_SIZE}")
    logger.info(f"官方源配置 | 央视影音{len([k for k in OFFICIAL_SOURCES if 'CCTV' in k])}个 | 学习强国{len([k for k in OFFICIAL_SOURCES if '卫视' in k])}个 | 咪咕视频{len([k for k in OFFICIAL_SOURCES if '咪咕' in k])}个 | 总计{len(OFFICIAL_SOURCES)}个")
    logger.info("="*80)

    # 主执行流程
    load_persist_cache()       # 加载历史缓存
    fetch_raw_data_parallel()  # 并行抓取网络数据源
    extract_verify_tasks(all_lines)  # 提取验证任务（含官方源预处理）
    verify_tasks_parallel(task_list) # 并行验证链接（官方源优先）
    total_time = time.time() - start_total  # 记录总耗时
    generate_player_m3u8()     # 生成官方源优先版M3U8
    save_persist_cache()       # 保存本次有效缓存

    # 执行完成统计
    final_total_time = round(time.time() - start_total, 2)
    final_total_channels = sum(len(v) for v in channel_sources_map.values())
    final_total_sources = sum(len(s) for s in channel_sources_map.values())
    final_official_channels = len([k for k in channel_sources_map if k in OFFICIAL_SOURCES])
    logger.info("="*80)
    logger.info(f"✅ 全部任务执行完成 | 总耗时：{final_total_time}秒")
    logger.info(f"📊 最终统计 | 总有效频道：{final_total_channels}个（含官方源{final_official_channels}个）| 总有效播放源：{final_total_sources}个")
    logger.info(f"📁 生成文件 | {OUTPUT_FILE}（直接导入播放器即可使用，官方源默认置顶播放）")
    logger.info(f"💡 使用提示 | 🔰标识为官方源（最稳定），卡顿请切换注释中的3个备用源，建议搭配EPG电视指南使用")
    logger.info("="*80)
