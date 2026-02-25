import re
import json
import time
import asyncio
import aiohttp
import logging
import fnmatch
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from tqdm import tqdm  # 进度条库

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
# 2. 全局配置优化（高性能并发+精准超时）
# ===============================
# 核心优化：TCP连接器参数调优，禁用DNS缓存，提升连接速度
TCP_CONNECTOR_CONFIG = {
    "limit": 200,  # 全局并发连接数（从80→200，提升批量请求效率）
    "limit_per_host": 30,  # 单域名并发（从15→30，适配CCTV等集中域名）
    "ttl_dns_cache": 0,  # 禁用DNS缓存，避免解析延迟
    "verify_ssl": False,  # 跳过SSL验证（非敏感请求，大幅提升速度）
}

# 🌟 新增：CCTV频道专属超时配置（可独立调整）
CCTV_AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(
    connect=4,  # CCTV频道连接超时（比通用配置稍长，适配官方源稳定性）
    sock_read=8,  # CCTV频道读取超时
    total=12,     # CCTV频道总超时
)

# 通用频道超时配置（原配置）
COMMON_AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(
    connect=3,  # 连接超时（从5→3，无效链接快速失败）
    sock_read=4,  # 读取超时（从6→5，平衡速度和成功率）
    total=6,  # 总超时（从10→8，减少整体等待时间）
)

CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",
    "OUTPUT_FILE": "iptv_playlist.m3u8",
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "keep-alive",  # 优化：长连接，减少握手耗时
        "Accept-Encoding": "gzip, deflate",  # 压缩传输，减少数据量
    },
    "TOP_K": 3,
    "IPTV_DISCLAIMER": "个人自用，请勿用于商业用途",
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo",
    "CACHE_FILE": "iptv_speed_cache.json",
    "CACHE_EXPIRE_SECONDS": 1800,  # 缓存有效期30分钟
    "BAD_KEYWORDS": ["ad", "advertising", "spam"],
    "CCTV_AIOHTTP_TIMEOUT": CCTV_AIOHTTP_TIMEOUT,
    "COMMON_AIOHTTP_TIMEOUT": COMMON_AIOHTTP_TIMEOUT,
    "TCP_CONNECTOR_CONFIG": TCP_CONNECTOR_CONFIG,
    "INVALID_URL_CACHE_SECONDS": 300,
}

# ===============================
# 3. 频道分类与别名映射（修复冗余正则+增强CCTV匹配）
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
# 4. 新增：CCTV频道精准匹配工具函数（核心修复）
# ===============================
def is_cctv_channel(channel_name: str) -> bool:
    """
    精准判断是否为CCTV频道（兼容别名/变体）
    :param channel_name: 频道名称
    :return: 是否为CCTV频道
    """
    if not channel_name:
        return False
    channel_name = channel_name.strip().upper()
    # 方式1：匹配CHANNEL_MAPPING中的所有别名
    for cctv_main, aliases in CHANNEL_MAPPING.items():
        if channel_name == cctv_main.upper() or any(alias.upper() == channel_name for alias in aliases):
            return True
    # 方式2：匹配央视频道分类中的基础名称
    if channel_name in [name.upper() for name in CHANNEL_CATEGORIES["央视频道"]]:
        return True
    # 方式3：模糊匹配（兼容非标准命名，如"CCTV 1综合"）
    if re.search(r'CCTV\s*[1-9]|CCTV\s*1[0-7]|CCTV\s*4K|CCTV\s*8K', channel_name):
        return True
    # 方式4：匹配"央视"中文变体
    if "央视" in channel_name or "中央电视台" in channel_name:
        return True
    return False

def extract_channel_info(line: str) -> tuple[str, str]:
    """
    提取M3U格式中的频道名称和播放地址
    :param line: M3U行内容
    :return: (频道名称, 播放地址)
    """
    # 匹配#EXTINF行 + 播放地址
    extinf_pattern = re.compile(r'#EXTINF:.*?,\s*(.*?)\s*\n(https?://.*?)\s*', re.IGNORECASE | re.MULTILINE)
    match = extinf_pattern.search(line)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    # 纯文本格式（仅播放地址）
    if line.strip().startswith(('http://', 'https://')):
        return "", line.strip()
    return "", ""

# ===============================
# 5. 缓存管理（原功能保留）
# ===============================
def load_speed_cache():
    """加载速度缓存"""
    cache_file = Path(CONFIG["CACHE_FILE"])
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        # 清理过期缓存
        now = time.time()
        valid_cache = {
            url: data for url, data in cache.items()
            if now - data["timestamp"] < CONFIG["CACHE_EXPIRE_SECONDS"]
        }
        return valid_cache
    except Exception as e:
        logger.error(f"加载缓存失败: {e}")
        return {}

