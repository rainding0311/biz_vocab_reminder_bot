import requests
import time
import mysql.connector
from dotenv import load_dotenv
import os

# -------------------------- 1. 加载配置（数据库+API）--------------------------
load_dotenv()  # 读取.env文件中的数据库配置
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': 'english_study',
    'port': int(os.getenv('DB_PORT', 3306))  # 支持自定义端口（默认3306）
}
API_DELAY = 1  # API请求间隔（1秒，防反爬）
EMPTY_SENTENCE_MARKER = '暂无例句'  # 未填充例句的标记（与数据库一致）


# -------------------------- 2. Tatoeba API查询（带延迟）--------------------------
def query_tatoeba_example(word, from_lang="eng", to_lang="cmn"):
    """调用Tatoeba API获取中英文例句，带1秒延迟"""
    # 1. 防反爬：请求前延迟1秒
    time.sleep(API_DELAY)
    
    # 2. 构造请求（处理关键词中的空格，避免URL错误）
    encoded_word = requests.utils.quote(word)  # 对单词编码（如"set up"→"set%20up"）
    url = f"https://tatoeba.org/en/api_v0/search?from={from_lang}&query={encoded_word}&to={to_lang}"
    
    try:
        resp = requests.get(url, timeout=10)  # 超时控制（10秒）
        if resp.status_code != 200:
            print(f"⚠️  单词[{word}] API请求失败（状态码：{resp.status_code}）")
            return None
        
        data = resp.json()
        results = data.get("results", [])
        if not results:
            print(f"❌ 单词[{word}] 未找到匹配例句")
            return None
        
        # 3. 提取第一个有效例句（英文原文+中文翻译）
        first_result = results[0]
        eng_sentence = first_result.get("text", "").strip()
        translations = first_result.get("translations", [])
        
        # 确保中文翻译存在且有效
        chn_sentence = ""
        if translations and isinstance(translations[0], list) and translations[0]:
            chn_sentence = translations[0][0].get("text", "").strip()
        
        if not eng_sentence or not chn_sentence:
            print(f"❌ 单词[{word}] 例句格式不完整（英文：{eng_sentence}，中文：{chn_sentence}）")
            return None
        
        print(f"✅ 单词[{word}] 成功获取例句")
        return {
            "example_sentence": eng_sentence,
            "example_chinese": chn_sentence
        }
    
    except Exception as e:
        print(f"⚠️  单词[{word}] API调用异常：{str(e)}")
        return None


# -------------------------- 3. 数据库联动（查询待补充数据+更新）--------------------------
def update_vocab_with_examples():
    """从数据库读取“暂无例句”的词汇，调用API补充后更新回数据库"""
    conn = None
    cursor = None
    try:
        # 1. 连接数据库
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)  # 用字典格式返回查询结果（便于取值）
        print("📦 成功连接数据库")
        
        # 2. 查询待补充例句的数据（只查example_sentence为“暂无例句”的记录）
        query_sql = """
        SELECT id, term 
        FROM business_vocab 
        WHERE example_sentence = %s 
        ORDER BY id ASC  # 按ID顺序处理，避免重复
        """
        cursor.execute(query_sql, (EMPTY_SENTENCE_MARKER,))
        pending_words = cursor.fetchall()  # 待处理的词汇列表
        
        if not pending_words:
            print("🎉 所有词汇已补充例句，无需处理！")
            return
        
        print(f"📋 共找到 {len(pending_words)} 个待补充例句的词汇，开始处理...")
        
        # 3. 逐个处理词汇（查询API+更新数据库）
        update_sql = """
        UPDATE business_vocab 
        SET example_sentence = %s, example_chinese = %s 
        WHERE id = %s AND example_sentence = %s  # 加条件：确保只更新“未填充”的记录（防覆盖）
        """
        
        success_count = 0  # 成功更新计数
        for vocab in pending_words:
            vocab_id = vocab["id"]
            vocab_term = vocab["term"]
            
            # 调用API获取例句
            example_data = query_tatoeba_example(vocab_term)
            if not example_data:
                continue  # 跳过获取失败的词汇
            
            # 执行数据库更新（带防覆盖条件）
            try:
                cursor.execute(
                    update_sql,
                    (
                        example_data["example_sentence"],
                        example_data["example_chinese"],
                        vocab_id,
                        EMPTY_SENTENCE_MARKER  # 关键：只更新“暂无例句”的记录，避免覆盖已有的
                    )
                )
                conn.commit()  # 实时提交（避免批量失败丢失数据）
                success_count += 1
            
            except Exception as e:
                conn.rollback()  # 单条更新失败，回滚避免影响其他
                print(f"⚠️  词汇[{vocab_term}]（ID：{vocab_id}）数据库更新失败：{str(e)}")
        
        # 4. 处理完成，输出统计
        print(f"\n📊 处理完成！共成功更新 {success_count}/{len(pending_words)} 个词汇的例句")
    
    except mysql.connector.Error as db_err:
        print(f"❌ 数据库操作异常：{db_err}")
    except Exception as e:
        print(f"❌ 程序整体异常：{str(e)}")
    finally:
        # 5. 关闭数据库连接（无论成功/失败都要关闭）
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            print("📦 已关闭数据库连接")


# -------------------------- 4. 主程序入口 --------------------------
if __name__ == "__main__":
    print("=" * 50)
    print("📚 商务英语词汇例句补充工具（Tatoeba API + MySQL）")
    print("=" * 50)
    update_vocab_with_examples()
    print("\n👋 程序结束")