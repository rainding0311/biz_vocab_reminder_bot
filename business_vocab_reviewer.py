# business_vocab_viewer.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import datetime
import fcntl
import sys
import random
import mysql.connector
import requests
from dotenv import load_dotenv

SH_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 上海时区

# ---------- 配置 ----------
load_dotenv()  # 加载 .env 文件

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "englishbot"),
    "charset": "utf8mb4"
}

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
LOCK_FILE = "reviewbot.lock"
LOG_FILE = "reviewbot.log"

# ---------- 工具函数 ----------
def acquire_lock(lock_file):
    fh = open(lock_file, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except BlockingIOError:
        print("已有复习脚本实例在运行，退出。")
        sys.exit(0)

def log(msg):
    ts = datetime.datetime.now(SH_TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ---------- 数据库逻辑 ----------
def fetch_review_words(limit=10):
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, term, part_of_speech, translation, review_count, last_review_date, example_sentence "
        "FROM business_vocab "
        "WHERE learned=1 AND needs_review=1"
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return []

    weighted_list = []
    for w in rows:
        weight = 1 / (1 + w['review_count'])**1.5
        weighted_list.extend([w] * max(int(weight * 100), 1))

    selected = random.sample(weighted_list, min(limit, len(rows)))

    seen = set()
    result = []
    for w in selected:
        if w['id'] not in seen:
            result.append(w)
            seen.add(w['id'])

    if len(result) < limit:
        remaining = [w for w in rows if w['id'] not in seen]
        random.shuffle(remaining)
        result.extend(remaining[:limit - len(result)])

    return result[:limit]

def mark_words_reviewed(word_ids):
    if not word_ids:
        return
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    sql = """
        UPDATE business_vocab
        SET review_count = review_count + 1,
            last_review_date = CURDATE()
        WHERE id IN (%s)
    """ % (",".join(["%s"] * len(word_ids)))
    cursor.execute(sql, word_ids)
    conn.commit()
    cursor.close()
    conn.close()

# ---------- 飞书卡片 ----------
def build_review_card(words):
    elements = []
    for idx, w in enumerate(words, start=1):
        last_review = w['last_review_date'].strftime('%Y-%m-%d') if w['last_review_date'] else "未复习过"
        pos_str = f"_({w['part_of_speech']})_" if w.get('part_of_speech') else ""

        # 随机决定题型：True=中文题（提示中文，答英文），False=英文题（提示英文，答中文）
        do_chinese = random.choice([True, False])

        if do_chinese:
            # 中文题：提示中文，答英文，不显示例句
            content = f"{idx}. ✨ **{w['translation']}** {pos_str}\n📝 请写出英文单词\n⏰ 上次复习: {last_review}"
        else:
            # 英文题：提示英文，答中文，显示例句（如果有）
            content = f"{idx}. ✨ **{w['term']}** {pos_str}"
            if w.get('example_sentence'):
                content += f"\n📖 {w['example_sentence']}"
            content += f"\n📝 请写出中文意思\n⏰ 上次复习: {last_review}"

        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "content": f"今日复习单词 🔄 | {datetime.datetime.now(SH_TZ).strftime('%Y-%m-%d')}",
                    "tag": "plain_text"
                }
            },
            "elements": elements
        }
    }

def send_to_feishu(card):
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and data.get("StatusCode") == 0:
            log("飞书复习卡片发送成功")
            return True
        else:
            log(f"飞书返回异常: {resp.text}")
            return False
    except Exception as e:
        log(f"飞书请求异常: {e}")
        return False

# ---------- 主逻辑 ----------
def run_review():
    words = fetch_review_words(10)
    if not words:
        log("没有找到待复习的单词。")
        return
    card = build_review_card(words)
    if send_to_feishu(card):
        mark_words_reviewed([w['id'] for w in words])

def main():
    lock_fh = acquire_lock(LOCK_FILE)
    try:
        run_review()
    finally:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()