def save_speed_cache(cache: dict):
    """保存速度缓存"""
    try:
        with open(CONFIG["CACHE_FILE"], 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存缓存失败: {e}")

# ===============================
# 6. 异步请求核心逻辑（原功能保留+CCTV超时适配）
# ===============================
async def fetch_url(session: aiohttp.ClientSession, url: str, is_cctv: bool = False) -> tuple[str, str]:
    """
    异步请求URL内容
    :param session: aiohttp会话
    :param url: 请求地址
    :param is_cctv: 是否为CCTV频道（适配专属超时）
    :return: (原始内容, 错误信息)
    """
    try:
        timeout = CONFIG["CCTV_AIOHTTP_TIMEOUT"] if is_cctv else CONFIG["COMMON_AIOHTTP_TIMEOUT"]
        async with session.get(
            url,
            headers=CONFIG["HEADERS"],
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            # 自动识别编码
            if response.charset is None or response.charset == 'ISO-8859-1':
                content = await response.read()
                try:
                    return content.decode('utf-8'), ""
                except:
                    return content.decode('gbk', errors='ignore'), ""
            else:
                return await response.text(), ""
    except Exception as e:
        return "", str(e)

async def process_source_url(session: aiohttp.ClientSession, url: str, progress: tqdm) -> list[tuple[str, str]]:
    """
    处理单个源URL，提取有效频道
    :param session: aiohttp会话
    :param url: 源地址
    :param progress: 进度条
    :return: 有效频道列表 [(频道名称, 播放地址)]
    """
    valid_channels = []
    content, error = await fetch_url(session, url)
    if error:
        logger.warning(f"请求源失败 {url}: {error}")
        progress.update(1)
        return valid_channels
    
    # 按行解析M3U内容
    lines = content.split('\n')
    current_extinf = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 过滤广告关键词
        if any(keyword in line.lower() for keyword in CONFIG["BAD_KEYWORDS"]):
            continue
        # 匹配EXTINF行（频道元数据）
        if line.startswith('#EXTINF:'):
            current_extinf = line
            continue
        # 匹配播放地址行
        if line.startswith(('http://', 'https://')):
            channel_name, _ = extract_channel_info(f"{current_extinf}\n{line}")
            # 核心修复：优先提取CCTV频道
            if is_cctv_channel(channel_name) or is_cctv_channel(line):
                # 补充CCTV频道名称（避免空名称）
                if not channel_name:
                    channel_name = f"CCTV_未知频道_{hash(line)[:6]}"
                valid_channels.append((channel_name, line))
            # 保留原逻辑：非CCTV频道也正常处理
            else:
                if channel_name:
                    valid_channels.append((channel_name, line))
            current_extinf = ""
    
    progress.update(1)
    return valid_channels

# ===============================
# 7. 主逻辑（原功能保留+CCTV频道优先输出）
# ===============================
async def main():
    """主执行函数"""
    # 1. 读取源文件
    source_file = Path(CONFIG["SOURCE_TXT_FILE"])
    if not source_file.exists():
        logger.error(f"源文件不存在: {source_file.absolute()}")
        return
    
    with open(source_file, 'r', encoding='utf-8') as f:
        source_urls = [line.strip() for line in f if line.strip().startswith(('http://', 'https://'))]
    
    if not source_urls:
        logger.warning("源文件中无有效URL")
        return
    
    # 2. 初始化异步会话
    connector = aiohttp.TCPConnector(**CONFIG["TCP_CONNECTOR_CONFIG"])
    async with aiohttp.ClientSession(connector=connector) as session:
        # 3. 批量处理源URL
        progress = tqdm(total=len(source_urls), desc="处理源地址", unit="个")
        tasks = [process_source_url(session, url, progress) for url in source_urls]
        results = await asyncio.gather(*tasks)
        progress.close()
    
    # 4. 合并结果并去重
    all_channels = []
    seen = set()
    for channels in results:
        for name, url in channels:
            key = (name.strip(), url.strip())
            if key not in seen:
                seen.add(key)
                all_channels.append(key)
    
    # 5. 分离CCTV频道和非CCTV频道（CCTV优先输出）
    cctv_channels = [ch for ch in all_channels if is_cctv_channel(ch[0])]
    other_channels = [ch for ch in all_channels if not is_cctv_channel(ch[0])]
    logger.info(f"提取到CCTV频道 {len(cctv_channels)} 个，其他频道 {len(other_channels)} 个")
    
    # 6. 生成M3U8文件（CCTV频道优先）
    output_file = Path(CONFIG["OUTPUT_FILE"])
    with StringIO() as sio, open(output_file, 'w', encoding='utf-8') as f:
        # M3U8头部
        sio.write("#EXTM3U x-tvg-url=\"https://epg.112114.xyz/pp.xml\"\n")
        sio.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        sio.write(f"# {CONFIG['IPTV_DISCLAIMER']}\n\n")
        
        # 优先写入CCTV频道
        sio.write("# ========== 央视频道（CCTV） ==========\n")
        for name, url in cctv_channels:
            sio.write(f"#EXTINF:-1 tvg-name=\"{name}\" group-title=\"央视频道\",{name}\n")
            sio.write(f"{url}\n")
        
        # 写入其他频道（保留原分类）
        sio.write("\n# ========== 其他频道 ==========\n")
        for name, url in other_channels:
            # 匹配分类
            group_title = "其他频道"
            for cat, chs in CHANNEL_CATEGORIES.items():
                if name in chs or any(alias in name for alias in CHANNEL_MAPPING.get(name, [])):
                    group_title = cat
                    break
            sio.write(f"#EXTINF:-1 tvg-name=\"{name}\" group-title=\"{group_title}\",{name}\n")
            sio.write(f"{url}\n")
        
        # 写入文件
        f.write(sio.getvalue())
    
    logger.info(f"生成完成！文件路径: {output_file.absolute()}")
    logger.info(f"总频道数: {len(all_channels)} (CCTV: {len(cctv_channels)}, 其他: {len(other_channels)})")

# ===============================
# 8. 入口函数（原功能保留）
# ===============================
if __name__ == "__main__":
    # 解决Windows异步事件循环问题
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 执行主逻辑
    start_time = time.time()
    asyncio.run(main())
    logger.info(f"程序总耗时: {time.time() - start_time:.2f} 秒")
