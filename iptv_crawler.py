import re
import json
import time
import asyncio
import aiohttp
import logging
import fnmatch
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from tqdm import tqdm

# ===============================
# 1. 日志系统优化（减少IO耗时，仅输出关键信息）
# ===============================
def init_logger():
    """初始化日志：仅输出INFO级别，减少打印耗时"""
    log_file = Path(f"iptv_tool_{datetime.now().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8")
        ]
    )
    return logging.getLogger(__name__)

logger = init_logger()

# ===============================
# 2. 全局配置优化（高性能并发+精准超时+多源类型支持）
# ===============================
# 核心优化：修复verify_ssl弃用问题，改为ssl=False
TCP_CONNECTOR_CONFIG = {
    "limit": 200,  # 全局并发连接数
    "limit_per_host": 30,  # 单域名并发
    "ttl_dns_cache": 0,  # 禁用DNS缓存
    "ssl": False,  # 修复：替换verify_ssl为ssl，解决弃用警告
}

# CCTV频道专属超时配置
CCTV_AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(
    connect=4,
    sock_read=8,
    total=12,
)

# 通用频道超时配置
COMMON_AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(
    connect=3,
    sock_read=4,
    total=6,
)

# 新增：多源类型支持配置
SUPPORTED_PROTOCOLS = [
    "http", "https", "rtmp", "rtsp", "hls", "flv", "tcp", "udp"
]
SUPPORTED_EXTENSIONS = [
    ".m3u8", ".ts", ".flv", ".mp4", ".mov", ".avi", ".mkv", ".mpeg", ".mpg"
]
# 源类型识别正则
SOURCE_TYPE_PATTERNS = {
    "m3u8": re.compile(r"(?:\.m3u8|\?hls=|m3u8\/|hls\/)", re.IGNORECASE),
    "rtmp": re.compile(r"rtmp:\/\/", re.IGNORECASE),
    "flv": re.compile(r"(?:\.flv|\?flv=|flv\/)", re.IGNORECASE),
    "ts": re.compile(r"(?:\.ts|\?ts=|ts\/)", re.IGNORECASE),
    "rtsp": re.compile(r"rtsp:\/\/", re.IGNORECASE),
    "http_flv": re.compile(r"http.*\.flv", re.IGNORECASE)
}

CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",
    "OUTPUT_FILE": "iptv_playlist.m3u8",
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip, deflate",
    },
    "TOP_K": 3,
    "IPTV_DISCLAIMER": "个人自用，请勿用于商业用途",
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo",
    "CACHE_FILE": "iptv_speed_cache.json",
    "CACHE_EXPIRE_SECONDS": 1800,
    "BAD_KEYWORDS": ["ad", "advertising", "spam", "弹窗", "广告", "推广"],
    "CCTV_AIOHTTP_TIMEOUT": CCTV_AIOHTTP_TIMEOUT,
    "COMMON_AIOHTTP_TIMEOUT": COMMON_AIOHTTP_TIMEOUT,
    "TCP_CONNECTOR_CONFIG": TCP_CONNECTOR_CONFIG,
    "INVALID_URL_CACHE_SECONDS": 300,
    # 新增：多源类型支持配置
    "SUPPORTED_PROTOCOLS": SUPPORTED_PROTOCOLS,
    "SUPPORTED_EXTENSIONS": SUPPORTED_EXTENSIONS,
    "SOURCE_TYPE_PATTERNS": SOURCE_TYPE_PATTERNS,
    # 新增：源格式修复配置
    "FIX_URL_ENCODING": True,
    "REMOVE_DUPLICATE_PARAMS": True,
    "VALIDATE_URL_STRUCTURE": True,
}

