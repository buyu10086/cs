import re
import json
import time
import asyncio
import aiohttp
import logging
import fnmatch
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
    "limit_per_host": 25,  # 单域名并发（从15→30，适配CCTV等集中域名）
    "ttl_dns_cache": 0,  # 禁用DNS缓存，避免解析延迟
    "ssl": False,  # 跳过SSL验证（非敏感请求，大幅提升速度）
}

# 超时配置优化：区分连接/读取超时，减少无效等待
AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(
    connect=4,  # 连接超时（从5→3，无效链接快速失败）
    sock_read=5,  # 读取超时（从6→5，平衡速度和成功率）
    total=9,  # 总超时（从10→8，减少整体等待时间）
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
    "AIOHTTP_TIMEOUT": AIOHTTP_TIMEOUT,
    "TCP_CONNECTOR_CONFIG": TCP_CONNECTOR_CONFIG,
    # 新增：无效链接短期缓存（5分钟内不重复测试）
    "INVALID_URL_CACHE_SECONDS": 300,
}

# ===============================
# 3. 频道分类与别名映射（保持不变）
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
    "CCTV15": ["CCTV15", "CCTV-15 HD", "CCTV15 HD", "CCTV-15音乐"],
    "CCTV16": ["CCTV16", "CCTV-16 HD", "CCTV-16 4K", "CCTV-16奥林匹克", "CCTV16 4K", "CCTV16奥林匹克4K"],
    "CCTV17": ["CCTV17", "CCTV-17 HD", "CCTV17 HD", "CCTV17农业农村"],
    "CCTV4K": ["CCTV4K超高清", "CCTV-4K超高清", "CCTV-4K 超高清", "CCTV 4K"],
    "CCTV8K": ["CCTV8K超高清", "CCTV-8K超高清", "CCTV-8K 超高清", "CCTV 8K"],
    "兵器科技": ["CCTV-兵器科技", "CCTV兵器科技"],
    "风云音乐": ["CCTV-风云音乐", "CCTV风云音乐"],
    "第一剧场": ["CCTV-第一剧场", "CCTV第一剧场"],
    "风云足球": ["CCTV-风云足球", "CCTV风云足球"],
    "风云剧场": ["CCTV-风云剧场", "CCTV风云剧场"],
    "怀旧剧场": ["CCTV-怀旧剧场", "CCTV怀旧剧场"],
    "女性时尚": ["CCTV-女性时尚", "CCTV女性时尚"],
    "世界地理": ["CCTV-世界地理", "CCTV世界地理"],
    "央视台球": ["CCTV-央视台球", "CCTV央视台球"],
    "高尔夫网球": ["CCTV-高尔夫网球", "CCTV高尔夫网球", "CCTV央视高网", "CCTV-高尔夫·网球", "央视高网"],
    "央视文化精品": ["CCTV-央视文化精品", "CCTV央视文化精品", "CCTV文化精品", "CCTV-文化精品", "文化精品"],
    "卫生健康": ["CCTV-卫生健康", "CCTV卫生健康"],
    "电视指南": ["CCTV-电视指南", "CCTV电视指南"],
    "农林卫视": ["陕西农林卫视"],
    "三沙卫视": ["海南三沙卫视"],
    "兵团卫视": ["新疆兵团卫视"],
    "延边卫视": ["吉林延边卫视"],
    "安多卫视": ["青海安多卫视"],
    "康巴卫视": ["四川康巴卫视"],
    "山东教育卫视": ["山东教育"],
    "中国教育1台": ["CETV1", "中国教育一台", "中国教育1", "CETV-1 综合教育", "CETV-1"],
    "中国教育2台": ["CETV2", "中国教育二台", "中国教育2", "CETV-2 空中课堂", "CETV-2"],
    "中国教育3台": ["CETV3", "中国教育三台", "中国教育3", "CETV-3 教育服务", "CETV-3"],
    "中国教育4台": ["CETV4", "中国教育四台", "中国教育4", "CETV-4 职业教育", "CETV-4"],
    "早期教育": ["中国教育5台", "中国教育五台", "CETV早期教育", "华电早期教育", "CETV 早期教育"],
    "湖南卫视": ["湖南卫视4K"],
    "北京卫视": ["北京卫视4K"],
    "东方卫视": ["东方卫视4K"],
    "广东卫视": ["广东卫视4K"],
    "深圳卫视": ["深圳卫视4K"],
    "山东卫视": ["山东卫视4K"],
    "四川卫视": ["四川卫视4K"],
    "浙江卫视": ["浙江卫视4K"],
    "CHC影迷电影": ["CHC高清电影", "CHC-影迷电影", "影迷电影", "chc高清电影"],
    "淘电影": ["IPTV淘电影", "北京IPTV淘电影", "北京淘电影"],
    "淘精彩": ["IPTV淘精彩", "北京IPTV淘精彩", "北京淘精彩"],
    "淘剧场": ["IPTV淘剧场", "北京IPTV淘剧场", "北京淘剧场"],
    "淘4K": ["IPTV淘4K", "北京IPTV4K超清", "北京淘4K", "淘4K", "淘 4K"],
    "淘娱乐": ["IPTV淘娱乐", "北京IPTV淘娱乐", "北京淘娱乐"],
    "淘BABY": ["IPTV淘BABY", "北京IPTV淘BABY", "北京淘BABY", "IPTV淘baby", "北京IPTV淘baby", "北京淘baby"],
    "淘萌宠": ["IPTV淘萌宠", "北京IPTV萌宠TV", "北京淘萌宠"],
    "魅力足球": ["上海魅力足球"],
    "睛彩青少": ["睛彩羽毛球"],
    "求索纪录": ["求索记录", "求索纪录4K", "求索记录4K", "求索纪录 4K", "求索记录 4K"],
    "金鹰纪实": ["湖南金鹰纪实", "金鹰记实"],
    "纪实科教": ["北京纪实科教", "BRTV纪实科教", "纪实科教8K"],
    "星空卫视": ["星空衛視", "星空衛視", "星空卫視"],
    "CHANNEL[V]": ["CHANNEL-V", "Channel[V]"],
    "凤凰卫视中文台": ["凤凰中文", "凤凰中文台", "凤凰卫视中文", "凤凰卫视"],
    "凤凰卫视香港台": ["凤凰香港台", "凤凰卫视香港", "凤凰香港"],
    "凤凰卫视资讯台": ["凤凰资讯", "凤凰资讯台", "凤凰咨询", "凤凰咨询台", "凤凰卫视咨询台", "凤凰卫视资讯", "凤凰卫视咨询"],
    "凤凰卫视电影台": ["凤凰电影", "凤凰电影台", "凤凰卫视电影", "鳳凰衛視電影台", " 凤凰电影"],
    "茶频道": ["湖南茶频道"],
    "快乐垂钓": ["湖南快乐垂钓"],
    "先锋乒羽": ["湖南先锋乒羽"],
    "天元围棋": ["天元围棋频道"],
    "汽摩": ["重庆汽摩", "汽摩频道", "重庆汽摩频道"],
    "梨园频道": ["河南梨园频道", "梨园", "河南梨园"],
    "文物宝库": ["河南文物宝库"],
    "武术世界": ["河南武术世界"],
    "乐游": ["乐游频道", "上海乐游频道", "乐游纪实", "SiTV乐游频道", "SiTV 乐游频道"],
    "欢笑剧场": ["上海欢笑剧场4K", "欢笑剧场 4K", "欢笑剧场4K", "上海欢笑剧场"],
    "生活时尚": ["生活时尚4K", "SiTV生活时尚", "上海生活时尚"],
    "都市剧场": ["都市剧场4K", "SiTV都市剧场", "上海都市剧场"],
    "游戏风云": ["游戏风云4K", "SiTV游戏风云", "上海游戏风云"],
    "金色学堂": ["金色学堂4K", "SiTV金色学堂", "上海金色学堂"],
    "动漫秀场": ["动漫秀场4K", "SiTV动漫秀场", "上海动漫秀场"],
    "卡酷少儿": ["北京KAKU少儿", "BRTV卡酷少儿", "北京卡酷少儿", "卡酷动画"],
    "哈哈炫动": ["炫动卡通", "上海哈哈炫动"],
    "优漫卡通": ["江苏优漫卡通", "优漫漫画"],
    "金鹰卡通": ["湖南金鹰卡通"],
    "中国交通": ["中国交通频道"],
    "中国天气": ["中国天气频道"],
    "华数4K": ["华数低于4K", "华数4K电影", "华数爱上4K"]
}

