#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import datetime
import fcntl
import sys
import time
import mysql.connector
import requests
from dotenv import load_dotenv

SH_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 上海时区

# ---------- 配置 ----------
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "englishbot"),
    "charset": "utf8mb4"
}

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
LOCK_FILE = "learnbot.lock"
LOG_FILE = "learnbot.log"

# ---------- 法定节假日列表 ----------
HOLIDAYS = {
    "2025-10-01", "2025-10-02", "2025-10-03",  # 国庆
    "2025-10-04", "2025-10-05", "2025-10-06",
    "2025-10-07", "2025-10-08"
}

# ---------- 工具函数 ----------
def acquire_lock(lock_file):
    fh = open(lock_file, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except BlockingIOError:
        print("已有实例在运行，退出。")
        sys.exit(0)

def log(msg):
    ts = datetime.datetime.now(SH_TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def is_workday_today():
    today = datetime.datetime.now(SH_TZ).date()
    return today.weekday() < 5 and today.strftime("%Y-%m-%d") not in HOLIDAYS

# ---------- 数据库逻辑 ----------
def fetch_new_words(limit=5):
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, term, part_of_speech, translation, example_sentence, example_chinese "
        "FROM business_vocab WHERE learned=0 ORDER BY RAND() LIMIT %s",
        (limit,)
    )
    words = cursor.fetchall()
    cursor.close()
    conn.close()
    return words

def mark_words_learned(word_ids):
    if not word_ids:
        return
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    sql = """
        UPDATE business_vocab
        SET learned=1, needs_review=1, learn_date=CURDATE()
        WHERE id IN (%s)
    """ % (",".join(["%s"] * len(word_ids)))
    cursor.execute(sql, word_ids)
    conn.commit()
    cursor.close()
    conn.close()

# ---------- 飞书卡片 ----------
def build_feishu_card(words):
    elements = []
    for w in words:
        term = w["term"]
        pos = w.get("part_of_speech") or ""
        translation = w["translation"]
        eng_ex = w.get("example_sentence")
        cn_ex = w.get("example_chinese")

        word_line = f"✨ **{term}** {f'_({pos})_' if pos else ''}"
        content = f"{word_line}\n📝 {translation}"
        if eng_ex:
            content += f"\n📖 {eng_ex}"
            if cn_ex:
                content += f"\n🇨🇳 {cn_ex}"

        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": content}
        })

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "green",
                "title": {
                    "content": f"今日必学商务词汇 ✨ | {datetime.datetime.now(SH_TZ).strftime('%Y-%m-%d')}",
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
            log("飞书卡片发送成功")
            return True
        else:
            log(f"飞书返回异常: {resp.text}")
            return False
    except Exception as e:
        log(f"飞书请求异常: {e}")
        return False

# ---------- 主逻辑 ----------
def run_once():
    if not is_workday_today():
        log("今天不是工作日或法定节假日，跳过推送。")
        return

    words = fetch_new_words(5)
    if not words:
        log("没有找到新的未学习单词。")
        return
    card = build_feishu_card(words)
    if send_to_feishu(card):
        mark_words_learned([w["id"] for w in words])

def main_loop():
    lock_fh = acquire_lock(LOCK_FILE)
    try:
        while True:
            now = datetime.datetime.now(SH_TZ)
            # 每天 10:30 推送
            if now.hour == 10 and now.minute == 30:
                run_once()
                # 等到下一分钟再检查，避免重复推送
                time.sleep(60)
            else:
                # 每 30 秒检查一次
                time.sleep(30)
    finally:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()
        except Exception:
            pass

if __name__ == "__main__":
    main_loop()