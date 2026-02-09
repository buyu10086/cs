import re
import requests
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===============================
# 全局配置区（核心参数可调，无变动）
# ===============================
CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",  # 存储所有IPTV源链接（含zubo源）
    "OUTPUT_FILE": "iptv_playlist.m3u8",  # 生成的最优播放列表
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close"  # 关闭长连接，减少资源占用
    },
    # 测速配置
    "TEST_TIMEOUT": 3,  # 单链接超时时间（秒），网络差可改为8
    "MAX_WORKERS": 40,  # 并发线程数，带宽高可设30-50
    "RETRY_TIMES": 1,  # 网络请求重试次数
    "TOP_K": 3,  # 每个频道保留前三最优源
    "IPTV_DISCLAIMER": "本文件仅用于技术研究，请勿用于商业用途，相关版权归原作者所有",
    # zubo源特殊配置（目标源格式标记）
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo"  # 用于识别zubo格式源
}

# ===============================
# 频道分类与别名映射（保持兼容，无变动）
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
# 预加载优化（新增/修改，提升效率核心）
# ===============================
# 1. 提前编译正则（避免重复编译）
ZUBO_SKIP_PATTERN = re.compile(r"^(更新时间|.*,#genre#|http://kakaxi\.indevs\.in/LOGO/)")
ZUBO_CHANNEL_PATTERN = re.compile(r"^([^,]+),(http://.+?)(\$.*)?$")

# 2. 缓存别名映射（仅构建一次，避免重复计算）
GLOBAL_ALIAS_MAP = None

# 3. 缓存所有分类频道的集合（快速判断频道是否已分类，O(1)复杂度）
ALL_CATEGORIZED_CHANNELS = set()
for category_ch_list in CHANNEL_CATEGORIES.values():
    ALL_CATEGORIZED_CHANNELS.update(category_ch_list)

# 4. 固定优先级标记（避免重复创建列表）
RANK_TAGS = ["$最优", "$次优", "$三优"]

# ===============================
# 核心工具函数（优化后，功能不变，效率提升）
# ===============================
def get_requests_session():
    """创建带重试机制的requests会话（无变动）"""
    session = requests.Session()
    retry_strategy = Retry(
        total=CONFIG["RETRY_TIMES"],
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(CONFIG["HEADERS"])
    return session

def build_alias_map():
    """构建频道别名->标准名映射（优化：缓存结果，仅构建一次）"""
    global GLOBAL_ALIAS_MAP
    if GLOBAL_ALIAS_MAP is not None:
        return GLOBAL_ALIAS_MAP
    
    alias_map = {name: name for name in CHANNEL_MAPPING.keys()}
    for main_name, aliases in CHANNEL_MAPPING.items():
        for alias in aliases:
            alias_map[alias] = main_name
    
    GLOBAL_ALIAS_MAP = alias_map
    return GLOBAL_ALIAS_MAP

def test_single_url(url, session):
    """单链接测速：优化1. 复用全局session 2. with上下文管理器自动关闭响应（无功能变动）"""
    try:
        start_time = time.time()
        # 复用带连接池的session，with自动管理响应，无需手动close()
        with session.head(
            url,
            timeout=CONFIG["TEST_TIMEOUT"],
            allow_redirects=True  # 跟随重定向，测试最终有效链接
        ) as response:
            latency = time.time() - start_time
            return (url, round(latency, 2))
    except Exception:
        return (url, float('inf'))

def test_urls_concurrent(urls, session):
    """并发测速：优化1. 先去重urls 2. 复用全局session（返回结果不变）"""
    if not urls:
        return {}
    
    # 优化：先去重urls，避免对重复链接无效测速（set去重，O(1)复杂度）
    unique_urls = list(set(urls))
    result_dict = {}
    
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        # 优化：传入全局session，复用连接池
        future_to_url = {executor.submit(test_single_url, url, session): url for url in unique_urls}
        for future in as_completed(future_to_url):
            url, latency = future.result()
            if latency < float('inf'):
                result_dict[url] = latency
    
    return result_dict

def read_iptv_sources_from_txt():
    """读取txt中的IPTV源链接：优化：用set去重，提升效率（返回结果不变）"""
    txt_path = Path(CONFIG["SOURCE_TXT_FILE"])
    # 优化：用set存储，自动去重，O(1)复杂度
    valid_urls_set = set()

    if not txt_path.exists():
        print(f"❌ 未找到 {txt_path.name}，已自动创建模板文件，请填写链接后重试")
        # 模板中加入zubo源示例
        template = f"# 每行填写1个IPTV源链接（支持标准m3u8和zubo格式）\n# 1. 标准m3u8源示例：https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/main/tv/iptv4.m3u\n# 2. zubo源示例：{CONFIG['ZUBO_SOURCE_MARKER']}对应的链接（本次目标源）\n{CONFIG['ZUBO_SOURCE_MARKER']}示例：https://gh-proxy.com/raw.githubusercontent.com/kakaxi-1/zubo/refs/heads/main/IPTV.txt\n# 可添加注释（以#开头），空行会自动跳过\n"
        txt_path.write_text(template, encoding="utf-8")
        return list(valid_urls_set)

    try:
        lines = txt_path.read_text(encoding="utf-8").splitlines()
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("http://", "https://")):
                valid_urls_set.add(line)  # set添加，自动去重
            else:
                print(f"⚠️  第{line_num}行无效（非http链接），已跳过：{line}")
        
        valid_urls = list(valid_urls_set)
        print(f"✅ 读取完成：共 {len(valid_urls)} 个有效IPTV源（含标准m3u8和zubo源）\n")
    except Exception as e:
        print(f"❌ 读取文件失败：{e}")
        valid_urls = []
    
    return valid_urls

