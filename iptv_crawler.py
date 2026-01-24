import requests
from bs4 import BeautifulSoup
import re

# 目标爬取的IPTV源页面（示例，可替换为其他公开源）
TARGET_URL = "https://example.com/iptv-list"  # 替换为真实的IPTV源页面
# 生成的m3u8文件路径
M3U8_FILE = "iptv_list.m3u8"

def get_ipv_urls():
    """爬取IPTV直播地址，返回{频道名: 播放地址}的字典"""
    iptv_dict = {}
    try:
        # 请求页面（添加请求头模拟浏览器，避免被反爬）
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.raise_for_status()  # 抛出HTTP错误
        response.encoding = response.apparent_encoding

        # 解析页面（根据目标网站的HTML结构调整解析规则）
        soup = BeautifulSoup(response.text, "lxml")
        # 示例：匹配所有包含m3u8/ts的链接（根据目标网站调整）
        links = soup.find_all("a", href=re.compile(r"(m3u8|ts)$", re.I))
        for link in links:
            channel_name = link.get_text(strip=True) or f"频道{len(iptv_dict)+1}"
            play_url = link["href"]
            # 补全相对路径为绝对路径
            if not play_url.startswith(("http://", "https://")):
                play_url = requests.compat.urljoin(TARGET_URL, play_url)
            iptv_dict[channel_name] = play_url

        # 额外：过滤无效地址（可选）
        iptv_dict = {k: v for k, v in iptv_dict.items() if v.strip()}
        print(f"成功爬取 {len(iptv_dict)} 个IPTV地址")
    except Exception as e:
        print(f"爬取失败：{str(e)}")
    return iptv_dict

def generate_m3u8(iptv_dict):
    """将爬取的地址生成标准的m3u8文件（IPTV播放器通用格式）"""
    m3u8_header = "#EXTM3U x-tvg-url=\"https://epg.112114.xyz/pp.xml\"\n"  # EPG节目指南（可选）
    with open(M3U8_FILE, "w", encoding="utf-8") as f:
        f.write(m3u8_header)
        for channel_name, play_url in iptv_dict.items():
            # m3u8格式规范：#EXTINF 行描述频道，下一行是播放地址
            f.write(f"#EXTINF:-1 group-title=\"默认\" tvg-name=\"{channel_name}\",{channel_name}\n")
            f.write(f"{play_url}\n")
    print(f"m3u8文件已生成：{M3U8_FILE}")

if __name__ == "__main__":
    # 1. 爬取地址
    iptv_urls = get_ipv_urls()
    # 2. 生成m3u8文件
    if iptv_urls:
        generate_m3u8(iptv_urls)
    else:
        print("未爬取到有效IPTV地址")
