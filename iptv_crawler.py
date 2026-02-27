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
    "SOURCE_TXT_FILE": "iptv_sources.txt",
    "OUTPUT_FILE": "iptv_playlist.m3u8",
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close"
    },
    "TEST_TIMEOUT": 3,      # 延长超时，适配可能较慢的直播源
    "MAX_WORKERS": 20,      # 降低并发，避免被封
    "RETRY_TIMES": 0,       # 关闭重试，加快测试速度
    "TOP_K": 3,
    "IPTV_DISCLAIMER": "个人自用，请勿用于商业用途",
    "ZUBO_SOURCE_MARKER": "kakaxi-1/zubo",
    "CCTV_SPECIFIC_CONFIG": {
        "enabled": True,
        "TEST_TIMEOUT": 5,
        "MAX_WORKERS": 10
    }
}

# ===============================
# 频道分类与别名（保持不变）
# ===============================
CHANNEL_CATEGORIES = {
    "央视频道": ["CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV5", "CCTV5+", "CCTV6", "CCTV7", "CCTV8", "CCTV9", "CCTV10", "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15", "CCTV16", "CCTV17"],
    "卫视频道": ["湖南卫视", "浙江卫视", "江苏卫视", "东方卫视"],
    "其他频道": []
}

CHANNEL_MAPPING = {
    "CCTV1": ["CCTV-1", "央视一套"],
    "CCTV2": ["CCTV-2", "央视二套"],
    "CCTV3": ["CCTV-3", "央视三套"],
    "CCTV4": ["CCTV-4", "央视四套"],
    "CCTV5": ["CCTV-5", "央视五套", "体育"],
    "CCTV5+": ["CCTV-5+", "体育赛事"],
    "CCTV6": ["CCTV-6", "央视六套", "电影"],
    "CCTV7": ["CCTV-7", "央视七套"],
    "CCTV8": ["CCTV-8", "央视八套", "电视剧"],
    "CCTV9": ["CCTV-9", "央视九套", "纪录"],
    "CCTV10": ["CCTV-10", "央视十套", "科教"],
    "CCTV11": ["CCTV-11", "央视十一套", "戏曲"],
    "CCTV12": ["CCTV-12", "央视十二套", "社会与法"],
    "CCTV13": ["CCTV-13", "央视十三套", "新闻"],
    "CCTV14": ["CCTV-14", "央视十四套", "少儿"],
    "CCTV15": ["CCTV-15", "央视十五套", "音乐"],
    "CCTV16": ["CCTV-16", "央视十六套", "奥林匹克"],
    "CCTV17": ["CCTV-17", "央视十七套", "农业农村"]
}

# ===============================
# 核心工具函数
# ===============================
def normalize_cctv_name(ch_name):
    if not ch_name:
        return ch_name
    ch_name = ch_name.upper()
    for std_name, aliases in CHANNEL_MAPPING.items():
        if ch_name == std_name or ch_name in [a.upper() for a in aliases]:
            return std_name
    # 从纯文本匹配（如 cctv10）
    match = re.search(r"CCTV(\d+\+?)", ch_name)
    if match:
        return f"CCTV{match.group(1)}"
    return ch_name

def extract_channel_from_url(url):
    """强制从URL提取频道名，作为兜底"""
    url_lower = url.lower()
    # 优先匹配CCTV
    match = re.search(r"cctv(\d+\+?)", url_lower)
    if match:
        return normalize_cctv_name(f"CCTV{match.group(1)}")
    # 匹配其他关键词
    for std_name, aliases in CHANNEL_MAPPING.items():
        if any(alias.lower() in url_lower for alias in aliases):
            return std_name
    # 最终兜底
    return Path(url).stem or "未知频道"

def get_requests_session():
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

def test_single_url(url, timeout):
    session = get_requests_session()
    try:
        start = time.time()
        # 直播源测试：直接获取并读取前100字节，验证是否为m3u8
        with session.get(url, timeout=timeout, stream=True) as res:
            if res.status_code == 200 and "#EXTM3U" in res.raw.read(100).decode('utf-8', errors='ignore'):
                return (url, round(time.time() - start, 2))
        return (url, float('inf'))
    except:
        return (url, float('inf'))
    finally:
        session.close()

def test_urls_concurrent(urls, timeout, max_workers):
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(test_single_url, url, timeout): url for url in urls}
        return {url: fut.result()[1] for fut, url in futures.items() if fut.result()[1] < float('inf')}

