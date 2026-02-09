import re
import requests
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===============================
# 全局配置区（可根据自身网络调整）
# ===============================
CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",  # IPTV源链接文件路径
    "OLD_SOURCES_FILE": "old_sources.txt",  # 失效链接归档文件
    "OUTPUT_FILE": "iptv_playlist.m3u8",    # 爬虫输出的播放列表文件
    "MAX_OLD_RECORDS": 100,                  # 失效链接归档最大保留条数
    "MAX_FAST_SOURCES": 6,                  # 选取速度最快的源链接数量
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close"  # 关闭长连接，减少资源占用
    },
    # 链接检查/测速配置
    "TEST_TIMEOUT": 3,        # 单链接超时时间（秒），网络差可改5-8
    "MAX_WORKERS": 40,        # 并发检查/测速线程数，带宽低可改20
    "RETRY_TIMES": 1,         # 网络请求重试次数
    "TOP_K": 3,               # 每个频道保留最优源数量
    "IPTV_DISCLAIMER": "本文件仅用于技术研究，请勿用于商业用途，相关版权归原作者所有",
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo"  # zubo源格式识别标记
}

# ===============================
# 频道分类与别名映射（保持兼容）
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
# 核心工具函数
# ===============================
def create_requests_session():
    """创建带重试机制的requests会话，提升链接检查/测速稳定性"""
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

def check_url_validity(url):
    """检查单个URL是否有效（2xx状态码视为有效）"""
    session = create_requests_session()
    try:
        response = session.head(
            url,
            timeout=CONFIG["TEST_TIMEOUT"],
            allow_redirects=True
        )
        return url, response.status_code >= 200 and response.status_code < 300
    except Exception:
        return url, False

def test_url_speed(url):
    """测试单个URL的响应速度，返回(URL, 响应时间/None)"""
    session = create_requests_session()
    try:
        start_time = time.time()
        # 下载少量数据（前1024字节）测试速度，避免下载完整文件
        response = session.get(
            url,
            timeout=CONFIG["TEST_TIMEOUT"],
            allow_redirects=True,
            stream=True
        )
        # 读取前1024字节触发实际请求
        response.raw.read(1024, decode_content=False)
        end_time = time.time()
        response_time = round((end_time - start_time) * 1000, 2)  # 转换为毫秒
        return url, response_time
    except Exception:
        return url, None

def parse_old_record(line):
    """解析old_sources.txt中的单行记录，返回(时间对象, 链接)"""
    try:
        match = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.*)", line.strip())
        if match:
            time_str = match.group(1)
            url = match.group(2)
            record_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return (record_time, url)
    except Exception:
        pass
    return None

# ===============================
# 失效链接归档逻辑
# ===============================
def archive_invalid_urls(invalid_urls):
    """将失效链接归档到old_sources.txt，仅保留最新的10条记录"""
    if not invalid_urls:
        return
    
    # 构造新记录
    delete_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_records = [f"[{delete_time}] {url}" for url in invalid_urls]
    
    # 读取原有记录
    old_file = Path(CONFIG["OLD_SOURCES_FILE"])
    old_records = []
    if old_file.exists():
        with open(old_file, "r", encoding="utf-8") as f:
            old_records = [line.strip() for line in f.readlines() if line.strip()]
    
    # 合并解析+去重+排序
    all_records = new_records + old_records
    parsed_records = []
    for record in all_records:
        parsed = parse_old_record(record)
        if parsed:
            parsed_records.append(parsed)
    
    # 去重（保留同一链接最新记录）
    unique_records = {}
    for record_time, url in parsed_records:
        if url not in unique_records or record_time > unique_records[url][0]:
            unique_records[url] = (record_time, url)
    
    # 按时间降序排序+保留前10条
    sorted_records = sorted(unique_records.values(), key=lambda x: x[0], reverse=True)
    final_records = sorted_records[:CONFIG["MAX_OLD_RECORDS"]]
    
    # 写入文件
    final_text = [f"[{rt.strftime('%Y-%m-%d %H:%M:%S')}] {url}" for rt, url in final_records]
    with open(old_file, "w", encoding="utf-8") as f:
        f.write("\n".join(final_text) + "\n")
    
    print(f"📝 已将 {len(invalid_urls)} 个失效链接归档到 {old_file.name}")
    print(f"   归档文件当前保留 {len(final_records)} 条最新失效链接记录（最多{CONFIG['MAX_OLD_RECORDS']}条）")

