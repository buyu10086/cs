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
    """核心优化：自动选择1个最优源+2个备用源，共3个源（完整逻辑，无语法漏洞）"""
    if not sources:
        logger.debug("选源失败：无有效播放源")
        return []
    
    # 1. 先按响应时间升序排序（最快在前，为选源打基础）
    sorted_sources = sorted(sources, key=lambda x: x[1])
    best_sources = []
    
    if AUTO_SELECT_SOURCE:
        # 2. 缓存源优先（响应时间0ms，直接作为最优源）
        cache_source = next((s for s in sorted_sources if s[1] == 0.0), None)
        if cache_source:
            best_sources.append(cache_source)
            # 排除已选的缓存源，剩余源用于选备用
            remaining_sources = [s for s in sorted_sources if s[0] != cache_source[0]]
            logger.debug(f"选源成功：命中缓存最优源，开始筛选备用源")
        else:
            # 3. 无缓存源，按「速度+格式」选择最优源
            primary_source = sorted_sources[0]
            
            # 速度相近时，优先选择.m3u8格式（稳定性更高）
            if PREFER_M3U8 and len(sorted_sources) >= 2:
                first_speed = sorted_sources[0][1]
                second_speed = sorted_sources[1][1]
                # 速度差值低于阈值，且第二个源是.m3u8格式
                if (second_speed - first_speed) <= SELECT_SPEED_THRESHOLD and RE_M3U8_SUFFIX.search(sorted_sources[1][0]):
                    primary_source = sorted_sources[1]
                    logger.debug(f"选源成功：速度相近，优先选择.m3u8格式作为最优源")
            
            best_sources.append(primary_source)
            # 排除已选的最优源，剩余源用于选备用
            remaining_sources = [s for s in sorted_sources if s[0] != primary_source[0]]
            logger.debug(f"选源成功：筛选出非缓存最优源，响应时间{primary_source[1]}ms")
        
        # 4. 从剩余源中筛选2个备用源（按速度排序，最多补够3个源）
        backup_count = TOTAL_SOURCES_PER_CHANNEL - len(best_sources)
        backup_sources = remaining_sources[:backup_count]
        best_sources.extend(backup_sources)
        
        # 5. 去重备用源（避免URL重复）
        unique_best_sources = []
        seen_urls = set()
        for s in best_sources:
            if s[0] not in seen_urls:
                seen_urls.add(s[0])
                unique_best_sources.append(s)
        best_sources = unique_best_sources[:TOTAL_SOURCES_PER_CHANNEL]
    
    else:
        # 关闭自动选源时，直接取前3个最快的源
        best_sources = sorted_sources[:TOTAL_SOURCES_PER_CHANNEL]
    
    # 6. 确保返回结果不超过设定的源数，且无空值
    final_sources = best_sources[:TOTAL_SOURCES_PER_CHANNEL]
    logger.debug(f"选源完成：该频道共保留{len(final_sources)}个有效播放源")
    return final_sources

# -------------------------- 辅助工具函数（完整） --------------------------
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
    if PLAYER_TITLE_SHOW_NUM and sources:
        title_parts.append(f"{len(sources)}源")
    if PLAYER_TITLE_SHOW_SPEED and sources:
        title_parts.append(get_best_speed_mark(sources))
    if PLAYER_TITLE_SHOW_UPDATE:
        title_parts.append(f"[{GLOBAL_UPDATE_TIME_SHORT}]")
    return " ".join(title_parts).replace("  ", " ")

# -------------------------- 缓存函数（完整） --------------------------
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
            logger.info(f"持久缓存过期（超过{CACHE_EXPIRE_HOURS}小时），清空重新生成")
            return
        cache_urls = cache_data.get("verified_urls", [])
        verified_urls = set([url for url in cache_urls if filter_invalid_urls(url)])
        TEMP_CACHE_SET.update(verified_urls)
        logger.info(f"加载持久缓存成功 → 有效缓存源数：{len(verified_urls):,}")
    except Exception as e:
        logger.warning(f"持久缓存加载失败：{str(e)[:50]}")
        verified_urls = set()

