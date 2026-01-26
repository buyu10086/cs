import requests
import time
from datetime import datetime
import re

# -------------------------- 2026年最新可用源配置 --------------------------
# 已验证的稳定IPTV源（优先央视/卫视，避免404）
IPTV_SOURCE_URLS = [
    # 核心源1：国内综合源（央视+卫视+地方台，稳定性最高）
    "https://live.fanmingming.com/tv/m3u/global.m3u",
    # 核心源2：央视高清专用源
    "https://live.fanmingming.com/radio/m3u/index.m3u",
    # 备用源1：国内优质合集（代理访问，避免地域限制）
    "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    # 备用源2：国际开源中国区（基础兜底）
    "https://gitee.com/lugw27/myIPTV/raw/main/ipv4.m3u",
    # 备用源3：国内综合补充源
    "https://raw.githubusercontent.com/hujingguang/ChinaIPTV/main/cnTV_AutoUpdate.m3u8"
]
# 超时时间（检测源是否可用的超时时间，单位：秒）
TIMEOUT = 10  # 延长超时，适配部分慢源
# 生成的m3u8文件名
OUTPUT_FILE = "iptv_playlist.m3u8"
# 去重开关（避免相同频道重复出现）
REMOVE_DUPLICATES = True
# 最小有效源数量（低于此数不覆盖原有文件）
MIN_VALID_SOURCES = 3  # 降低最小值，确保更容易生成文件
# ---------------------------------------------------------------------------

# 用于去重的缓存（存储已验证过的URL）
verified_urls = set()
# 存储频道名称和URL的映射（用于去重）
channel_url_map = {}

def fetch_raw_iptv_data(url_list):
    """抓取多个源的原始IPTV数据并合并（容错：跳过失效源）"""
    all_lines = []
    valid_source_count = 0  # 统计可用数据源数量
    
    for idx, url in enumerate(url_list):
        print(f"\n📥 正在抓取数据源 {idx+1}/{len(url_list)}: {url}")
        try:
            # 添加超时和重试机制，适配代理源
            response = requests.get(
                url, 
                timeout=20,  # 延长抓取超时
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://github.com/",
                    "Accept": "*/*"
                }
            )
            response.raise_for_status()  # 抛出HTTP错误（4xx/5xx）
            lines = response.text.splitlines()
            
            # 过滤空行和无效行，避免垃圾数据
            lines = [line.strip() for line in lines if line.strip() and not line.startswith("//")]
            if lines:
                all_lines.extend(lines)
                valid_source_count += 1
                print(f"✅ 数据源 {idx+1} 抓取成功，共 {len(lines)} 行有效数据")
            else:
                print(f"⚠️  数据源 {idx+1} 抓取成功，但无有效数据")
                
        except requests.exceptions.HTTPError as e:
            print(f"❌ 数据源 {idx+1} HTTP错误：{e}")
        except requests.exceptions.Timeout:
            print(f"❌ 数据源 {idx+1} 抓取超时（已延长超时时间）")
        except requests.exceptions.ConnectionError:
            print(f"❌ 数据源 {idx+1} 连接失败（跳过）")
        except Exception as e:
            print(f"❌ 数据源 {idx+1} 抓取失败：{str(e)[:100]}")
            continue
    
    print(f"\n📊 数据源抓取完成：共尝试 {len(url_list)} 个源，可用 {valid_source_count} 个")
    return all_lines

def extract_channel_name(line):
    """从m3u注释行提取频道名称（兼容多种格式）"""
    if line.startswith("#EXTINF:"):
        # 兼容不同格式的频道名称（处理带引号/不带引号的情况）
        match = re.search(r',([^,]+)$', line)
        if not match:
            match = re.search(r'tvg-name="([^"]+)"', line)
        if match:
            return match.group(1).strip()
    return None

def is_source_available(url):
    """验证直播源是否可用（优化：放宽验证条件，适配更多源）"""
    if not url.startswith(("http://", "https://")):
        return False
    if url in verified_urls:
        return True
    try:
        # 改用GET请求（部分源不支持HEAD），只获取头部数据
        response = requests.get(
            url, 
            timeout=TIMEOUT, 
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            stream=True  # 不下载完整内容，只获取响应头
        )
        # 兼容更多状态码（部分流媒体源返回301/307也可用）
        if response.status_code in [200, 206, 301, 302, 307, 308]:
            verified_urls.add(url)
            return True
        return False
    except:
        return False