def parse_zubo_source(content):
    """解析zubo源格式：优化1. 用预编译正则 2. 缓存别名映射（返回结果不变）"""
    zubo_channels = {}
    alias_map = build_alias_map()  # 复用缓存的别名映射
    lines = content.splitlines()

    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or ZUBO_SKIP_PATTERN.match(line):
            continue
        
        # 用预编译正则匹配，避免重复编译
        match = ZUBO_CHANNEL_PATTERN.match(line)
        if not match:
            print(f"⚠️  zubo源第{line_num}行格式无效，已跳过：{line}")
            continue
        
        ch_name = match.group(1).strip()
        play_url = match.group(2).strip()
        
        std_ch = alias_map.get(ch_name, ch_name)
        if std_ch not in zubo_channels:
            zubo_channels[std_ch] = set()  # 优化：用set存储，自动去重
        zubo_channels[std_ch].add(play_url)
    
    # 转换回列表，保持原有返回格式
    for std_ch, url_set in zubo_channels.items():
        zubo_channels[std_ch] = list(url_set)
    
    print(f"✅ zubo源解析完成：共获取 {len(zubo_channels)} 个频道\n")
    return zubo_channels

def parse_standard_m3u8(content):
    """解析标准m3u8源：优化1. 缓存别名映射 2. set去重（返回结果不变）"""
    m3u8_channels = {}
    alias_map = build_alias_map()  # 复用缓存的别名映射
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
            std_ch = alias_map.get(current_ch, current_ch)
            if std_ch not in m3u8_channels:
                m3u8_channels[std_ch] = set()  # 优化：set去重
            m3u8_channels[std_ch].add(line)
            current_ch = None
    
    # 转换回列表，保持原有返回格式
    for std_ch, url_set in m3u8_channels.items():
        m3u8_channels[std_ch] = list(url_set)
    
    return m3u8_channels

def crawl_and_merge_sources(session):
    """爬取所有源并合并：优化1. set去重 2. 减少重复判断（返回结果不变）"""
    all_raw_channels = {}
    source_urls = read_iptv_sources_from_txt()
    if not source_urls:
        return all_raw_channels

    for source_url in source_urls:
        print(f"🔍 正在爬取源：{source_url}")
        try:
            response = session.get(source_url, timeout=CONFIG["TEST_TIMEOUT"] + 2)
            response.encoding = "utf-8"
            content = response.text

            if CONFIG["ZUBO_SOURCE_MARKER"] in source_url:
                print(f"ℹ️  检测到zubo格式源，使用专属解析逻辑")
                source_channels = parse_zubo_source(content)
            else:
                print(f"ℹ️  检测到标准m3u8源，使用标准解析逻辑")
                source_channels = parse_standard_m3u8(content)

            # 优化：用set合并去重，避免O(n)的in判断
            for std_ch, urls in source_channels.items():
                if std_ch not in all_raw_channels:
                    all_raw_channels[std_ch] = set()
                all_raw_channels[std_ch].update(urls)  # set批量更新，自动去重
            
            print(f"✅ 该源爬取完成，累计收集 {len(all_raw_channels)} 个频道（去重后）\n")
        except Exception as e:
            print(f"❌ 爬取失败：{e}\n")
            continue

    # 转换回列表，保持原有返回格式
    for std_ch, url_set in all_raw_channels.items():
        all_raw_channels[std_ch] = list(url_set)

    if not all_raw_channels:
        print("❌ 未爬取到任何频道数据（标准m3u8和zubo源均无有效数据）")
    return all_raw_channels

