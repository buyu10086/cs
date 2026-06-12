# -*- coding: utf-8 -*-
import os
import re

def clean_name(s):
    """清理频道名中的不可见字符"""
    return re.sub(r'[\x00-\x1f]', '', s).strip()

def main():
    txt_files = [
        "iptv_sources.txt",
        "m3u8_sources.txt"
    ]
    output_file = "iptv_playlist.m3u8"

    channels = []
    seen = set()

    for fpath in txt_files:
        if not os.path.exists(fpath):
            continue

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except:
            continue

        for line in lines:
            line = line.strip()
            # 跳过空行、注释行
            if not line or line.startswith("#"):
                continue
            # 必须有逗号分隔 频道名,链接
            if "," not in line:
                continue

            parts = line.split(",", 1)
            name = clean_name(parts[0])
            url = parts[1].strip()

            if not name or not url:
                continue

            # 去重 key
            key = (name.lower(), url)
            if key in seen:
                continue
            seen.add(key)
            channels.append((name, url))

    # 按频道名排序
    channels.sort(key=lambda x: x[0])

    # 写入标准 m3u8
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, url in channels:
            f.write(f'#EXTINF:-1 tvg-name="{name}",{name}\n')
            f.write(f"{url}\n")

    print(f"✅ 合并完成，有效频道数：{len(channels)}")
    print(f"📁 输出文件：{output_file}")

if __name__ == "__main__":
    main()
