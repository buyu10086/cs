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

# -------------------------- 全局配置（新增多类型排序开关） --------------------------
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

# 2. 效率核心配置
TIMEOUT_VERIFY = 3.0
TIMEOUT_FETCH = 10
MIN_VALID_CHANNELS = 1
MAX_THREADS_VERIFY_BASE = 20
MAX_THREADS_FETCH_BASE = 4
MIN_DELAY = 0.1
MAX_DELAY = 0.3
DISABLE_SSL_VERIFY = True
BATCH_PROCESS_SIZE = 50

# 3. 输出与缓存配置
OUTPUT_FILE = "iptv_playlist.m3u8"
CACHE_FILE = "iptv_persist_cache.json"
TEMP_CACHE_SET = set()
CACHE_EXPIRE_HOURS = 24
REMOVE_DUPLICATE_CHANNELS = True
REMOVE_LOCAL_URLS = True

# 4. 排序+播放端配置（新增多类型排序开关）
CHANNEL_SORT_ENABLE = True
CCTV_SORT_ENABLE = True          # CCTV按数字排序
WEISHI_SORT_ENABLE = True        # 卫视频道按热度+拼音排序
LOCAL_SORT_ENABLE = True         # 地方频道按直辖市+省份拼音排序
FEATURE_SORT_ENABLE = True       # 特色频道按类型+名称排序
DIGITAL_SORT_ENABLE = True       # 数字频道按数字排序

# 分组配置
GROUP_SECONDARY_CCTV = "📺 央视频道-CCTV1-17"
GROUP_SECONDARY_WEISHI = "📡 卫视频道-一线/地方"
GROUP_SECONDARY_LOCAL = "🏙️ 地方频道-各省市区"
GROUP_SECONDARY_FEATURE = "🎬 特色频道-电影/体育/少儿"
GROUP_SECONDARY_DIGITAL = "🔢 数字频道-按数字排序"
GROUP_SECONDARY_OTHER = "🌀 其他频道-综合"

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
SOURCE_NUM_PREFIX = "📶"
SPEED_MARK_CACHE = "💾缓存"
SPEED_MARK_1 = "⚡极速"
SPEED_MARK_2 = "🚀快速"
SPEED_MARK_3 = "▶普通"
SPEED_LEVEL_1 = 50
SPEED_LEVEL_2 = 150

# -------------------------- 排序核心配置（新增多类型排序规则） --------------------------
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

# -------------------------- 底层优化：正则+全局变量 --------------------------
# 预编译正则（新增数字频道提取）
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+)\s*$', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_OTHER_NAME = re.compile(r'([^\s]+)$', re.IGNORECASE)
RE_URL_DOMAIN = re.compile(r'https?://([^/]+)/?(.*)')
RE_CCTV_NUMBER = re.compile(r'CCTV(\d+)', re.IGNORECASE)
RE_DIGITAL_NUMBER = re.compile(r'^(\d+)(频道|台)?$', re.IGNORECASE)  # 提取数字频道
LOCAL_HOSTS = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}
VALID_SUFFIX = {".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s"}
VALID_CONTENT_TYPE = {"video/", "application/x-mpegurl", "audio/", "application/octet-stream"}

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
        pool_connections=20,
        pool_maxsize=50,
        max_retries=2,
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

# -------------------------- 工具函数（新增多类型排序逻辑） --------------------------
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

def get_channel_subgroup(channel_name: str) -> str:
    """新增：细分频道分组（数字/特色/其他）"""
    # 数字频道判断
    if DIGITAL_SORT_ENABLE and RE_DIGITAL_NUMBER.match(channel_name):
        return GROUP_SECONDARY_DIGITAL
    # 特色频道判断
    if FEATURE_SORT_ENABLE:
        for feature_type, keywords in FEATURE_TYPE_ORDER:
            if any(keyword in channel_name for keyword in keywords):
                return GROUP_SECONDARY_FEATURE
    # 原有分组判断
    if "CCTV" in channel_name or "央视" in channel_name or "中央" in channel_name:
        return GROUP_SECONDARY_CCTV
    if "卫视" in channel_name:
        return GROUP_SECONDARY_WEISHI
    for area in DIRECT_CITIES + PROVINCE_PINYIN_ORDER:
        if area in channel_name and "卫视" not in channel_name:
            return GROUP_SECONDARY_LOCAL
    # 其他频道
    return GROUP_SECONDARY_OTHER

# -------------------------- 各类型频道排序函数 --------------------------
def get_cctv_sort_key(channel_name: str) -> Tuple[int, str]:
    """CCTV频道排序：数字升序"""
    if not CCTV_SORT_ENABLE or "CCTV" not in channel_name.upper():
        return (999, channel_name.upper())
    match = RE_CCTV_NUMBER.search(channel_name.upper())
    return (int(match.group(1)) if match else 999, channel_name.upper())

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

