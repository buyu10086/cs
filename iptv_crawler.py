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

# -------------------------- 全局配置（效率+播放端美化专属配置） --------------------------
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

# 2. 效率核心配置（深度优化）
TIMEOUT_VERIFY = 2.5  # 缩短验证超时，提升效率（核心验证足够稳定）
TIMEOUT_FETCH = 8
MIN_VALID_CHANNELS = 3
MAX_THREADS_VERIFY_BASE = 40  # 提升验证线程基础值（异步化后无过载风险）
MAX_THREADS_FETCH_BASE = 6
MIN_DELAY = 0.03  # 极致低延迟，兼顾反爬和效率
MAX_DELAY = 0.15
DISABLE_SSL_VERIFY = True  # 关闭SSL验证，减少IO耗时
BATCH_PROCESS_SIZE = 100  # 批量处理URL，减少循环开销

# 3. 输出与缓存配置（分层缓存）
OUTPUT_FILE = "iptv_playlist.m3u8"
CACHE_FILE = "iptv_persist_cache.json"  # 持久缓存（24小时）
TEMP_CACHE_SET = set()  # 临时缓存（本次运行，内存级）
CACHE_EXPIRE_HOURS = 24
REMOVE_DUPLICATE_CHANNELS = True
REMOVE_LOCAL_URLS = True

# 4. 播放端专属美化配置（核心！贴合播放器）
CHANNEL_SORT_ENABLE = True
# 播放器二级分组（播放器内分类更清晰）
GROUP_SECONDARY_CCTV = "📺 央视频道-CCTV1-17"
GROUP_SECONDARY_WEISHI = "📡 卫视频道-一线/地方"
GROUP_SECONDARY_LOCAL = "🏙️ 地方频道-各省市区"
GROUP_SECONDARY_OTHER = "🎬 其他频道-特色/数字"
# 播放端标题配置（简洁+关键信息，播放器内显示友好）
PLAYER_TITLE_PREFIX = True  # 频道类型图标前缀
PLAYER_TITLE_SHOW_SPEED = True  # 显示最优源速度
PLAYER_TITLE_SHOW_NUM = True  # 显示有效源数
PLAYER_TITLE_SHOW_UPDATE = True  # 显示更新时间（精简格式）
UPDATE_TIME_FORMAT_SHORT = "%m-%d %H:%M"  # 播放器标题内精简更新时间格式
UPDATE_TIME_FORMAT_FULL = "%Y-%m-%d %H:%M:%S"  # 日志/文件头完整格式
# 其他美化
GROUP_SEPARATOR = "#" * 50
URL_TRUNCATE_DOMAIN = True  # 智能截断URL（播放器注释友好）
URL_TRUNCATE_LENGTH = 50
SOURCE_NUM_PREFIX = "📶"  # 播放器注释内源前缀（精简）
SPEED_MARK_CACHE = "💾缓存"
SPEED_MARK_1 = "⚡极速"  # <50ms
SPEED_MARK_2 = "🚀快速"  # 50-150ms
SPEED_MARK_3 = "▶普通"  # >150ms
SPEED_LEVEL_1 = 50
SPEED_LEVEL_2 = 150

# -------------------------- 底层极致优化：预编译+全局常量+内存复用 --------------------------
# 预编译所有正则（仅一次编译，全程复用）
RE_CHANNEL_NAME = re.compile(r',\s*([^,]+)\s*$', re.IGNORECASE)
RE_TVG_NAME = re.compile(r'tvg-name="([^"]+)"', re.IGNORECASE)
RE_TITLE_NAME = re.compile(r'title="([^"]+)"', re.IGNORECASE)
RE_URL_DOMAIN = re.compile(r'https?://([^/]+)/?(.*)')
RE_CCTV = re.compile(r'CCTV(\d+)', re.IGNORECASE)
RE_WEISHI = re.compile(r'(.+)卫视', re.IGNORECASE)
# 全局常量（内存复用，避免重复创建）
LOCAL_HOSTS = {"localhost", "127.0.0.1", "192.168.", "10.", "172.", "169.254."}
VALID_SUFFIX = {".m3u8", ".ts", ".flv", ".rtmp", ".rtsp", ".m4s"}
VALID_CONTENT_TYPE = {"video/", "application/x-mpegurl", "audio/", "application/octet-stream"}
# 全局变量（一次生成，全程复用）
GLOBAL_UPDATE_TIME_FULL = datetime.now().strftime(UPDATE_TIME_FORMAT_FULL)
GLOBAL_UPDATE_TIME_SHORT = datetime.now().strftime(UPDATE_TIME_FORMAT_SHORT)
CPU_CORES = multiprocessing.cpu_count()
# 动态线程池（异步化后，按CPU核心数翻倍，无过载风险）
MAX_THREADS_VERIFY = min(MAX_THREADS_VERIFY_BASE, CPU_CORES * 8)
MAX_THREADS_FETCH = min(MAX_THREADS_FETCH_BASE, CPU_CORES * 3)
# 内存复用对象
channel_sources_map = dict()  # 复用字典
verified_urls = set()  # 持久缓存URL
task_list = list()  # 复用任务列表
all_lines = list()  # 复用抓取结果列表

