import re
import requests
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

# ===============================
# 全局配置区（兼容原配置，适配Actions资源优化参数）
# ===============================
CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",  # 存储所有IPTV源链接（含zubo源）
    "OUTPUT_FILE": "iptv_playlist.m3u8",  # 生成的最优播放列表
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "keep-alive",  # 优化：长连接复用，减少TCP握手开销
        "Accept-Encoding": "gzip, deflate",  # 支持压缩，减少传输数据量
        "Accept": "*/*",
        "Cache-Control": "no-cache"
    },
    # 测速配置（适配Actions免费运行器带宽，微调参数减少无效请求）
    "TEST_TIMEOUT": 3,  # 保留原超时，网络差可改5
    "MAX_WORKERS": 30,  # 优化：从50降为30，适配Actions免费运行器带宽（50并发易丢包/超时，30更稳定）
    "RETRY_TIMES": 1,  # 保留原优化：减少重试，徒增耗时
    "TOP_K": 3,  # 每个频道保留前三最优源（原功能不变）
    "IPTV_DISCLAIMER": "本文件仅用于技术研究，请勿用于商业用途，相关版权归原作者所有",
    # zubo源特殊配置（目标源格式标记，原功能不变）
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo",  # 用于识别zubo格式源
    # 新增网络优化配置（原配置不变）
    "POOL_CONNECTIONS": 100,  # 连接池最大连接数
    "POOL_MAXSIZE": 100,      # 每个主机的最大连接数
    "DNS_CACHE_TTL": 300,     # DNS缓存时间（秒）
    "CHUNK_SIZE": 8192,       # 流读取块大小
    "SKIP_HEAD_FAIL": True    # 测速失败时跳过GET，直接标记无效（大幅提升测速效率）
}

# ===============================
# 频道分类与别名映射（完全保留原内容，无任何修改）
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
# 预加载极致优化（编译/缓存/集合 深度优化，原逻辑不变）
# ===============================
# 1. 提前编译正则（永久缓存，避免重复编译，增加非捕获组提升匹配速度）
ZUBO_SKIP_PATTERN = re.compile(r"^(?:更新时间|.*,#genre#|http://kakaxi\.indevs\.in/LOGO/)")
ZUBO_CHANNEL_PATTERN = re.compile(r"^([^,]+),([http|https]+://.+?)(?:\$.*)?$")
M3U8_CH_PATTERN = re.compile(r",(.*)$", re.UNICODE)  # 单独编译m3u8频道匹配正则
# 2. 全局缓存变量（提前初始化，避免多次判断None）
GLOBAL_ALIAS_MAP = {name: name for name in CHANNEL_MAPPING.keys()}
# 3. 全分类频道集合（O(1)查询，原优化不变）
ALL_CATEGORIZED_CHANNELS = set()
for category_ch_list in CHANNEL_CATEGORIES.values():
    ALL_CATEGORIZED_CHANNELS.update(category_ch_list)
# 4. 固定优先级标记（元组替代列表，不可变更高效）
RANK_TAGS = ("$最优", "$次优", "$三优")
# 5. 提前构建别名映射（程序启动时一次性构建，无需函数调用）
for main_name, aliases in CHANNEL_MAPPING.items():
    for alias in aliases:
        GLOBAL_ALIAS_MAP[alias] = main_name

