import requests
import feedparser
from bs4 import BeautifulSoup
from openai import OpenAI
import os
import json
import traceback
import time
from datetime import datetime, timezone, timedelta
import firebase_admin
from firebase_admin import credentials, firestore

print("=======================================")
print("🚀 開始執行每日新聞抓取與 AI 全文翻譯任務")
print("=======================================")

# 1. 初始設定
nvidia_api_key = os.environ.get("NVIDIA_API_KEY")
if not nvidia_api_key:
    print("❌ 錯誤: 找不到 NVIDIA_API_KEY 環境變數")
    exit(1)

client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nvidia_api_key)

firebase_sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
if not firebase_sa_json:
    print("❌ 錯誤: 找不到 FIREBASE_SERVICE_ACCOUNT 環境變數")
    exit(1)

if not firebase_admin._apps:
    try:
        cred_dict = json.loads(firebase_sa_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase 初始化成功")
    except Exception as e:
        print(f"❌ Firebase 初始化失敗: {e}")
        exit(1)

db = firestore.client()
RSS_FEED_URL = "https://techcrunch.com/feed/"

def fetch_and_parse_news():
    print("📡 正在從 RSS 抓取新聞列表...")
    feed = feedparser.parse(RSS_FEED_URL)
    if not feed.entries:
        raise Exception("無法從 RSS 獲取新聞列表")
    
    articles = []
    # 抓取最新的 5 篇頭條
    for top_article in feed.entries[:5]:
        title = top_article.title
        link = top_article.link
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            response = requests.get(link, headers=headers, timeout=15)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 抓取所有內容段落
            paragraphs = soup.find_all('p')
            # 🌟 擴大抓取範圍至前 20 段，確保涵蓋全文
            content_segments = [p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 30]
            content_text = "\n\n".join(content_segments[:20]) 
            
            articles.append({"title": title, "link": link, "content": content_text})
        except Exception as e:
            print(f"  ⚠️ 無法抓取文章 {title}: {e}")
            continue
        
    print(f"✅ 成功獲取 {len(articles)} 篇新聞內容。")
    return articles

def analyze_and_translate_with_llm(title, content):
    # 🌟 優化提示詞，要求全文逐段翻譯
    prompt = f"""
    你是一個專業的科技新聞編譯。請閱讀以下英文新聞並進行全文翻譯。
    
    新聞標題: {title}
    
    新聞全文內容:
    {content}
    
    任務要求：
    1. 評估重要程度 (importance): 1-5 數字。
    2. 客觀性分析 (objectivity_analysis): 簡短一句話。
    3. 全文翻譯 (content): 將提供的每一段英文內容都翻譯成流暢的繁體中文。
    
    請嚴格遵守以下 JSON 格式回傳：
    {{
      "importance": 5,
      "objectivity_analysis": "...",
      "content": [
        {{ "en": "Original paragraph 1...", "zh": "對應的繁體中文翻譯..." }},
        {{ "en": "Original paragraph 2...", "zh": "對應的繁體中文翻譯..." }}
      ]
    }}
    """
    
    response = client.chat.completions.create(
        model="meta/llama-3.1-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=4096, # 🌟 提高 Token 上限以容納全文內容
    )
    
    try:
        raw_text = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_text)
    except Exception as e:
        raise Exception(f"LLM 解析失敗: {str(e)}")

def main():
    try:
        articles = fetch_and_parse_news()
        final_data = []
        
        for idx, article in enumerate(articles):
            print(f"⏳ [{idx+1}/{len(articles)}] 正在進行 AI 全文翻譯: {article['title']}")
            try:
                # 稍微休息避免 API 頻率限制
                time.sleep(3) 
                result = analyze_and_translate_with_llm(article['title'], article['content'])
                final_data.append({
                    "title": article['title'],
                    "url": article['link'],
                    "importance": result.get("importance", 3),
                    "objectivity": result.get("objectivity_analysis", "中立報導"),
                    "paragraphs": result.get("content", [])
                })
                print(f"  ✔️ 全文翻譯完成！共 {len(result.get('content', []))} 個段落。")
            except Exception as ai_e:
                print(f"  ❌ 翻譯失敗: {ai_e}")
                continue
                
        if not final_data:
            print("❌ 嚴重錯誤：無任何資料存入")
            exit(1)

        # 取得台灣日期
        tz_tpe = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_tpe).strftime("%Y-%m-%d")
        
        doc_ref = db.collection('daily_news').document(today_str)
        doc_ref.set({
            'date': today_str,
            'timestamp': datetime.now(timezone.utc),
            'articles': final_data
        })
        
        print(f"🎉 任務圓滿完成！{today_str} 的新聞已全面更新至資料庫。")

    except Exception as e:
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()
