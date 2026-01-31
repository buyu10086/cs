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

# -------------------------- 全局配置（极速优化版） --------------------------
# 1. 数据源配置（只保留高可用卫视频道源）
IPTV_SOURCE_URLS = [
    # 核心卫视频道源（过滤掉无效垃圾源）
    "https://raw.githubusercontent.com/zhouweitong123/IPTV/main/IPTV/卫视.m3u",
    "https://raw.githubusercontent.com/chenfenping/iptv/main/tv/m3u8/weishi.m3u",
    "https://raw.githubusercontent.com/yangzongzhuan/IPTV/master/m3u/weishi.m3u",
    "https://raw.githubusercontent.com/linkease/iptv/main/playlist/weishi.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u"
]

# 2. 效率核心配置（极速优化）
TIMEOUT_VERIFY = 1.5  # 验证超时从3.5秒缩短到1.5秒
TIMEOUT_FETCH = 8     # 抓取超时从12秒缩短到8秒
MIN_VALID_CHANNELS = 1
MAX_THREADS_VERIFY_BASE = 8  # 验证线程从25降到8（避免网络阻塞）
MAX_THREADS_FETCH_BASE = 4   # 抓取线程从6降到4
MIN_DELAY = 0.05      # 延迟从0.15降到0.05
MAX_DELAY = 0.15      # 延迟从0.4降到0.15
DISABLE_SSL_VERIFY = True
BATCH_PROCESS_SIZE = 50

# 3. 输出与缓存配置
OUTPUT_FILE = "iptv_playlist.m3u8"
CACHE_FILE = "iptv_persist_cache.json"
TEMP_CACHE_SET = set()
CACHE_EXPIRE_HOURS = 24
REMOVE_DUPLICATE_CHANNELS = True  # 开启频道去重（减少无效验证）
REMOVE_LOCAL_URLS = True

# 4. 自动选源+保留3个源配置
AUTO_SELECT_SOURCE = True
TOTAL_SOURCES_PER_CHANNEL = 3
SELECT_SPEED_THRESHOLD = 30
PREFER_M3U8 = True

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
PLAYER_TITLE_SHOW_SPEED = True
PLAYER_TITLE_SHOW_NUM = True
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
RE_M3U8_SUFFIX = re.compile(r'\.m3u8$', re.IGNORECASE)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}
VALID_SUFFIX = {".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s", ".mp4"}
VALID_CONTENT_TYPE = {"video/", "application/x-mpegurl", "audio/", "application/octet-stream", "video/mp4"}

# 全局变量
GLOBAL_UPDATE_TIME_FULL = datetime.now().strftime(UPDATE_TIME_FORMAT_FULL)
GLOBAL_UPDATE_TIME_SHORT = datetime.now().strftime(UPDATE_TIME_FORMAT_SHORT)
CPU_CORES = multiprocessing.cpu_count()
MAX_THREADS_VERIFY = min(MAX_THREADS_VERIFY_BASE, CPU_CORES * 2)  # 线程数上限=CPU*2
MAX_THREADS_FETCH = min(MAX_THREADS_FETCH_BASE, CPU_CORES * 1)   # 线程数上限=CPU*1
channel_sources_map = dict()
verified_urls = set()
task_list = list()
all_lines = list()

# -------------------------- 日志初始化 --------------------------
def init_logger():
    logger = logging.getLogger("IPTV_Spider")
    logger.setLevel(logging.INFO)  # 降低日志级别，减少IO耗时
    logger.handlers.clear()
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    ch.setFormatter(ch_fmt)
    fh = logging.FileHandler("iptv_spider.log", encoding="utf-8", mode="a")
    fh.setLevel(logging.INFO)
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
        pool_connections=10,  # 连接池从25降到10
        pool_maxsize=30,      # 最大连接数从60降到30
        max_retries=1,        # 重试次数从3降到1（快速放弃无效源）
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

# -------------------------- 工具函数（极速优化） --------------------------
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
        # 过滤无效频道名（减少垃圾任务）
        if len(name) < 2 or "测试" in name or "无效" in name:
            return None
        return name if name else None
    return None

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
    if not channel_name:
        return GROUP_SECONDARY_OTHER
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
    """核心：自动选择1个最优源+2个备用源"""
    if not sources:
        return []
    
    # 按响应时间升序排序
    sorted_sources = sorted(sources, key=lambda x: x[1])
    best_sources = []
    
    if AUTO_SELECT_SOURCE:
        # 缓存源优先
        cache_source = next((s for s in sorted_sources if s[1] == 0.0), None)
        if cache_source:
            best_sources.append(cache_source)
            remaining_sources = [s for s in sorted_sources if s[0] != cache_source[0]]
        else:
            # 无缓存源，按速度+格式选最优
            primary_source = sorted_sources[0]
            if PREFER_M3U8 and len(sorted_sources) >= 2:
                first_speed = sorted_sources[0][1]
                second_speed = sorted_sources[1][1]
                if (second_speed - first_speed) <= SELECT_SPEED_THRESHOLD and RE_M3U8_SUFFIX.search(sorted_sources[1][0]):
                    primary_source = sorted_sources[1]
            best_sources.append(primary_source)
            remaining_sources = [s for s in sorted_sources if s[0] != primary_source[0]]
        
        # 选2个备用源
        backup_count = TOTAL_SOURCES_PER_CHANNEL - len(best_sources)
        backup_sources = remaining_sources[:backup_count]
        best_sources.extend(backup_sources)
        
        # 去重
        unique_best_sources = []
        seen_urls = set()
        for s in best_sources:
            if s[0] not in seen_urls:
                seen_urls.add(s[0])
                unique_best_sources.append(s)
        best_sources = unique_best_sources[:TOTAL_SOURCES_PER_CHANNEL]
    else:
        best_sources = sorted_sources[:TOTAL_SOURCES_PER_CHANNEL]
    
    return best_sources[:TOTAL_SOURCES_PER_CHANNEL]