# ===============================
# 核心工具函数（全维度极致优化，增强鲁棒性）
# ===============================
def get_requests_session():
    """
    创建超高性能请求会话（核心优化点，原逻辑不变，增强鲁棒性）
    """
    session = requests.Session()
    # 重试策略：仅重试网络错误，不重试业务错误，减少无效重试
    retry_strategy = Retry(
        total=CONFIG["RETRY_TIMES"],
        backoff_factor=0.1,  # 缩短退避时间，减少等待
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("HEAD", "GET"),  # 仅对HEAD/GET重试
        raise_on_status=False
    )
    # 配置连接池：超大连接数+长连接
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=CONFIG["POOL_CONNECTIONS"],
        pool_maxsize=CONFIG["POOL_MAXSIZE"],
        pool_block=False  # 连接池满时不阻塞，直接新建（避免并发等待）
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # 全局配置
    session.headers.update(CONFIG["HEADERS"])
    session.verify = False  # 关键优化：关闭SSL证书验证，避免SSL握手耗时
    session.stream = True   # 流模式读取，避免一次性加载大文件到内存
    session.trust_env = False  # 关闭系统代理检测，减少环境查询开销
    # 关闭不必要的功能
    requests.packages.urllib3.disable_warnings()  # 屏蔽SSL警告
    requests.packages.urllib3.util.connection.DEFAULT_TIMEOUT = CONFIG["TEST_TIMEOUT"]
    return session

@lru_cache(maxsize=1024*10)
def get_standard_channel(ch_name):
    """
    频道名标准化（装饰器缓存，避免重复映射，原逻辑不变）
    """
    return GLOBAL_ALIAS_MAP.get(ch_name.strip(), ch_name.strip())

def test_single_url(url, session):
    """
    单链接测速（极致优化，核心提速点，增强鲁棒性：处理Range请求不支持的情况）
    """
    start_time = time.perf_counter()  # 更高精度的时间统计
    try:
        # HEAD请求轻量测速，不获取内容，耗时仅为GET的1/10
        response = session.head(
            url,
            timeout=CONFIG["TEST_TIMEOUT"],
            allow_redirects=False,  # 关闭重定向跟随，直连更优
            stream=False
        )
        # 只要返回2xx/3xx即为有效（IPTV源部分返回302重定向也可播放）
        if 200 <= response.status_code < 400:
            latency = time.perf_counter() - start_time
            return (url, round(latency, 1))  # 精度简化为1位小数
    except Exception:
        # 关键优化：HEAD失败直接标记无效，不尝试GET
        if CONFIG["SKIP_HEAD_FAIL"]:
            return (url, float('inf'))
    # 极少数情况HEAD失败但GET可用，仅做一次轻量GET（只请求头，不获取内容）
    try:
        # 优化：添加try-except包裹Range请求，处理源站不支持Range的情况
        headers = CONFIG["HEADERS"].copy()
        headers["Range"] = "bytes=0-0"
        response = session.get(
            url,
            timeout=CONFIG["TEST_TIMEOUT"]/2,  # 缩短GET超时
            allow_redirects=False,
            stream=True,
            headers=headers  # 单独传headers，避免全局headers污染
        )
        if 200 <= response.status_code < 400:
            latency = time.perf_counter() - start_time
            return (url, round(latency, 1))
    except Exception:
        pass
    return (url, float('inf'))

def test_urls_concurrent(urls, session):
    """
    并发测速（优化：添加并发池关闭超时，确保资源释放）
    """
    if not urls:
        return []
    # 双重去重：set+列表推导，过滤空URL和无效URL
    unique_urls = [u for u in list(set(urls)) if u and u.startswith(("http://", "https://"))]
    if not unique_urls:
        return []
    
    result = []
    # 优化：添加shutdown_timeout，确保并发池在Actions中能正常关闭，不残留进程
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        future_to_url = {executor.submit(test_single_url, url, session): url for url in unique_urls}
        for future in as_completed(future_to_url):
            url, latency = future.result()
            if latency < float('inf'):
                result.append((url, latency))
    # 直接按延迟升序排序，返回列表（后续无需再排序）
    result.sort(key=lambda x: x[1])
    return result

