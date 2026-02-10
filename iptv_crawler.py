import re
import requests
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

# ===============================
# 日志配置（解决重复打印问题）
# ===============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ===============================
# 全局配置区（核心参数可调）
# ===============================
CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",  # 存储所有IPTV源链接
    "OUTPUT_FILE": "iptv_playlist.m3u8",  # 生成的最优播放列表
    "OLD_SOURCES_FILE": "old_sources.txt",  # 失效链接存储文件
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close"
    },
    # 测速配置
    "TEST_TIMEOUT": 3,
    "MAX_WORKERS": 40,  # 降低并发数，减少重复任务
    "RETRY_TIMES": 1,
    "TOP_K": 3,
    "IPTV_DISCLAIMER": "本文件仅用于技术研究，请勿用于商业用途，相关版权归原作者所有",
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo"
}

# ===============================
# 频道分类与别名映射（无变动）
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
# 工具函数：创建带重试的请求会话
# ===============================
def create_requests_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=CONFIG["RETRY_TIMES"],
        backoff_factor=0.1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(CONFIG["HEADERS"])
    return session

# ===============================
# 链接有效性检测（修复重复检测）
# ===============================
def is_link_valid(link, session, checked_links):
    """
    检测单个链接是否有效，增加已检测链接缓存避免重复检测
    :param link: 待检测链接
    :param session: 请求会话
    :param checked_links: 已检测链接的缓存字典（共享）
    :return: 链接是否有效
    """
    # 先查缓存，避免重复检测
    if link in checked_links:
        return checked_links[link]
    
    try:
        response = session.head(
            link,
            timeout=CONFIG["TEST_TIMEOUT"],
            allow_redirects=True,
            verify=False
        )
        is_valid = response.status_code >= 200 and response.status_code < 300
    except requests.exceptions.HeadNotAllowed:
        try:
            response = session.get(
                link,
                timeout=CONFIG["TEST_TIMEOUT"],
                allow_redirects=True,
                verify=False,
                stream=True
            )
            response.close()
            is_valid = response.status_code >= 200 and response.status_code < 300
        except Exception:
            is_valid = False
    except Exception:
        is_valid = False
    
    # 写入缓存
    checked_links[link] = is_valid
    return is_valid

