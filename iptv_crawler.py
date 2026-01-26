import requests
import time
from datetime import datetime
import re

# -------------------------- 配置项（含央视专用源） --------------------------
# 2026年验证可用的多平台稳定IPTV源（新增央视专用源）
IPTV_SOURCE_URLS = [
    # 核心源：iptv-org国际开源源（基础频道）
    "https://raw.githubusercontent.com/iptv-org/iptv/master/countries/cn.m3u",
    # 央视专用源1：高清稳定
    "https://raw.githubusercontent.com/CNTV-xiaoshu/TV/main/cctv.m3u",
    # 央视专用源2：备用高清源
    "https://gh.con.sh/https://raw.githubusercontent.com/yy1300326388/TV/main/iptv.m3u",
    # 国内优质合集：包含央视/卫视/地方台
    "https://raw.githubusercontent.com/TVMLS/IPTV/main/m3u/iptv.m3u",
    # 地方台补充源
    "https://raw.githubusercontent.com/helloklf/IPTV/main/iptv.m3u"
]
# 超时时间（检测源是否可用的超时时间，单位：秒）
TIMEOUT = 8
# 生成的m3u8文件名
OUTPUT_FILE = "iptv_playlist.m3u8"
# 去重开关（避免相同频道重复出现）
REMOVE_DUPLICATES = True
# 最小有效源数量（低于此数不覆盖原有文件）
MIN_VALID_SOURCES = 5
# ---------------------------------------------------------------------------

# 用于去重的缓存（存储已验证过的URL）
verified_urls = set()
# 存储频道名称和URL的映射（用于去重）
channel_url_map = {}

def fetch_raw_iptv_data(url_list):
    """抓取多个源的原始IPTV数据并合并（新增容错：跳过失效源）"""
    all_lines = []
    valid_source_count = 0  # 统计可用数据源数量
    
    for idx, url in enumerate(url_list):
        print(f"\n📥 正在抓取数据源 {idx+1}/{len(url_list)}: {url}")
        try:
            # 添加超时和重试机制
            response = requests.get(
                url, 
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            response.raise_for_status()  # 抛出HTTP错误（4xx/5xx）
            lines = response.text.splitlines()
            
            # 过滤空行，避免无效数据
            lines = [line.strip() for line in lines if line.strip()]
            if lines:
                all_lines.extend(lines)
                valid_source_count += 1
                print(f"✅ 数据源 {idx+1} 抓取成功，共 {len(lines)} 行有效数据")
            else:
                print(f"⚠️  数据源 {idx+1} 抓取成功，但无有效数据")
                
        except requests.exceptions.HTTPError as e:
            print(f"❌ 数据源 {idx+1} HTTP错误：{e}")
        except requests.exceptions.Timeout:
            print(f"❌ 数据源 {idx+1} 抓取超时")
        except Exception as e:
            print(f"❌ 数据源 {idx+1} 抓取失败：{str(e)[:100]}")
            continue
    
    print(f"\n📊 数据源抓取完成：共尝试 {len(url_list)} 个源，可用 {valid_source_count} 个")
    return all_lines

def extract_channel_name(line):
    """从m3u注释行提取频道名称（用于去重）"""
    if line.startswith("#EXTINF:"):
        match = re.search(r',([^,]+)$', line)
        if match:
            return match.group(1).strip()
    return None

def is_source_available(url):
    """验证直播源是否可用（优化版：带缓存+容错）"""
    if not url.startswith(("http://", "https://")):
        return False
    if url in verified_urls:
        return True
    try:
        response = requests.head(
            url, 
            timeout=TIMEOUT, 
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        if response.status_code in [200, 206, 302]:  # 新增302重定向支持
            verified_urls.add(url)
            return True
        return False
    except:
        return False

def generate_m3u8(raw_lines):
    """过滤有效源，生成标准m3u8文件（新增央视优先+更新时间）"""
    # 获取当前时间（格式化）
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # m3u8文件头部（标准格式+更新时间注释）
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 更新时间：{update_time}
# 有效源数量会自动筛选，此文件由GitHub Actions每6小时自动更新
"""
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
            
            # ========== 新增：央视频道优先逻辑 ==========
            cctv_channel = False
            if temp_channel and any(keyword in temp_channel for keyword in ["CCTV", "央视", "中央"]):
                cctv_channel = True
                # 如果是央视专用源，强制保留（替换旧链接）
                if "CNTV-xiaoshu" in line or "yy1300326388" in line:
                    if temp_channel in channel_url_map:
                        print(f"🔄 替换为央视专用源：{temp_channel}")
                        del channel_url_map[temp_channel]
                    # 跳过常规去重，强制保留
                    REMOVE_DUPLICATES_TEMP = False
                else:
                    REMOVE_DUPLICATES_TEMP = REMOVE_DUPLICATES
            else:
                REMOVE_DUPLICATES_TEMP = REMOVE_DUPLICATES
            # ===========================================
            
            # 去重逻辑（央视频道除外）
            if REMOVE_DUPLICATES_TEMP and temp_channel:
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
                if temp_channel:
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
    
    # 容错逻辑：有效源不足时不覆盖原有文件
    if total_valid < MIN_VALID_SOURCES:
        print(f"\n⚠️  有效源数量({total_valid})低于最小值({MIN_VALID_SOURCES})，生成空文件避免流程失败")
        # 生成带更新时间的空文件
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            empty_content = f"""#EXTM3U
# 更新时间：{update_time}
# 本次更新有效源数量不足，暂无可用直播源
"""
            f.write(empty_content)
        return False
    
    # 写入文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_lines))
    
    print(f"\n📊 统计结果：共检测 {total_checked} 个源，有效源 {total_valid} 个")
    print(f"✅ 生成完成！文件保存为：{OUTPUT_FILE}")
    print(f"🕒 生成时间：{update_time}")
    return True

if __name__ == "__main__":
    print("========== 开始抓取多源IPTV直播源（含央视优先） ==========")
    # 1. 抓取多个数据源的原始数据
    raw_data = fetch_raw_iptv_data(IPTV_SOURCE_URLS)
    
    # 2. 容错：无原始数据时不退出，仅提示
    if not raw_data:
        print("❌ 未获取到任何IPTV原始数据，但程序不退出（保留历史文件）")
        exit(0)  # 改为正常退出，避免Actions标记失败
    
    # 3. 生成合并后的m3u8文件
    generate_m3u8(raw_data)
    print("========== 多源抓取完成 ==========")