# ===============================
# 4. 预加载优化（保持不变）
# ===============================
ZUBO_SKIP_PATTERN = re.compile(r"^(更新时间|.*,#genre#|http://kakaxi\.indevs\.in/LOGO/)")
ZUBO_CHANNEL_PATTERN = re.compile(r"^([^,]+),(http://.+?)(\$.*)?$")
M3U_HEADER_PATTERN = re.compile(r"^#EXTM3U", re.IGNORECASE)
JSON_START_PATTERN = re.compile(r"^\s*\{|\s*\[")

GLOBAL_ALIAS_MAP = None
ALL_CATEGORIZED_CHANNELS = set()
for category_ch_list in CHANNEL_CATEGORIES.values():
    ALL_CATEGORIZED_CHANNELS.update(category_ch_list)

RANK_TAGS = ["$最优", "$次优", "$三优"]

# ===============================
# 5. 核心优化工具函数（性能重点优化）
# ===============================
def load_speed_cache():
    """加载缓存（优化：懒加载，减少IO）"""
    cache_file = Path(CONFIG["CACHE_FILE"])
    if not cache_file.exists():
        return {"valid": {}, "invalid": {}}  # 拆分有效/无效缓存
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 兼容旧缓存格式
            if not isinstance(data, dict) or "valid" not in data:
                return {"valid": data, "invalid": {}}
            return data
    except Exception as e:
        logger.error(f"加载缓存失败：{e}")
        return {"valid": {}, "invalid": {}}

