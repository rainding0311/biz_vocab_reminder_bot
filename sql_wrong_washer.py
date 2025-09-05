import os
import re
import mysql.connector
from dotenv import load_dotenv

# ---------- 环境变量 ----------
load_dotenv()
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME', 'english_study'),
    'port': int(os.getenv('DB_PORT', 3306))
}

# ---------- 连接数据库 ----------
conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor(dictionary=True)

# ---------- 获取所有记录 ----------
cursor.execute("SELECT id, term, translation FROM business_vocab")
rows = cursor.fetchall()

# ---------- 匹配下一个单词及词性 ----------
pattern = re.compile(r'([a-zA-Z- ]+)\s*(adj|v|n|a\.|adv)\.\s*')  # 支持空格的英文单词

for row in rows:
    translation = row['translation']
    splits = list(pattern.finditer(translation))
    if not splits:
        continue  # 正常记录，无需处理

    # 修正当前记录的翻译：取第一个匹配前的内容
    first = splits[0]
    fixed_translation = translation[:first.start()].strip('; ')
    if fixed_translation != translation:
        print(f"修正 {row['term']}: {fixed_translation}")
        cursor.execute(
            "UPDATE business_vocab SET translation=%s WHERE id=%s",
            (fixed_translation, row['id'])
        )

    # 从第一个匹配开始，把剩下的拆成新单词（只插入 term 和 translation）
    for i, match in enumerate(splits):
        new_term = match.group(1).strip()
        start = match.end()
        end = splits[i+1].start() if i+1 < len(splits) else len(translation)
        new_translation = translation[start:end].strip('; ')

        print(f"新增单词: {new_term} => {new_translation}")
        cursor.execute(
            "INSERT IGNORE INTO business_vocab (term, translation) VALUES (%s,%s)",
            (new_term, new_translation)
        )

# ---------- 提交修改 ----------
conn.commit()
cursor.close()
conn.close()