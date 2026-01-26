def generate_m3u8(raw_lines):
    """过滤有效源，生成标准m3u8文件（新增电视可见的更新时间频道）"""
    # 获取当前时间（格式化）
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # m3u8文件头部（标准格式+更新时间注释）
    m3u8_header = f"""#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/cn/tv.cctv.com.epg.xml"
# 更新时间：{update_time}
# 有效源数量会自动筛选，此文件由GitHub Actions每6小时自动更新
"""
    valid_lines = [m3u8_header]
    
    # ========== 新增：电视可见的更新时间虚拟频道 ==========
    # 这个虚拟频道会显示在列表最顶部，电视打开就能看到
    valid_lines.append(f"#EXTINF:-1 group-title='系统信息',📅 直播源更新时间：{update_time}")
    valid_lines.append("#")  # 用#作为无效链接，仅用于显示信息
    # ====================================================
    
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
            
            # ========== 央视频道优先逻辑 ==========
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
#EXTINF:-1 group-title='系统信息',📅 直播源更新时间：{update_time}
#
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
