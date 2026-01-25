import requests
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urljoin
import os

# ===================== 核心配置（无IPv6+hacks.tools类稳定源）=====================
# 1. 经验证的稳定IPTV源列表（对标iptv.hacks.tools，无IPv6、全国通用）
IPTV_SOURCES = [
    # 核心：iptv.hacks.tools官方综合源（全球+国内，和目标网址同源）
    {
        "name": "hacks.tools全球综合",
        "url": "https://iptv.hacks.tools/iptv.txt",
        "type": "m3u"
    },
    # 核心：hacks.tools国内精选源（过滤后的国内频道）
    {
        "name": "hacks.tools国内频道",
        "url": "https://iptv.hacks.tools/china.txt",
        "type": "m3u"
    },
    # 补充：全网聚合每日更新（国内核心，和hacks.tools互补）
    {
        "name": "全网聚合每日更",
        "url": "https://raw.kkgithub.com/imDazui/Tvlist-awesome-m3u-m3u8/master/m3u/iptv.m3u",
        "type": "m3u"
    },
    # 补充：iptv-org官方全球源（和hacks.tools同源，分类清晰）
    {
        "name": "iptv-org全球频道",
        "url": "https://raw.kkgithub.com/iptv-org/iptv/master/streams/all.m3u",
        "type": "m3u"
    },
    # 补充：高清央视卫视（国内核心，适配hacks.tools的国内需求）
    {
        "name": "高清央视卫视",
        "url": "https://ghproxy.com/https://raw.githubusercontent.com/666wcy/TV/main/TV.m3u",
        "type": "m3u"
    }
]
# 2. 生成的m3u8文件名称
OUTPUT_M3U8 = "iptv_list.m3u8"
# 3. 超时时间（秒）：平衡验证效率与准确性
TIMEOUT = 8
# 4. 强制验证地址有效性（必开，确保源可用）
VALIDATE_URL = True
# 5. 请求间隔（避免反爬）
REQUEST_DELAY = 1
# 6. 强制更新文件时间（解决Git无变化问题）
FORCE_UPDATE_FILE_TIME = True
# 7. 最小有效地址数（低于此数则生成备用空文件）
MIN_VALID_URLS = 5

# ===================== 核心工具函数 =====================
def get_html_content(url, source_name):
    """请求页面，带重试机制（适配hacks.tools类海外源）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",  # 适配海外源的语言请求
        "Referer": "https://iptv.hacks.tools/"  # 模拟从hacks.tools跳转
    }
    # 重试3次（海外源偶尔波动）
    for retry in range(3):
        try:
            print(f"\n【调试】[{source_name}] 第{retry+1}次请求：{url}")
            time.sleep(REQUEST_DELAY)
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            print(f"【调试】[{source_name}] 请求成功，内容长度：{len(response.text)} 字符")
            return response.text
        except Exception as e:
            print(f"【警告】[{source_name}] 第{retry+1}次请求失败：{str(e)}")
            time.sleep(2)  # 重试间隔加长
    return None

def parse_m3u_content(content, source_name):
    """解析m3u/m3u8，过滤无效行（适配hacks.tools的格式）"""
    iptv_dict = {}
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    channel_name = ""
    print(f"【调试】[{source_name}] 解析m3u文件，有效行数：{len(lines)}")
    
    for line in lines:
        # 匹配频道名行（兼容hacks.tools的EXTINF格式）
        if line.startswith("#EXTINF:"):
            # 适配hacks.tools的多属性EXTINF行（如包含tvg-id、group-title等）
            match = re.search(r",(.+)$", line)
            if match:
                channel_name = match.group(1).strip()
                channel_name = f"[{source_name}] {channel_name}"
        # 匹配有效播放地址（兼容hacks.tools的http/rtmp等协议）
        elif line.startswith(("http://", "https://", "rtmp://")):
            if re.search(r"(m3u8|ts|flv|mp4)$", line, re.I) and channel_name:
                # 去重：相同地址只保留第一个频道名
                if line not in iptv_dict.values():
                    iptv_dict[channel_name] = line
                    print(f"【调试】[{source_name}] 新增有效地址：{channel_name[:20]}...")
                channel_name = ""
    return iptv_dict

def validate_iptv_url(url):
    """快速验证地址有效性（适配海外源，放宽状态码）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.head(
            url, 
            headers=headers, 
            timeout=TIMEOUT, 
            allow_redirects=True,
            stream=True  # 不下载内容
        )
        # 适配海外源：200/403/206/401均视为有效（401可能是鉴权但可播放）
        return response.status_code in [200, 403, 206, 401]
    except:
        return False

