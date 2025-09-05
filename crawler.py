# 本次爬虫来源 https://english.koolearn.com/20170619/821129.html
import requests
from bs4 import BeautifulSoup
import time
import mysql.connector
from dotenv import load_dotenv
import os
import re

# 加载数据库配置
load_dotenv()
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': 'english_study'
}

# 主页面URL（包含A-Z分类链接）
INDEX_URL = "https://english.koolearn.com/20170619/821129.html"
# 爬取间隔（秒），避免请求过于频繁
REQUEST_DELAY = 1

def get_letter_links():
    """从主页面获取所有字母分类的词汇页面链接"""
    try:
        response = requests.get(INDEX_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://english.koolearn.com/"  # 新增Referer，模拟正常访问
        })
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        letter_links = []
        for a in soup.find_all('a', href=True):
            if "BEC商务英语初级必备词汇：" in a.text:
                full_url = a['href'] if a['href'].startswith('http') else f"https://english.koolearn.com{a['href']}"
                letter_links.append((a.text.strip(), full_url))
        
        print(f"成功获取 {len(letter_links)} 个字母分类链接")
        return letter_links
    
    except Exception as e:
        print(f"获取字母链接失败：{str(e)}")
        return []

def parse_vocab_page(url):
    """解析单个字母页面，提取词汇、词性、中文解释（核心修改处）"""
    try:
        time.sleep(REQUEST_DELAY)
        response = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": INDEX_URL  # 关联主页面，避免反爬
        })
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        # -------------------------- 关键修改1：修改内容区域的class --------------------------
        content_div = soup.find('div', class_='xqy_core_text')  # 原class是art-content，现在改成xqy_core_text
        if not content_div:
            print(f"页面 {url} 未找到内容区域（xqy_core_text）")
            # 调试用：打印页面前1000字符，确认是否获取到页面内容
            print(f"页面预览：{response.text[:1000]}")
            return []
        
        # 提取文本并处理全角空格（页面里的空格是全角“　”，先换成半角“ ”）
        text = content_div.get_text(separator='\n', strip=True)
        text = text.replace('\u3000', ' ')  # 全角空格转半角，避免影响正则匹配
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # -------------------------- 关键修改2：优化正则，适配页面格式 --------------------------
        # 匹配规则：开头允许空格 + 单词 + 空格 + 词性（如n.、adv.） + . + 空格 + 中文解释
        # 例："yield n. 有效产量"、"abroad adv. 在国外，出国"
        pattern = re.compile(r'^(\w+)\s+([a-zA-Z.]+)\.\s+(.*)$')
        
        vocab_list = []
        for line in lines:
            # 跳过字母标题（如"A"、"B"、"Y-Z"）和无关内容（如介绍文字）
            if re.match(r'^[A-Z\-]+$', line):  # 匹配纯字母或字母+横杠（如Y-Z）
                continue
            if "更多请点击" in line or "新东方在线" in line:  # 跳过广告/导航文字
                continue
            
            match = pattern.match(line)
            if match:
                term = match.group(1).strip()
                pos = match.group(2).strip()  # 词性（n、adv、v等）
                translation = match.group(3).strip()
                vocab_list.append({
                    'term': term,
                    'part_of_speech': pos,
                    'translation': translation,
                    'example_sentence': '暂无例句',  # 后续可补充
                    'example_chinese': ''
                })
        
        print(f"从 {url} 提取到 {len(vocab_list)} 个词汇")
        # 调试用：打印前3个词汇，确认匹配正确
        if vocab_list:
            print(f"示例词汇：{vocab_list[:3]}")
        return vocab_list
    
    except Exception as e:
        print(f"解析页面 {url} 失败：{str(e)}")
        return []

def save_to_database(vocab_list):
    """将词汇数据保存到数据库"""
    if not vocab_list:
        return
    
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        insert_sql = """
        INSERT IGNORE INTO business_vocab 
        (term, part_of_speech, translation, example_sentence, example_chinese, 
         learned, needs_review, learn_date, review_count, last_review_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        data = [
            (
                vocab['term'],
                vocab['part_of_speech'],
                vocab['translation'],
                vocab['example_sentence'],
                vocab['example_chinese'],
                False, False, None, 0, None
            ) for vocab in vocab_list
        ]
        
        cursor.executemany(insert_sql, data)
        conn.commit()
        print(f"成功保存 {cursor.rowcount} 条新词汇到数据库\n")
    
    except mysql.connector.Error as err:
        print(f"数据库错误：{err}\n")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

def main():
    letter_links = get_letter_links()
    if not letter_links:
        print("未获取到分类链接，程序退出")
        return
    
    for letter, url in letter_links:
        print(f"=== 开始爬取 {letter}：{url} ===")
        vocab_list = parse_vocab_page(url)
        if vocab_list:
            save_to_database(vocab_list)
    
    print("所有词汇爬取完成！")

if __name__ == "__main__":
    main()