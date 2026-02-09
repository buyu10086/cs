#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPTV源链接爬虫工具（性能优化版）
核心优化：协程异步测速 + 按域名限流 + 测速缓存 + 动态并发 + HEAD请求优先
功能：清理失效链接+高性能并发测速+筛选最快6条+失效链接归档（最多10条）
"""
import re
import time
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed, ProcessPoolExecutor

# ===============================
# 全局配置（可根据实际需求调整）
# ===============================
CONFIG = {
    # 文件路径配置
    "SOURCE_TXT_FILE": "iptv_sources.txt",    # 原始IPTV源链接文件
    "OLD_SOURCES_FILE": "old_sources.txt",    # 失效链接归档文件
    "OUTPUT_FILE": "iptv_playlist.m3u8",      # 最终生成的播放列表文件
    # 核心规则配置
    "MAX_OLD_RECORDS": 10,                    # 失效链接归档最多保留10条
    "MAX_FAST_SOURCES": 6,                    # 选取速度最快的6条有效链接
    # 网络请求配置（性能优化核心）
    "HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "keep-alive",           # 复用连接，减少握手开销
        "Accept": "*/*"                       # 简化请求头，减少服务器处理开销
    },
    "TEST_TIMEOUT_TOTAL": 3,                  # 单链接总超时时间（秒）
    "TEST_TIMEOUT_CONNECT": 1,                # 连接超时（秒）：建立TCP连接的最大时间
    "TEST_TIMEOUT_READ": 2,                   # 读取超时（秒）：读取响应头的最大时间
    "BASE_MAX_CONCURRENT": 60,                # 基础最大并发数（协程）
    "DOMAIN_MAX_CONCURRENT": 5,               # 单个域名最大并发数（避免封禁）
    "CACHE_EXPIRE_SECONDS": 600,              # 测速缓存有效期（10分钟）
    "RETRY_TIMES": 1,                         # 同步请求重试次数
    # 爬虫辅助配置
    "TOP_K": 3,                               # 每个频道保留最优源数量
    "IPTV_DISCLAIMER": "本文件仅用于技术研究，请勿用于商业用途，相关版权归原作者所有"
}

# 全局测速缓存（key=url, value=(测速时间戳, 响应时间ms)）
SPEED_CACHE = {}

# ===============================
# 频道分类映射（按需扩展）
# ===============================
CHANNEL_CATEGORIES = {
    "央视频道": ["CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV5", "CCTV5+", "CCTV6", "CCTV7", "CCTV8", "CCTV9", "CCTV10", "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15", "CCTV16", "CCTV17"],
    "卫视频道": ["湖南卫视", "浙江卫视", "江苏卫视", "东方卫视", "北京卫视", "广东卫视", "河南卫视", "湖北卫视", "四川卫视", "重庆卫视"],
    "地方频道": ["湖北公共新闻", "武汉新闻综合", "郑州1新闻综合", "洛阳-1新闻综合"]
}

# ===============================
# 同步工具函数（仅用于链接有效性检查）
# ===============================
def create_stable_session():
    """创建带重试机制的稳定requests会话（同步，仅用于链接有效性检查）"""
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

def check_url_validity(url):
    """检查单个URL是否有效（同步HEAD请求，轻量高效）"""
    session = create_stable_session()
    try:
        response = session.head(
            url,
            timeout=CONFIG["TEST_TIMEOUT_TOTAL"],
            allow_redirects=True,
            verify=False
        )
        return url, 200 <= response.status_code < 300
    except Exception:
        return url, False

def extract_domain(url):
    """提取URL的域名（用于按域名限流）"""
    try:
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        domain = url.split("//")[1].split("/")[0]
        # 去除端口号（如xxx.com:8080 → xxx.com）
        if ":" in domain:
            domain = domain.split(":")[0]
        return domain.lower()
    except Exception:
        return "unknown_domain"

# ===============================
# 异步核心函数（性能优化重点）
# ===============================
async def create_async_session():
    """创建高性能异步会话（带连接池、精细化超时、禁用Cookie）"""
    # 精细化超时配置
    timeout = aiohttp.ClientTimeout(
        connect=CONFIG["TEST_TIMEOUT_CONNECT"],
        sock_read=CONFIG["TEST_TIMEOUT_READ"],
        total=CONFIG["TEST_TIMEOUT_TOTAL"]
    )
    # 连接池配置：轻量、高效、避免端口耗尽
    connector = aiohttp.TCPConnector(
        limit=CONFIG["BASE_MAX_CONCURRENT"] * 2,  # 连接池大小（略大于并发数）
        limit_per_host=CONFIG["DOMAIN_MAX_CONCURRENT"],  # 单个域名默认连接数
        ttl_dns_cache=300,  # DNS缓存5分钟，减少重复解析
        use_tcp_cork=True,  # 启用TCP Cork，减少小包传输
        fast_open=True      # 启用TCP快速打开（需系统支持）
    )
    # 禁用Cookie（IPTV源无需登录，减少开销）
    session = aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers=CONFIG["HEADERS"],
        cookie_jar=aiohttp.DummyCookieJar(),
        trust_env=True
    )
    return session

async def test_single_url_speed_async(url, semaphore):
    """
    异步测速单个URL（核心优化）
    策略：1. 先查缓存 2. HEAD请求优先 3. 失败则降级GET读取1字节 4. 结果缓存
    """
    # 1. 检查缓存（未过期则直接返回）
    now = time.time()
    if url in SPEED_CACHE:
        cache_time, cache_rt = SPEED_CACHE[url]
        if now - cache_time < CONFIG["CACHE_EXPIRE_SECONDS"]:
            print(f"📌 缓存复用 | {url} | 响应时间：{cache_rt}ms")
            return url, cache_rt

    # 2. 信号量限流（按域名/全局）
    async with semaphore:
        start_time = time.time()
        response_time = None
        try:
            async with await create_async_session() as session:
                # 3. 优先使用HEAD请求（最轻量）
                try:
                    async with session.head(
                        url,
                        allow_redirects=True,
                        ssl=False  # 忽略SSL证书错误
                    ) as resp:
                        if 200 <= resp.status < 300:
                            response_time = round((time.time() - start_time) * 1000, 2)
                except Exception:
                    # 4. HEAD失败则降级为GET（仅读取1字节，触发连接即可）
                    async with session.get(
                        url,
                        allow_redirects=True,
                        ssl=False,
                        stream=True
                    ) as resp:
                        await resp.content.read(1)  # 仅读取1字节，避免下载大文件
                        if 200 <= resp.status < 300:
                            response_time = round((time.time() - start_time) * 1000, 2)
            
            # 5. 缓存有效测速结果
            if response_time and response_time > 0:
                SPEED_CACHE[url] = (now, response_time)
                print(f"✅ 测速成功 | {url} | 响应时间：{response_time}ms")
            else:
                print(f"❌ 测速失败 | {url} | 原因：非2xx状态码")
        
        except Exception as e:
            print(f"❌ 测速异常 | {url} | 错误：{str(e)[:50]}")
        
        return url, response_time

async def dynamic_concurrent_speed_test(url_list):
    """
    动态并发测速（核心优化）
    策略：1. 预热测试 2. 按成功率调整并发 3. 按域名限流 4. 异步批量处理
    """
    if not url_list:
        return []
    
    speed_results = []
    print(f"\n⚡ 开始高性能并发测速 | 待测速链接数：{len(url_list)} | 基础并发数：{CONFIG['BASE_MAX_CONCURRENT']}")

    # ========== 步骤1：预热测试，动态调整并发数 ==========
    warmup_size = max(10, len(url_list) // 10)  # 取10%或最少10条做预热
    warmup_urls = url_list[:warmup_size]
    warmup_sem = asyncio.Semaphore(CONFIG["BASE_MAX_CONCURRENT"] // 2)  # 预热并发减半
    
    # 执行预热测速
    warmup_tasks = [test_single_url_speed_async(url, warmup_sem) for url in warmup_urls]
    warmup_results = await asyncio.gather(*warmup_tasks)
    
    # 计算预热成功率，动态调整最终并发数
    warmup_success = len([r for r in warmup_results if r[1] is not None and r[1] > 0])
    success_rate = warmup_success / len(warmup_urls) if warmup_urls else 1.0
    
    if success_rate < 0.8:
        final_max_concurrent = CONFIG["BASE_MAX_CONCURRENT"] // 2
        print(f"⚠️  预热成功率{success_rate:.1%} < 80%，降低并发数至：{final_max_concurrent}")
    else:
        final_max_concurrent = CONFIG["BASE_MAX_CONCURRENT"]
        print(f"✅ 预热成功率{success_rate:.1%} ≥ 80%，使用基础并发数：{final_max_concurrent}")

    # ========== 步骤2：按域名分组，精细化限流 ==========
    domain_groups = defaultdict(list)
    for url in url_list:
        domain = extract_domain(url)
        domain_groups[domain].append(url)
    
    # 为每个域名创建独立信号量（避免对单一域名打满）
    domain_semaphores = {
        domain: asyncio.Semaphore(min(CONFIG["DOMAIN_MAX_CONCURRENT"], final_max_concurrent // 2))
        for domain in domain_groups.keys()
    }

    # ========== 步骤3：批量执行异步测速 ==========
    tasks = []
    for domain, urls in domain_groups.items():
        sem = domain_semaphores[domain]
        for url in urls:
            tasks.append(test_single_url_speed_async(url, sem))
    
    # 异步收集所有结果（高效批量处理）
    all_results = await asyncio.gather(*tasks)

    # ========== 步骤4：过滤有效结果并异步排序 ==========
    valid_results = [(url, rt) for url, rt in all_results if rt is not None and rt > 0]
    
    # 异步排序（避免阻塞主线程）
    def sort_results(results):
        return sorted(results, key=lambda x: x[1])
    
    # 使用进程池执行排序（大数据量更高效）
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=1) as executor:
        sorted_results = await loop.run_in_executor(executor, sort_results, valid_results)

    print(f"\n📊 测速完成 | 成功{len(sorted_results)}条 | 失败{len(url_list)-len(sorted_results)}条")
    return sorted_results

# ===============================
# 业务逻辑函数（保留原有核心功能）
# ===============================
def archive_invalid_urls(invalid_urls):
    """归档失效链接到old_sources.txt，仅保留最新10条"""
    if not invalid_urls:
        return
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_records = [f"[{current_time}] {url}" for url in invalid_urls]
    
    old_file = Path(CONFIG["OLD_SOURCES_FILE"])
    old_records = []
    if old_file.exists():
        with open(old_file, "r", encoding="utf-8") as f:
            old_records = [line.strip() for line in f.readlines() if line.strip()]
    
    # 合并+解析+去重+排序
    all_records = new_records + old_records
    parsed_records = []
    pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.*)")
    
    for record in all_records:
        match = pattern.match(record)
        if match:
            try:
                record_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                url = match.group(2)
                parsed_records.append((record_time, url))
            except Exception:
                continue
    
    # 去重：同一链接保留最新记录
    unique_dict = {}
    for rt, url in parsed_records:
        if url not in unique_dict or rt > unique_dict[url][0]:
            unique_dict[url] = (rt, url)
    
    # 按时间降序排序，保留前10条
    sorted_records = sorted(unique_dict.values(), key=lambda x: x[0], reverse=True)
    final_records = sorted_records[:CONFIG["MAX_OLD_RECORDS"]]
    
    # 写入文件
    with open(old_file, "w", encoding="utf-8") as f:
        f.write("\n".join([f"[{rt.strftime('%Y-%m-%d %H:%M:%S')}] {url}" for rt, url in final_records]) + "\n")
    
    print(f"\n📝 失效链接归档完成 | 新增{len(invalid_urls)}条 | 归档文件保留{len(final_records)}/{CONFIG['MAX_OLD_RECORDS']}条")

def clean_invalid_sources():
    """清理失效链接（同步并发），返回有效链接列表"""
    source_file = Path(CONFIG["SOURCE_TXT_FILE"])
    
    if not source_file.exists():
        print(f"⚠️  源文件 {source_file.name} 不存在，程序退出")
        return []
    
    # 读取并预处理链接
    with open(source_file, "r", encoding="utf-8") as f:
        raw_urls = [line.strip() for line in f.readlines()]
    original_urls = list(set([url for url in raw_urls if url]))  # 去重
    if not original_urls:
        print(f"⚠️  源文件 {source_file.name} 中无有效链接，程序退出")
        return []
    
    print(f"🔍 开始检查 {len(original_urls)} 个IPTV源链接有效性...")
    
    # 同步并发检查有效性
    valid_urls = []
    invalid_urls = []
    with ThreadPoolExecutor(max_workers=CONFIG["BASE_MAX_CONCURRENT"] // 2) as executor:
        future_tasks = {executor.submit(check_url_validity, url): url for url in original_urls}
        for future in as_completed(future_tasks):
            url, is_valid = future.result()
            if is_valid:
                valid_urls.append(url)
            else:
                invalid_urls.append(url)
    
    # 写回有效链接
    with open(source_file, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_urls))
    print(f"\n🧹 链接清理完成 | 原始{len(original_urls)}条 | 有效{len(valid_urls)}条 | 失效{len(invalid_urls)}条")
    
    # 归档失效链接
    archive_invalid_urls(invalid_urls)
    
    return valid_urls

def generate_iptv_playlist(fastest_urls):
    """基于最快的6条链接生成M3U8播放列表"""
    if not fastest_urls:
        print("\n⚠️  无可用链接，无法生成播放列表")
        return
    
    print(f"\n📄 开始生成IPTV播放列表（基于{len(fastest_urls)}条最快链接）...")
    m3u8_content = [
        "#EXTM3U",
        f"# 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# {CONFIG['IPTV_DISCLAIMER']}",
        "#"
    ]
    
    for i, url in enumerate(fastest_urls, 1):
        m3u8_content.append(f"#EXTINF:-1 group-title=\"IPTV源\" tvg-name=\"源{i}\",IPTV源_{i}")
        m3u8_content.append(url)
    
    with open(CONFIG["OUTPUT_FILE"], "w", encoding="utf-8") as f:
        f.write("\n".join(m3u8_content))
    
    print(f"✅ 播放列表生成完成 | 路径：{CONFIG['OUTPUT_FILE']}")

# ===============================
# 主流程（整合同步+异步逻辑）
# ===============================
async def main_async():
    """异步主流程：清理→动态并发测速→筛选→生成播放列表"""
    print("="*60)
    print("🎬 IPTV源链接爬虫工具（性能优化版 v2.0）")
    print(f"🕒 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    try:
        # 步骤1：同步清理失效链接，获取有效链接
        valid_urls = clean_invalid_sources()
        if not valid_urls:
            return
        
        # 步骤2：高性能异步测速+筛选最快6条
        if len(valid_urls) <= CONFIG["MAX_FAST_SOURCES"]:
            print(f"\n✅ 有效链接数({len(valid_urls)})≤{CONFIG['MAX_FAST_SOURCES']}，无需测速，直接使用所有有效链接")
            fastest_urls = valid_urls
        else:
            # 执行动态并发测速
            sorted_speed_results = await dynamic_concurrent_speed_test(valid_urls)
            # 选取前6条最快的链接
            fastest_urls = [item[0] for item in sorted_speed_results[:CONFIG["MAX_FAST_SOURCES"]]]
            # 输出排名
            print(f"\n🏆 最快{CONFIG['MAX_FAST_SOURCES']}条链接排名：")
            for i, (url, rt) in enumerate(sorted_speed_results[:CONFIG["MAX_FAST_SOURCES"]], 1):
                print(f"   {i}. {url} | {rt}ms")
        
        # 步骤3：生成播放列表
        generate_iptv_playlist(fastest_urls)
        
        print("\n🎉 所有任务执行完成！")
    
    except KeyboardInterrupt:
        print("\n⚠️  程序被用户手动中断")
    except Exception as e:
        print(f"\n❌ 程序执行出错：{str(e)}")

def main():
    """程序入口（适配异步逻辑）"""
    # 解决Windows下asyncio的事件循环问题
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main_async())

if __name__ == "__main__":
    import sys
    main()