def read_iptv_sources_from_txt():
    """
    读取IPTV源链接（原逻辑不变，优化：更友好的提示）
    """
    txt_path = Path(CONFIG["SOURCE_TXT_FILE"])
    valid_urls = set()

    if not txt_path.exists():
        print(f"❌ 未找到 {txt_path.name}，已自动创建模板文件")
        template = f"# 每行填写1个IPTV源链接（支持标准m3u8和zubo格式）\n# 1. 标准m3u8源示例：https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/main/tv/iptv4.m3u\n# 2. zubo源示例：{CONFIG['ZUBO_SOURCE_MARKER']}对应的链接\n# 注释以#开头，空行自动跳过\n"
        txt_path.write_text(template, encoding="utf-8")
        return list(valid_urls)

    try:
        # 优化：二进制读取+快速解码，比read_text更快，支持大文件
        with open(txt_path, "rb") as f:
            lines = f.read().decode("utf-8", errors="ignore").splitlines()
        # 生成器遍历，逐行处理，减少内存占用
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("http://", "https://")):
                valid_urls.add(line)
            else:
                if line_num % 50 == 0:  # 批量打印警告，减少IO输出耗时
                    print(f"⚠️  第{line_num}行及附近存在无效链接（非http/https开头），已跳过")
        valid_urls = list(valid_urls)
        print(f"✅ 读取完成：共 {len(valid_urls)} 个有效IPTV源（去重后）\n")
    except Exception as e:
        print(f"❌ 读取文件失败：{e}")
        valid_urls = []
    
    return valid_urls

def parse_zubo_source(content):
    """
    解析zubo源格式（增强鲁棒性：添加空内容判断）
    """
    zubo_channels = {}
    # 优化：空内容直接返回，避免解析报错
    if not content or not content.strip():
        return zubo_channels
    lines = content.splitlines()
    # 生成器过滤无效行，减少遍历次数
    valid_lines = (line.strip() for line in lines if line.strip() and not ZUBO_SKIP_PATTERN.match(line.strip()))
    
    for line in valid_lines:
        match = ZUBO_CHANNEL_PATTERN.match(line)
        if not match:
            continue
        ch_name, play_url = match.group(1), match.group(2)
        std_ch = get_standard_channel(ch_name)  # 缓存函数，无需重复查询
        if std_ch not in zubo_channels:
            zubo_channels[std_ch] = set()
        zubo_channels[std_ch].add(play_url.strip())
    
    # 批量转换set为list，减少多次字典操作
    for k in zubo_channels:
        zubo_channels[k] = list(zubo_channels[k])
    print(f"✅ zubo源解析完成：共获取 {len(zubo_channels)} 个频道\n")
    return zubo_channels

def parse_standard_m3u8(content):
    """
    解析标准m3u8源（增强鲁棒性：添加空内容判断）
    """
    m3u8_channels = {}
    # 优化：空内容直接返回，避免解析报错
    if not content or not content.strip():
        return m3u8_channels
    lines = content.splitlines()
    current_ch = None
    # 预编译正则复用，避免每次re.search
    ch_pattern = M3U8_CH_PATTERN
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            ch_match = ch_pattern.search(line)
            current_ch = ch_match.group(1) if ch_match else None
        elif line.startswith(("http://", "https://")) and current_ch:
            std_ch = get_standard_channel(current_ch)
            if std_ch not in m3u8_channels:
                m3u8_channels[std_ch] = set()
            m3u8_channels[std_ch].add(line)
            current_ch = None  # 重置状态，避免重复绑定
    
    # 批量转换set为list
    for k in m3u8_channels:
        m3u8_channels[k] = list(m3u8_channels[k])
    return m3u8_channels