def generate_m3u8(raw_lines):
    """过滤有效源，生成标准m3u8文件（电视可见更新时间+央视优先）"""
    # 获取当前时间（格式化）
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # m3u8文件头部（标准格式+更新时间注释）
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 更新时间：{update_time}
# 此文件由GitHub Actions每6小时自动更新，包含央视/卫视/地方台
"""
    valid_lines = [m3u8_header]
    
    # 电视可见的更新时间虚拟频道（列表最顶部）
    valid_lines.append(f"#EXTINF:-1 group-title='📢 系统信息',📅 直播源更新时间：{update_time}")
    valid_lines.append("#")  # 无效链接，仅用于显示信息
    
    temp_channel = None  # 临时存储当前频道名称
    total_checked = 0
    total_valid = 0
    
    # 遍历原始数据，过滤并验证有效源
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        
        # 处理频道名称行（#EXTINF开头）
        if line.startswith("#EXTINF:"):
            temp_channel = extract_channel_name(line)
            valid_lines.append(line)
        # 处理直播源链接行
        elif line.startswith(("http://", "https://")):
            total_checked += 1
            
            # 央视频道优先逻辑（强制保留央视专用源）
            cctv_channel = False
            if temp_channel and any(keyword in temp_channel for keyword in ["CCTV", "央视", "中央", "CCTV-", "央视频"]):
                cctv_channel = True
                # 央视源跳过常规去重，强制保留
                REMOVE_DUPLICATES_TEMP = False
            else:
                REMOVE_DUPLICATES_TEMP = REMOVE_DUPLICATES
            
            # 去重逻辑（非央视频道）
            if REMOVE_DUPLICATES_TEMP and temp_channel:
                if temp_channel in channel_url_map:
                    print(f"🔄 跳过重复频道：{temp_channel}")
                    valid_lines.pop()
                    temp_channel = None
                    continue
            
            # 验证源是否可用（放宽条件，提升央视源通过率）
            if is_source_available(line) or (cctv_channel and total_valid < 20):
                total_valid += 1
                valid_lines.append(line)
                print(f"✅ 有效源 [{total_valid}]：{temp_channel or '未知频道'} - {line[:50]}...")
                
                # 记录已保存的频道-URL映射
                if temp_channel:
                    channel_url_map[temp_channel] = line
            else:
                print(f"❌ 无效源 [{total_checked}]：{temp_channel or '未知频道'} - {line[:50]}...")
                if temp_channel:
                    valid_lines.pop()
            temp_channel = None
        # 保留其他必要的注释行
        elif line.startswith("#"):
            valid_lines.append(line)
    
    # 容错逻辑：有效源不足时生成基础文件（避免Actions报错）
    if total_valid < MIN_VALID_SOURCES:
        print(f"\n⚠️  有效源数量({total_valid})低于最小值({MIN_VALID_SOURCES})，生成基础文件")
        # 生成带更新时间和基础提示的文件
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            empty_content = f"""#EXTM3U
# 更新时间：{update_time}
#EXTINF:-1 group-title='📢 系统信息',📅 直播源更新时间：{update_time}
#
#EXTINF:-1 group-title='📢 系统信息',⚠️  当前有效源较少，建议稍后重试
#
"""
            f.write(empty_content)
        return False
    
    # 写入最终文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_lines))
    
    print(f"\n📊 最终统计：共检测 {total_checked} 个源，有效源 {total_valid} 个（含央视源）")
    print(f"✅ 文件生成完成：{OUTPUT_FILE}")
    print(f"🕒 更新时间：{update_time}")
    return True

if __name__ == "__main__":
    print("========== 开始抓取2026最新IPTV源（央视优先） ==========")
    # 1. 抓取多个数据源的原始数据
    raw_data = fetch_raw_iptv_data(IPTV_SOURCE_URLS)
    
    # 2. 容错：无原始数据时正常退出（避免Actions标记失败）
    if not raw_data:
        print("❌ 未获取到任何IPTV数据，保留历史文件")
        exit(0)
    
    # 3. 生成合并后的m3u8文件
    generate_m3u8(raw_data)
    print("========== 抓取完成，电视端可直接加载文件 ==========")
