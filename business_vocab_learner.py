# business_vocab_learner.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import datetime
import fcntl
import sys
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

LOCK_FILE = "learnbot.lock"
LOG_FILE = "learnbot.log"


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

        # 单词标题（加粗+emoji，模拟大号字体效果）
        word_line = f"✨ **{term}** {f'_({pos})_' if pos else ''}"

        # 翻译
        content = f"{word_line}\n📝 {translation}"

        # 如果有英文例句
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
    words = fetch_new_words(5)
    if not words:
        log("没有找到新的未学习单词。")
        return
    card = build_feishu_card(words)
    if send_to_feishu(card):
        mark_words_learned([w["id"] for w in words])


def main():
    lock_fh = acquire_lock(LOCK_FILE)
    try:
        run_once()
    finally:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()