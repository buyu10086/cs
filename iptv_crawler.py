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
# 全局配置区
# ===============================
CONFIG = {
    "SOURCE_TXT_FILE": "iptv_sources.txt",
    "M3U8_SOURCES_FILE": "m3u8_sources.txt",
    "OUTPUT_FILE": "iptv_playlist.m3u8",
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close"
    },
    "TEST_TIMEOUT": 2,
    "MAX_WORKERS": 50,
    "RETRY_TIMES": 1,
    "TOP_K": 3,  # 每个频道只保留前3个最优源
    "IPTV_DISCLAIMER": "个人自用，请勿用于商业用途",
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo",
    "CCTV_SPECIFIC_CONFIG": {
        "enabled": True,
        "TEST_TIMEOUT": 5,
        "MAX_WORKERS": 20
    }
}

# ===============================
# 频道分类
# ===============================
CHANNEL_CATEGORIES = {
    "央视频道": [
        "CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV4欧洲", "CCTV4美洲", "CCTV5", "CCTV5+", "CCTV6", "CCTV7",
        "CCTV8", "CCTV9", "CCTV10", "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15", "CCTV16", "CCTV17", "CCTV4K", "CCTV8K"
    ],
    "卫视频道": [
        "湖南卫视", "浙江卫视", "江苏卫视", "东方卫视", "深圳卫视", "北京卫视", "广东卫视", "广西卫视", "东南卫视", "海南卫视",
        "河北卫视", "河南卫视", "湖北卫视", "江西卫视", "四川卫视", "重庆卫视", "贵州卫视", "云南卫视", "天津卫视", "安徽卫视",
        "山东卫视", "辽宁卫视", "黑龙江卫视", "吉林卫视", "内蒙古卫视", "宁夏卫视", "山西卫视", "陕西卫视", "甘肃卫视", "青海卫视",
        "新疆卫视", "西藏卫视", "三沙卫视", "兵团卫视", "延边卫视", "安多卫视", "康巴卫视", "农林卫视", "厦门卫视", "山东教育卫视",
        "中国教育1台", "中国教育2台", "中国教育3台", "中国教育4台", "早期教育"
    ],
    "数字频道": [
        "CHC动作电影", "CHC家庭影院", "CHC影迷电影", "星空卫视", "CHANNEL[V]", "凤凰卫视中文台", "凤凰卫视资讯台", "凤凰卫视香港台",
        "凤凰卫视电影台", "求索纪录", "金鹰纪实", "纪实科教", "魅力足球", "五星体育", "劲爆体育", "快乐垂钓", "茶频道", "先锋乒羽",
        "天元围棋", "汽摩", "梨园频道", "文物宝库", "武术世界", "游戏风云", "动漫秀场", "卡酷少儿", "金鹰卡通", "优漫卡通", "哈哈炫动", "嘉佳卡通"
    ],
    "湖北地方台": [
        "湖北公共新闻", "湖北经视频道", "湖北综合频道", "湖北垄上频道", "湖北影视频道", "湖北生活频道", "湖北教育频道",
        "武汉新闻综合", "武汉电视剧", "武汉科技生活", "武汉文体频道", "武汉教育频道"
    ],
    "河南省级": [
        "河南卫视", "河南都市频道", "河南民生频道", "河南法治频道", "河南电视剧频道", "河南新闻频道",
        "河南乡村频道", "河南戏曲频道"
    ],
    "河南市县": [
        "郑州1新闻综合", "洛阳-1新闻综合", "南阳1新闻综合", "商丘1新闻综合", "周口公共频道", "开封1新闻综合"
    ]
}