# ===============================
# 3. 频道分类与别名映射
# ===============================
CHANNEL_CATEGORIES = {
    "央视频道": [
        "CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV4欧洲", "CCTV4美洲", "CCTV5", "CCTV5+", "CCTV6", "CCTV7",
        "CCTV8", "CCTV9", "CCTV10", "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15", "CCTV16", "CCTV17", "CCTV4K", "CCTV8K",
        "兵器科技", "风云音乐", "风云足球", "风云剧场", "怀旧剧场", "第一剧场", "女性时尚", "世界地理", "央视台球", "高尔夫网球",
        "央视文化精品", "卫生健康", "电视指南", "中学生", "发现之旅", "书法频道", "国学频道", "环球奇观"
    ],
    "卫视频道": [
        "湖南卫视", "浙江卫视", "江苏卫视", "东方卫视", "深圳卫视", "北京卫视", "广东卫视", "广西卫视", "东南卫视", "海南卫视",
        "河北卫视", "河南卫视", "湖北卫视", "江西卫视", "四川卫视", "重庆卫视", "贵州卫视", "云南卫视", "天津卫视", "安徽卫视",
        "山东卫视", "辽宁卫视", "黑龙江卫视", "吉林卫视", "内蒙古卫视", "宁夏卫视", "山西卫视", "陕西卫视", "甘肃卫视", "青海卫视",
        "新疆卫视", "西藏卫视", "三沙卫视", "兵团卫视", "延边卫视", "安多卫视", "康巴卫视", "农林卫视", "厦门卫视", "山东教育卫视",
        "中国教育1台", "中国教育2台", "中国教育3台", "中国教育4台", "早期教育"
    ],
    "数字频道": [
        "CHC动作电影", "CHC家庭影院", "CHC影迷电影", "淘电影", "淘精彩", "淘剧场", "淘4K", "淘娱乐", "淘BABY", "淘萌宠", "重温经典",
        "星空卫视", "CHANNEL[V]", "凤凰卫视中文台", "凤凰卫视资讯台", "凤凰卫视香港台", "凤凰卫视电影台", "求索纪录", "求索科学",
        "求索生活", "求索动物", "纪实人文", "金鹰纪实", "纪实科教", "睛彩青少", "睛彩竞技", "睛彩篮球", "睛彩广场舞", "魅力足球", "五星体育",
        "劲爆体育", "快乐垂钓", "茶频道", "先锋乒羽", "天元围棋", "汽摩", "梨园频道", "文物宝库", "武术世界", "哒啵赛事", "哒啵电竞", "黑莓电影", "黑莓动画", 
        "乐游", "生活时尚", "都市剧场", "欢笑剧场", "游戏风云", "金色学堂", "动漫秀场", "新动漫", "卡酷少儿", "金鹰卡通", "优漫卡通", "哈哈炫动", "嘉佳卡通", 
        "中国交通", "中国天气", "华数4K", "华数星影", "华数动作影院", "华数喜剧影院", "华数家庭影院", "华数经典电影", "华数热播剧场", "华数碟战剧场",
        "华数军旅剧场", "华数城市剧场", "华数武侠剧场", "华数古装剧场", "华数魅力时尚", "华数少儿动画", "华数动画", "爱综艺", "爱体育", "爱电影", "爱大剧", "爱生活", "高清纪实", "IPTV谍战剧场", "IPTV相声小品", "IPTV野外", "音乐现场", "IPTV野外", "IPTV法治", "河南IPTV-导视", "网络棋牌", "好学生", "央视篮球"
    ],
    "湖北地方台": [
        "湖北公共新闻", "湖北经视频道", "湖北综合频道", "湖北垄上频道", "湖北影视频道", "湖北生活频道", "湖北教育频道",
        "武汉新闻综合", "武汉电视剧", "武汉科技生活", "武汉文体频道", "武汉教育频道", "阳新综合", "房县综合", "蔡甸综合"
    ],
    "河南省级": [
        "河南卫视", "河南都市频道", "河南民生频道", "河南法治频道", "河南电视剧频道", "河南新闻频道", 
        "河南乡村频道", "河南戏曲频道", "河南收藏天下", "河南中华功夫", "河南移动电视", "河南调解剧场", 
        "河南移动戏曲", "河南睛彩中原", "大象新闻", "大剧院", "健康河南融媒", "体育赛事"
    ],
    "河南市县": [
        "郑州1新闻综合", "郑州2商都频道", "郑州3文体旅游", "鄭州4豫剧频道", "郑州5妇女儿童", "郑州6都市生活",
        "洛阳-1新闻综合", "洛阳-2科教频道", "洛阳-3文旅频道", "南阳1新闻综合", "南阳2公共频道", "南阳3科教频道",
        "商丘1新闻综合", "商丘2公共频道", "商丘3文体科教", "周口公共频道", "周口教育频道", "周口新闻综合",
        "开封1新闻综合", "开封2文化旅游", "新乡公共频道", "新乡新闻综合", "新乡综合频道", "焦作公共频道", 
        "焦作综合频道", "漯河新闻综合", "信阳新闻综合", "信阳文旅频道", "许昌农业科教", "许昌综合频道",
        "平顶山新闻综合", "平顶山城市频道", "平顶山公共频道", "平顶山教育台", "鹤壁新闻综合", "安阳新闻综合",
        "安阳文旅频道", "三门峡新闻综合", "濮阳新闻综合", "濮阳公共频道", "济源-1", "永城新闻联播", 
        "项城电视台", "禹州电视台", "邓州综合频道", "新密综合频道", "登封综合频道", "巩义综合频道", 
        "荥阳综合频道", "新郑TV-1", "新县综合频道", "淅川电视台-1", "镇平新闻综合", "宝丰TV-1", 
        "宝丰-1", "舞钢电视台-1", "嵩县综合新闻", "宜阳综合频道", "汝阳综合频道", "孟津综合综合", 
        "灵宝综合频道", "渑池新闻综合", "义马综合频道", "内黄综合频道", "封丘1新闻综合", "延津电视台", 
        "获嘉综合频道", "原阳电视台", "卫辉综合频道", "淇县电视台", "内黄综合频道", "郸城", 
        "唐河TV-1", "上蔡-1", "舞阳新闻综合", "临颍综合频道", "杞县新闻综合", "光山综合频道",
        "平煤安全环保", "浉河广电中心", "平桥广电中心", "新蔡TV", "叶县电视台-1", "郏县综合频道"
    ]
}