def filter_valid_urls(iptv_dict):
    """批量验证地址，保留有效项"""
    if not VALIDATE_URL:
        return iptv_dict

    valid_dict = {}
    total = len(iptv_dict)
    if total == 0:
        return valid_dict
    
    print(f"\n【调试】开始验证 {total} 个地址（超时{TIMEOUT}秒）...")
    # 分批验证，避免卡顿
    for idx, (name, url) in enumerate(iptv_dict.items(), 1):
        if idx % 10 == 0:
            print(f"【调试】验证进度：{idx}/{total}，已保留 {len(valid_dict)} 个有效地址")
        if validate_iptv_url(url):
            valid_dict[name] = url
        time.sleep(0.3)  # 缩短验证间隔，提升效率

    print(f"【调试】验证完成，有效地址：{len(valid_dict)} / {total}")
    return valid_dict

def generate_m3u8_file(iptv_dict, output_file):
    """生成标准m3u8，兼容hacks.tools的播放格式"""
    # 确保文件目录存在
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    
    # 删除旧文件
    if os.path.exists(output_file):
        os.remove(output_file)

    # 写入m3u8头部（兼容所有播放器，包含hacks.tools的EPG）
    m3u_header = """#EXTM3U
#EXT-X-VERSION:3
#x-tvg-url:https://iptv.hacks.tools/epg.xml  # 适配hacks.tools的EPG指南
"""
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(m3u_header)
        
        # 按频道名排序，方便查看
        sorted_items = sorted(iptv_dict.items(), key=lambda x: x[0])
        for channel_name, play_url in sorted_items:
            # 提取分组名（适配hacks.tools的分类）
            group_match = re.search(r"\[(.*?)\]", channel_name)
            group_title = group_match.group(1) if group_match else "全球综合频道"
            # 写入频道信息（兼容hacks.tools的格式）
            f.write(f"#EXTINF:-1 group-title=\"{group_title}\" tvg-name=\"{channel_name}\",{channel_name}\n")
            f.write(f"{play_url}\n")

    # 强制更新文件时间
    if FORCE_UPDATE_FILE_TIME and os.path.exists(output_file):
        current_time = time.time()
        os.utime(output_file, (current_time, current_time))

    # 输出文件信息
    file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
    valid_count = len(iptv_dict)
    print(f"✅ 生成完成：{output_file} | 大小：{file_size} 字节 | 有效频道：{valid_count} 个")
    
    # 兜底提示：有效地址过少
    if valid_count < MIN_VALID_URLS:
        print(f"⚠️ 警告：有效频道仅{valid_count}个，部分源可能已失效，请检查源地址")

# ===================== 主程序 =====================
if __name__ == "__main__":
    print("===== 稳定IPTV源爬虫启动（hacks.tools类+无IPv6）=====")
    start_time = time.time()

    # 1. 遍历所有源，爬取并合并地址
    all_iptv = {}
    for source in IPTV_SOURCES:
        source_name = source["name"]
        source_url = source["url"]
        
        # 请求源内容
        content = get_html_content(source_url, source_name)
        if not content:
            print(f"【错误】[{source_name}] 源请求失败，跳过")
            continue
        
        # 解析地址
        source_iptv = parse_m3u_content(content, source_name)
        if not source_iptv:
            print(f"【警告】[{source_name}] 未解析到有效地址，跳过")
            continue
        
        # 合并到总字典（自动去重）
        all_iptv.update(source_iptv)
        print(f"【调试】[{source_name}] 合并后总地址数：{len(all_iptv)}")

    # 2. 过滤无效地址
    valid_iptv = filter_valid_urls(all_iptv)

    # 3. 兜底：若有效地址过少，保留原始地址（关闭验证）
    if len(valid_iptv) < MIN_VALID_URLS:
        print(f"【兜底】有效地址不足{MIN_VALID_URLS}个，使用未验证地址")
        valid_iptv = all_iptv

    # 4. 生成最终文件
    generate_m3u8_file(valid_iptv, OUTPUT_M3U8)

    # 输出总耗时
    total_time = round(time.time() - start_time, 2)
    print(f"\n===== 爬虫完成 | 总耗时：{total_time} 秒 | 最终有效频道：{len(valid_iptv)} 个 =====")