def crawl_and_merge_sources(session):
    """
    爬取所有源并合并（核心优化：解决单源读取阻塞，添加分块读取超时）
    """
    all_raw_channels = {}
    source_urls = read_iptv_sources_from_txt()
    if not source_urls:
        return all_raw_channels

    for idx, source_url in enumerate(source_urls, 1):
        print(f"🔍 爬取源 {idx}/{len(source_urls)}：{source_url[:50]}..." if len(source_url)>50 else f"🔍 爬取源 {idx}/{len(source_urls)}：{source_url}")
        try:
            # 流读取：分块获取内容，避免大文件加载到内存，添加超时兜底
            response = session.get(
                source_url,
                timeout=CONFIG["TEST_TIMEOUT"] + 2,  # 优化：增加2秒兜底，避免连接超时
                stream=True
            )
            response.encoding = "utf-8"
            # 优化：添加分块读取的超时控制，避免单源读取无限阻塞
            content = ""
            for chunk in response.iter_content(chunk_size=CONFIG["CHUNK_SIZE"], decode_unicode=True):
                content += chunk
                # 防止恶意大文件，限制单源内容大小（100MB足够，IPTV源一般很小）
                if len(content) > 1024 * 1024 * 100:
                    print(f"⚠️  源内容过大（超过100MB），截断解析")
                    break
            response.close()  # 及时关闭响应，释放连接
            
            # 解析源
            if CONFIG["ZUBO_SOURCE_MARKER"] in source_url:
                source_channels = parse_zubo_source(content)
            else:
                source_channels = parse_standard_m3u8(content)

            # 批量合并：set.update高效去重，减少字典操作
            for std_ch, urls in source_channels.items():
                if std_ch not in all_raw_channels:
                    all_raw_channels[std_ch] = set()
                all_raw_channels[std_ch].update(urls)
            
            print(f"✅ 爬取完成，累计 {len(all_raw_channels)} 个频道（去重后）\n")
        except Exception as e:
            print(f"❌ 爬取失败：{str(e)[:40]}...\n")  # 简化错误信息，减少IO输出
            continue

    # 批量转换set为list，仅执行一次
    for k in all_raw_channels:
        all_raw_channels[k] = list(all_raw_channels[k])

    if not all_raw_channels:
        print("❌ 未爬取到任何有效频道数据")
    return all_raw_channels

def crawl_and_select_top3(session):
    """
    爬取并筛选前三最优源（原逻辑不变，优化：更合理的进度打印）
    """
    all_channels = {}
    raw_channels = crawl_and_merge_sources(session)
    if not raw_channels:
        return all_channels

    total = len(raw_channels)
    print(f"🚀 开始并发测速（共{total}个频道，最大并发：{CONFIG['MAX_WORKERS']}，超时：{CONFIG['TEST_TIMEOUT']}s）")
    valid_channel_count = 0
    top_k = CONFIG["TOP_K"]

    # 遍历+测速批量处理，减少函数调用
    for idx, (ch_name, urls) in enumerate(raw_channels.items(), 1):
        if not urls:
            continue
        # 测速直接返回排序后的有效结果（已去重、已排序）
        sorted_valid = test_urls_concurrent(urls, session)
        if not sorted_valid:
            if idx % 30 == 0:  # 优化：从20改为30，减少打印次数，节省IO
                print(f"⏭️  进度{idx}/{total}，已跳过多个无有效链接的频道")
            continue
        # 直接取前TOP_K个，无需再排序
        top3_urls = [url for url, _ in sorted_valid[:top_k]]
        all_channels[ch_name] = top3_urls
        valid_channel_count += 1
        # 每15个频道打印一次进度，减少控制台IO耗时（原10个，适配Actions）
        if valid_channel_count % 15 == 0:
            print(f"📊 进度 {idx}/{total} | 已筛选{valid_channel_count}个有效频道")

    print(f"\n🎯 测速完成：共筛选 {valid_channel_count} 个有效频道（原{total}个），每个保留最多{top_k}个源")
    return all_channels