# -------------------------- 日志分级优化：控制台精简+文件详细 --------------------------
def init_logger():
    logger = logging.getLogger("IPTV_Spider")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    # 控制台处理器：仅INFO级别，精简输出（减少IO）
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    ch.setFormatter(ch_fmt)
    # 文件处理器：DEBUG级别，详细输出（保留日志）
    fh = logging.FileHandler("iptv_spider.log", encoding="utf-8", mode="a")
    fh.setLevel(logging.DEBUG)
    fh_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fh_fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger

logger = init_logger()

# -------------------------- Session连接池极致优化：全局单例+长连接 --------------------------
def init_global_session():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=30,  # 增大连接池
        pool_maxsize=100,
        max_retries=1,
        pool_block=False  # 非阻塞连接池，避免等待
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # 全局请求头（精简+通用）
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache"
    })
    # 关闭SSL验证（深度效率优化）
    if DISABLE_SSL_VERIFY:
        session.verify = False
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    return session

# 全局单例Session，抓取+验证共用（连接池复用，效率拉满）
GLOBAL_SESSION = init_global_session()

# -------------------------- 工具函数：效率优先+播放端美化适配 --------------------------
def add_random_delay():
    """极致低延迟，兼顾反爬"""
    if MIN_DELAY < MAX_DELAY:
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

def filter_invalid_urls(url: str) -> bool:
    """批量URL过滤，逻辑极简，效率优先"""
    if not url or not url.startswith(("http://", "https://")):
        return False
    if REMOVE_LOCAL_URLS:
        for host in LOCAL_HOSTS:
            if host in url.lower():
                return False
    # 临时缓存命中，直接有效（本次运行不重复过滤）
    if url in TEMP_CACHE_SET:
        return True
    TEMP_CACHE_SET.add(url)
    return True

def batch_filter_urls(url_list: List[str]) -> List[str]:
    """批量URL过滤，减少循环次数（效率优化）"""
    return [url for url in url_list if filter_invalid_urls(url)]

def safe_extract_channel_name(line: str) -> Optional[str]:
    """极简频道名提取，预编译正则，无冗余判断"""
    if not line.startswith("#EXTINF:"):
        return None
    match = RE_CHANNEL_NAME.search(line) or RE_TVG_NAME.search(line)
    if match:
        name = match.group(1).strip()
        return name if name and not name.isdigit() else None
    return None