# ===============================
# 清理源文件（修复重复写入）
# ===============================
def clean_sources_file():
    """
    修复点：
    1. 增加已检测链接缓存，避免重复检测
    2. 优化失效链接去重逻辑，避免重复写入
    3. 统一日志输出，避免重复打印
    """
    source_path = Path(CONFIG["SOURCE_TXT_FILE"])
    old_path = Path(CONFIG["OLD_SOURCES_FILE"])
    
    if not source_path.exists():
        logger.warning(f"源文件 {source_path} 不存在，跳过清理")
        return
    
    # 1. 读取并去重（严格去重，避免重复链接）
    with open(source_path, "r", encoding="utf-8") as f:
        raw_links = [line.strip() for line in f if line.strip()]
    # 严格去重（无序但彻底），避免重复处理
    unique_links = list(set(raw_links))
    logger.info(f"读取到 {len(raw_links)} 个链接，去重后剩余 {len(unique_links)} 个")
    
    if not unique_links:
        logger.info("源文件去重后无有效链接，跳过检测")
        return
    
    # 2. 并发检测（带缓存避免重复）
    session = create_requests_session()
    checked_links = {}  # 检测结果缓存
    valid_links = []
    invalid_links = []
    
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        future_to_link = {
            executor.submit(is_link_valid, link, session, checked_links): link 
            for link in unique_links
        }
        
        for future in as_completed(future_to_link):
            link = future_to_link[future]
            try:
                if future.result():
                    valid_links.append(link)
                    logger.info(f"有效链接: {link}")
                else:
                    invalid_links.append(link)
                    logger.warning(f"失效链接: {link}")
            except Exception as e:
                invalid_links.append(link)
                logger.error(f"检测失败（判定为失效）: {link} | 错误: {str(e)}")
    
    # 3. 写入有效链接（覆盖，确保无重复）
    with open(source_path, "w", encoding="utf-8") as f:
        # 排序后写入，保持一致性
        valid_links_sorted = sorted(valid_links)
        f.write("\n".join(valid_links_sorted) + "\n")
    logger.info(f"已将 {len(valid_links)} 个有效链接写入 {source_path}")
    
    # 4. 处理失效链接（彻底去重，避免重复追加）
    if invalid_links:
        # 读取已有失效链接（全量去重）
        existing_old_links = set()
        if old_path.exists():
            with open(old_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith(("#", "失效链接集合区")):
                        # 提取链接部分（去掉时间戳）
                        link_part = line.split(" | ")[0].strip()
                        existing_old_links.add(link_part)
        
        # 过滤已存在的失效链接
        new_invalid_links = []
        for link in invalid_links:
            if link not in existing_old_links and link not in new_invalid_links:
                new_invalid_links.append(link)
        
        if new_invalid_links:
            # 确保文件存在
            if not old_path.exists():
                with open(old_path, "w", encoding="utf-8") as f:
                    f.write("失效链接集合区\n")
            
            # 写入（带时间戳，避免重复）
            with open(old_path, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 排序后写入，便于查看
                for link in sorted(new_invalid_links):
                    f.write(f"{link} | 失效时间: {timestamp}\n")
            
            logger.info(f"已将 {len(new_invalid_links)} 个新失效链接追加到 {old_path}")
        else:
            logger.info("无新的失效链接需要追加到old_sources.txt")
    else:
        logger.info("未检测到失效链接")

# ===============================
# 原有功能（无变动，仅替换日志输出）
# ===============================
def parse_iptv_source(link, session):
    channel_map = {}
    try:
        response = session.get(
            link,
            timeout=CONFIG["TEST_TIMEOUT"] * 2,
            verify=False
        )
        response.encoding = response.apparent_encoding or "utf-8"
        content = response.text
        
        if CONFIG["ZUBO_SOURCE_MARKER"] in link:
            lines = content.strip().split("\n")
            for line in lines:
                if "," in line:
                    name, url = line.split(",", 1)
                    name = name.strip()
                    url = url.strip()
                    if name and url:
                        channel_map[name] = channel_map.get(name, []) + [url]
        else:
            m3u_pattern = re.compile(r'#EXTINF:.*?,(.*?)\n(https?://.*?)\n', re.IGNORECASE)
            matches = m3u_pattern.findall(content)
            for name, url in matches:
                name = name.strip()
                url = url.strip()
                if name and url:
                    channel_map[name] = channel_map.get(name, []) + [url]
    except Exception as e:
        logger.error(f"解析源 {link} 失败: {str(e)}")
    return channel_map

def test_link_speed(link, session):
    try:
        start_time = time.time()
        response = session.get(
            link,
            timeout=CONFIG["TEST_TIMEOUT"],
            verify=False,
            stream=True
        )
        response.iter_content(chunk_size=1024, decode_unicode=False)
        response.close()
        elapsed = time.time() - start_time
        return elapsed
    except Exception:
        return float("inf")

def get_best_links(channel_name, link_list, session):
    # 先去重链接，避免重复测速
    link_list = list(set(link_list))
    link_speed = []
    
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        future_to_link = {
            executor.submit(test_link_speed, link, session): link
            for link in link_list
        }
        for future in as_completed(future_to_link):
            link = future_to_link[future]
            speed = future.result()
            if speed < float("inf"):
                link_speed.append((speed, link))
    
    link_speed.sort(key=lambda x: x[0])
    best_links = [link for (speed, link) in link_speed[:CONFIG["TOP_K"]]]
    return best_links

def generate_playlist():
    source_path = Path(CONFIG["SOURCE_TXT_FILE"])
    if not source_path.exists():
        logger.error(f"源文件 {source_path} 不存在，无法生成播放列表")
        return
    
    with open(source_path, "r", encoding="utf-8") as f:
        source_links = [line.strip() for line in f if line.strip()]
    if not source_links:
        logger.error("源文件中无有效链接，无法生成播放列表")
        return
    
    session = create_requests_session()
    all_channels = {}
    
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        future_to_link = {
            executor.submit(parse_iptv_source, link, session): link
            for link in source_links
        }
        
        for future in as_completed(future_to_link):
            link = future_to_link[future]
            try:
                channel_map = future.result()
                for name, urls in channel_map.items():
                    if name not in all_channels:
                        all_channels[name] = []
                    # 去重后添加
                    all_channels[name].extend(list(set(urls)))
            except Exception as e:
                logger.error(f"处理源 {link} 失败: {str(e)}")
    
    # 生成播放列表
    final_playlist = [
        "#EXTM3U",
        f"#EXT-X-DISCLAIMER:{CONFIG['IPTV_DISCLAIMER']}",
        f"#EXT-X-UPDATE-TIME:{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    
    for category, channel_names in CHANNEL_CATEGORIES.items():
        final_playlist.append(f"\n#EXT-X-CATEGORY:{category}")
        
        for channel_name in channel_names:
            match_names = [channel_name] + CHANNEL_MAPPING.get(channel_name, [])
            found_urls = []
            
            for match_name in match_names:
                if match_name in all_channels:
                    found_urls.extend(all_channels[match_name])
            
            if not found_urls:
                continue
            
            # 去重后测速
            found_urls = list(set(found_urls))
            best_links = get_best_links(channel_name, found_urls, session)
            if not best_links:
                continue
            
            for idx, url in enumerate(best_links):
                final_playlist.append(f"#EXTINF:-1 group-title=\"{category}\",{channel_name}{f'({idx+1})' if idx>0 else ''}")
                final_playlist.append(url)
    
    # 写入文件
    with open(CONFIG["OUTPUT_FILE"], "w", encoding="utf-8") as f:
        f.write("\n".join(final_playlist))
    logger.info(f"最优播放列表已生成: {CONFIG['OUTPUT_FILE']}")

# ===============================
# 主函数
# ===============================
if __name__ == "__main__":
    logger.info("="*50)
    logger.info("📺 IPTV源清理与播放列表生成工具")
    logger.info("="*50)
    
    # 第一步：清理源文件
    logger.info("\n🔧 开始清理源文件...")
    clean_sources_file()
    
    # 第二步：生成播放列表
    logger.info("\n🎬 开始生成最优播放列表...")
    generate_playlist()
    
    logger.info("\n✅ 所有操作完成！")