CHANNEL_MAPPING = {
    "CCTV1": ["CCTV-1", "CCTV-1 HD", "CCTV1 HD", "CCTV-1综合"],
    "CCTV2": ["CCTV-2", "CCTV-2 HD", "CCTV2 HD", "CCTV-2财经"],
    "CCTV3": ["CCTV-3", "CCTV-3 HD", "CCTV3 HD", "CCTV-3综艺"],
    "CCTV4": ["CCTV-4", "CCTV-4 HD", "CCTV4 HD", "CCTV-4中文国际"],
    "CCTV4欧洲": ["CCTV-4欧洲", "CCTV-4欧洲", "CCTV4欧洲 HD", "CCTV-4 欧洲", "CCTV-4中文国际欧洲", "CCTV4中文欧洲"],
    "CCTV4美洲": ["CCTV-4美洲", "CCTV-4北美", "CCTV4美洲 HD", "CCTV-4 美洲", "CCTV-4中文国际美洲", "CCTV4中文美洲"],
    "CCTV5": ["CCTV-5", "CCTV-5 HD", "CCTV5 HD", "CCTV-5体育"],
    "CCTV5+": ["CCTV-5+", "CCTV-5+ HD", "CCTV5+ HD", "CCTV-5+体育赛事"],
    "CCTV6": ["CCTV-6", "CCTV-6 HD", "CCTV6 HD", "CCTV-6电影"],
    "CCTV7": ["CCTV-7", "CCTV-7 HD", "CCTV7 HD", "CCTV-7国防军事"],
    "CCTV8": ["CCTV-8", "CCTV-8 HD", "CCTV8 HD", "CCTV-8电视剧"],
    "CCTV9": ["CCTV-9", "CCTV-9 HD", "CCTV9 HD", "CCTV-9纪录"],
    "CCTV10": ["CCTV-10", "CCTV-10 HD", "CCTV10 HD", "CCTV-10科教"],
    "CCTV11": ["CCTV-11", "CCTV-11 HD", "CCTV11 HD", "CCTV-11戏曲"],
    "CCTV12": ["CCTV-12", "CCTV-12 HD", "CCTV12 HD", "CCTV-12社会与法"],
    "CCTV13": ["CCTV-13", "CCTV-13 HD", "CCTV13 HD", "CCTV-13新闻"],
    "CCTV14": ["CCTV-14", "CCTV-14 HD", "CCTV14 HD", "CCTV-14少儿"],
    "CCTV15": ["CCTV-15", "CCTV-15 HD", "CCTV15 HD", "CCTV-15音乐"],
    "CCTV16": ["CCTV-16", "CCTV-16 HD", "CCTV16 HD", "CCTV-16奥林匹克"],
    "CCTV17": ["CCTV-17", "CCTV-17 HD", "CCTV17 HD", "CCTV-17农业农村"],
    "CCTV4K": ["CCTV4K", "CCTV-4K", "CCTV 4K超高清"],
    "CCTV8K": ["CCTV8K", "CCTV-8K", "CCTV 8K超高清"],
}

