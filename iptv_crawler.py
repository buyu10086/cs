import requests
import re
from typing import List, Dict, Tuple

# 超时时间设置（单位：秒），响应时间越短，认为源越快
TIMEOUT = 3

def cctv_channel_sort(channels: List[Dict]) -> List[Dict]:
    """
    CCTV频道排序：按频道号正序排列（如CCTV-1 < CCTV-2 < CCTV-13 < CCTV-5+）
    """
    def extract_channel_number(channel_name: str) -> Tuple[int, str]:
        """提取频道号，处理特殊频道（如CCTV-5+）"""
        # 正则匹配频道号（数字部分 + 可能的后缀）
        match = re.search(r'CCTV-(\d+)([+]?)', channel_name)
        if match:
            number = int(match.group(1))
            suffix = match.group(2)  # 处理5+、16+这类后缀
            return (number, suffix)
        # 非数字频道（如CCTV-新闻），放在排序末尾
        return (999, channel_name)
    
    # 按提取的频道号进行排序
    return sorted(channels, key=lambda x: extract_channel_number(x['name']))

def test_source_speed(source_url: str) -> float:
    """
    测试播放源的响应速度，返回响应时间（单位：秒）
    若源不可用（超时、连接失败、状态码非200），返回一个极大值
    """
    try:
        start_time = requests.utils.datetime.datetime.now()
        # 只请求头部信息（不下载完整内容，提高测速效率）
        response = requests.head(
            source_url,
            timeout=TIMEOUT,
            allow_redirects=True  # 允许重定向，兼容部分跳转源
        )
        end_time = requests.utils.datetime.datetime.now()
        response_time = (end_time - start_time).total_seconds()
        
        # 仅当状态码为200时，认为源可用，返回实际响应时间
        return response_time if response.status_code == 200 else float('inf')
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
            requests.exceptions.RequestException):
        # 各种异常情况，认为源不可用，返回极大值
        return float('inf')

def auto_select_fast_source(channel: Dict) -> Dict:
    """
    为单个CCTV频道自动选择最快的可用播放源
    """
    source_list = channel.get('sources', [])
    if not source_list:
        channel['fastest_source'] = None
        channel['response_time'] = None
        return channel
    
    # 对每个源进行测速，生成（响应时间，源地址）的列表
    source_speed = [(test_source_speed(source), source) for source in source_list]
    
    # 筛选出可用源（响应时间不是极大值），并按响应时间升序排序
    available_sources = [(speed, url) for speed, url in source_speed if speed != float('inf')]
    if not available_sources:
        channel['fastest_source'] = None
        channel['response_time'] = '无可用源'
        return channel
    
    # 选择响应时间最短的源
    fastest_speed, fastest_url = sorted(available_sources, key=lambda x: x[0])[0]
    channel['fastest_source'] = fastest_url
    channel['response_time'] = f"{fastest_speed:.4f} 秒"
    
    return channel

def main():
    """主函数：整合排序和快速源选择功能"""
    # 示例CCTV频道数据（可根据实际情况扩展播放源）
    cctv_channels = [
        {
            'name': 'CCTV-13 新闻频道',
            'sources': [
                'https://example.com/cctv13/stream1.m3u8',
                'https://example.com/cctv13/stream2.m3u8',
                'https://example.com/cctv13/stream3.m3u8'
            ]
        },
        {
            'name': 'CCTV-5+ 体育赛事频道',
            'sources': [
                'https://example.com/cctv5plus/stream1.m3u8',
                'https://example.com/cctv5plus/stream2.m3u8'
            ]
        },
        {
            'name': 'CCTV-1 综合频道',
            'sources': [
                'https://example.com/cctv1/stream1.m3u8',
                'https://example.com/cctv1/stream2.m3u8'
            ]
        },
        {
            'name': 'CCTV-2 财经频道',
            'sources': [
                'https://example.com/cctv2/stream1.m3u8'
            ]
        }
    ]
    
    # 步骤1：CCTV频道排序
    sorted_channels = cctv_channel_sort(cctv_channels)
    print("=== 已完成CCTV频道排序 ===")
    
    # 步骤2：为每个排序后的频道选择最快播放源
    print("\n=== 正在自动检测最优播放源（请稍候）===")
    final_result = [auto_select_fast_source(channel) for channel in sorted_channels]
    
    # 步骤3：输出最终结果
    print("\n=== 最终结果（排序后 + 快速源）===")
    for idx, channel in enumerate(final_result, 1):
        print(f"\n{idx}. 频道名称：{channel['name']}")
        print(f"   最快播放源：{channel['fastest_source'] or '无可用播放源'}")
        print(f"   响应时间：{channel['response_time']}")

if __name__ == "__main__":
    # 安装依赖提示（若未安装requests）
    try:
        import requests
    except ImportError:
        print("请先安装requests依赖：pip install requests")
    else:
        main()