def save_persist_cache():
    try:
        cache_path = Path(CACHE_FILE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_urls = list(verified_urls)[:3000]  # 扩大缓存容量，保留更多卫视频源
        cache_data = {
            "cache_time": GLOBAL_UPDATE_TIME_FULL,
            "verified_urls": cache_urls
        }
        with open(cache_path, "w", encoding="utf-8", buffering=1024*1024) as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=0)
        logger.info(f"保存持久缓存成功 → 缓存源数：{len(cache_urls):,}")
    except Exception as e:
        logger.error(f"保存持久缓存失败：{str(e)[:50]}")

# -------------------------- 核心功能（抓取+验证，完整） --------------------------
def fetch_single_source(url: str, idx: int) -> List[str]:
    add_random_delay()
    try:
        with GLOBAL_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as resp:
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            lines = [line.strip() for line in resp.iter_lines(decode_unicode=True) if line.strip()]
            logger.debug(f"数据源{idx+1}抓取完成 → 有效行：{len(lines)}")
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
    logger.info(f"抓取完成 → 总有效行：{len(all_lines):,}（包含大量卫视频道数据）")
    return all_lines

def verify_single_url(url: str, channel_name: str) -> Optional[Tuple[str, str, float]]:
    if url in verified_urls:
        return (channel_name, url, 0.0)
    add_random_delay()
    connect_timeout = 1.5
    read_timeout = max(1.5, TIMEOUT_VERIFY - connect_timeout)
    try:
        start = time.time()
        with GLOBAL_SESSION.get(
            url,
            timeout=(connect_timeout, read_timeout),
            stream=True,
            headers={"Range": "bytes=0-1024"}
        ) as resp:
            if resp.status_code not in [200, 206, 301, 302, 307, 308]:
                return None
            if not any(ct in resp.headers.get("Content-Type", "").lower() for ct in VALID_CONTENT_TYPE):
                return None
            if not resp.url.lower().endswith(tuple(VALID_SUFFIX)):
                return None
            # 放宽m3u8文件头验证，适配更多卫视频源
            if resp.url.lower().endswith(".m3u8"):
                stream_data = resp.content[:1024].decode("utf-8", errors="ignore")
                if "#EXTM3U" not in stream_data and "EXTM3U" not in stream_data:
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
    # 仅对URL去重，保留不同名称的卫视频道（避免丢失全量卫视）
    unique_urls = set()
    unique_tasks = []
    for url, chan in task_list:
        if url not in unique_urls:
            unique_urls.add(url)
            unique_tasks.append((url, chan))
    task_list = unique_tasks
    logger.info(f"提取验证任务 → 总任务数：{len(task_list):,}（包含大量卫视频道任务）")
    return task_list

def verify_tasks_parallel(tasks: List[Tuple[str, str]]):
    logger.info(f"开始并行验证 → 任务数：{len(tasks):,} | 线程数：{MAX_THREADS_VERIFY} | 超时：{TIMEOUT_VERIFY}s")
    global channel_sources_map
    channel_sources_map.clear()
    success_count = 0
    weishi_count = 0  # 统计卫视频道数量，用于验证是否抓取成功
    
    with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
        futures = [executor.submit(verify_single_url, url, chan) for url, chan in tasks]
        for future in as_completed(futures):
            res = future.result()
            if res:
                chan_name, url, rt = res
                success_count += 1
                
                # 统计卫视频道数量
                if is_weishi_channel(chan_name):
                    weishi_count += 1
                
                # 存入频道-源映射表
                if chan_name not in channel_sources_map:
                    channel_sources_map[chan_name] = []
                channel_sources_map[chan_name].append((url, rt))
    
    # 打印验证结果，方便排查问题
    verify_rate = round(success_count / len(tasks) * 100, 1) if tasks else 0.0
    logger.info(f"验证完成 → 成功：{success_count:,} | 失败：{len(tasks)-success_count:,} | 成功率：{verify_rate}%")
    logger.info(f"卫视频道统计 → 成功验证卫视频道：{weishi_count} 个（全量收录）")
    
    # 筛选有有效源的频道
    channel_sources_map = {k: v for k, v in channel_sources_map.items() if v}
    logger.info(f"有效频道筛选 → 剩余总有效频道：{len(channel_sources_map):,}个")

