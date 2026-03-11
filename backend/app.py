import json
import logging
from typing import List, Optional

import requests
import sqlite3
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Bilibili Comment Monitor API")
scheduler = BackgroundScheduler()
scheduler.start()

# --- 抓取配置（用于“线程完整”但避免请求过多） ---
TOP_LEVEL_MAX_PAGES = 5
SUB_REPLY_PAGE_SIZE = 20
REQUEST_SLEEP_SECONDS = 0.5

# --- 数据库初始化 ---
DB_NAME = "monitor.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            oid TEXT PRIMARY KEY,
            bv_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS seen_comments (
            rpid TEXT PRIMARY KEY,
            oid TEXT NOT NULL,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS root_reply_state (
            root_rpid TEXT PRIMARY KEY,
            oid TEXT NOT NULL,
            last_rcount INTEGER DEFAULT 0
        )
        ''')
        # 为 oid 创建索引以加速查询
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_oid ON seen_comments (oid)')
        conn.commit()

init_db()

# --- 数据模型 ---
class VideoIn(BaseModel):
    bv_id: str

class ConfigIn(BaseModel):
    cookie: Optional[str] = None
    dingtalk_webhook: Optional[str] = None
    interval_minutes: Optional[float] = None

# --- 工具函数 ---

def get_config(key, default=None):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

def set_config(key, value):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()

def md5(code):
    return hashlib.md5(code.encode('utf-8')).hexdigest()

def send_dingtalk(title, comments):
    webhook = get_config("dingtalk_webhook")
    if not webhook:
        return
    
    msg_list = []
    for c in comments:
        msg_list.append(f"- **类型**: {c['type']}\n- **用户**: {c['user']}\n- **内容**: {c['message']}\n- **时间**: {c['time']}")
    
    content = "\n\n---\n\n".join(msg_list)
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"B站新评论: {title}",
            "text": f"## 视频：{title}\n\n{content}"
        }
    }
    try:
        requests.post(webhook, json=data, timeout=10)
    except Exception as e:
        logger.error(f"发送钉钉通知失败: {e}")

# --- 核心抓取逻辑 ---

def _fetch_top_level_wbi_page(oid, header, mixin_key_salt, next_cursor):
    params = {
        'oid': oid,
        'type': 1,
        'mode': 2,
        'plat': 1,
        'web_location': 1315875,
        'wts': int(time.time()),
    }
    if next_cursor:
        params['pagination_str'] = json.dumps({'offset': str(next_cursor)})

    query_for_w_rid = urllib.parse.urlencode(sorted(params.items()))
    w_rid = md5(query_for_w_rid + mixin_key_salt)
    params['w_rid'] = w_rid
    url = f"https://api.bilibili.com/x/v2/reply/wbi/main?{urllib.parse.urlencode(params)}"
    response = requests.get(url, headers=header, timeout=5)
    response.raise_for_status()
    return response.json()

def _fetch_top_level_fallback_page(oid, header, page_number, page_size=20):
    params = {'oid': oid, 'type': 1, 'sort': 1, 'pn': page_number, 'ps': page_size}
    url = f"https://api.bilibili.com/x/v2/reply/main?{urllib.parse.urlencode(params)}"
    response = requests.get(url, headers=header, timeout=5)
    response.raise_for_status()
    return response.json()

def _extract_pinned_replies(data):
    pinned = []
    if not isinstance(data, dict): return pinned
    top = data.get('top')
    if isinstance(top, dict):
        for key in ('upper', 'admin', 'vote'):
            item = top.get(key)
            if item: pinned.append(item)
    upper = data.get('upper')
    if isinstance(upper, dict):
        item = upper.get('top')
        if item: pinned.append(item)
    return pinned

def fetch_top_level_comments(oid, header, max_pages=TOP_LEVEL_MAX_PAGES):
    if not oid: return []
    mixin_key_salt = "ea1db124af3c7062474693fa704f4ff8"
    all_replies = []
    next_cursor = 0
    use_fallback = False
    fallback_page_number = 1
    fallback_page_size = 20
    seen_rpid = set()

    for _ in range(max_pages):
        try:
            if use_fallback:
                comment_data = _fetch_top_level_fallback_page(oid, header, fallback_page_number, page_size=fallback_page_size)
            else:
                comment_data = _fetch_top_level_wbi_page(oid, header, mixin_key_salt, next_cursor)
        except Exception as e:
            logger.error(f"抓取 oid={oid} 顶层评论出错: {e}")
            break

        if comment_data.get('code') != 0:
            msg = comment_data.get('message', '')
            if not use_fallback and ("权限" in msg or "访问" in msg or "permission" in msg.lower()):
                use_fallback = True
                next_cursor = 0
                fallback_page_number = 1
                continue
            break

        data = comment_data.get('data') or {}
        # 置顶处理
        for item in _extract_pinned_replies(data):
            rpid = str(item.get('rpid_str') or item.get('rpid', ''))
            if rpid and rpid not in seen_rpid:
                all_replies.append(item)
                seen_rpid.add(rpid)

        replies = data.get('replies', []) or []
        if not replies: break
        for item in replies:
            rpid = str(item.get('rpid_str') or item.get('rpid', ''))
            if rpid and rpid not in seen_rpid:
                all_replies.append(item)
                seen_rpid.add(rpid)

        if use_fallback:
            if len(replies) < fallback_page_size: break
            fallback_page_number += 1
        else:
            cursor = data.get('cursor') or {}
            next_cursor = cursor.get('next', 0)
            if cursor.get('is_end') or not next_cursor: break
        time.sleep(REQUEST_SLEEP_SECONDS)
    return all_replies

def fetch_all_sub_replies(oid, root_rpid, header):
    all_replies = []
    page_number = 1
    while True:
        url = f"https://api.bilibili.com/x/v2/reply/reply?oid={oid}&type=1&root={root_rpid}&pn={page_number}&ps={SUB_REPLY_PAGE_SIZE}"
        try:
            resp = requests.get(url, headers=header, timeout=5).json()
            if resp.get('code') == 0 and resp.get('data'):
                replies = resp['data'].get('replies', [])
                if not replies: break
                all_replies.extend(replies)
                page_number += 1
                time.sleep(REQUEST_SLEEP_SECONDS)
            else: break
        except: break
    return all_replies

def get_video_info(bv, header):
    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv}"
    try:
        data = requests.get(api_url, headers=header, timeout=5).json()
        if data.get('code') == 0:
            v = data.get('data', {})
            return str(v.get('aid')), v.get('title', '').strip(), str(v.get('owner', {}).get('mid', ''))
    except: pass
    return None, None, None

def monitor_job():
    cookie = get_config("cookie")
    if not cookie: return
    header = {"Cookie": cookie, "User-Agent": 'Mozilla/5.0...', "Referer": "https://www.bilibili.com"}

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT oid, bv_id, title FROM videos")
        videos = cursor.fetchall()

    for oid, bv_id, title in videos:
        _, _, owner_mid = get_video_info(bv_id, header)
        if not owner_mid: continue

        # 加载已见
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rpid FROM seen_comments WHERE oid = ?", (oid,))
            seen_ids = {r[0] for r in cursor.fetchall()}
            cursor.execute("SELECT root_rpid, last_rcount FROM root_reply_state WHERE oid = ?", (oid,))
            root_state = {r[0]: r[1] for r in cursor.fetchall()}

        latest_comments = fetch_top_level_comments(oid, header)
        new_comments_found = []

        for comment in latest_comments:
            c_mid = str(comment.get('member', {}).get('mid', ''))
            rpid = str(comment.get('rpid_str', ''))
            
            # UP主主评论
            if c_mid == owner_mid:
                if rpid not in seen_ids:
                    seen_ids.add(rpid)
                    with sqlite3.connect(DB_NAME) as conn:
                        conn.cursor().execute("INSERT OR IGNORE INTO seen_comments (rpid, oid) VALUES (?, ?)", (rpid, oid))
                    new_comments_found.append({"user": comment['member']['uname'], "message": comment['content']['message'], "type": "主评论", "time": datetime.datetime.fromtimestamp(comment['ctime']).strftime('%Y-%m-%d %H:%M:%S')})

                # 楼中楼
                rcount = comment.get('rcount', 0)
                if rcount > root_state.get(rpid, 0):
                    sub_replies = fetch_all_sub_replies(oid, rpid, header)
                    for sub in sub_replies:
                        s_mid = str(sub.get('member', {}).get('mid', ''))
                        s_rpid = str(sub.get('rpid_str', ''))
                        if s_mid == owner_mid and s_rpid not in seen_ids:
                            seen_ids.add(s_rpid)
                            with sqlite3.connect(DB_NAME) as conn:
                                conn.cursor().execute("INSERT OR IGNORE INTO seen_comments (rpid, oid) VALUES (?, ?)", (s_rpid, oid))
                            new_comments_found.append({"user": sub['member']['uname'], "message": sub['content']['message'], "type": f"回复@{comment['member']['uname']}", "time": datetime.datetime.fromtimestamp(sub['ctime']).strftime('%Y-%m-%d %H:%M:%S')})
                    
                    with sqlite3.connect(DB_NAME) as conn:
                        conn.cursor().execute("INSERT OR REPLACE INTO root_reply_state (root_rpid, oid, last_rcount) VALUES (?, ?, ?)", (rpid, oid, rcount))

        if new_comments_found:
            send_dingtalk(title, new_comments_found)

# --- API ---
@app.get("/status")
def read_status():
    job = scheduler.get_job('monitor_task')
    return {
        "is_running": bool(job),
        "next_run": str(job.next_run_time) if job else None,
        "config": {"has_cookie": bool(get_config("cookie")), "has_webhook": bool(get_config("dingtalk_webhook"))}
    }

@app.post("/config")
def update_config(cfg: ConfigIn):
    if cfg.cookie: set_config("cookie", cfg.cookie)
    if cfg.dingtalk_webhook: set_config("dingtalk_webhook", cfg.dingtalk_webhook)
    if cfg.interval_minutes:
        set_config("interval_minutes", cfg.interval_minutes)
        if scheduler.get_job('monitor_task'):
            scheduler.reschedule_job('monitor_task', trigger=IntervalTrigger(minutes=cfg.interval_minutes))
    return {"status": "ok"}

@app.get("/videos")
def list_videos():
    with sqlite3.connect(DB_NAME) as conn:
        return [{"oid": r[0], "bv_id": r[1], "title": r[2]} for r in conn.cursor().execute("SELECT oid, bv_id, title FROM videos").fetchall()]

@app.post("/videos")
def add_video(vid: VideoIn):
    cookie = get_config("cookie")
    header = {"Cookie": cookie or ""}
    oid, title, _ = get_video_info(vid.bv_id, header)
    if not oid: raise HTTPException(status_code=400, detail="Invalid BV ID")
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("INSERT OR REPLACE INTO videos (oid, bv_id, title) VALUES (?, ?, ?)", (oid, vid.bv_id, title))
    return {"status": "ok", "title": title}

@app.delete("/videos/{oid}")
def delete_video(oid: str):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("DELETE FROM videos WHERE oid = ?", (oid,))
    return {"status": "ok"}

@app.post("/jobs/start")
def start_task():
    if not scheduler.get_job('monitor_task'):
        interval = float(get_config("interval_minutes", 5.0))
        scheduler.add_job(monitor_job, IntervalTrigger(minutes=interval), id='monitor_task')
    return {"status": "ok"}

@app.post("/jobs/stop")
def stop_task():
    if scheduler.get_job('monitor_task'):
        scheduler.remove_job('monitor_task')
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