# ===============================
# 别名映射
# ===============================
CHANNEL_MAPPING = {
    "CCTV1": ["CCTV-1", "CCTV 1", "CCTV1 HD", "CCTV-1 HD", "央视一套", "中央一台"],
    "CCTV2": ["CCTV-2", "CCTV 2", "CCTV2 HD", "CCTV-2 HD", "央视二套", "中央二台"],
    "CCTV3": ["CCTV-3", "CCTV 3", "CCTV3 HD", "CCTV-3 HD", "央视三套", "中央三台"],
    "CCTV4": ["CCTV-4", "CCTV 4", "CCTV4 HD", "CCTV-4 HD", "央视四套", "中央四台"],
    "CCTV4欧洲": ["CCTV-4欧洲", "CCTV 4欧洲", "CCTV4欧洲 HD"],
    "CCTV4美洲": ["CCTV-4美洲", "CCTV 4美洲", "CCTV4美洲 HD"],
    "CCTV5": ["CCTV-5", "CCTV 5", "CCTV5 HD", "CCTV-5 HD", "央视五套", "中央五台"],
    "CCTV5+": ["CCTV-5+", "CCTV 5+", "CCTV5+ HD", "CCTV-5+ HD", "体育赛事频道"],
    "CCTV6": ["CCTV-6", "CCTV 6", "CCTV6 HD", "CCTV-6 HD", "央视六套", "中央六台"],
    "CCTV7": ["CCTV-7", "CCTV 7", "CCTV7 HD", "CCTV-7 HD", "央视七套", "中央七台"],
    "CCTV8": ["CCTV-8", "CCTV 8", "CCTV8 HD", "CCTV-8 HD", "央视八套", "中央八台"],
    "CCTV9": ["CCTV-9", "CCTV 9", "CCTV9 HD", "CCTV-9 HD", "央视九套", "中央九台"],
    "CCTV10": ["CCTV-10", "CCTV 10", "CCTV10 HD", "CCTV-10 HD", "央视十套", "中央十台"],
    "CCTV11": ["CCTV-11", "CCTV 11", "CCTV11 HD", "CCTV-11 HD", "央视十一套", "中央十一套"],
    "CCTV12": ["CCTV-12", "CCTV 12", "CCTV12 HD", "CCTV-12 HD", "央视十二套", "中央十二台"],
    "CCTV13": ["CCTV-13", "CCTV 13", "CCTV13 HD", "CCTV-13 HD", "央视十三套", "中央十三台"],
    "CCTV14": ["CCTV-14", "CCTV 14", "CCTV14 HD", "CCTV-14 HD", "央视十四套", "中央十四台"],
    "CCTV15": ["CCTV-15", "CCTV 15", "CCTV15 HD", "CCTV-15 HD", "央视十五套", "中央十五台"],
    "CCTV16": ["CCTV-16", "CCTV 16", "CCTV16 HD", "CCTV-16 HD", "奥林匹克频道"],
    "CCTV17": ["CCTV-17", "CCTV 17", "CCTV17 HD", "CCTV-17 HD", "农业农村频道"],
    "CCTV4K": ["CCTV4K超高清", "CCTV-4K", "央视4K"],
    "CCTV8K": ["CCTV8K超高清", "CCTV-8K", "央视8K"]
}

# ===============================
# 正则
# ===============================
ZUBO_SKIP_PATTERN = re.compile(r"^(更新时间|.*,#genre#|http://kakaxi\.indevs\.in/LOGO/)")
ZUBO_CHANNEL_PATTERN = re.compile(r"^([^,]+),(http://.+?)(\$.*)?$")
URL_CHANNEL_PATTERN = re.compile(r"/(cctv\d+|cctv\d+\+|cctv4k|cctv8k)", re.IGNORECASE)
CCTV_PATTERN = re.compile(
    r"(?:CCTV|央视|中央)[\s\-]?(\d+)(?:\+|PLUS)?|央视(一套|二套|三套|四套|五套|六套|七套|八套|九套|十套|十一套|十二套|十三套|十四套|十五套|十六套|十七套)|央视(体育|电影|纪录|科教|戏曲|新闻|少儿|音乐|奥林匹克|农业农村)",
    re.IGNORECASE
)

GLOBAL_ALIAS_MAP = None
ALL_CATEGORIZED_CHANNELS = set()
for cat in CHANNEL_CATEGORIES.values():
    ALL_CATEGORIZED_CHANNELS.update(cat)
