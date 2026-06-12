import re
import requests
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------- 进度条（可选依赖）----------
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        total = kwargs.get('total', len(iterable) if hasattr(iterable, '__len__') else None)
        if total:
            print(f"进度：共 {total} 项，处理中...（安装 tqdm 可获实时进度条）")
        return iterable
    print("提示：未安装 tqdm，使用简单进度显示。运行 'pip install tqdm' 获得更好体验")

# ===============================
# 全局配置区（核心参数可调）
# ===============================
CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",          # 存储所有IPTV源链接（远程源）
    "M3U8_SOURCES_FILE": "m3u8_sources.txt",        # 新增：存储独立m3u8链接的文件
    "OUTPUT_FILE": "iptv_playlist.m3u8",            # 生成的最优播放列表
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close"                        # 关闭长连接，减少资源占用
    },
    # 全局测速配置
    "TEST_TIMEOUT": 2,                                # 单链接超时时间（秒），网络差可改为8
    "MAX_WORKERS": 50,                                # 并发线程数，带宽高可设30-50
    "RETRY_TIMES": 1,                                 # 网络请求重试次数
    "TOP_K": 3,                                       # 每个频道保留前三最优源
    "IPTV_DISCLAIMER": "个人自用，请勿用于商业用途",
    # txt源特殊配置（目标源格式标记）
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo",            # 用于识别txt格式源
    # CCTV 单独测速配置（可针对CCTV频道使用更宽松的超时或更低的并发）
    "CCTV_SPECIFIC_CONFIG": {
        "enabled": True,                               # 是否启用单独配置
        "TEST_TIMEOUT": 5,                             # CCTV 频道超时时间（秒）
        "MAX_WORKERS": 20                              # CCTV 频道并发线程数
    }
}

# ===============================
# 频道分类与别名映射（增强CCTV识别）
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

# 增强CCTV别名映射：覆盖更多变体（空格、符号、大小写、中英文混合）
CHANNEL_MAPPING = {
    "CCTV1": ["CCTV-1", "CCTV 1", "CCTV1 HD", "CCTV-1 HD", "CCTV 1 HD", "CCTV-1综合", "CCTV1综合", "央视一套", "中央一台"],
    "CCTV2": ["CCTV-2", "CCTV 2", "CCTV2 HD", "CCTV-2 HD", "CCTV 2 HD", "CCTV-2财经", "CCTV2财经", "央视二套", "中央二台"],
    "CCTV3": ["CCTV-3", "CCTV 3", "CCTV3 HD", "CCTV-3 HD", "CCTV 3 HD", "CCTV-3综艺", "CCTV3综艺", "央视三套", "中央三台"],
    "CCTV4": ["CCTV-4", "CCTV 4", "CCTV4 HD", "CCTV-4 HD", "CCTV 4 HD", "CCTV-4中文国际", "CCTV4中文国际", "央视四套", "中央四台"],
    "CCTV4欧洲": ["CCTV-4欧洲", "CCTV 4欧洲", "CCTV4欧洲 HD", "CCTV-4 欧洲", "CCTV 4 欧洲", "CCTV-4中文国际欧洲", "CCTV4中文欧洲", "央视四套欧洲"],
    "CCTV4美洲": ["CCTV-4美洲", "CCTV 4美洲", "CCTV4美洲 HD", "CCTV-4 美洲", "CCTV 4 美洲", "CCTV-4中文国际美洲", "CCTV4中文美洲", "央视四套美洲"],
    "CCTV5": ["CCTV-5", "CCTV 5", "CCTV5 HD", "CCTV-5 HD", "CCTV 5 HD", "CCTV-5体育", "CCTV5体育", "央视五套", "中央五台", "央视体育"],
    "CCTV5+": ["CCTV-5+", "CCTV 5+", "CCTV5+ HD", "CCTV-5+ HD", "CCTV 5+ HD", "CCTV-5+体育赛事", "CCTV5+体育赛事", "央视五+", "中央五+", "体育赛事频道"],
    "CCTV6": ["CCTV-6", "CCTV 6", "CCTV6 HD", "CCTV-6 HD", "CCTV 6 HD", "CCTV-6电影", "CCTV6电影", "央视六套", "中央六台", "央视电影"],
    "CCTV7": ["CCTV-7", "CCTV 7", "CCTV7 HD", "CCTV-7 HD", "CCTV 7 HD", "CCTV-7国防军事", "CCTV7国防军事", "央视七套", "中央七台"],
    "CCTV8": ["CCTV-8", "CCTV 8", "CCTV8 HD", "CCTV-8 HD", "CCTV 8 HD", "CCTV-8电视剧", "CCTV8电视剧", "央视八套", "中央八台"],
    "CCTV9": ["CCTV-9", "CCTV 9", "CCTV9 HD", "CCTV-9 HD", "CCTV 9 HD", "CCTV-9纪录", "CCTV9纪录", "央视九套", "中央九台"],
    "CCTV10": ["CCTV-10", "CCTV 10", "CCTV10 HD", "CCTV-10 HD", "CCTV 10 HD", "CCTV-10科教", "CCTV10科教", "央视十套", "中央十台"],
    "CCTV11": ["CCTV-11", "CCTV 11", "CCTV11 HD", "CCTV-11 HD", "CCTV 11 HD", "CCTV-11戏曲", "CCTV11戏曲", "央视十一套", "中央十一台"],
    "CCTV12": ["CCTV-12", "CCTV 12", "CCTV12 HD", "CCTV-12 HD", "CCTV 12 HD", "CCTV-12社会与法", "CCTV12社会与法", "央视十二套", "中央十二台"],
    "CCTV13": ["CCTV-13", "CCTV 13", "CCTV13 HD", "CCTV-13 HD", "CCTV 13 HD", "CCTV-13新闻", "CCTV13新闻", "央视十三套", "中央十三台"],
    "CCTV14": ["CCTV-14", "CCTV 14", "CCTV14 HD", "CCTV-14 HD", "CCTV 14 HD", "CCTV-14少儿", "CCTV14少儿", "央视十四套", "中央十四台"],
    "CCTV15": ["CCTV-15", "CCTV 15", "CCTV15 HD", "CCTV-15 HD", "CCTV 15 HD", "CCTV-15音乐", "CCTV15音乐", "央视十五套", "中央十五台"],
    "CCTV16": ["CCTV-16", "CCTV 16", "CCTV16 HD", "CCTV-16 HD", "CCTV 16 HD", "CCTV-16奥林匹克", "CCTV16奥林匹克", "央视十六套", "中央十六台"],
    "CCTV17": ["CCTV-17", "CCTV 17", "CCTV17 HD", "CCTV-17 HD", "CCTV 17 HD", "CCTV-17农业农村", "CCTV17农业农村", "央视十七套", "中央十七台"],
    "CCTV4K": ["CCTV-4K", "CCTV 4K", "CCTV4K超高清", "央视4K"],
    "CCTV8K": ["CCTV-8K", "CCTV 8K", "CCTV8K超高清", "央视8K"]
}

