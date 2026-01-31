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

# -------------------------- 全局配置（修复数据源提取+URL过滤） --------------------------
# 1. 数据源配置（保留原有效源）
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

# 2. 效率核心配置（放宽部分限制）
TIMEOUT_VERIFY = 3.0  # 适当增加验证超时
TIMEOUT_FETCH = 10
MIN_VALID_CHANNELS = 1
MAX_THREADS_VERIFY_BASE = 20  # 减少验证线程数，避免网络拥塞
MAX_THREADS_FETCH_BASE = 4
MIN_DELAY = 0.1  # 适当增加延迟，避免反爬拦截
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

# 4. 播放端专属美化配置
CHANNEL_SORT_ENABLE = True
GROUP_SECONDARY_CCTV = "📺 央视频道-CCTV1-17"
GROUP_SECONDARY_WEISHI = "📡 卫视频道-一线/地方"
GROUP_SECONDARY_LOCAL = "🏙️ 地方频道-各省市区"
GROUP_SECONDARY_OTHER = "🎬 其他频道-特色/数字"
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

# -------------------------- 底层优化：修复正则+保留M3U8成对关系 --------------------------
# 预编译正则（放宽频道名提取条件）
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+)\s*$', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_OTHER_NAME = re.compile(r'([^\s]+)$', re.IGNORECASE)  # 新增：提取行尾内容作为频道名
RE_URL_DOMAIN = re.compile(r'https?://([^/]+)/?(.*)')
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
        max_retries=2,  # 增加重试次数，提升抓取成功率
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

# -------------------------- 工具函数（修复频道名提取+URL过滤） --------------------------
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
    """修复：放宽频道名提取条件，兼容更多数据源格式"""
    if not line.startswith("#EXTINF:"):
        return None
    # 尝试多种正则提取，确保能拿到频道名
    match = RE_CHANNEL_NAME.search(line) or RE_TVG_NAME.search(line) or RE_TITLE_NAME.search(line) or RE_OTHER_NAME.search(line)
    if match:
        name = match.group(1).strip()
        return name if name else "未知频道"  # 无法识别时返回“未知频道”，避免丢失任务
    return "未知频道"

def get_player_channel_group(channel_name: str) -> str:
    if not channel_name:
        return GROUP_SECONDARY_OTHER
    if "CCTV" in channel_name or "央视" in channel_name or "中央" in channel_name:
        return GROUP_SECONDARY_CCTV
    if "卫视" in channel_name:
        return GROUP_SECONDARY_WEISHI
    province = {"北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
                "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
                "广东", "广西", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海"}
    for p in province:
        if p in channel_name:
            return GROUP_SECONDARY_LOCAL
    return GROUP_SECONDARY_OTHER

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
        if GROUP_SECONDARY_CCTV in get_player_channel_group(channel_name):
            title_parts.append("📺")
        elif GROUP_SECONDARY_WEISHI in get_player_channel_group(channel_name):
            title_parts.append("📡")
        elif GROUP_SECONDARY_LOCAL in get_player_channel_group(channel_name):
            title_parts.append("🏙️")
        else:
            title_parts.append("🎬")
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

# -------------------------- 核心功能（修复数据源提取+保留M3U8成对关系） --------------------------
def fetch_single_source(url: str, idx: int) -> List[str]:
    add_random_delay()
    try:
        with GLOBAL_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as resp:
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            # 保留原始行顺序（修复：不做全局去重，避免破坏M3U8成对关系）
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
    logger.info(f"抓取完成 → 总有效行：{len(all_lines):,}（保留原始顺序，避免破坏M3U8结构）")
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
    """修复：保留M3U8中#EXTINF和URL的成对关系，避免任务数为0"""
    global task_list
    task_list.clear()
    temp_channel = None
    for line in raw_lines:
        if line.startswith("#EXTINF:"):
            temp_channel = safe_extract_channel_name(line)  # 放宽提取条件
        elif temp_channel and filter_invalid_urls(line):
            task_list.append((line, temp_channel))
            temp_channel = None
    # 仅对URL去重，保留频道名对应关系
    unique_urls = set()
    unique_tasks = []
    for url, chan in task_list:
        if url not in unique_urls:
            unique_urls.add(url)
            unique_tasks.append((url, chan))
    task_list = unique_tasks
    logger.info(f"提取验证任务 → 总任务数：{len(task_list):,}（已去重URL，保留频道对应关系）")
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

# -------------------------- 播放端M3U8生成 --------------------------
def generate_player_m3u8() -> bool:
    if not channel_sources_map:
        logger.error("无有效频道，无法生成M3U8（可尝试更换数据源）")
        return False
    player_groups = {
        GROUP_SECONDARY_CCTV: [],
        GROUP_SECONDARY_WEISHI: [],
        GROUP_SECONDARY_LOCAL: [],
        GROUP_SECONDARY_OTHER: []
    }
    for chan_name, sources in channel_sources_map.items():
        sources_sorted = sorted(sources, key=lambda x: x[1])[:3]
        group = get_player_channel_group(chan_name)
        player_groups[group].append((chan_name, sources_sorted))
    for group in player_groups:
        player_groups[group].sort(key=lambda x: x[0])
    player_groups = {k: v for k, v in player_groups.items() if v}

    m3u8_content = [
        "#EXTM3U x-tvg-url=https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml",
        GROUP_SEPARATOR,
        f"# 📺 IPTV直播源 - 修复版 | {GLOBAL_UPDATE_TIME_FULL}",
        f"# 🚀 适配：保留M3U8成对关系 | 放宽频道名提取 | 增加重试",
        f"# 🎯 兼容：TVBox/Kodi/完美视频/极光TV",
        GROUP_SEPARATOR,
        ""
    ]

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

    total_channels = sum(len(v) for v in player_groups.values())
    total_sources = sum(len(s[1]) for v in player_groups.values() for s in v)
    m3u8_content.extend([
        f"# 📊 汇总 | {GLOBAL_UPDATE_TIME_FULL}",
        f"# 频道：{total_channels}个 | 源：{total_sources}个 | 成功率：{round(total_sources/len(task_list)*100,1) if task_list else 100}%",
        f"# 提示：优先播放第一个URL，卡顿切换其他源",
        GROUP_SEPARATOR
    ])

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8", buffering=1024*1024) as f:
            f.write("\n".join(m3u8_content))
        logger.info(f"✅ M3U8生成完成 → {OUTPUT_FILE}")
        return True
    except Exception as e:
        logger.error(f"写入失败：{str(e)[:50]}")
        return False

# -------------------------- 主程序 --------------------------
if __name__ == "__main__":
    start_total = time.time()
    logger.info("="*60)
    logger.info("IPTV直播源抓取工具 - 修复版（解决任务数为0的问题）")
    logger.info("="*60)
    logger.info(f"启动 | CPU：{CPU_CORES}核 | 验证线程：{MAX_THREADS_VERIFY} | 抓取线程：{MAX_THREADS_FETCH}")
    logger.info(f"更新时间 | 完整：{GLOBAL_UPDATE_TIME_FULL} | 精简：{GLOBAL_UPDATE_TIME_SHORT}")
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