RANK_TAGS = ["$最优", "$次优", "$三优"]

# ===============================
# 工具函数
# ===============================
def normalize_cctv_name(ch_name):
    if not ch_name:
        return ch_name
    clean_name = re.sub(r"[\s\-· HD高清超高清]+", "", ch_name.strip())
    match = CCTV_PATTERN.search(ch_name)
    if match:
        num_group = match.group(1)
        if num_group:
            return f"CCTV{num_group}+" if "+" in clean_name or "PLUS" in clean_name.upper() else f"CCTV{num_group}"
        chinese_group = match.group(2)
        if chinese_group:
            num_map = {"一套": "1", "二套": "2", "三套": "3", "四套": "4", "五套": "5", "六套": "6", "七套": "7", "八套": "8", "九套": "9", "十套": "10", "十一套": "11", "十二套": "12", "十三套": "13", "十四套": "14", "十五套": "15", "十六套": "16", "十七套": "17"}
            return f"CCTV{num_map.get(chinese_group, '')}"
        name_group = match.group(3)
        if name_group:
            name_map = {"体育": "5", "电影": "6", "纪录": "9", "科教": "10", "戏曲": "11", "新闻": "13", "少儿": "14", "音乐": "15", "奥林匹克": "16", "农业农村": "17"}
            return f"CCTV{name_map.get(name_group, '')}"
    if "4K" in clean_name and "CCTV" in clean_name:
        return "CCTV4K"
    if "8K" in clean_name and "CCTV" in clean_name:
        return "CCTV8K"
    return ch_name