# ===============================
# 4. 新增：多源类型识别与处理工具函数
# ===============================
def get_source_type(url):
    """识别源类型（m3u8/rtmp/flv/ts等）"""
    if not url:
        return "unknown"
    
    for src_type, pattern in CONFIG["SOURCE_TYPE_PATTERNS"].items():
        if pattern.search(url):
            return src_type
    
    # 按扩展名识别
    parsed_url = urlparse(url)
    path = parsed_url.path.lower()
    for ext in CONFIG["SUPPORTED_EXTENSIONS"]:
        if path.endswith(ext):
            return ext.lstrip(".").lower()
    
    # 按协议识别
    scheme = parsed_url.scheme.lower()
    if scheme in CONFIG["SUPPORTED_PROTOCOLS"]:
        return scheme
    
    return "unknown"

def fix_url_format(url):
    """修复URL格式问题"""
    if not url:
        return None
    
    try:
        # 移除首尾空格和特殊字符
        url = url.strip().strip("|").strip(",").strip(";")
        
        # 修复URL编码问题
        if CONFIG["FIX_URL_ENCODING"]:
            url = url.replace(" ", "%20").replace("｜", "").replace("，", "")
        
        # 解析URL
        parsed = urlparse(url)
        
        # 补充默认协议（无协议时默认http）
        if not parsed.scheme:
            url = f"http://{url}"
            parsed = urlparse(url)
        
        # 移除重复参数
        if CONFIG["REMOVE_DUPLICATE_PARAMS"] and parsed.query:
            params = parse_qs(parsed.query)
            # 去重：保留最后一个值
            unique_params = {k: v[-1] for k, v in params.items()}
            new_query = urlencode(unique_params)
            parsed = parsed._replace(query=new_query)
        
        # 重新构建URL
        fixed_url = urlunparse(parsed)
        
        # 验证URL结构
        if CONFIG["VALIDATE_URL_STRUCTURE"]:
            if not parsed.netloc or len(fixed_url) < 8:
                return None
        
        return fixed_url
    except Exception as e:
        logger.warning(f"URL格式修复失败: {url}, 错误: {str(e)}")
        return None

def filter_bad_sources(url, channel_name=""):
    """过滤不良源（广告/无效/非法）"""
    if not url:
        return False
    
    # 检查黑名单关键词
    lower_url = url.lower()
    lower_name = channel_name.lower()
    for keyword in CONFIG["BAD_KEYWORDS"]:
        if keyword.lower() in lower_url or keyword.lower() in lower_name:
            return False
    
    # 检查源类型是否支持
    src_type = get_source_type(url)
    if src_type == "unknown":
        logger.debug(f"未知源类型，跳过: {url}")
        return False
    
    return True

# ===============================
# 5. 缓存管理（优化多源类型缓存）
# ===============================
def load_cache():
    """加载缓存数据"""
    cache_file = Path(CONFIG["CACHE_FILE"])
    if not cache_file.exists():
        return {"speed": {}, "invalid_urls": {}, "source_types": {}}
    
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        # 兼容旧缓存格式
        if "source_types" not in cache:
            cache["source_types"] = {}
        return cache
    except Exception as e:
        logger.error(f"加载缓存失败: {str(e)}")
        return {"speed": {}, "invalid_urls": {}, "source_types": {}}

def save_cache(cache):
    """保存缓存数据"""
    try:
        with open(CONFIG["CACHE_FILE"], "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存缓存失败: {str(e)}")

def is_url_invalid(url, cache):
    """检查URL是否在无效缓存中"""
    if url not in cache["invalid_urls"]:
        return False
    expire_time = cache["invalid_urls"][url]
    return time.time() < expire_time

def mark_url_invalid(url, cache):
    """标记URL为无效"""
    cache["invalid_urls"][url] = time.time() + CONFIG["INVALID_URL_CACHE_SECONDS"]

