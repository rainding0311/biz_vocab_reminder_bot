import requests
import time
import mysql.connector
from dotenv import load_dotenv
import os

# -------------------------- 1. 配置常量 --------------------------
load_dotenv()
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': 'english_study',
    'port': int(os.getenv('DB_PORT', 3306))
}
API_DELAY = 1  # 1秒延迟防反爬
EMPTY_SENTENCE_MARKER = '暂无例句'  # 未填充标记（英文/中文通用）
EMPTY_CHINESE_MARKER = '暂无中文翻译'  # 中文缺失时的专用标记（可选，也可仍用EMPTY_SENTENCE_MARKER）


# -------------------------- 2. Tatoeba API查询（核心优化）--------------------------
def query_tatoeba_example(word, from_lang="eng", to_lang="cmn"):
    """优化：有英文就保留，中文缺失则填充默认值"""
    time.sleep(API_DELAY)
    encoded_word = requests.utils.quote(word)
    url = f"https://tatoeba.org/en/api_v0/search?from={from_lang}&query={encoded_word}&to={to_lang}"
    
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️  单词[{word}] API请求失败（状态码：{resp.status_code}）")
            return None
        
        data = resp.json()
        results = data.get("results", [])
        if not results:
            print(f"❌ 单词[{word}] 未找到任何英文例句")
            return None
        
        # 提取英文例句（优先保留有效英文）
        first_result = results[0]
        eng_sentence = first_result.get("text", "").strip()
        if not eng_sentence:
            print(f"❌ 单词[{word}] 英文例句为空，跳过")
            return None
        
        # 提取中文翻译（缺失则用默认值）
        translations = first_result.get("translations", [])
        chn_sentence = EMPTY_CHINESE_MARKER  # 默认值：中文缺失
        if translations and isinstance(translations[0], list) and translations[0]:
            chn_text = translations[0][0].get("text", "").strip()
            if chn_text:  # 只有中文非空时才替换默认值
                chn_sentence = chn_text
        
        # 日志区分“中文缺失”和“完整例句”
        if chn_sentence == EMPTY_CHINESE_MARKER:
            print(f"ℹ️  单词[{word}] 获取到英文例句，中文缺失（英文：{eng_sentence[:30]}...）")
        else:
            print(f"✅ 单词[{word}] 成功获取完整例句（英文：{eng_sentence[:30]}...）")
        
        return {
            "example_sentence": eng_sentence,
            "example_chinese": chn_sentence
        }
    
    except Exception as e:
        print(f"⚠️  单词[{word}] API调用异常：{str(e)}")
        return None


# -------------------------- 3. 数据库联动（逻辑不变，适配中文默认值）--------------------------
def update_vocab_with_examples():
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        print("📦 成功连接数据库")
        
        # 只查询“英文例句未填充”的记录
        query_sql = """
        SELECT id, term 
        FROM business_vocab 
        WHERE example_sentence = %s 
        ORDER BY id ASC
        """
        cursor.execute(query_sql, (EMPTY_SENTENCE_MARKER,))
        pending_words = cursor.fetchall()
        
        if not pending_words:
            print("🎉 所有词汇已补充英文例句，无需处理！")
            return
        
        print(f"📋 共找到 {len(pending_words)} 个待补充例句的词汇，开始处理...\n")
        
        # 更新SQL：仍保留防覆盖条件
        update_sql = """
        UPDATE business_vocab 
        SET example_sentence = %s, example_chinese = %s 
        WHERE id = %s AND example_sentence = %s
        """
        
        success_count = 0
        for vocab in pending_words:
            vocab_id = vocab["id"]
            vocab_term = vocab["term"]
            
            example_data = query_tatoeba_example(vocab_term)
            if not example_data:
                continue
            
            # 执行更新（中文缺失时自动写入默认值）
            try:
                cursor.execute(
                    update_sql,
                    (
                        example_data["example_sentence"],
                        example_data["example_chinese"],
                        vocab_id,
                        EMPTY_SENTENCE_MARKER
                    )
                )
                conn.commit()
                success_count += 1
            
            except Exception as e:
                conn.rollback()
                print(f"⚠️  词汇[{vocab_term}]（ID：{vocab_id}）数据库更新失败：{str(e)}\n")
        
        print(f"\n📊 处理完成！共成功更新 {success_count}/{len(pending_words)} 个词汇")
        print(f"   - 完整例句（含中文）：{sum(1 for v in pending_words if query_tatoeba_example(v['term']) and query_tatoeba_example(v['term'])['example_chinese'] != EMPTY_CHINESE_MARKER)} 个")
        print(f"   - 仅英文例句（中文缺失）：{success_count - sum(1 for v in pending_words if query_tatoeba_example(v['term']) and query_tatoeba_example(v['term'])['example_chinese'] != EMPTY_CHINESE_MARKER)} 个")
    
    except mysql.connector.Error as db_err:
        print(f"❌ 数据库操作异常：{db_err}")
    except Exception as e:
        print(f"❌ 程序整体异常：{str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            print("\n📦 已关闭数据库连接")


# -------------------------- 4. 主程序入口 --------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("📚 商务英语词汇例句补充工具（优化版：保留英文，中文缺失用默认值）")
    print("=" * 60)
    update_vocab_with_examples()
    print("\n👋 程序结束")