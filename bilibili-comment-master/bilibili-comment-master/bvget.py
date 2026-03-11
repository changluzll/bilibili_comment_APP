# filename: bvget.py
import requests
import time
import os
import re
from typing import Optional, List

# --- 配置 ---
COOKIE_FILE_PATH = 'bili_cookie.txt'
API_URL = 'https://member.bilibili.com/x/web/data/archive_diagnose/compare'


def _read_sessdata_from_cookie_file() -> Optional[str]:
    """
    内部函数：从指定的cookie文件中读取SESSDATA的值。
    """
    if not os.path.exists(COOKIE_FILE_PATH):
        # 这个文件由 monitor.py 管理，这里只负责读取
        return None
    try:
        with open(COOKIE_FILE_PATH, 'r', encoding='utf-8') as f:
            cookie_content = f.read().strip()
            # 从完整的 cookie 字符串中提取 SESSDATA
            # 使用 re.search 更健壮地查找 SESSDATA=...; 或 SESSDATA=...$
            match = re.search(r'SESSDATA=([^;]+)', cookie_content)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"[bvget] 读取Cookie文件时发生错误: {e}")
    return None


def get_all_bvids_from_api() -> Optional[List[str]]:
    """
    获取B站UP主发布的所有视频的BV号列表。

    Returns:
        list[str] | None: 成功则返回BV号列表，失败则返回None。
    """
    sessdata = _read_sessdata_from_cookie_file()
    if not sessdata:
        print("[bvget] 错误：无法从 bili_cookie.txt 读取 SESSDATA。")
        return None

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Referer': 'https://member.bilibili.com/x/web/data/archive',
    }
    cookies = {
        'SESSDATA': sessdata
    }
    # B站创作中心似乎可以一次返回最多10000个稿件
    params = {
        'size': 10000,
        't': int(time.time())
    }

    try:
        print("[bvget] 正在通过创作中心API获取您的所有稿件...")
        response = requests.get(API_URL, headers=headers, cookies=cookies, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()

        if data.get('code') == 0:
            video_list = data.get('data', {}).get('list', [])
            bvid_list = [video.get('bvid') for video in video_list if video.get('bvid')]
            return bvid_list
        else:
            error_message = data.get('message', '未知错误')
            print(f"[bvget] API返回错误。代码: {data.get('code')}, 信息: {error_message}")
            if data.get('code') == -101:
                print("[bvget] 提示: 错误码 -101 通常表示登录失效，请尝试重新登录。")
            return None

    except requests.exceptions.RequestException as e:
        print(f"[bvget] 网络请求失败: {e}")
        return None
    except ValueError:
        print(f"[bvget] 解析JSON响应失败。收到的内容: {response.text[:200]}")
        return None