def get_player_channel_group(channel_name: str) -> str:
    """播放端二级分组，贴合播放器分类逻辑"""
    if not channel_name:
        return GROUP_SECONDARY_OTHER
    if "CCTV" in channel_name or "央视" in channel_name or "中央" in channel_name:
        return GROUP_SECONDARY_CCTV
    if "卫视" in channel_name:
        return GROUP_SECONDARY_WEISHI
    # 地方频道关键词（精简，效率优先）
    province = {"北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
                "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
                "广东", "广西", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海"}
    for p in province:
        if p in channel_name:
            return GROUP_SECONDARY_LOCAL
    return GROUP_SECONDARY_OTHER

def get_speed_mark(response_time: float) -> str:
    """播放端友好速度标注，精简图标"""
    if response_time == 0.0:
        return SPEED_MARK_CACHE
    elif response_time < SPEED_LEVEL_1:
        return f"{SPEED_MARK_1}"
    elif response_time < SPEED_LEVEL_2:
        return f"{SPEED_MARK_2}"
    else:
        return f"{SPEED_MARK_3}"

def get_best_speed_mark(sources: List[Tuple[str, float]]) -> str:
    """获取频道最优源速度标注（用于播放端标题）"""
    if not sources:
        return SPEED_MARK_3
    min_time = min([s[1] for s in sources])
    return get_speed_mark(min_time)

def smart_truncate_url(url: str) -> str:
    """播放端友好URL截断，保留域名，注释更清晰"""
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
    """播放端专属标题构建，简洁+关键信息，播放器内显示最优"""
    title_parts = []
    # 图标前缀
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
    # 有效源数
    if PLAYER_TITLE_SHOW_NUM:
        title_parts.append(f"{len(sources)}源")
    # 最优源速度
    if PLAYER_TITLE_SHOW_SPEED and sources:
        title_parts.append(get_best_speed_mark(sources))
    # 精简更新时间
    if PLAYER_TITLE_SHOW_UPDATE:
        title_parts.append(f"[{GLOBAL_UPDATE_TIME_SHORT}]")
    # 拼接标题（播放器友好，无特殊字符）
    return " ".join(title_parts).replace("  ", " ")

# -------------------------- 分层缓存优化：持久缓存+临时缓存 --------------------------
def load_persist_cache():
    """加载持久缓存，流式读取，效率优先"""
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
            logger.info(f"持久缓存过期（>24h），清空重新生成")
            return
        # 批量加载缓存URL，效率优先
        cache_urls = cache_data.get("verified_urls", [])
        verified_urls = set(batch_filter_urls(cache_urls))
        TEMP_CACHE_SET.update(verified_urls)  # 同步到临时缓存
        logger.info(f"加载持久缓存成功 → 有效源数：{len(verified_urls):,}")
    except Exception as e:
        logger.warning(f"持久缓存加载失败，忽略：{str(e)[:50]}")
        verified_urls = set()

def save_persist_cache():
    """保存持久缓存，批量写入，效率优先"""
    try:
        cache_path = Path(CACHE_FILE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # 批量转换为列表，减少内存开销
        cache_urls = list(verified_urls)[:2000]  # 限制缓存大小，避免文件过大
        cache_data = {
            "cache_time": GLOBAL_UPDATE_TIME_FULL,
            "verified_urls": cache_urls
        }
        with open(cache_path, "w", encoding="utf-8", buffering=1024*1024) as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=0)  # 无缩进，减小文件大小
        logger.info(f"保存持久缓存成功 → 缓存源数：{len(cache_urls):,} | 有效期24h")
    except Exception as e:
        logger.error(f"保存持久缓存失败：{str(e)[:50]}")

# -------------------------- 核心功能：并行抓取+验证（深度效率优化） --------------------------
def fetch_single_source(url: str, idx: int) -> List[str]:
    """单数据源抓取，流式读取，批量处理，效率优先"""
    add_random_delay()
    try:
        with GLOBAL_SESSION.get(url, timeout=TIMEOUT_FETCH, stream=True) as resp:
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            # 流式读取+批量处理，减少内存占用
            lines = [line.strip() for line in resp.iter_lines(decode_unicode=True) if line.strip()]
            return batch_filter_urls(lines)
    except Exception as e:
        logger.debug(f"数据源{idx+1}抓取失败：{str(e)[:30]}")
        return []

def fetch_raw_data_parallel() -> List[str]:
    """并行抓取所有数据源，批量合并，效率拉满"""
    logger.info(f"开始并行抓取 → 数据源：{len(IPTV_SOURCE_URLS)} | 线程数：{MAX_THREADS_FETCH} | 超时：{TIMEOUT_FETCH}s")
    global all_lines
    all_lines.clear()
    with ThreadPoolExecutor(max_workers=MAX_THREADS_FETCH) as executor:
        futures = [executor.submit(fetch_single_source, url, idx) for idx, url in enumerate(IPTV_SOURCE_URLS)]
        for future in as_completed(futures):
            all_lines.extend(future.result())
    # 全局批量去重，避免后续重复处理（核心效率优化）
    all_lines = list(set(all_lines))
    logger.info(f"抓取完成 → 总有效行：{len(all_lines):,}（已全局去重+过滤无效URL）")
    return all_lines

def verify_single_url(url: str, channel_name: str) -> Optional[Tuple[str, str, float]]:
    """单URL验证，极简逻辑，异步非阻塞，效率优先"""
    # 持久缓存/临时缓存命中，直接返回（耗时0，免验证）
    if url in verified_urls:
        return (channel_name, url, 0.0)
    add_random_delay()
    connect_timeout = 1.0
    read_timeout = max(0.5, TIMEOUT_VERIFY - connect_timeout)
    try:
        start = time.time()
        with GLOBAL_SESSION.get(
            url,
            timeout=(connect_timeout, read_timeout),
            stream=True,
            headers={"Range": "bytes=0-512"}  # 仅读前512字节，减少IO
        ) as resp:
            # 核心有效性验证（仅保留必要判断）
            if resp.status_code not in [200, 206, 301, 302, 307, 308]:
                return None
            if not any(ct in resp.headers.get("Content-Type", "").lower() for ct in VALID_CONTENT_TYPE):
                return None
            if not resp.url.lower().endswith(tuple(VALID_SUFFIX)):
                return None
            # 计算耗时（毫秒，保留1位，减少计算开销）
            response_time = round((time.time() - start) * 1000, 1)
            # 验证通过，加入双缓存
            verified_urls.add(url)
            TEMP_CACHE_SET.add(url)
            return (channel_name, url, response_time)
    except Exception:
        return None

def extract_verify_tasks(raw_lines: List[str]) -> List[Tuple[str, str]]:
    """提取验证任务，批量处理，减少循环（效率优化）"""
    global task_list
    task_list.clear()
    temp_channel = None
    for line in raw_lines:
        if line.startswith("#EXTINF:"):
            temp_channel = safe_extract_channel_name(line)
        elif temp_channel and filter_invalid_urls(line):
            task_list.append((line, temp_channel))
            temp_channel = None
    # 任务批量去重，避免重复验证（核心效率优化）
    task_list = list(set(task_list))
    logger.info(f"提取验证任务 → 总任务数：{len(task_list):,}（已批量去重+缓存命中）")
    return task_list

def verify_tasks_parallel(tasks: List[Tuple[str, str]]):
    """并行验证所有URL，深度效率优化，内存复用"""
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
                # 内存复用字典，避免重复创建
                if chan_name not in channel_sources_map:
                    channel_sources_map[chan_name] = []
                channel_sources_map[chan_name].append((url, rt))
    # 计算成功率，避免除零
    verify_rate = round(success_count / len(tasks) * 100, 1) if tasks else 0.0
    logger.info(f"验证完成 → 成功：{success_count:,} | 失败：{len(tasks)-success_count:,} | 成功率：{verify_rate}%")
    # 过滤无有效源的频道，播放端无空频道
    channel_sources_map = {k: v for k, v in channel_sources_map.items() if v}
    logger.info(f"有效频道筛选 → 剩余有效频道：{len(channel_sources_map):,}个（已过滤无源流频道）")

# -------------------------- 播放端专属M3U8生成：贴合播放器展示逻辑 --------------------------
def generate_player_m3u8() -> bool:
    """生成播放端专属美化M3U8，严格遵循M3U8规范，播放器友好"""
    if not channel_sources_map:
        logger.error("无有效频道，无法生成M3U8")
        return False
    # 按播放端二级分组整理频道
    player_groups = {
        GROUP_SECONDARY_CCTV: [],
        GROUP_SECONDARY_WEISHI: [],
        GROUP_SECONDARY_LOCAL: [],
        GROUP_SECONDARY_OTHER: []
    }
    for chan_name, sources in channel_sources_map.items():
        # 源按速度排序（最快在前，播放器优先选择第一个）
        sources_sorted = sorted(sources, key=lambda x: x[1])[:3]  # 保留最快3个
        group = get_player_channel_group(chan_name)
        player_groups[group].append((chan_name, sources_sorted))
    # 频道内排序，播放端展示有序
    for group in player_groups:
        player_groups[group].sort(key=lambda x: x[0])
    # 过滤无有效频道的分组，播放器内无空分类
    player_groups = {k: v for k, v in player_groups.items() if v}

    # 构建M3U8内容（播放端专属，结构清晰，规范友好）
    m3u8_content = [
        "#EXTM3U x-tvg-url=https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml",
        GROUP_SEPARATOR,
        f"# 📺 IPTV直播源 - 播放端专属版 | {GLOBAL_UPDATE_TIME_FULL}",
        f"# 🚀 效率优化：CPU{CPU_CORES}核自适应 | 全局连接池 | 分层缓存 | 批量处理",
        f"# ✨ 播放端优化：二级分类 | 专属标题 | 速度标注 | 精简注释",
        f"# 🎯 兼容播放器：TVBox/Kodi/完美视频/极光TV/小米电视/当贝/乐播",
        GROUP_SEPARATOR,
        ""
    ]

    # 生成播放端分组内容（核心：贴合播放器分类逻辑）
    for group_name, channels in player_groups.items():
        m3u8_content.extend([
            f"# 📌 分组：{group_name} | 频道数：{len(channels)} | 更新：{GLOBAL_UPDATE_TIME_FULL}",
            GROUP_SEPARATOR,
            ""
        ])
        # 遍历每个频道，生成播放端专属内容
        for chan_name, sources in channels:
            player_title = build_player_title(chan_name, sources)
            # M3U8标准行（group-title为播放器分类，title为播放器显示标题）
            m3u8_content.append(f'#EXTINF:-1 group-title="{group_name}",{player_title}')
            # 播放端友好注释（精简+关键信息，无冗余）
            for idx, (url, rt) in enumerate(sources, 1):
                speed_mark = get_speed_mark(rt)
                trunc_url = smart_truncate_url(url)
                m3u8_content.append(f"# {SOURCE_NUM_PREFIX}{idx} {speed_mark}：{trunc_url}")
            # 原始播放URL（播放器唯一识别，无修改，保证播放）
            m3u8_content.append(sources[0][0])
            m3u8_content.append("")
        m3u8_content.append(GROUP_SEPARATOR)
        m3u8_content.append("")

    # 生成播放端汇总信息（精简，贴合播放器注释逻辑）
    total_channels = sum(len(v) for v in player_groups.values())
    total_sources = sum(len(s[1]) for v in player_groups.values() for s in v)
    m3u8_content.extend([
        f"# 📊 播放列表汇总 | {GLOBAL_UPDATE_TIME_FULL}",
        f"# 📺 总有效频道：{total_channels}个 | 📶 总有效源：{total_sources}个",
        f"# ⚡ 验证成功率：{round(total_sources/len(task_list)*100,1) if task_list else 100}% | 缓存源数：{len(verified_urls):,}个",
        f"# 📌 播放器使用提示：优先播放第一个URL，卡顿请手动切换其他源",
        f"# 📅 更新提示：建议每6-12小时重新运行，保证源的新鲜度和有效性",
        f"# 🎯 最佳兼容：播放器设置编码为UTF-8，关闭广告过滤/URL重写",
        GROUP_SEPARATOR
    ])

    # 流式写入M3U8文件，效率优先，避免内存溢出
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8", buffering=1024*1024) as f:
            f.write("\n".join(m3u8_content))
        logger.info(f"✅ 播放端专属M3U8生成完成 → {OUTPUT_FILE}")
        logger.info(f"📊 最终统计 | 频道：{total_channels}个 | 源：{total_sources}个 | 更新：{GLOBAL_UPDATE_TIME_FULL}")
        return True
    except Exception as e:
        logger.error(f"写入M3U8失败：{str(e)[:50]}")
        return False

# -------------------------- 主程序：全流程深度效率优化，一键运行 --------------------------
if __name__ == "__main__":
    start_total = time.time()
    logger.info("="*60)
    logger.info("IPTV直播源抓取工具 - 究极版（效率拉满+播放端专属）")
    logger.info("="*60)
    logger.info(f"程序启动 | CPU：{CPU_CORES}核 | 验证线程：{MAX_THREADS_VERIFY} | 抓取线程：{MAX_THREADS_FETCH}")
    logger.info(f"更新时间 | 完整：{GLOBAL_UPDATE_TIME_FULL} | 精简：{GLOBAL_UPDATE_TIME_SHORT}")
    logger.info("="*60)

    # 核心流程（全深度效率优化，步骤最少，开销最低）
    load_persist_cache()          # 加载分层缓存
    fetch_raw_data_parallel()     # 并行抓取+批量处理
    extract_verify_tasks(all_lines)  # 提取验证任务+批量去重
    verify_tasks_parallel(task_list) # 并行验证+内存复用
    generate_player_m3u8()        # 生成播放端专属M3U8
    save_persist_cache()          # 保存分层缓存

    # 总耗时统计，精确到毫秒
    total_time = round(time.time() - start_total, 2)
    logger.info("="*60)
    logger.info(f"程序运行完成 | 总耗时：{total_time}秒 | 生成文件：{OUTPUT_FILE}")
    logger.info(f"使用建议：1. 播放器导入{OUTPUT_FILE} 2. 定时每6小时运行 3. 播放器编码设为UTF-8")
    logger.info("="*60)