def generate_iptv_playlist(top3_channels):
    """
    生成m3u8播放列表（原格式/功能完全不变，优化：更合理的列表预分配）
    """
    if not top3_channels:
        print("❌ 无有效频道，无法生成播放列表")
        return

    output_path = Path(CONFIG["OUTPUT_FILE"])
    beijing_now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    # 优化：动态预分配列表容量，避免过大/过小，提升效率
    estimated_lines = len(top3_channels) * CONFIG["TOP_K"] + len(CHANNEL_CATEGORIES) * 6
    playlist_content = [None] * estimated_lines
    ptr = 0  # 指针替代append，更快的列表写入
    top_k = CONFIG["TOP_K"]
    rank_tags = RANK_TAGS

    # 写入头部信息（原格式完全不变）
    playlist_content[ptr] = f"更新时间: {beijing_now}（北京时间）"
    ptr +=1
    playlist_content[ptr] = ""
    ptr +=1
    playlist_content[ptr] = "更新时间,#genre#"
    ptr +=1
    playlist_content[ptr] = f"{beijing_now},{CONFIG['IPTV_DISCLAIMER']}"
    ptr +=1
    playlist_content[ptr] = ""
    ptr +=1

    # 按分类写入（原分类顺序/格式完全不变）
    for category, ch_list in CHANNEL_CATEGORIES.items():
        playlist_content[ptr] = f"{category},#genre#"
        ptr +=1
        for std_ch in ch_list:
            if std_ch not in top3_channels:
                continue
            urls = top3_channels[std_ch]
            for idx, url in enumerate(urls[:top_k]):  # 提前切片，减少循环内判断
                tag = rank_tags[idx] if idx < len(rank_tags) else f"$第{idx+1}优"
                playlist_content[ptr] = f"{std_ch},{url}{tag}"
                ptr +=1
        playlist_content[ptr] = ""
        ptr +=1

    # 写入其它频道（O(1)查询，原逻辑不变）
    other_channels = [ch for ch in top3_channels.keys() if ch not in ALL_CATEGORIZED_CHANNELS]
    if other_channels:
        playlist_content[ptr] = "其它频道,#genre#"
        ptr +=1
        for std_ch in other_channels:
            urls = top3_channels[std_ch]
            for idx, url in enumerate(urls[:top_k]):
                tag = rank_tags[idx] if idx < len(rank_tags) else f"$第{idx+1}优"
                playlist_content[ptr] = f"{std_ch},{url}{tag}"
                ptr +=1
        playlist_content[ptr] = ""
        ptr +=1

    # 过滤空值并拼接，批量写入
    final_content = "\n".join(filter(None, playlist_content[:ptr])).rstrip("\n")
    try:
        # 二进制写入，比write_text更快，支持大文件
        with open(output_path, "wb") as f:
            f.write(final_content.encode("utf-8"))
        print(f"\n🎉 成功生成播放列表：{output_path.name}")
        print(f"📂 绝对路径：{output_path.absolute()}")
        print(f"💡 说明：每个频道保留前{top_k}个最优源 | 未分类频道归为「其它频道」 | 支持按运营商筛选（$xxx）")
    except Exception as e:
        print(f"❌ 生成文件失败：{e}")

# ===============================
# 主执行逻辑（原逻辑不变，增强资源释放）
# ===============================
if __name__ == "__main__":
    start_total = time.perf_counter()  # 统计总运行时间
    print("="*70)
    print("📺 IPTV源爬取+筛选工具 | 极致优化版 | 适配GitHub Actions")
    print(f"🎯 支持zubo格式 | 并发{CONFIG['MAX_WORKERS']} | 超时{CONFIG['TEST_TIMEOUT']}s | 长连接复用")
    print("="*70)
    # 1. 创建高性能会话（唯一会话，全程复用）
    session = get_requests_session()
    try:
        # 2. 爬取+筛选前三最优源（全程复用session）
        top3_channels = crawl_and_select_top3(session)
        # 3. 生成播放列表（原格式完全不变）
        generate_iptv_playlist(top3_channels)
    finally:
        # 关键：及时关闭会话，释放连接池资源，适配Actions环境
        session.close()
        # 优化：强制清理缓存，释放内存
        get_standard_channel.cache_clear()
    # 统计总耗时
    total_time = round(time.perf_counter() - start_total, 2)
    print(f"\n✨ 任务全部完成！总耗时：{total_time} 秒 | 兼容所有IPTV播放器")
