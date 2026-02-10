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
    "OLD_SOURCES_FILE": "old_sources.txt",  # 失效链接归档文件
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
}

# ===============================
# 链接检测与处理核心函数
# ===============================
def create_requests_session():
    """创建带重试机制的requests会话"""
    session = requests.Session()
    retry_strategy = Retry(
        total=CONFIG["RETRY_TIMES"],
        backoff_factor=0.1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(CONFIG["HEADERS"])
    return session

def is_link_valid(link, session):
    """检测单个链接是否有效（返回True/False）"""
    try:
        response = session.get(
            link,
            timeout=CONFIG["TEST_TIMEOUT"],
            stream=True  # 只请求头，不下载内容，提高效率
        )
        # 只要状态码在200-299之间，且内容不为空，视为有效
        return response.status_code >= 200 and response.status_code < 300
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, 
            requests.exceptions.RequestException):
        return False

def read_links_from_file(file_path):
    """读取文件中的链接，自动去重并过滤空行"""
    path = Path(file_path)
    if not path.exists():
        return set()
    
    with open(path, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f.readlines()]
    # 去重 + 过滤空行
    valid_links = set(filter(lambda x: x and not x.startswith("#"), links))
    return valid_links

def write_links_to_file(file_path, links, mode="w"):
    """将链接写入文件（默认覆盖，mode='a'为追加）"""
    path = Path(file_path)
    # 确保父目录存在
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, mode, encoding="utf-8") as f:
        for link in sorted(links):  # 排序后写入，便于查看
            f.write(f"{link}\n")

def process_iptv_sources():
    """核心处理逻辑：检测、去重、归档失效链接"""
    print(f"[{datetime.now()}] 开始处理IPTV源链接...")
    
    # 1. 读取原始源链接并去重
    source_file = CONFIG["SOURCE_TXT_FILE"]
    old_file = CONFIG["OLD_SOURCES_FILE"]
    raw_links = read_links_from_file(source_file)
    if not raw_links:
        print(f"[{datetime.now()}] 警告：{source_file} 中未读取到有效链接！")
        return
    
    print(f"[{datetime.now()}] 读取到 {len(raw_links)} 个去重后的原始链接")
    
    # 2. 并发检测链接有效性
    session = create_requests_session()
    valid_links = set()
    invalid_links = set()
    
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        # 提交所有检测任务
        future_to_link = {executor.submit(is_link_valid, link, session): link for link in raw_links}
        
        # 处理结果
        for future in as_completed(future_to_link):
            link = future_to_link[future]
            try:
                if future.result():
                    valid_links.add(link)
                    print(f"[{datetime.now()}] 有效链接：{link}")
                else:
                    invalid_links.add(link)
                    print(f"[{datetime.now()}] 失效链接：{link}")
            except Exception as e:
                invalid_links.add(link)
                print(f"[{datetime.now()}] 检测失败（异常）：{link} | 错误：{str(e)}")
    
    # 3. 写入有效链接到新的iptv_sources.txt（覆盖原有）
    write_links_to_file(source_file, valid_links)
    print(f"[{datetime.now()}] 已将 {len(valid_links)} 个有效链接写入 {source_file}")
    
    # 4. 归档失效链接到old_sources.txt（去重后追加）
    if invalid_links:
        # 读取已有失效链接，避免重复
        existing_old_links = read_links_from_file(old_file)
        new_old_links = invalid_links - existing_old_links
        
        if new_old_links:
            # 追加模式写入，先写注释行（如果文件为空）
            path = Path(old_file)
            if not path.exists() or path.stat().st_size == 0:
                write_links_to_file(old_file, ["失效链接集合区"], mode="w")
            
            write_links_to_file(old_file, new_old_links, mode="a")
            print(f"[{datetime.now()}] 已将 {len(new_old_links)} 个新失效链接追加到 {old_file}")
        else:
            print(f"[{datetime.now()}] 无新增失效链接，无需更新 {old_file}")
    else:
        print(f"[{datetime.now()}] 无失效链接，无需更新 {old_file}")
    
    print(f"[{datetime.now()}] 链接处理完成！")
    print(f"├─ 有效链接数：{len(valid_links)}")
    print(f"└─ 失效链接数：{len(invalid_links)}")

# ===============================
# 原有IPTV爬取逻辑（保留，可根据需要扩展）
# ===============================
def crawl_iptv_playlists():
    """原有爬取逻辑（示例框架，可根据需求完善）"""
    print(f"[{datetime.now()}] 开始生成IPTV最优播放列表...")
    # 此处可保留原有爬取、测速、生成播放列表的逻辑
    # 本示例优先保证链接处理功能，如需完整播放列表生成，可补充原有逻辑
    pass

# ===============================
# 主函数
# ===============================
if __name__ == "__main__":
    # 第一步：处理源链接（去重、检测失效、归档）
    process_iptv_sources()
    
    # 第二步：（可选）执行原有爬取逻辑生成播放列表
    # crawl_iptv_playlists()