def save_speed_cache(cache_data):
    """保存缓存（优化：批量保存，减少IO次数）"""
    try:
        with open(CONFIG["CACHE_FILE"], "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=0)  # 无缩进，减少文件大小
    except Exception as e:
        logger.error(f"保存缓存失败：{e}")

def is_url_valid(url):
    """过滤规则（保持放宽，仅过滤垃圾关键词）"""
    if any(keyword in url.lower() for keyword in CONFIG["BAD_KEYWORDS"]):
        return False
    return True

def detect_source_format(content, url):
    """自动识别源格式（保持不变）"""
    url_lower = url.lower()
    if fnmatch.fnmatch(url_lower, "*.txt") or CONFIG["ZUBO_SOURCE_MARKER"] in url:
        return "txt"
    elif fnmatch.fnmatch(url_lower, "*.m3u") or fnmatch.fnmatch(url_lower, "*.m3u8"):
        return "m3u8"
    elif fnmatch.fnmatch(url_lower, "*.json"):
        return "json"
    
    if M3U_HEADER_PATTERN.match(content):
        return "m3u8"
    elif JSON_START_PATTERN.match(content):
        return "json"
    elif ZUBO_CHANNEL_PATTERN.search(content):
        return "txt"
    
    return "unknown"

def build_alias_map():
    """构建别名映射（缓存，仅构建一次）"""
    global GLOBAL_ALIAS_MAP
    if GLOBAL_ALIAS_MAP is not None:
        return GLOBAL_ALIAS_MAP
    
    alias_map = {name: name for name in CHANNEL_MAPPING.keys()}
    for main_name, aliases in CHANNEL_MAPPING.items():
        for alias in aliases:
            alias_map[alias] = main_name
    
    GLOBAL_ALIAS_MAP = alias_map
    return GLOBAL_ALIAS_MAP

# 核心优化1：测速函数（批量处理+缓存精准复用）
async def test_single_url_async(url, session, cache_data):
    """异步测速：优化缓存逻辑，无效链接短期不重复测试"""
    now = time.time()
    
    # 1. 先检查无效链接缓存（5分钟内不重复测试）
    if url in cache_data["invalid"]:
        if now - cache_data["invalid"][url] < CONFIG["INVALID_URL_CACHE_SECONDS"]:
            return (url, float('inf'))
    
    # 2. 检查有效链接缓存（30分钟有效期）
    if url in cache_data["valid"]:
        cache_info = cache_data["valid"][url]
        if now - cache_info["timestamp"] < CONFIG["CACHE_EXPIRE_SECONDS"]:
            return (url, cache_info["latency"])
    
    # 3. 执行测速（HEAD请求，优化超时）
    try:
        start_time = time.time()
        async with session.head(
            url,
            timeout=CONFIG["AIOHTTP_TIMEOUT"],
            allow_redirects=True,
            headers=CONFIG["HEADERS"]
        ) as response:
            latency = round(time.time() - start_time, 2)
            # 更新有效缓存
            cache_data["valid"][url] = {"latency": latency, "timestamp": now}
            return (url, latency)
    except Exception:
        # 更新无效缓存（短期不重复测试）
        cache_data["invalid"][url] = now
        return (url, float('inf'))

# 核心优化2：批量测速（分批次处理，避免任务堆积）
async def test_urls_async(urls, cache_data):
    """异步批量测速：分批次处理，提升并发效率"""
    if not urls:
        return {}
    
    # 全局去重 + 过滤垃圾链接
    unique_urls = list({url for url in urls if is_url_valid(url)})
    if not unique_urls:
        return {}
    
    # 分批次处理（每批100个，避免任务过多导致调度耗时）
    batch_size = 100
    batches = [unique_urls[i:i+batch_size] for i in range(0, len(unique_urls), batch_size)]
    
    result_dict = {}
    # 复用TCP连接器，减少创建开销
    connector = aiohttp.TCPConnector(**CONFIG["TCP_CONNECTOR_CONFIG"])
    async with aiohttp.ClientSession(connector=connector) as session:
        for batch in batches:
            tasks = [test_single_url_async(url, session, cache_data) for url in batch]
            results = await asyncio.gather(*tasks)
            for url, latency in results:
                if latency < float('inf'):
                    result_dict[url] = latency
    
    # 批量保存缓存（减少IO次数）
    save_speed_cache(cache_data)
    return result_dict

# 核心优化3：爬取函数（异步批量爬取，减少IO）
async def crawl_and_merge_sources():
    """异步爬取：优化连接池，批量处理"""
    all_raw_channels = defaultdict(set)
    source_urls = read_iptv_sources_from_txt()
    if not source_urls:
        return all_raw_channels

    # 优化TCP连接器，提升爬取速度
    connector = aiohttp.TCPConnector(**CONFIG["TCP_CONNECTOR_CONFIG"])
    async with aiohttp.ClientSession(connector=connector) as session:
        # 批量爬取（并发处理所有源）
        tasks = []
        for source_url in source_urls:
            task = asyncio.create_task(_crawl_single_source(source_url, session))
            tasks.append(task)
        
        # 收集所有源的结果
        for task in asyncio.as_completed(tasks):
            source_channels = await task
            for std_ch, urls in source_channels.items():
                all_raw_channels[std_ch].update(urls)

    # 转换为列表（减少后续转换耗时）
    result = {k: list(v) for k, v in all_raw_channels.items()}
    if not result:
        logger.error("未爬取到任何频道数据")
    return result

async def _crawl_single_source(source_url, session):
    """爬取单个源：独立函数，便于批量处理"""
    try:
        async with session.get(
            source_url,
            timeout=CONFIG["AIOHTTP_TIMEOUT"],
            headers=CONFIG["HEADERS"],
            compress=True  # 启用压缩，减少数据传输耗时
        ) as response:
            response.encoding = "utf-8"
            content = await response.text()
        
        source_format = detect_source_format(content, source_url)
        if source_format == "txt":
            return parse_zubo_source(content)
        elif source_format == "m3u8":
            return parse_standard_m3u8(content)
        elif source_format == "json":
            return parse_json_source(content)
        else:
            logger.warning(f"不支持的源格式：{source_format}，跳过 {source_url}")
            return {}
    except Exception as e:
        logger.error(f"爬取失败 {source_url}：{e}")
        return {}

# 其余解析函数（保持不变，仅优化数据结构）
def parse_zubo_source(content):
    """解析txt源：优化集合操作"""
    zubo_channels = {}
    alias_map = build_alias_map()
    lines = content.splitlines()

    for line in lines:
        line = line.strip()
        if not line or ZUBO_SKIP_PATTERN.match(line):
            continue
        
        match = ZUBO_CHANNEL_PATTERN.match(line)
        if not match:
            continue
        
        ch_name = match.group(1).strip()
        play_url = match.group(2).strip()
        
        if not is_url_valid(play_url):
            continue
        
        std_ch = alias_map.get(ch_name, ch_name)
        if std_ch not in zubo_channels:
            zubo_channels[std_ch] = set()
        zubo_channels[std_ch].add(play_url)
    
    return {k: list(v) for k, v in zubo_channels.items()}

def parse_standard_m3u8(content):
    """解析m3u8源：优化遍历逻辑"""
    m3u8_channels = {}
    alias_map = build_alias_map()
    lines = content.splitlines()
    current_ch = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            ch_match = re.search(r",(.*)$", line)
            current_ch = ch_match.group(1).strip() if ch_match else None
        elif line.startswith(("http://", "https://")) and current_ch:
            if not is_url_valid(line):
                continue
            std_ch = alias_map.get(current_ch, current_ch)
            if std_ch not in m3u8_channels:
                m3u8_channels[std_ch] = set()
            m3u8_channels[std_ch].add(line)
            current_ch = None
    
    return {k: list(v) for k, v in m3u8_channels.items()}

def parse_json_source(content):
    """解析JSON源：保持不变"""
    json_channels = {}
    alias_map = build_alias_map()
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict) or "name" not in item or "url" not in item:
                    continue
                ch_name = item["name"].strip()
                play_url = item["url"].strip()
                if not is_url_valid(play_url):
                    continue
                std_ch = alias_map.get(ch_name, ch_name)
                if std_ch not in json_channels:
                    json_channels[std_ch] = set()
                json_channels[std_ch].add(play_url)
        return {k: list(v) for k, v in json_channels.items()}
    except Exception as e:
        logger.error(f"JSON源解析失败：{e}")
        return {}