# -------------------------- 核心：生成带3个源的m3u8文件（完整，带更新校验） --------------------------
def generate_player_m3u8() -> bool:
    if not channel_sources_map:
        logger.error("生成失败：无有效频道（可尝试更换数据源或检查网络）")
        return False
    
    # 1. 按分组整理频道，并为每个频道筛选3个最优源
    player_groups = {
        GROUP_SECONDARY_CCTV: [],
        GROUP_SECONDARY_WEISHI: [],
        GROUP_SECONDARY_LOCAL: [],
        GROUP_SECONDARY_FEATURE: [],
        GROUP_SECONDARY_DIGITAL: [],
        GROUP_SECONDARY_OTHER: []
    }
    
    for chan_name, sources in channel_sources_map.items():
        # 调用选源函数，获取1个最优+2个备用，共3个源
        best_3_sources = select_best_sources(sources)
        if not best_3_sources:
            continue
        
        # 按分组归类
        subgroup = get_channel_subgroup(chan_name)
        player_groups[subgroup].append((chan_name, best_3_sources))
    
    # 2. 各分组按对应规则排序
    for group_name, channels in player_groups.items():
        if channels:
            channels.sort(key=lambda x: get_channel_sort_key(group_name, x[0]))
            # 重点打印卫视频道排序结果，方便验证
            if group_name == GROUP_SECONDARY_WEISHI:
                logger.info(f"卫视频道排序完成 → 前20个：{[chan[0] for chan in channels[:20]]}...")
            else:
                logger.info(f"{group_name}排序完成 → 前10个：{[chan[0] for chan in channels[:10]]}...")
    
    # 3. 过滤无有效频道的分组
    player_groups = {k: v for k, v in player_groups.items() if v}
    if not player_groups:
        logger.error("生成失败：无有效分组频道")
        return False
    
    # 4. 构建m3u8文件内容（带更新时间，确保文件有变化）
    m3u8_content = [
        "#EXTM3U x-tvg-url=https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml",
        GROUP_SEPARATOR,
        f"# 📺 IPTV直播源 - 自动选最优+3个手动切换源 | 更新时间：{GLOBAL_UPDATE_TIME_FULL}",
        f"# 🚀 选源规则：缓存源优先→速度优先→.m3u8格式优先 | 每个频道保留3个有效源",
        f"# 📡 卫视频道：一线卫视+省级卫视+地方卫视（全量收录）",
        f"# 🎯 兼容：TVBox/Kodi/完美视频/极光TV",
        GROUP_SEPARATOR,
        ""
    ]
    
    # 5. 写入各分组的频道和播放源
    for group_name, channels in player_groups.items():
        m3u8_content.extend([
            f"# 📌 分组：{group_name} | 频道数：{len(channels)} | 更新：{GLOBAL_UPDATE_TIME_FULL}",
            GROUP_SEPARATOR,
            ""
        ])
        
        for chan_name, best_3_sources in channels:
            # 构建播放器显示标题
            player_title = build_player_title(chan_name, best_3_sources)
            m3u8_content.append(f'#EXTINF:-1 group-title="{group_name}",{player_title}')
            
            # 写入3个源的备注（方便查看速度）和实际播放URL（第一个为最优默认源）
            for idx, (url, rt) in enumerate(best_3_sources, 1):
                speed_mark = get_speed_mark(rt)
                trunc_url = smart_truncate_url(url)
                m3u8_content.append(f"# {SOURCE_NUM_PREFIX}{idx} {speed_mark}：{trunc_url}")
            
            # 写入默认播放URL（最优源，播放器打开即播）
            m3u8_content.append(best_3_sources[0][0])
            m3u8_content.append("")
        
        m3u8_content.append(GROUP_SEPARATOR)
        m3u8_content.append("")
    
    # 6. 写入汇总统计，确保每次生成的文件内容不同
    total_channels = sum(len(v) for v in player_groups.values())
    weishi_total = len(player_groups.get(GROUP_SECONDARY_WEISHI, []))
    total_sources = sum(len(s[1]) for v in player_groups.values() for s in v)
    
    m3u8_content.extend([
        f"# 📊 汇总统计 | {GLOBAL_UPDATE_TIME_FULL}",
        f"# 总频道数：{total_channels}个 | 卫视频道：{weishi_total}个 | 总有效源：{total_sources}个",
        f"# 验证成功率：{round(total_sources/len(task_list)*100,1) if task_list else 100}%",
        f"# 提示：默认播放第1个最优源，卡顿可手动切换其他2个备用源",
        GROUP_SEPARATOR
    ])
    
    # 7. 写入文件（覆盖原有文件，确保更新）
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8", buffering=1024*1024) as f:
            f.write("\n".join(m3u8_content))
        
        # 验证文件是否生成成功，且有有效大小
        file_size = Path(OUTPUT_FILE).stat().st_size / 1024
        logger.info(f"✅ m3u8文件生成完成 → 文件名：{OUTPUT_FILE} | 文件大小：{file_size:.2f}KB")
        logger.info(f"✅ 每个频道保留3个播放源，默认播放最优源，支持手动切换备用源")
        return True
    except Exception as e:
        logger.error(f"生成失败：文件写入出错 → {str(e)[:50]}")
        return False

