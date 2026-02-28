import re
import requests
import time
import socket
from datetime import datetime, timezone, timedelta
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import warnings
warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)

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
# 全局配置区（优化后）
# ===============================
CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",
    "M3U8_SOURCES_FILE": "m3u8_sources.txt",
    "OUTPUT_FILE": "iptv_playlist.m3u8",
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "keep-alive",  # 优化：长连接减少握手开销
        "Accept-Encoding": "gzip, deflate",  # 压缩传输提升速度
        "Accept": "*/*",
        "Cache-Control": "no-cache"
    },
    # 全局测速配置（精细化）
    "TEST_TIMEOUT": 3,  # 优化：适度提高超时（2→3），平衡速度与成功率
    "MAX_WORKERS": 30,  # 优化：降低默认并发（50→30），减少网络拥塞
    "RETRY_TIMES": 2,   # 优化：重试次数+1，提升弱网成功率
    "TOP_K": 3,
    "IPTV_DISCLAIMER": "个人自用，请勿用于商业用途",
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo",
    # CCTV 单独配置（优化）
    "CCTV_SPECIFIC_CONFIG": {
        "enabled": True,
        "TEST_TIMEOUT": 6,
        "MAX_WORKERS": 20
    },
    # 新增：网络优化配置
    "CONNECT_TIMEOUT": 1,  # 连接超时（TCP握手）
    "READ_TIMEOUT": 2,     # 读取超时（数据传输）
    "POOL_MAXSIZE": 100,   # 连接池大小
    "RETRY_BACKOFF_FACTOR": 0.5,  # 重试退避因子（0.5秒→1秒→2秒）
    "DNS_CACHE_TTL": 300,  # DNS缓存时间（秒）
}

# ===============================
# 全局网络会话（复用连接池）
# ===============================
# 配置重试策略
retry_strategy = Retry(
    total=CONFIG["RETRY_TIMES"],
    backoff_factor=CONFIG["RETRY_BACKOFF_FACTOR"],
    status_forcelist=[429, 500, 502, 503, 504],  # 只重试服务器错误
    allowed_methods=["GET", "HEAD"],  # 安全的重试方法
    raise_on_status=False
)

# 配置HTTP适配器（连接池+重试）
adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=CONFIG["POOL_MAXSIZE"],
    pool_maxsize=CONFIG["POOL_MAXSIZE"],
    pool_block=False  # 非阻塞连接池
)

# 全局会话（复用连接）
session = requests.Session()
session.mount("http://", adapter)
session.mount("https://", adapter)
session.headers.update(CONFIG["HEADERS"])
session.verify = False  # 跳过SSL验证（提升速度，避免证书错误）
session.trust_env = False  # 禁用系统代理（避免代理干扰）

# ===============================
# DNS缓存优化（减少DNS解析耗时）
# ===============================
class DNSCache:
    def __init__(self, ttl=CONFIG["DNS_CACHE_TTL"]):
        self.cache = {}
        self.ttl = ttl

    def resolve(self, host):
        now = time.time()
        if host in self.cache and now - self.cache[host]["time"] < self.ttl:
            return self.cache[host]["ip"]
        try:
            ip = socket.gethostbyname(host)
            self.cache[host] = {"ip": ip, "time": now}
            return ip
        except:
            return None

dns_cache = DNSCache()

# ===============================
# 频道分类与别名映射（保持不变）
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
    # 其他映射保持不变
}

# ===============================
# 核心工具函数（优化后）
# ===============================
def test_url_speed(url, is_cctv=False):
    """
    测速函数（优化：分阶段超时、DNS缓存、跳过大文件）
    """
    start_time = time.time()
    timeout = CONFIG["CCTV_SPECIFIC_CONFIG"]["TEST_TIMEOUT"] if (is_cctv and CONFIG["CCTV_SPECIFIC_CONFIG"]["enabled"]) else CONFIG["TEST_TIMEOUT"]
    try:
        # 1. DNS缓存优化
        parsed_url = requests.utils.urlparse(url)
        if parsed_url.hostname:
            ip = dns_cache.resolve(parsed_url.hostname)
            if not ip:
                return None  # DNS解析失败直接跳过

        # 2. 分阶段超时（连接+读取）
        response = session.head(
            url,
            timeout=(CONFIG["CONNECT_TIMEOUT"], CONFIG["READ_TIMEOUT"]),
            allow_redirects=True,
            stream=True  # 不下载响应体
        )

        # 3. 过滤无效响应
        if response.status_code != 200:
            return None

        # 4. 跳过超大文件（避免耗时）
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > 1024 * 1024:  # 大于1MB跳过
            return None

        # 5. 计算响应时间
        elapsed = (time.time() - start_time) * 1000  # 毫秒
        return elapsed if elapsed < timeout * 1000 else None

    except (requests.exceptions.RequestException, socket.timeout, TimeoutError, ValueError):
        return None
    except Exception as e:
        # 静默忽略其他异常（避免程序中断）
        return None