def read_iptv_sources_from_txt():
    """读取源链接：优化IO，一次性读取"""
    txt_path = Path(CONFIG["SOURCE_TXT_FILE"])
    valid_urls_set = set()

    if not txt_path.exists():
        logger.warning(f"未找到 {txt_path.name}，创建模板文件")
        template = f"# 每行填写1个IPTV源链接（支持txt/m3u/m3u8/json格式）\n# 示例：https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/main/tv/iptv4.m3u\n# 可添加注释（以#开头），空行会自动跳过\n"
        txt_path.write_text(template, encoding="utf-8")
        return list(valid_urls_set)

    try:
        # 一次性读取所有行，减少IO次数
        with open(txt_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("http://", "https://")):
                valid_urls_set.add(line)
            else:
                logger.warning(f"第{line_num}行无效（非http链接）：{line}")
        
        valid_urls = list(valid_urls_set)
        logger.info(f"读取完成：共 {len(valid_urls)} 个有效IPTV源")
    except Exception as e:
        logger.error(f"读取文件失败：{e}")
        valid_urls = []
    
    return valid_urls

# 核心优化4：筛选最优源（减少排序耗时）
async def crawl_and_select_top3():
    """爬取+筛选：优化排序逻辑，减少计算耗时"""
    all_channels = {}
    raw_channels = await crawl_and_merge_sources()
    if not raw_channels:
        return all_channels

    logger.info(f"开始异步测速（共{len(raw_channels)}个频道，并发数：{CONFIG['TCP_CONNECTOR_CONFIG']['limit']}）")
    valid_channel_count = 0
    top_k = CONFIG["TOP_K"]
    cache_data = load_speed_cache()

    # 进度条优化：减少刷新频率
    pbar = tqdm(
        raw_channels.items(), 
        total=len(raw_channels),
        desc="📡 频道测速中",
        unit="频道",
        ncols=100,
        colour="green",
        mininterval=0.5  # 最少0.5秒刷新一次，减少IO
    )

    for ch_name, urls in pbar:
        pbar.set_postfix({"当前频道": ch_name[:15] + "..." if len(ch_name) > 15 else ch_name})
        
        if len(urls) == 0:
            continue

        # 批量测速
        latency_dict = await test_urls_async(urls, cache_data)
        if not latency_dict:
            continue

        # 优化排序：仅取前top_k个，减少排序数据量
        sorted_items = sorted(latency_dict.items(), key=lambda x: x[1])[:top_k]
        top3_urls = [url for url, _ in sorted_items]
        all_channels[ch_name] = top3_urls
        valid_channel_count += 1

    pbar.close()
    logger.info(f"测速完成：共筛选出 {valid_channel_count} 个有效频道")
    return all_channels