def get_requests_session():
    session = requests.Session()
    retry = Retry(total=CONFIG["RETRY_TIMES"], backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(CONFIG["HEADERS"])
    return session

def build_alias_map():
    global GLOBAL_ALIAS_MAP
    if GLOBAL_ALIAS_MAP is not None:
        return GLOBAL_ALIAS_MAP
    alias_map = {name: name for name in CHANNEL_MAPPING.keys()}
    for main_name, aliases in CHANNEL_MAPPING.items():
        for alias in aliases:
            alias_map[alias] = main_name
    GLOBAL_ALIAS_MAP = alias_map
    return alias_map

def test_single_url(url, timeout):
    session = get_requests_session()
    try:
        start = time.time()
        try:
            with session.head(url, timeout=timeout, allow_redirects=True) as r:
                return url, round(time.time() - start, 2)
        except:
            start = time.time()
            with session.get(url, timeout=timeout, stream=True) as r:
                r.raw.read(1)
                return url, round(time.time() - start, 2)
    except:
        return url, float('inf')
    finally:
        session.close()

def test_urls_concurrent(urls, timeout, max_workers):
    if not urls:
        return {}
    unique = list(set(urls))
    res = {}
    with ThreadPoolExecutor(max_workers) as pool:
        futs = {pool.submit(test_single_url, u, timeout): u for u in unique}
        for f in as_completed(futs):
            u, t = f.result()
            if t < float('inf'):
                res[u] = t
    return res

# ===============================
# 读取与解析
# ===============================
def read_iptv_sources_from_txt():
    p = Path(CONFIG["SOURCE_TXT_FILE"])
    urls = set()
    if not p.exists():
        p.write_text("# 填写你的源链接\n", encoding="utf-8")
        return []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.startswith(("http://", "https://")):
            urls.add(line)
    return list(urls)

def read_standalone_m3u8_links():
    p = Path(CONFIG["M3U8_SOURCES_FILE"])
    res = {}
    if not p.exists():
        return res
    alias = build_alias_map()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = URL_CHANNEL_PATTERN.search(line)
        if m:
            name = m.group(1).upper()
            std = alias.get(normalize_cctv_name(name), name)
            res.setdefault(std, set()).add(line)
    for k in res:
        res[k] = list(res[k])
    return res

def parse_zubo_source(content):
    res = {}
    alias = build_alias_map()
    for line in content.splitlines():
        line = line.strip()
        if not line or ZUBO_SKIP_PATTERN.match(line):
            continue
        m = ZUBO_CHANNEL_PATTERN.match(line)
        if m:
            name, url = m.group(1).strip(), m.group(2).strip()
            std = alias.get(normalize_cctv_name(name), name)
            res.setdefault(std, set()).add(url)
    for k in res:
        res[k] = list(res[k])
    return res

def parse_standard_m3u8(content):
    res = {}
    alias = build_alias_map()
    cur = None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            cur = line.split(",")[-1].strip() if "," in line else None
        elif line.startswith(("http://", "https://")) and cur:
            std = alias.get(normalize_cctv_name(cur), cur)
            res.setdefault(std, set()).add(line)
            cur = None
    for k in res:
        res[k] = list(res[k])
    return res

# ===============================
# 爬取 + 合并 + 每个频道只留前3
# ===============================
def crawl_and_merge_sources(session):
    all_ch = {}
    st = read_standalone_m3u8_links()
    for ch, ls in st.items():
        all_ch.setdefault(ch, set()).update(ls)
    for url in read_iptv_sources_from_txt():
        try:
            r = session.get(url, timeout=10)
            r.encoding = "utf-8"
            chs = parse_zubo_source(r.text) if CONFIG["ZUBO_SOURCE_MARKER"] in url else parse_standard_m3u8(r.text)
            for ch, ls in chs.items():
                all_ch.setdefault(ch, set()).update(ls)
        except:
            continue
    for ch in all_ch:
        all_ch[ch] = list(all_ch[ch])
    return all_ch

def crawl_and_select_top3(session):
    raw = crawl_and_merge_sources(session)
    top = {}
    topk = CONFIG["TOP_K"]
    for ch, urls in tqdm(raw.items(), desc="测速筛选"):
        if not urls:
            continue
        cfg = CONFIG["CCTV_SPECIFIC_CONFIG"]
        to, mw = (cfg["TEST_TIMEOUT"], cfg["MAX_WORKERS"]) if cfg["enabled"] and ch.startswith("CCTV") else (CONFIG["TEST_TIMEOUT"], CONFIG["MAX_WORKERS"])
        lat = test_urls_concurrent(urls, to, mw)
        if not lat:
            continue
        # 按速度排序，只保留前3个
        sorted_urls = sorted(lat.keys(), key=lambda x: lat[x])
        top[ch] = sorted_urls[:topk]
    return top

# ===============================
# 生成播放列表
# ===============================
def generate_iptv_playlist(top_channels):
    if not top_channels:
        return
    p = Path(CONFIG["OUTPUT_FILE"])
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    lines = [f"更新时间: {now}", "", "更新时间,#genre#", f"{now},{CONFIG['IPTV_DISCLAIMER']}", ""]
    for cat, chs in CHANNEL_CATEGORIES.items():
        lines.append(f"{cat},#genre#")
        for ch in chs:
            if ch not in top_channels:
                continue
            for i, u in enumerate(top_channels[ch]):
                tag = RANK_TAGS[i] if i < len(RANK_TAGS) else f"${i+1}"
                lines.append(f"{ch},{u}{tag}")
        lines.append("")
    others = [ch for ch in top_channels if ch not in ALL_CATEGORIZED_CHANNELS]
    if others:
        lines.append("其它频道,#genre#")
        for ch in others:
            for i, u in enumerate(top_channels[ch]):
                tag = RANK_TAGS[i] if i < len(RANK_TAGS) else f"${i+1}"
                lines.append(f"{ch},{u}{tag}")
        lines.append("")
    p.write_text("\n".join(lines).rstrip(), encoding="utf-8")
    print(f"\n已生成：{p.name}，每个频道最多保留 {CONFIG['TOP_K']} 个源")

# ===============================
# 主程序
# ===============================
if __name__ == "__main__":
    print("IPTV 源自动测速 · 每个频道只保留前3最优源")
    session = get_requests_session()
    build_alias_map()
    top_channels = crawl_and_select_top3(session)
    generate_iptv_playlist(top_channels)
    print("完成！")