def read_iptv_sources_from_txt():
    txt_path = Path(CONFIG["SOURCE_TXT_FILE"])
    if not txt_path.exists():
        txt_path.write_text("""# 测试用有效源（请替换为你的链接）
http://69.30.245.50/live/cctv1.m3u8
http://69.30.245.50/live/cctv10.m3u8
# 备用测试源（如果上面的无效，取消下面注释）
# https://live.fcdn.stream/cctv1.m3u8""", encoding="utf-8")
        print(f"⚠️  已创建 {txt_path.name}，请检查链接有效性")
        return []
    
    valid = [line.strip() for line in txt_path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#") and line.startswith(("http://", "https://"))]
    print(f"✅ 读取到 {len(valid)} 个源链接")
    return valid

def crawl_and_merge_sources():
    """核心修改：强制从URL生成频道，不再依赖爬取内容"""
    all_channels = {}
    source_urls = read_iptv_sources_from_txt()
    if not source_urls:
        return all_channels

    session = get_requests_session()
    for source_url in source_urls:
        print(f"🔍 正在处理源：{source_url}")
        # 第一步：强制从URL提取频道名（兜底核心）
        ch_name = extract_channel_from_url(source_url)
        std_ch = normalize_cctv_name(ch_name)
        
        # 第二步：尝试爬取验证（仅作日志，不影响频道创建）
        is_valid = False
        try:
            res = session.get(source_url, timeout=CONFIG["TEST_TIMEOUT"], stream=True)
            if res.status_code == 200:
                is_valid = True
                print(f"ℹ️  链接可访问，准备测速")
            else:
                print(f"⚠️  链接返回错误码：{res.status_code}")
        except Exception as e:
            print(f"⚠️  链接访问失败：{str(e)[:30]}...")
        
        # 第三步：无论是否爬取成功，先将链接加入频道（测速阶段会过滤）
        if std_ch not in all_channels:
            all_channels[std_ch] = set()
        all_channels[std_ch].add(source_url)
        
        # 更新统计
        print(f"✅ 处理完成，累计收集 {len(all_channels)} 个频道（去重后）\n")
    
    session.close()
    # 转换为列表
    return {k: list(v) for k, v in all_channels.items()}

def crawl_and_select_top3():
    raw_channels = crawl_and_merge_sources()
    if not raw_channels:
        return {}

    print(f"🚀 开始测速筛选（共 {len(raw_channels)} 个频道）")
    top_channels = {}
    for ch_name, urls in tqdm(raw_channels.items(), desc="测速进度"):
        # 配置测速参数
        if ch_name.startswith("CCTV") and CONFIG["CCTV_SPECIFIC_CONFIG"]["enabled"]:
            timeout = CONFIG["CCTV_SPECIFIC_CONFIG"]["TEST_TIMEOUT"]
            workers = CONFIG["CCTV_SPECIFIC_CONFIG"]["MAX_WORKERS"]
        else:
            timeout = CONFIG["TEST_TIMEOUT"]
            workers = CONFIG["MAX_WORKERS"]
        
        # 测速
        latency = test_urls_concurrent(urls, timeout, workers)
        if latency:
            # 按延迟排序
            sorted_urls = [k for k, v in sorted(latency.items(), key=lambda x: x[1])]
            top_channels[ch_name] = sorted_urls[:CONFIG["TOP_K"]]
            print(f"\n✅ {ch_name}：保留 {len(top_channels[ch_name])} 个有效源")
        else:
            print(f"\n❌ {ch_name}：无有效源，已剔除")

    return top_channels

def generate_iptv_playlist(top_channels):
    if not top_channels:
        print("❌ 无有效频道，生成失败")
        return

    output = Path(CONFIG["OUTPUT_FILE"])
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    content = [
        "#EXTM3U x-tvg-url=\"\"",
        f"# 生成时间：{now} | 免责声明：{CONFIG['IPTV_DISCLAIMER']}",
        ""
    ]

    # 按分类写入
    for category, ch_list in CHANNEL_CATEGORIES.items():
        content.append(f"#EXTGRP:{category}")
        for ch in ch_list:
            if ch in top_channels:
                for idx, url in enumerate(top_channels[ch]):
                    content.append(f"#EXTINF:-1 group-title=\"{category}\",{ch} (第{idx+1}优)")
                    content.append(url)
        content.append("")
    
    # 其他频道
    other = [ch for ch in top_channels if ch not in sum(CHANNEL_CATEGORIES.values(), [])]
    if other:
        content.append(f"#EXTGRP:其他频道")
        for ch in other:
            for idx, url in enumerate(top_channels[ch]):
                content.append(f"#EXTINF:-1 group-title=\"其他频道\",{ch} (第{idx+1}优)")
                content.append(url)

    output.write_text("\n".join(content), encoding="utf-8")
    print(f"\n🎉 成功生成播放列表：{output.absolute()}")
    print(f"📊 最终有效频道数：{len(top_channels)}")

# ===============================
# 主执行
# ===============================
if __name__ == "__main__":
    print("=" * 60)
    print("📺 IPTV 直播源筛选工具（强制兜底版）")
    print("=" * 60)
    
    top3 = crawl_and_select_top3()
    generate_iptv_playlist(top3)
    print("\n✨ 任务结束")