# 生成播放列表（保持不变，减少IO）
def generate_iptv_playlist(top3_channels):
    """生成播放列表：一次性写入，减少IO次数"""
    if not top3_channels:
        logger.error("无有效频道，无法生成播放列表")
        return

    output_path = Path(CONFIG["OUTPUT_FILE"])
    beijing_now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    playlist_content = [
        f"更新时间: {beijing_now}（北京时间）",
        "",
        "更新时间,#genre#",
        f"{beijing_now},{CONFIG['IPTV_DISCLAIMER']}",
        ""
    ]
    top_k = CONFIG["TOP_K"]

    # 按分类写入
    for category, ch_list in CHANNEL_CATEGORIES.items():
        playlist_content.append(f"{category},#genre#")
        for std_ch in ch_list:
            if std_ch not in top3_channels:
                continue
            urls = top3_channels[std_ch]
            for idx, url in enumerate(urls):
                if idx >= top_k:
                    break
                tag = RANK_TAGS[idx] if idx < len(RANK_TAGS) else f"$第{idx+1}优"
                playlist_content.append(f"{std_ch},{url}{tag}")
        playlist_content.append("")

    # 未分类频道
    other_channels = [ch for ch in top3_channels if ch not in ALL_CATEGORIZED_CHANNELS]
    if other_channels:
        playlist_content.append("其它频道,#genre#")
        for std_ch in other_channels:
            urls = top3_channels[std_ch]
            for idx, url in enumerate(urls):
                if idx >= top_k:
                    break
                tag = RANK_TAGS[idx] if idx < len(RANK_TAGS) else f"$第{idx+1}优"
                playlist_content.append(f"{std_ch},{url}{tag}")
        playlist_content.append("")

    # 一次性写入文件，减少IO次数
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(playlist_content).rstrip("\n"))
        logger.info(f"成功生成播放列表：{output_path.absolute()}")
    except Exception as e:
        logger.error(f"生成文件失败：{e}")

# ===============================
# 6. 主执行逻辑（优化事件循环）
# ===============================
if __name__ == "__main__":
    start_time = time.time()
    logger.info("="*70)
    logger.info("📺 IPTV直播源爬取")
    logger.info(f"🎯 并发数：{CONFIG['TCP_CONNECTOR_CONFIG']['limit']} | 单域名并发：{CONFIG['TCP_CONNECTOR_CONFIG']['limit_per_host']}")
    logger.info("="*70)
    
    build_alias_map()
    
    try:
        # 优化事件循环（适配不同系统）
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except:
            pass
        
        top3_channels = asyncio.run(crawl_and_select_top3())
        generate_iptv_playlist(top3_channels)
        
        # 输出总耗时
        total_time = round(time.time() - start_time, 2)
        logger.info(f"✨ 任务完成！总耗时：{total_time} 秒")
    except KeyboardInterrupt:
        logger.info("用户中断程序")
    except Exception as e:
        logger.error(f"程序执行失败：{e}", exc_info=True)