# -------------------------- 辅助工具函数 --------------------------
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

# -------------------------- 缓存函数 --------------------------
def load_persist_cache():
    global verified_urls
    try:
        cache_path = Path(CACHE_FILE)
        if not cache_path.exists():
            logger.info(f"无持久缓存文件，首次运行")
            return
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        cache_time = datetime.strptime(cache_data.get("cache_time", ""), UPDATE_TIME_FORMAT_FULL)
        if datetime.now() - cache_time > timedelta(hours=CACHE_EXPIRE_HOURS):
            logger.info(f"持久缓存过期，清空重新生成")
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
        cache_urls = list(verified_urls)[:2000]  # 减少缓存量，加快写入
        cache_data = {
            "cache_time": GLOBAL_UPDATE_TIME_FULL,
            "verified_urls": cache_urls
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=0)
        logger.info(f"保存持久缓存成功 → 缓存源数：{len(cache_urls):,}")
    except Exception as e:
        logger.error(f"保存持久缓存失败：{str(e)[:50]}")

# -------------------------- 核心功能（极速优化） --------------------------
def fetch_single_source(url: str, idx: int) -> List[str]:
    add_random_delay()
    try:
        with GLOBAL_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as resp:
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            # 只读取前10000行（避免超大文件耗时）
            lines = []
            line_count = 0
            for line in resp.iter_lines(decode_unicode=True):
                if line_count >= 10000:
                    break
                line_strip = line.strip()
                if line_strip:
                    lines.append(line_strip)
                    line_count += 1
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
    logger.info(f"抓取完成 → 总有效行：{len(all_lines):,}")
    return all_lines

def verify_single_url(url: str, channel_name: str) -> Optional[Tuple[str, str, float]]:
    """极速验证：只做基础检查，快速返回"""
    if url in verified_urls:
        return (channel_name, url, 0.0)
    add_random_delay()
    try:
        start = time.time()
        # 只发送HEAD请求（不下载内容，节省带宽和时间）
        resp = GLOBAL_SESSION.head(
            url,
            timeout=TIMEOUT_VERIFY,
            allow_redirects=True
        )
        if resp.status_code not in [200, 301, 302, 307, 308]:
            return None
        # 简单检查Content-Type
        if not any(ct in resp.headers.get("Content-Type", "").lower() for ct in VALID_CONTENT_TYPE):
            return None
        response_time = round((time.time() - start) * 1000, 1)
        verified_urls.add(url)
        TEMP_CACHE_SET.add(url)
        return (channel_name, url, response_time)
    except Exception:
        return None

def extract_verify_tasks(raw_lines: List[str]) -> List[Tuple[str, str]]:
    """提取任务时过滤无效频道，减少验证量"""
    global task_list
    task_list.clear()
    temp_channel = None
    # 只保留核心频道（央视+卫视+特色）
    keep_channel_keywords = ["CCTV", "央视", "卫视", "电影", "体育", "少儿", "新闻"]
    
    for line in raw_lines:
        if line.startswith("#EXTINF:"):
            temp_channel = safe_extract_channel_name(line)
            # 过滤非核心频道，减少验证任务
            if temp_channel and not any(kw in temp_channel for kw in keep_channel_keywords):
                temp_channel = None
        elif temp_channel and filter_invalid_urls(line):
            task_list.append((line, temp_channel))
            temp_channel = None
    
    # 去重（URL+频道名），进一步减少任务量
    unique_tasks = []
    seen_pairs = set()
    for url, chan in task_list:
        pair_key = f"{chan}_{url[:50]}"
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            unique_tasks.append((url, chan))
    task_list = unique_tasks[:5000]  # 最多只验证5000个任务（足够覆盖所有核心频道）
    logger.info(f"提取验证任务 → 过滤后任务数：{len(task_list):,}（仅保留核心频道）")
    return task_list