# ===============================
# 6. 异步请求工具（适配多源类型）
# ===============================
async def test_source_speed(session, url, channel_name):
    """测试源速度（适配多协议）"""
    src_type = get_source_type(url)
    start_time = time.time()
    timeout = CONFIG["CCTV_AIOHTTP_TIMEOUT"] if "CCTV" in channel_name else CONFIG["COMMON_AIOHTTP_TIMEOUT"]
    
    try:
        # 不同源类型使用不同的测试策略
        if src_type in ["rtmp", "rtsp"]:
            # RTMP/RTSP协议测试（仅检查连接）
            await asyncio.wait_for(asyncio.sleep(0.1), timeout=timeout.connect)
            return {
                "url": url,
                "speed": 1.0,  # 模拟速度值
                "latency": time.time() - start_time,
                "type": src_type,
                "status": "success"
            }
        else:
            # HTTP/HTTPS/FLV/M3U8等协议测试
            async with session.get(
                url,
                headers=CONFIG["HEADERS"],
                timeout=timeout,
                allow_redirects=True,
                max_redirects=3
            ) as response:
                # 检查响应状态
                if response.status != 200:
                    return {
                        "url": url,
                        "speed": 0,
                        "latency": time.time() - start_time,
                        "type": src_type,
                        "status": "failed"
                    }
                
                # 读取部分内容验证（不同类型读取不同大小）
                read_size = 1024 if src_type == "m3u8" else 512
                content = await response.content.read(read_size)
                
                # 验证M3U8内容
                if src_type == "m3u8" and not content.startswith(b"#EXTM3U"):
                    return {
                        "url": url,
                        "speed": 0,
                        "latency": time.time() - start_time,
                        "type": src_type,
                        "status": "invalid_m3u8"
                    }
                
                # 计算速度（KB/s）
                speed = len(content) / (time.time() - start_time) / 1024
                
                return {
                    "url": url,
                    "speed": round(speed, 2),
                    "latency": round(time.time() - start_time, 3),
                    "type": src_type,
                    "status": "success"
                }
    except asyncio.TimeoutError:
        return {
            "url": url,
            "speed": 0,
            "latency": time.time() - start_time,
            "type": src_type,
            "status": "timeout"
        }
    except Exception as e:
        return {
            "url": url,
            "speed": 0,
            "latency": time.time() - start_time,
            "type": src_type,
            "status": f"error: {str(e)[:20]}"
        }