def get_channel_sort_key(group_name: str, channel_name: str) -> Tuple[int, str]:
    """统一排序入口：根据分组调用对应排序函数"""
    if group_name == GROUP_SECONDARY_CCTV:
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

# -------------------------- 其他工具函数 --------------------------
def get_speed_mark(response_time: float) -> str:
    if response_time == 0.0:
        return SPEED_MARK_CACHE
    elif response_time < SPEED_LEVEL_1:
        return f"{SPEED_MARK_1}"
    elif response_time < SPEED_LEVEL_2:
        return f"{SPEED_MARK_2}"
    else:
        return f"{SPEED_MARK_3}"

def get_best_speed_mark(sources: List[Tuple[str, float]]) -> str:
    if not sources:
        return SPEED_MARK_3
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
    if PLAYER_TITLE_PREFIX:
        subgroup = get_channel_subgroup(channel_name)
        if subgroup == GROUP_SECONDARY_CCTV:
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
    if PLAYER_TITLE_SHOW_NUM:
        title_parts.append(f"{len(sources)}源")
    if PLAYER_TITLE_SHOW_SPEED and sources:
        title_parts.append(get_best_speed_mark(sources))
    if PLAYER_TITLE_SHOW_UPDATE:
        title_parts.append(f"[{GLOBAL_UPDATE_TIME_SHORT}]")
    return " ".join(title_parts).replace("  ", " ")

# -------------------------- 缓存函数 --------------------------
def load_persist_cache():
    global verified_urls
    try:
        cache_path = Path(CACHE_FILE)
        if not cache_path.exists():
            logger.info(f"无持久缓存文件，首次运行")
            return
        with open(cache_path, "r", encoding="utf-8", buffering=1024*1024) as f:
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
        cache_urls = list(verified_urls)[:2000]
        cache_data = {
            "cache_time": GLOBAL_UPDATE_TIME_FULL,
            "verified_urls": cache_urls
        }
        with open(cache_path, "w", encoding="utf-8", buffering=1024*1024) as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=0)
        logger.info(f"保存持久缓存成功 → 缓存源数：{len(cache_urls):,}")
    except Exception as e:
        logger.error(f"保存持久缓存失败：{str(e)[:50]}")

# -------------------------- 核心功能（抓取+验证） --------------------------
def fetch_single_source(url: str, idx: int) -> List[str]:
    add_random_delay()
    try:
        with GLOBAL_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as resp:
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            lines = [line.strip() for line in resp.iter_lines(decode_unicode=True) if line.strip()]
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

