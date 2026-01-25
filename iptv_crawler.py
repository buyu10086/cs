import requests
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urljoin
import os  # 用于文件操作和修改时间更新

# ===================== 配置参数（核心：新增多IPTV源列表）=====================
# 1. 多IPTV源列表（公开、合法的测试源，可自行增删）
IPTV_SOURCES = [
    # 源1：iptv-org 国内频道（核心源）
    {
        "name": "国内综合频道",
        "url": "https://github.com/iptv-org/iptv/raw/master/streams/cn.m3u",
        "type": "m3u"  # 类型：m3u/m3u8 或 html
    },
    # 源2：iptv-org 央视频道
    {
        "name": "央视频道",
        "url": "https://github.com/iptv-org/iptv/raw/master/streams/cn/cctv.m3u",
        "type": "m3u"
    },
    # 源3：iptv-org 卫视频道
    {
        "name": "各省卫视频道",
        "url": "https://github.com/iptv-org/iptv/raw/master/streams/cn/hd.m3u",
        "type": "m3u"
    },
    # 源4：公开测试源（港澳台/海外）
    {
        "name": "港澳台/海外频道",
        "url": "https://github.com/iptv-org/iptv/raw/master/streams/hk.m3u",
        "type": "m3u"
    },
    # 源5：公开HTML格式的IPTV列表（示例）
    {
        "name": "公开HTML测试源",
        "url": "https://iptv-org.github.io/iptv/countries/cn.html",
        "type": "html"
    }
]
# 2. 生成的m3u8文件名称
OUTPUT_M3U8 = "iptv_list.m3u8"
# 3. 超时时间（秒）：请求页面/验证地址的超时时间
TIMEOUT = 10
# 4. 验证地址有效性（True=验证，False=不验证，加快爬取速度）
VALIDATE_URL = True
# 5. 请求间隔（秒）：避免频繁请求被反爬
REQUEST_DELAY = 1
# 6. 强制更新文件修改时间（即使内容不变，也让Git检测到变化）
FORCE_UPDATE_FILE_TIME = True

# ===================== 核心函数 =====================
def get_html_content(url, source_name):
    """请求目标页面，返回页面文本内容"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://github.com/"
    }
    try:
        print(f"\n【调试】[{source_name}] 正在请求页面：{url}")
        time.sleep(REQUEST_DELAY)  # 请求间隔
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        print(f"【调试】[{source_name}] 页面请求成功，响应长度：{len(response.text)} 字符")
        return response.text
    except Exception as e:
        print(f"【错误】[{source_name}] 请求页面失败：{str(e)}")
        return None

def parse_m3u_content(content, source_name):
    """解析m3u/m3u8格式的内容，返回{频道名: 播放地址}"""
    iptv_dict = {}
    lines = content.splitlines()
    channel_name = ""
    print(f"【调试】[{source_name}] 解析m3u文件，总行数：{len(lines)}")
    
    for idx, line in enumerate(lines):
        line = line.strip()
        # 匹配频道名行
        if line.startswith("#EXTINF:"):
            match = re.search(r",(.+)$", line)
            if match:
                channel_name = match.group(1).strip()
                # 给频道名添加源标识（方便区分来源）
                channel_name = f"[{source_name}] {channel_name}"
                print(f"【调试】[{source_name}] 解析到频道：{channel_name}（行号：{idx+1}）")
            else:
                channel_name = ""
        # 匹配播放地址行
        elif line.startswith(("http://", "https://")) and re.search(r"(m3u8|ts)$", line, re.I):
            if channel_name and line not in iptv_dict.values():
                iptv_dict[channel_name] = line
                print(f"【调试】[{source_name}] 新增地址：{channel_name} → {line[:50]}...")  # 截断长地址
            channel_name = ""
    return iptv_dict

def parse_html_content(content, base_url, source_name):
    """解析HTML格式的内容，返回{频道名: 播放地址}"""
    iptv_dict = {}
    soup = BeautifulSoup(content, "lxml")
    a_tags = soup.find_all("a", href=re.compile(r"(m3u8|ts)$", re.I))
    print(f"【调试】[{source_name}] 解析HTML页面，找到m3u8/ts链接数：{len(a_tags)}")
    
    for tag in a_tags:
        name = tag.get_text(strip=True) or f"[{source_name}] 未命名频道{len(iptv_dict)+1}"
        url = tag["href"]
        full_url = urljoin(base_url, url)
        
        if name not in iptv_dict and full_url not in iptv_dict.values():
            iptv_dict[name] = full_url
            print(f"【调试】[{source_name}] 新增地址：{name} → {full_url[:50]}...")
    return iptv_dict

def parse_iptv_urls(content, source_info):
    """统一解析不同类型的源内容"""
    source_name = source_info["name"]
    source_type = source_info["type"]
    base_url = source_info["url"]
    
    if source_type == "m3u":
        return parse_m3u_content(content, source_name)
    elif source_type == "html":
        return parse_html_content(content, base_url, source_name)
    else:
        print(f"【错误】[{source_name}] 不支持的源类型：{source_type}")
        return {}

def validate_iptv_url(url, channel_name):
    """验证IPTV地址是否有效"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.head(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        is_valid = response.status_code in [200, 403]
        print(f"【调试】验证地址：{channel_name[:20]}... → {'有效' if is_valid else '无效'}（状态码：{response.status_code}）")
        return is_valid
    except Exception as e:
        print(f"【调试】验证地址失败：{channel_name[:20]}... → {str(e)}")
        return False