def verify_tasks_parallel(tasks: List[Tuple[str, str]]):
    logger.info(f"开始并行验证 → 任务数：{len(tasks):,} | 线程数：{MAX_THREADS_VERIFY} | 超时：{TIMEOUT_VERIFY}s")
    global channel_sources_map
    channel_sources_map.clear()
    success_count = 0
    
    # 分批验证（每批200个，避免线程池过载）
    batch_size = 200
    for batch_idx in range(0, len(tasks), batch_size):
        batch_tasks = tasks[batch_idx:batch_idx+batch_size]
        with ThreadPoolExecutor(max_workers=MAX_THREADS_VERIFY) as executor:
            futures = [executor.submit(verify_single_url, url, chan) for url, chan in batch_tasks]
            for future in as_completed(futures):
                res = future.result()
                if res:
                    chan_name, url, rt = res
                    success_count += 1
                    if chan_name not in channel_sources_map:
                        channel_sources_map[chan_name] = []
                    channel_sources_map[chan_name].append((url, rt))
        logger.info(f"批次{batch_idx//batch_size +1}验证完成 → 累计成功：{success_count}")
    
    # 筛选有有效源的频道
    channel_sources_map = {k: v for k, v in channel_sources_map.items() if v}
    logger.info(f"验证完成 → 成功：{success_count:,} | 有效频道：{len(channel_sources_map):,}个")

# -------------------------- 生成m3u8文件 --------------------------
def generate_player_m3u8() -> bool:
    if not channel_sources_map:
        logger.error("生成失败：无有效频道")
        return False
    
    # 按分组整理频道
    player_groups = {
        GROUP_SECONDARY_CCTV: [],
        GROUP_SECONDARY_WEISHI: [],
        GROUP_SECONDARY_LOCAL: [],
        GROUP_SECONDARY_FEATURE: [],
        GROUP_SECONDARY_DIGITAL: [],
        GROUP_SECONDARY_OTHER: []
    }
    
    for chan_name, sources in channel_sources_map.items():
        best_3_sources = select_best_sources(sources)
        if not best_3_sources:
            continue
        subgroup = get_channel_subgroup(chan_name)
        player_groups[subgroup].append((chan_name, best_3_sources))
    
    # 排序
    for group_name, channels in player_groups.items():
        if channels:
            channels.sort(key=lambda x: get_channel_sort_key(group_name, x[0]))
    
    # 过滤空分组
    player_groups = {k: v for k, v in player_groups.items() if v}
    if not player_groups:
        logger.error("生成失败：无有效分组频道")
        return False
    
    # 构建内容
    m3u8_content = [
        "#EXTM3U x-tvg-url=https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml",
        GROUP_SEPARATOR,
        f"# 📺 IPTV直播源 - 自动选最优+3个手动切换源 | 更新时间：{GLOBAL_UPDATE_TIME_FULL}",
        f"# 🚀 极速版：仅验证核心频道，耗时大幅降低",
        GROUP_SEPARATOR,
        ""
    ]
    
    # 写入分组
    for group_name, channels in player_groups.items():
        m3u8_content.extend([
            f"# 📌 分组：{group_name} | 频道数：{len(channels)}",
            GROUP_SEPARATOR,
            ""
        ])
        
        for chan_name, best_3_sources in channels:
            player_title = build_player_title(chan_name, best_3_sources)
            m3u8_content.append(f'#EXTINF:-1 group-title="{group_name}",{player_title}')
            
            # 写入源备注
            for idx, (url, rt) in enumerate(best_3_sources, 1):
                speed_mark = get_speed_mark(rt)
                trunc_url = smart_truncate_url(url)
                m3u8_content.append(f"# {SOURCE_NUM_PREFIX}{idx} {speed_mark}：{trunc_url}")
            
            # 写入默认播放URL
            m3u8_content.append(best_3_sources[0][0])
            m3u8_content.append("")
        
        m3u8_content.append(GROUP_SEPARATOR)
        m3u8_content.append("")
    
    # 写入汇总
    total_channels = sum(len(v) for v in player_groups.values())
    total_sources = sum(len(s[1]) for v in player_groups.values() for s in v)
    m3u8_content.extend([
        f"# 📊 汇总统计 | {GLOBAL_UPDATE_TIME_FULL}",
        f"# 总频道数：{total_channels}个 | 总有效源：{total_sources}个",
        GROUP_SEPARATOR
    ])
    
    # 写入文件
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(m3u8_content))
        
        file_size = Path(OUTPUT_FILE).stat().st_size / 1024
        logger.info(f"✅ m3u8文件生成完成 → 大小：{file_size:.2f}KB")
        return True
    except Exception as e:
        logger.error(f"生成失败：{str(e)[:50]}")
        return False

# -------------------------- 排序函数 --------------------------
def get_cctv_sort_key(channel_name: str) -> Tuple[int, str]:
    if not CCTV_SORT_ENABLE or "CCTV" not in channel_name.upper():
        return (999, channel_name.upper())
    match = RE_CCTV_NUMBER.search(channel_name.upper())
    return (int(match.group(1)) if match else 999, channel_name.upper())

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

def get_channel_sort_key(group_name: str, channel_name: str) -> Tuple[int, str]:
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

# -------------------------- 主程序 --------------------------
if __name__ == "__main__":
    start_total = time.time()
    logger.info("="*60)
    logger.info("IPTV直播源抓取工具 - 极速优化版（自动选最优+3个手动切换源）")
    logger.info("="*60)
    logger.info(f"启动配置 |