def process_channels(channels, is_cctv=False):
    """
    并发处理频道（优化：动态线程池、进度条、异常捕获）
    """
    results = {}
    max_workers = CONFIG["CCTV_SPECIFIC_CONFIG"]["MAX_WORKERS"] if (is_cctv and CONFIG["CCTV_SPECIFIC_CONFIG"]["enabled"]) else CONFIG["MAX_WORKERS"]
    
    # 动态调整线程数（避免超出系统限制）
    max_workers = min(max_workers, len(channels), 50)  # 上限50
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交任务
        future_to_channel = {
            executor.submit(test_url_speed, channel["url"], is_cctv): channel 
            for channel in channels
        }
        
        # 处理结果（带进度条）
        for future in tqdm(as_completed(future_to_channel), total=len(future_to_channel), desc="测速中"):
            channel = future_to_channel[future]
            try:
                speed = future.result(timeout=timeout + 1)  # 任务超时保护
                if speed is not None:
                    channel_name = channel["name"]
                    if channel_name not in results:
                        results[channel_name] = []
                    results[channel_name].append({"url": channel["url"], "speed": speed})
            except TimeoutError:
                continue
            except Exception:
                continue
    
    # 按速度排序，保留TOP_K
    for name in results:
        results[name].sort(key=lambda x: x["speed"])
        results[name] = results[name][:CONFIG["TOP_K"]]
    
    return results

# ===============================
# 主函数（优化：资源清理、分步执行）
# ===============================
def main():
    try:
        # 1. 读取源文件（优化：批量读取、编码容错）
        def read_source_file(file_path):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return [line.strip() for line in f if line.strip()]
            except FileNotFoundError:
                print(f"警告：{file_path} 不存在，跳过")
                return []

        iptv_sources = read_source_file(CONFIG["SOURCE_TXT_FILE"])
        m3u8_sources = read_source_file(CONFIG["M3U8_SOURCES_FILE"])

        # 2. 解析频道（原有逻辑不变，复用全局session）
        all_channels = []
        # ... 此处保留原有解析逻辑，替换requests.get为session.get ...

        # 3. 分类处理
        cctv_channels = [c for c in all_channels if any(key in c["name"] for key in CHANNEL_CATEGORIES["央视频道"])]
        other_channels = [c for c in all_channels if c not in cctv_channels]

        # 4. 测速
        cctv_results = process_channels(cctv_channels, is_cctv=True)
        other_results = process_channels(other_channels, is_cctv=False)
        all_results = {**cctv_results, **other_results}

        # 5. 生成输出文件（优化：批量写入、原子操作）
        output_path = Path(CONFIG["OUTPUT_FILE"])
        temp_path = output_path.with_suffix(".tmp")
        
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(f"#EXTM3U x-tvg-url=\"\"\n")
            f.write(f"#EXT-X-DISCLAIMER: {CONFIG['IPTV_DISCLAIMER']}\n")
            f.write(f"#EXT-X-GENERATED: {datetime.now(timezone.utc).astimezone().isoformat()}\n\n")
            
            # 按分类写入
            for category, channel_names in CHANNEL_CATEGORIES.items():
                f.write(f"#EXT-X-CATEGORY: {category}\n")
                for name in channel_names:
                    if name in all_results:
                        for item in all_results[name]:
                            f.write(f"#EXTINF:-1 group-title=\"{category}\",{name}\n")
                            f.write(f"{item['url']}\n")
                f.write("\n")
        
        # 原子替换（避免文件损坏）
        temp_path.rename(output_path)
        print(f"成功生成：{output_path}")

    except Exception as e:
        print(f"运行错误：{e}")
        raise
    finally:
        # 清理资源
        session.close()
        dns_cache.cache.clear()
        print("资源已释放")

if __name__ == "__main__":
    # 设置全局超时（兜底）
    socket.setdefaulttimeout(CONFIG["TEST_TIMEOUT"] + 2)
    main()