# ===============================
# 工具函数
# ===============================
def create_request_session():
    """创建带重试机制的请求会话"""
    session = requests.Session()
    retry_strategy = Retry(
        total=CONFIG["RETRY_TIMES"],
        backoff_factor=0.1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(CONFIG["HEADERS"])
    return session

def load_source_urls(file_path):
    """加载iptv_sources.txt中的源链接（去重、过滤注释/空行）"""
    source_urls = []
    if not Path(file_path).exists():
        print(f"警告：{file_path} 文件不存在，跳过加载")
        return source_urls
    
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 过滤注释行和空行
            if not line or line.startswith("#"):
                continue
            # 过滤重复链接
            if line not in source_urls:
                source_urls.append(line)
    print(f"从 {file_path} 加载到 {len(source_urls)} 个源链接")
    return source_urls

def fetch_source_content(url, session):
    """获取远程源文件的内容"""
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        # 自动识别编码（兼容不同编码的源文件）
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except Exception as e:
        print(f"获取 {url} 失败：{str(e)}")
        return ""

def parse_channel_links(content):
    """解析源文件内容，提取频道名+播放链接（兼容所有格式）"""
    channels = {}
    # 正则匹配：支持 频道名,链接 / 频道名|链接 / 频道名 链接 等格式
    patterns = [
        r'([^\s,|]+)[\s,|]+(https?://[^\s,|]+)',  # 频道名 分隔符 链接
        r'(https?://[^\s,|]+)[\s,|]+([^\s,|]+)',  # 链接 分隔符 频道名（反向）
    ]
    
    for line in content.splitlines():
        line = line.strip()
        if not line or not line.startswith(("http", "https")):
            continue
        
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                # 区分频道名和链接
                g1, g2 = match.groups()
                if g1.startswith(("http", "https")):
                    link, name = g1, g2
                else:
                    name, link = g1, g2
                
                # 标准化频道名（去重、别名映射）
                std_name = standardize_channel_name(name)
                if std_name not in channels:
                    channels[std_name] = []
                if link not in channels[std_name]:
                    channels[std_name].append(link)
                break
    return channels

def standardize_channel_name(name):
    """标准化频道名（统一别名、去空格/符号、大小写）"""
    if not name:
        return ""
    
    # 预处理：去空格、特殊符号，转大写
    std_name = re.sub(r'[\s\-_\.]+', '', name).upper()
    std_name = std_name.replace("HD", "").replace("高清", "")
    
    # 别名映射匹配
    for official_name, aliases in CHANNEL_MAPPING.items():
        # 匹配官方名本身
        if std_name == re.sub(r'[\s\-_\.]+', '', official_name).upper():
            return official_name
        # 匹配别名
        for alias in aliases:
            alias_std = re.sub(r'[\s\-_\.]+', '', alias).upper().replace("HD", "").replace("高清", "")
            if std_name == alias_std:
                return official_name
    
    # 无匹配则返回原始标准化名称
    return name.strip()

def test_link_speed(link, timeout):
    """测试链接速度（返回耗时/None，兼容非M3U8链接）"""
    start_time = time.time()
    session = create_request_session()
    try:
        # 只请求头部（减少流量，兼容所有HTTP链接）
        response = session.head(link, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            elapsed = time.time() - start_time
            return round(elapsed, 3)
        else:
            return None
    except Exception:
        return None
    finally:
        session.close()

def sort_channels_by_speed(channels):
    """按测速结果排序频道链接，保留TOP_K个最优链接"""
    sorted_channels = {}
    total_links = sum(len(links) for links in channels.values())
    print(f"开始测速 {total_links} 个播放链接（并发数：{CONFIG['MAX_WORKERS']}）")
    
    with tqdm(total=total_links, desc="测速进度") as pbar:
        for channel_name, links in channels.items():
            # 区分CCTV频道和普通频道的测速配置
            if CONFIG["CCTV_SPECIFIC_CONFIG"]["enabled"] and any(c in channel_name for c in CHANNEL_CATEGORIES["央视频道"]):
                timeout = CONFIG["CCTV_SPECIFIC_CONFIG"]["TEST_TIMEOUT"]
                max_workers = CONFIG["CCTV_SPECIFIC_CONFIG"]["MAX_WORKERS"]
            else:
                timeout = CONFIG["TEST_TIMEOUT"]
                max_workers = CONFIG["MAX_WORKERS"]
            
            # 并发测速
            link_speeds = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_link = {executor.submit(test_link_speed, link, timeout): link for link in links}
                for future in as_completed(future_to_link):
                    link = future_to_link[future]
                    speed = future.result()
                    if speed is not None:
                        link_speeds[link] = speed
                    pbar.update(1)
            
            # 按速度排序（快→慢），保留TOP_K
            sorted_links = sorted(link_speeds.items(), key=lambda x: x[1])[:CONFIG["TOP_K"]]
            if sorted_links:
                sorted_channels[channel_name] = [link for link, _ in sorted_links]
            else:
                # 所有链接测速失败，保留原始链接（无测速）
                sorted_channels[channel_name] = links[:CONFIG["TOP_K"]]
    
    return sorted_channels

def generate_m3u8_playlist(channels, output_file):
    """生成M3U8播放列表（兼容非M3U8链接）"""
    # M3U8头部
    m3u8_header = f"""#EXTM3U x-tvg-url=""
#EXT-X-DISCONTINUITY
# 生成时间：{datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}
# 免责声明：{CONFIG['IPTV_DISCLAIMER']}
"""
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(m3u8_header)
        
        # 按分类写入频道
        for category, official_names in CHANNEL_CATEGORIES.items():
            f.write(f"\n# {category}\n")
            # 先写分类内的官方频道
            for official_name in official_names:
                if official_name in channels:
                    for link in channels[official_name]:
                        # ✅ 修复：将内部双引号改为单引号，避免f-string语法冲突
                        f.write(f"#EXTINF:-1 group-title='{category}',{official_name}\n")
                        f.write(f"{link}\n")
            
            # 写入未匹配到官方分类但属于该类的频道（兜底）
            for channel_name, links in channels.items():
                if channel_name in official_names:
                    continue
                if any(keyword in channel_name for keyword in official_names):
                    for link in links:
                        f.write(f"#EXTINF:-1 group-title='{category}',{channel_name}\n")
                        f.write(f"{link}\n")
        
        # 写入未分类的频道
        uncategorized = []
        for channel_name, links in channels.items():
            is_categorized = False
            for category_names in CHANNEL_CATEGORIES.values():
                if channel_name in category_names or any(kw in channel_name for kw in category_names):
                    is_categorized = True
                    break
            if not is_categorized:
                uncategorized.append((channel_name, links))
        
        if uncategorized:
            f.write(f"\n# 其他频道\n")
            for channel_name, links in uncategorized:
                for link in links:
                    f.write(f"#EXTINF:-1 group-title='其他频道',{channel_name}\n")
                    f.write(f"{link}\n")
    
    print(f"播放列表已生成：{output_file}（共 {len(channels)} 个频道）")

# ===============================
# 主流程
# ===============================
def main():
    print("=== IPTV源爬取与播放列表生成工具 ===\n")
    
    # 1. 加载源链接
    source_urls = load_source_urls(CONFIG["SOURCE_TXT_FILE"])
    if not source_urls:
        print("无可用源链接，程序退出")
        return
    
    # 2. 创建请求会话
    session = create_request_session()
    
    # 3. 批量获取源内容
    all_content = ""
    for url in tqdm(source_urls, desc="获取远程源内容"):
        content = fetch_source_content(url, session)
        if content:
            all_content += content + "\n"
    
    # 4. 解析频道和链接
    print("\n开始解析频道链接...")
    channels = parse_channel_links(all_content)
    print(f"解析出 {len(channels)} 个有效频道")
    
    if not channels:
        print("未解析到任何频道链接，程序退出")
        return
    
    # 5. 测速并排序链接
    sorted_channels = sort_channels_by_speed(channels)
    
    # 6. 生成M3U8播放列表
    generate_m3u8_playlist(sorted_channels, CONFIG["OUTPUT_FILE"])
    
    print("\n=== 操作完成 ===")

if __name__ == "__main__":
    main()