def filter_valid_urls(iptv_dict):
    """过滤无效的IPTV地址"""
    if not VALIDATE_URL:
        print(f"【调试】关闭地址验证，保留 {len(iptv_dict)} 个地址")
        return iptv_dict

    valid_dict = {}
    total = len(iptv_dict)
    print(f"\n【调试】开始验证 {total} 个地址的有效性...")
    
    for idx, (name, url) in enumerate(iptv_dict.items(), 1):
        print(f"【调试】验证进度：{idx}/{total}")
        if validate_iptv_url(url, name):
            valid_dict[name] = url
        time.sleep(0.5)

    print(f"【调试】验证完成，有效地址：{len(valid_dict)} / {total}")
    return valid_dict

def generate_m3u8_file(iptv_dict, output_file):
    """生成标准的m3u8文件，支持多源合并"""
    # 删除旧文件
    if os.path.exists(output_file):
        os.remove(output_file)
        print(f"【调试】删除旧文件：{output_file}")

    # 生成文件（即使无有效地址也生成空文件）
    m3u_header = """#EXTM3U
#EXT-X-VERSION:3
#x-tvg-url:https://epg.112114.xyz/pp.xml
"""
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(m3u_header)
        
        if not iptv_dict:
            print("【警告】无有效IPTV地址，生成空文件")
            return
        
        # 按源分组排序（可选：让同来源的频道放在一起）
        sorted_items = sorted(iptv_dict.items(), key=lambda x: x[0])
        for channel_name, play_url in sorted_items:
            # 提取分组名（从频道名的[源名称]中提取）
            group_match = re.search(r"\[(.*?)\]", channel_name)
            group_title = group_match.group(1) if group_match else "其他频道"
            
            f.write(f"#EXTINF:-1 group-title=\"{group_title}\" tvg-name=\"{channel_name}\",{channel_name}\n")
            f.write(f"{play_url}\n")

    # 强制更新文件修改时间
    if FORCE_UPDATE_FILE_TIME and os.path.exists(output_file):
        current_time = time.time()
        os.utime(output_file, (current_time, current_time))
        print(f"【调试】强制更新文件修改时间：{time.ctime(current_time)}")

    # 输出文件信息
    file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
    print(f"✅ m3u8文件生成成功：{output_file}（大小：{file_size} 字节，包含 {len(iptv_dict)} 个频道）")

# ===================== 主程序 =====================
if __name__ == "__main__":
    print("===== 多源IPTV爬虫开始运行 =====")
    start_time = time.time()

    # 1. 遍历所有源，爬取并合并地址
    all_iptv_dict = {}
    for source in IPTV_SOURCES:
        source_name = source["name"]
        source_url = source["url"]
        
        # 请求并解析单个源
        content = get_html_content(source_url, source_name)
        if not content:
            continue
        
        # 解析地址并合并到总字典（自动去重）
        source_iptv = parse_iptv_urls(content, source)
        all_iptv_dict.update(source_iptv)  # update自动去重（相同频道名会覆盖）

    print(f"\n【调试】所有源爬取完成，合并后总地址数：{len(all_iptv_dict)}")

    # 2. 过滤无效地址
    valid_iptv = filter_valid_urls(all_iptv_dict)

    # 3. 生成最终的m3u8文件
    generate_m3u8_file(valid_iptv, OUTPUT_M3U8)

    # 输出总耗时
    total_time = round(time.time() - start_time, 2)
    print(f"\n===== 多源IPTV爬虫运行完成（总耗时：{total_time} 秒）=====")