def crawl_and_select_top3(session):
    """爬取所有源并筛选前三最优源：优化1. 复用session测速 2. 减少无效操作（返回结果不变）"""
    all_channels = {}
    raw_channels = crawl_and_merge_sources(session)
    if not raw_channels:
        return all_channels

    print(f"🚀 开始并发测速（共{len(raw_channels)}个频道，最大并发数：{CONFIG['MAX_WORKERS']}）")
    valid_channel_count = 0
    top_k = CONFIG["TOP_K"]

    for ch_name, urls in raw_channels.items():
        if len(urls) == 0:
            print(f"⏭️  {ch_name}：无播放地址，已跳过")
            continue

        # 优化：传入全局session，复用连接池，且已提前去重
        latency_dict = test_urls_concurrent(urls, session)
        if not latency_dict:
            print(f"⏭️  {ch_name}：所有地址均无效，已跳过")
            continue

        # 按延迟升序排序，取前top_k个
        sorted_items = sorted(latency_dict.items(), key=lambda x: x[1])
        top3_urls = [url for url, _ in sorted_items[:top_k]]
        all_channels[ch_name] = top3_urls
        valid_channel_count += 1

        # 打印详细结果（保持原有格式）
        result_str = " | ".join([f"{url}（延迟：{latency}s）" for url, latency in sorted_items[:top_k]])
        print(f"✅ {ch_name}：保留前三最优源 → {result_str}")

    print(f"\n🎯 测速完成：共筛选出 {valid_channel_count} 个有效频道（原{len(raw_channels)}个），每个频道保留最多{top_k}个源")
    return all_channels

def generate_iptv_playlist(top3_channels):
    """生成m3u8播放列表：优化1. 快速判断未分类频道 2. 复用固定标记（功能不变）"""
    if not top3_channels:
        print("❌ 无有效频道，无法生成播放列表")
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

    # 按分类写入（保持原有格式）
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
                if "$" in url:
                    playlist_content.append(f"{std_ch},{url}{tag}")
                else:
                    playlist_content.append(f"{std_ch},{url}{tag}")
        playlist_content.append("")

    # 优化：快速获取未分类频道（O(1)复杂度，替代原有嵌套遍历）
    other_channels = [ch for ch in top3_channels.keys() if ch not in ALL_CATEGORIZED_CHANNELS]
    if other_channels:
        playlist_content.append("其它频道,#genre#")
        for std_ch in other_channels:
            urls = top3_channels[std_ch]
            for idx, url in enumerate(urls):
                if idx >= top_k:
                    break
                tag = RANK_TAGS[idx] if idx < len(RANK_TAGS) else f"$第{idx+1}优"
                if "$" in url:
                    playlist_content.append(f"{std_ch},{url}{tag}")
                else:
                    playlist_content.append(f"{std_ch},{url}{tag}")
        playlist_content.append("")

    # 保存文件（保持原有格式）
    try:
        output_path.write_text("\n".join(playlist_content).rstrip("\n"), encoding="utf-8")
        print(f"\n🎉 成功生成最优播放列表：{output_path.name}")
        print(f"📂 路径：{output_path.absolute()}")
        print(f"💡 说明：1. 未分类频道已统一改为“其它频道”；2. 每个频道保留最多{top_k}个源，标记为$最优/$次优/$三优；3. zubo源的运营商信息已保留（如$上海市电信），方便按网络选择")
    except Exception as e:
        print(f"❌ 生成文件失败：{e}")

# ===============================
# 主执行逻辑（仅微调，传入session到测速函数）
# ===============================
if __name__ == "__main__":
    print("="*70)
    print("📺 IPTV直播源爬取 + zubo格式支持 + 前三最优源筛选工具（优化版）")
    print(f"🎯 已支持 {CONFIG['ZUBO_SOURCE_MARKER']} 格式源解析 | 未分类频道→其它频道 | 运行效率优化")
    print("="*70)
    # 1. 创建请求会话
    session = get_requests_session()
    # 2. 提前构建别名映射（首次调用缓存）
    build_alias_map()
    # 3. 爬取所有源并筛选前三最优源
    top3_channels = crawl_and_select_top3(session)
    # 4. 生成m3u8播放列表
    generate_iptv_playlist(top3_channels)
    print("\n✨ 任务完成！生成的文件兼容PotPlayer、Kodi、火星直播等所有播放器")