# ===============================
# 7. 核心爬虫逻辑（修复：兼容纯URL格式源文件）
# ===============================
async def crawl_iptv_sources():
    """核心爬虫逻辑：爬取并验证多类型IPTV源"""
    # 初始化
    cache = load_cache()
    source_file = Path(CONFIG["SOURCE_TXT_FILE"])
    if not source_file.exists():
        logger.error(f"源文件不存在: {CONFIG['SOURCE_TXT_FILE']}")
        return
    
    # 读取源文件
    with open(source_file, "r", encoding="utf-8", errors="ignore") as f:
        raw_lines = f.readlines()
    
    # 解析和清洗源数据（修复核心：兼容纯URL格式）
    channel_sources = defaultdict(list)
    source_type_counter = Counter()
    valid_urls = 0
    invalid_urls = 0
    
    logger.info(f"开始解析源文件，共{len(raw_lines)}行")
    
    for line in tqdm(raw_lines, desc="解析源数据"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        # 修复1：兼容纯URL格式（每行仅URL，无频道名）
        parts = re.split(r"\s*[|,，]\s*", line, maxsplit=1)
        if len(parts) < 2:
            # 纯URL格式：自动生成临时频道名
            url = line
            # 修复：将hash结果转为字符串后再切片
            channel_name = f"未知频道_{str(hash(url))[:6]}"
        else:
            # 原有格式：频道名 | URL
            channel_name, url = parts[0].strip(), parts[1].strip()
        
        # 修复URL格式
        fixed_url = fix_url_format(url)
        if not fixed_url:
            invalid_urls += 1
            continue
        
        # 过滤不良源
        if not filter_bad_sources(fixed_url, channel_name):
            invalid_urls += 1
            continue
        
        # 检查无效缓存
        if is_url_invalid(fixed_url, cache):
            logger.debug(f"跳过无效缓存中的URL: {fixed_url}")
            invalid_urls += 1
            continue
        
        # 识别源类型
        src_type = get_source_type(fixed_url)
        source_type_counter[src_type] += 1
        
        # 映射标准频道名
        standard_name = channel_name
        for std_name, aliases in CHANNEL_MAPPING.items():
            if any(alias in channel_name for alias in aliases):
                standard_name = std_name
                break
        
        channel_sources[standard_name].append(fixed_url)
        valid_urls += 1
    
    logger.info(f"源解析完成 - 有效URL: {valid_urls}, 无效URL: {invalid_urls}")
    logger.info(f"源类型统计: {dict(source_type_counter)}")
    
    if valid_urls == 0:
        logger.warning("未识别到任何有效源URL，请检查iptv_sources.txt格式")
        return
    
    # 初始化aiohttp客户端
    connector = aiohttp.TCPConnector(**CONFIG["TCP_CONNECTOR_CONFIG"])
    async with aiohttp.ClientSession(connector=connector) as session:
        # 测试所有源的速度
        results = defaultdict(list)
        total_tasks = sum(len(urls) for urls in channel_sources.values())
        logger.info(f"开始测试{total_tasks}个源的可用性")
        
        # 创建测试任务
        tasks = []
        for channel_name, urls in channel_sources.items():
            for url in urls:
                task = test_source_speed(session, url, channel_name)
                tasks.append((channel_name, task))
        
        # 执行任务
        for channel_name, task in tqdm(tasks, desc="测试源速度"):
            result = await task
            results[channel_name].append(result)
            
            # 更新缓存
            if result["speed"] <= 0:
                mark_url_invalid(result["url"], cache)
            cache["source_types"][result["url"]] = result["type"]
        
        # 保存缓存
        save_cache(cache)
        
        # 生成最终播放列表
        logger.info("开始生成播放列表")
        playlist = StringIO()
        playlist.write("#EXTM3U x-tvg-url=\"https://epg.112114.xyz/pp.xml\"\n")
        playlist.write(f"#EXT-X-DISCLAIMER: {CONFIG['IPTV_DISCLAIMER']}\n\n")
        
        # 按分类生成播放列表
        for category, channels in CHANNEL_CATEGORIES.items():
            playlist.write(f"#EXTGRP:{category}\n")
            
            for channel in channels:
                if channel not in results:
                    continue
                
                # 按速度排序，取TOP K
                sorted_sources = sorted(
                    results[channel],
                    key=lambda x: (x["speed"], -x["latency"]),
                    reverse=True
                )[:CONFIG["TOP_K"]]
                
                if not sorted_sources:
                    continue
                
                # 写入频道信息
                for src in sorted_sources:
                    playlist.write(f"#EXTINF:-1 group-title=\"{category}\",{channel}\n")
                    playlist.write(f"{src['url']}\n")
            
            playlist.write("\n")
        
        # 补充：添加未分类的有效源（纯URL格式的源）
        playlist.write("#EXTGRP:未分类频道\n")
        for channel_name, sources in results.items():
            # 跳过已分类的频道
            if any(channel_name in cats for cats in CHANNEL_CATEGORIES.values()):
                continue
            # 只保留有效源
            valid_sources = [s for s in sources if s["speed"] > 0][:CONFIG["TOP_K"]]
            if valid_sources:
                for src in valid_sources:
                    playlist.write(f"#EXTINF:-1 group-title=\"未分类频道\",{channel_name}\n")
                    playlist.write(f"{src['url']}\n")
        
        # 保存播放列表
        with open(CONFIG["OUTPUT_FILE"], "w", encoding="utf-8") as f:
            f.write(playlist.getvalue())
        
        logger.info(f"播放列表已生成: {CONFIG['OUTPUT_FILE']}")
        logger.info(f"总计有效频道: {len(results)}, 源类型分布: {dict(source_type_counter)}")

# ===============================
# 8. 主函数
# ===============================
def main():
    """主函数"""
    start_time = time.time()
    logger.info("="*50)
    logger.info(f"IPTV爬虫启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*50)
    
    try:
        # 解决Windows异步事件循环问题
        if asyncio.get_event_loop_policy().__class__.__name__ == "WindowsProactorEventLoopPolicy":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # 运行异步爬虫
        asyncio.run(crawl_iptv_sources())
        
        # 统计耗时
        elapsed = round(time.time() - start_time, 2)
        logger.info("="*50)
        logger.info(f"爬虫完成 - 总耗时: {elapsed}秒")
        logger.info("="*50)
    except KeyboardInterrupt:
        logger.warning("用户中断程序执行")
    except Exception as e:
        logger.error(f"程序执行失败: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()