def verify_single_url(url: str, channel_name: str) -> Optional[Tuple[str, str, float]]:
    if url in verified_urls:
        return (channel_name, url, 0.0)
    add_random_delay()
    connect_timeout = 1.0
    read_timeout = max(1.0, TIMEOUT_VERIFY - connect_timeout)
    try:
        start = time.time()
        with GLOBAL_SESSION.get(
            url,
            timeout=(connect_timeout, read_timeout),
            stream=True,
            headers={"Range": "bytes=0-512"}
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
    global task_list
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
    task_list = unique_tasks
    logger.info(f"提取验证任务 → 总任务数：{len(task_list):,}")
    return task_list

def verify_tasks_parallel(tasks: List[Tuple[str, str]]):
    logger.info(f"开始并行验证 → 任务数：{len(tasks):,} | 线程数：{MAX_THREADS_VERIFY} | 超时：{TIMEOUT_VERIFY}s")
    global channel_sources_map
    channel_sources_map.clear()
    success_count = 0
    with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
        futures = [executor.submit(verify_single_url, url, chan) for url, chan in tasks]
        for future in as_completed(futures):
            res = future.result()
            if res:
                chan_name, url, rt = res
                success_count += 1
                if chan_name not in channel_sources_map:
                    channel_sources_map[chan_name] = []
                channel_sources_map[chan_name].append((url, rt))
    verify_rate = round(success_count / len(tasks) * 100, 1) if tasks else 0.0
    logger.info(f"验证完成 → 成功：{success_count:,} | 失败：{len(tasks)-success_count:,} | 成功率：{verify_rate}%")
    channel_sources_map = {k: v for k, v in channel_sources_map.items() if v}
    logger.info(f"有效频道筛选 → 剩余有效频道：{len(channel_sources_map):,}个")

# -------------------------- 核心：生成排序后的M3U8 --------------------------
def generate_player_m3u8() -> bool:
    if not channel_sources_map:
        logger.error("无有效频道，无法生成M3U8（可尝试更换数据源）")
        return False
    # 按细分分组整理频道
    player_groups = {
        GROUP_SECONDARY_CCTV: [],
        GROUP_SECONDARY_WEISHI: [],
        GROUP_SECONDARY_LOCAL: [],
        GROUP_SECONDARY_FEATURE: [],
        GROUP_SECONDARY_DIGITAL: [],
        GROUP_SECONDARY_OTHER: []
    }
    for chan_name, sources in channel_sources_map.items():
        sources_sorted = sorted(sources, key=lambda x: x[1])[:3]
        subgroup = get_channel_subgroup(chan_name)
        player_groups[subgroup].append((chan_name, sources_sorted))
    
    # 各分组按对应规则排序
    for group_name, channels in player_groups.items():
        if channels:
            channels.sort(key=lambda x: get_channel_sort_key(group_name, x[0]))
            logger.info(f"{group_name}排序完成 → 顺序：{[chan[0] for chan in channels[:10]]}...")  # 只打印前10个
    
    # 过滤无有效频道的分组
    player_groups = {k: v for k, v in player_groups.items() if v}

    # 生成M3U8内容
    m3u8_content = [
        "#EXTM3U x-tvg-url=https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml",
        GROUP_SEPARATOR,
        f"# 📺 IPTV直播源 - 全类型排序版 | {GLOBAL_UPDATE_TIME_FULL}",
        f"# 🚀 排序规则：",
        f"#   央视频道：CCTV1→CCTV2→...→CCTV17（数字升序）",
        f"#   卫视频道：一线卫视优先→省份拼音排序",
        f"#   地方频道：直辖市优先→省份拼音排序",
        f"#   特色频道：电影→体育→少儿→财经→综艺（类型优先）",
        f"#   数字频道：1→2→3→...→10→11（数字升序）",
        f"# 🎯 兼容：TVBox/Kodi/完美视频/极光TV",
        GROUP_SEPARATOR,
        ""
    ]

    # 写入各分组内容
    for group_name, channels in player_groups.items():
        m3u8_content.extend([
            f"# 📌 分组：{group_name} | 频道数：{len(channels)} | 更新：{GLOBAL_UPDATE_TIME_FULL}",
            GROUP_SEPARATOR,
            ""
        ])
        for chan_name, sources in channels:
            player_title = build_player_title(chan_name, sources)
            m3u8_content.append(f'#EXTINF:-1 group-title="{group_name}",{player_title}')
            for idx, (url, rt) in enumerate(sources, 1):
                speed_mark = get_speed_mark(rt)
                trunc_url = smart_truncate_url(url)
                m3u8_content.append(f"# {SOURCE_NUM_PREFIX}{idx} {speed_mark}：{trunc_url}")
            m3u8_content.append(sources[0][0])
            m3u8_content.append("")
        m3u8_content.append(GROUP_SEPARATOR)
        m3u8_content.append("")

    # 汇总统计
    total_channels = sum(len(v) for v in player_groups.values())
    total_sources = sum(len(s[1]) for v in player_groups.values() for s in v)
    m3u8_content.extend([
        f"# 📊 汇总 | {GLOBAL_UPDATE_TIME_FULL}",
        f"# 总频道数：{total_channels}个 | 总有效源：{total_sources}个 | 验证成功率：{round(total_sources/len(task_list)*100,1) if task_list else 100}%",
        f"# 排序说明：所有频道按类型分组排序，播放器内查找更高效",
        f"# 提示：优先播放第一个URL（最快），卡顿可切换后续备用源",
        GROUP_SEPARATOR
    ])

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8", buffering=1024*1024) as f:
            f.write("\n".join(m3u8_content))
        logger.info(f"✅ 全类型排序版M3U8生成完成 → {OUTPUT_FILE}")
        return True
    except Exception as e:
        logger.error(f"写入失败：{str(e)[:50]}")
        return False

# -------------------------- 主程序 --------------------------
if __name__ == "__main__":
    start_total = time.time()
    logger.info("="*60)
    logger.info("IPTV直播源抓取工具 - 全类型排序终极版")
    logger.info("="*60)
    logger.info(f"启动 | CPU：{CPU_CORES}核 | 验证线程：{MAX_THREADS_VERIFY} | 抓取线程：{MAX_THREADS_FETCH}")
    logger.info(f"更新时间 | 完整：{GLOBAL_UPDATE_TIME_FULL} | 精简：{GLOBAL_UPDATE_TIME_SHORT}")
    logger.info(f"排序配置 | CCTV：{CCTV_SORT_ENABLE} | 卫视：{WEISHI_SORT_ENABLE} | 地方：{LOCAL_SORT_ENABLE} | 特色：{FEATURE_SORT_ENABLE} | 数字：{DIGITAL_SORT_ENABLE}")
    logger.info("="*60)

    load_persist_cache()
    fetch_raw_data_parallel()
    extract_verify_tasks(all_lines)
    verify_tasks_parallel(task_list)
    generate_player_m3u8()
    save_persist_cache()

    total_time = round(time.time() - start_total, 2)
    logger.info("="*60)
    logger.info(f"完成 | 耗时：{total_time}秒 | 生成文件：{OUTPUT_FILE}")
    logger.info("="*60)
