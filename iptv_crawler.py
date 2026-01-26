import requests
import time
from datetime import datetime
import re

# -------------------------- 配置项（小白可修改这里） --------------------------
# 多平台稳定IPTV源数据源（已筛选可靠公开源，涵盖不同平台/地区）
IPTV_SOURCE_URLS = [
    # 全球IPTV组织-中国区（基础核心源）
    "https://raw.githubusercontent.com/iptv-org/iptv/master/countries/cn.m3u",
    # 央视/卫视高清源
    "https://raw.githubusercontent.com/imDazui/Tvlist-awesome-m3u-m3u8/master/IPTV/8.m3u",
    # 地方台补充源
    "https://raw.githubusercontent.com/imDazui/Tvlist-awesome-m3u-m3u8/master/IPTV/9.m3u",
    # 特色频道（影视/体育）
    "https://raw.githubusercontent.com/imDazui/Tvlist-awesome-m3u-m3u8/master/IPTV/10.m3u",
    # 备用源（防止主源失效）
    "https://raw.githubusercontent.com/666wcy/TV/main/tv.m3u"
]
# 超时时间（检测源是否可用的超时时间，单位：秒）
TIMEOUT = 5
# 生成的m3u8文件名
OUTPUT_FILE = "iptv_playlist.m3u8"
# 去重开关（避免相同频道重复出现）
REMOVE_DUPLICATES = True
# ---------------------------------------------------------------------------

# 用于去重的缓存（存储已验证过的URL）
verified_urls = set()
# 存储频道名称和URL的映射（用于去重）
channel_url_map = {}

def fetch_raw_iptv_data(url_list):
    """抓取多个源的原始IPTV数据并合并"""
    all_lines = []
    for idx, url in enumerate(url_list):
        print(f"\n📥 正在抓取数据源 {idx+1}/{len(url_list)}: {url}")
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            lines = response.text.splitlines()
            all_lines.extend(lines)
            print(f"✅ 数据源 {idx+1} 抓取成功，共 {len(lines)} 行")
        except Exception as e:
            print(f"❌ 数据源 {idx+1} 抓取失败：{e}")
            continue
    return all_lines

def extract_channel_name(line):
    """从m3u注释行提取频道名称（用于去重）"""
    if line.startswith("#EXTINF:"):
        # 匹配频道名称（处理不同格式）
        match = re.search(r',([^,]+)$', line)
        if match:
            return match.group(1).strip()
    return None

def is_source_available(url):
    """验证直播源是否可用（优化版：带缓存避免重复验证）"""
    # 跳过非HTTP链接
    if not url.startswith(("http://", "https://")):
        return False
    # 缓存命中，直接返回结果
    if url in verified_urls:
        return True
    try:
        # 使用HEAD请求，减少数据传输
        response = requests.head(
            url, 
            timeout=TIMEOUT, 
            allow_redirects=True,
            # 添加请求头，模拟浏览器访问
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        if response.status_code in [200, 206]:
            verified_urls.add(url)
            return True
        return False
    except:
        return False

def generate_m3u8(raw_lines):
    """过滤有效源，生成标准m3u8文件（支持多源合并+去重）"""
    # m3u8文件头部（标准格式）
    m3u8_header = "#EXTM3U x-tvg-url=\"https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml\"\n"
    valid_lines = [m3u8_header]
    
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
            # 去重逻辑
            if REMOVE_DUPLICATES and temp_channel:
                # 如果该频道已有有效URL，跳过
                if temp_channel in channel_url_map:
                    print(f"🔄 跳过重复频道：{temp_channel}")
                    # 移除上一行添加的频道名称
                    valid_lines.pop()
                    temp_channel = None
                    continue
            
            # 验证源是否可用
            if is_source_available(line):
                total_valid += 1
                valid_lines.append(line)
                print(f"✅ 有效源 [{total_valid}]：{temp_channel or '未知频道'} - {line[:50]}...")
                
                # 记录已保存的频道-URL映射
                if REMOVE_DUPLICATES and temp_channel:
                    channel_url_map[temp_channel] = line
            else:
                print(f"❌ 无效源 [{total_checked}]：{temp_channel or '未知频道'} - {line[:50]}...")
                # 移除上一行添加的频道名称
                if temp_channel:
                    valid_lines.pop()
            temp_channel = None
        # 保留其他必要的注释行
        elif line.startswith("#"):
            valid_lines.append(line)
    
    # 写入文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_lines))
    
    print(f"\n📊 统计结果：共检测 {total_checked} 个源，有效源 {total_valid} 个")
    print(f"✅ 生成完成！文件保存为：{OUTPUT_FILE}")
    print(f"🕒 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    print("========== 开始抓取多源IPTV直播源 ==========")
    # 1. 抓取多个数据源的原始数据
    raw_data = fetch_raw_iptv_data(IPTV_SOURCE_URLS)
    if not raw_data:
        print("❌ 未获取到任何IPTV数据，程序退出")
        exit(1)
    
    # 2. 生成合并后的m3u8文件
    generate_m3u8(raw_data)
    print("========== 多源抓取完成 ==========")