# -------------------------- 各类型频道排序函数（完整） --------------------------
def get_cctv_sort_key(channel_name: str) -> Tuple[int, str]:
    if not CCTV_SORT_ENABLE or "CCTV" not in channel_name.upper():
        return (999, channel_name.upper())
    match = RE_CCTV_NUMBER.search(channel_name.upper())
    return (int(match.group(1)) if match else 999, channel_name.upper())

def get_weishi_sort_key(channel_name: str) -> Tuple[int, str]:
    if not WEISHI_SORT_ENABLE:
        return (999, channel_name.upper())
    # 一线卫视优先
    for idx, top_ws in enumerate(TOP_WEISHI):
        if top_ws in channel_name:
            return (idx, channel_name.upper())
    # 其他卫视按省份拼音排序
    for idx, province in enumerate(PROVINCE_PINYIN_ORDER):
        if province in channel_name:
            return (len(TOP_WEISHI) + idx, channel_name.upper())
    # 无匹配的卫视排最后
    return (len(TOP_WEISHI) + len(PROVINCE_PINYIN_ORDER), channel_name.upper())

def get_local_sort_key(channel_name: str) -> Tuple[int, str]:
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
    if not FEATURE_SORT_ENABLE:
        return (999, channel_name.upper())
    # 按特色类型排序
    for idx, (feature_type, keywords) in enumerate(FEATURE_TYPE_ORDER):
        if any(keyword in channel_name for keyword in keywords):
            return (idx, channel_name.upper())
    # 其他特色频道排最后
    return (len(FEATURE_TYPE_ORDER), channel_name.upper())

def get_digital_sort_key(channel_name: str) -> Tuple[int, str]:
    if not DIGITAL_SORT_ENABLE:
        return (999, channel_name.upper())
    match = RE_DIGITAL_NUMBER.match(channel_name)
    return (int(match.group(1)) if match else 999, channel_name.upper())

def get_channel_sort_key(group_name: str, channel_name: str) -> Tuple[int, str]:
    """统一排序入口，根据分组调用对应排序函数"""
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

# -------------------------- 主程序（完整，带流程校验） --------------------------
if __name__ == "__main__":
    start_total = time.time()
    logger.info("="*60)
    logger.info("IPTV直播源抓取工具 - 自动选最优+3个手动切换源（终极修复版）")
    logger.info("="*60)
    logger.info(f"启动配置 | CPU：{CPU_CORES}核 | 验证线程：{MAX_THREADS_VERIFY} | 抓取线程：{MAX_THREADS_FETCH}")
    logger.info(f"更新时间 | 完整：{GLOBAL_UPDATE_TIME_FULL} | 精简：{GLOBAL_UPDATE_TIME_SHORT}")
    logger.info(f"选源配置 | 自动选最优：{AUTO_SELECT_SOURCE} | 每个频道保留源数：{TOTAL_SOURCES_PER_CHANNEL}")
    logger.info("="*60)
    
    # 执行核心流程
    load_persist_cache()
    fetch_raw_data_parallel()
    extract_verify_tasks(all_lines)
    verify_tasks_parallel(task_list)
    generate_success = generate_player_m3u8()
    save_persist_cache()
    
    # 打印最终执行结果
    total_time = round(time.time() - start_total, 2)
    logger.info("="*60)
    if generate_success:
        logger.info(f"执行完成 | 总耗时：{total_time}秒 | 生成文件：{OUTPUT_FILE}（已更新）")
        logger.info(f"核心效果 | 自动选最优源，保留3个手动切换源，m3u8文件内容已更新")
    else:
        logger.error(f"执行失败 | 总耗时：{total_time}秒 | 未生成有效m3u8文件")
    logger.info("="*60)