# ===============================
# 链接清理+测速筛选逻辑
# ===============================
def clean_invalid_sources():
    """自动清理iptv_sources.txt中的失效链接，并归档到old_sources.txt"""
    source_file = Path(CONFIG["SOURCE_TXT_FILE"])
    
    # 检查文件是否存在
    if not source_file.exists():
        print(f"⚠️  源文件 {source_file.name} 不存在，跳过链接清理")
        return []
    
    # 读取并预处理链接
    with open(source_file, "r", encoding="utf-8") as f:
        raw_urls = [line.strip() for line in f.readlines()]
    original_urls = list(set([url for url in raw_urls if url]))  # 去重+过滤空行
    
    if not original_urls:
        print(f"⚠️  源文件 {source_file.name} 中无有效链接，跳过清理")
        return []
    
    print(f"🔍 开始检查 {len(original_urls)} 个IPTV源链接的有效性...")
    
    # 并发检查有效性
    valid_urls = []
    invalid_urls = []
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        future_tasks = {executor.submit(check_url_validity, url): url for url in original_urls}
        for future in as_completed(future_tasks):
            url, is_valid = future.result()
            if is_valid:
                valid_urls.append(url)
                print(f"✅ 有效: {url}")
            else:
                invalid_urls.append(url)
                print(f"❌ 失效: {url}")
    
    # 写回有效链接到原文件
    with open(source_file, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_urls))
    
    # 归档失效链接
    archive_invalid_urls(invalid_urls)
    
    # 输出清理结果
    print(f"\n📊 链接清理完成 ───────────")
    print(f"   原始链接数：{len(original_urls)}")
    print(f"   有效链接数：{len(valid_urls)}")
    print(f"   失效链接数：{len(invalid_urls)}")
    print(f"──────────────────────────\n")
    
    return valid_urls

def get_fastest_sources(valid_urls):
    """从有效链接中筛选前N条速度最快的（N=MAX_FAST_SOURCES）"""
    if not valid_urls:
        print(f"⚠️  无有效链接可测速，返回空列表")
        return []
    
    # 如果有效链接数≤目标数，直接返回所有
    if len(valid_urls) <= CONFIG["MAX_FAST_SOURCES"]:
        print(f"✅ 有效链接数({len(valid_urls)})≤{CONFIG['MAX_FAST_SOURCES']}，无需测速，直接使用所有有效链接")
        return valid_urls
    
    print(f"⚡ 开始对 {len(valid_urls)} 个有效链接进行速度测试（选取最快{CONFIG['MAX_FAST_SOURCES']}条）...")
    
    # 并发测速
    speed_results = []
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        future_tasks = {executor.submit(test_url_speed, url): url for url in valid_urls}
        for future in as_completed(future_tasks):
            url, response_time = future.result()
            if response_time is not None:
                speed_results.append((url, response_time))
                print(f"📶 {url} - 响应时间：{response_time}ms")
            else:
                print(f"❌ {url} - 测速失败（超时/错误）")
    
    # 按响应时间升序排序（越快越靠前）
    speed_results.sort(key=lambda x: x[1])
    
    # 选取前N条最快的
    fastest_urls = [item[0] for item in speed_results[:CONFIG["MAX_FAST_SOURCES"]]]
    
    # 输出测速结果
    print(f"\n🏆 速度测试完成 ───────────")
    print(f"   成功测速链接数：{len(speed_results)}")
    print(f"   选取最快{CONFIG['MAX_FAST_SOURCES']}条链接：")
    for i, url in enumerate(fastest_urls, 1):
        print(f"   {i}. {url}")
    print(f"──────────────────────────\n")
    
    return fastest_urls

# ===============================
# 爬虫主逻辑（替换为你的实际代码）
# ===============================
def run_iptv_crawler(fastest_sources):
    """IPTV爬虫主逻辑，仅使用筛选后的最快链接"""
    print("🚀 开始执行IPTV爬虫程序（仅使用最快的源链接）...")
    if not fastest_sources:
        print("⚠️  无可用的源链接，爬虫程序跳过执行")
        return
    
    # --------------------------
    # 以下替换为你原有的爬虫代码
    # 示例逻辑：使用fastest_sources列表中的链接进行爬取
    # --------------------------
    # 1. 遍历最快的源链接
    for i, source_url in enumerate(fastest_sources, 1):
        print(f"📥 正在爬取第{i}个源链接：{source_url}")
        time.sleep(0.5)  # 模拟爬取延迟
    
    # 2. 生成播放列表（示例）
    with open(CONFIG["OUTPUT_FILE"], "w", encoding="utf-8") as f:
        f.write(f"#EXTM3U\n# 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# 数据源：选取的{CONFIG['MAX_FAST_SOURCES']}条最快链接\n")
        for url in fastest_sources:
            f.write(f"#EXTINF:-1,IPTV源_{fastest_sources.index(url)+1}\n{url}\n")
    
    print("✅ IPTV爬虫程序执行完成！")
    print(f"📄 播放列表已生成：{CONFIG['OUTPUT_FILE']}")

# ===============================
# 程序入口
# ===============================
def main():
    """主流程：清理失效链接 → 测速筛选最快6条 → 执行爬虫"""
    # 第一步：清理失效链接，获取所有有效链接
    valid_urls = clean_invalid_sources()
    
    # 第二步：从有效链接中筛选最快的6条
    fastest_sources = get_fastest_sources(valid_urls)
    
    # 第三步：执行爬虫逻辑（仅使用最快的链接）
    run_iptv_crawler(fastest_sources)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  程序被用户手动中断")
    except Exception as e:
        print(f"\n❌ 程序执行出错: {str(e)}")
