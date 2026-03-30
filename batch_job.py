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
print("🚀 開始執行每日新聞抓取與 AI 翻譯批次任務")
print("=======================================")

# ==========================================
# 1. 初始設定 (NVIDIA & Firebase)
# ==========================================
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

# ==========================================
# 2. 爬蟲與 AI 翻譯函數 (已解除時間限制)
# ==========================================
def fetch_and_parse_news():
    print("📡 正在從 RSS 抓取新聞列表...")
    feed = feedparser.parse(RSS_FEED_URL)
    if not feed.entries:
        raise Exception("無法從 RSS 獲取新聞列表")
    
    articles = []
    # 🌟 因為 GitHub 沒有 10 秒限制，我們霸氣地一次抓 6 篇頭條！
    for top_article in feed.entries[:6]:
        title = top_article.title
        link = top_article.link
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(link, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        paragraphs = soup.find_all('p')
        # 🌟 每篇抓取前 5 段，讓翻譯內容更豐富
        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20][:5])
        articles.append({"title": title, "link": link, "content": content_text})
        
    print(f"✅ 成功獲取 {len(articles)} 篇新聞，準備交給 AI 翻譯。")
    return articles

def analyze_and_translate_with_llm(title, content):
    prompt = f"""
    你是一個專業、中立的科技新聞編譯。請閱讀以下英文新聞標題與內文。
    新聞標題: {title}
    新聞內文:
    {content}
    
    請幫我完成以下任務，並嚴格遵守 JSON 格式回傳（純粹的 JSON 字串）：
    1. "importance": 評估這則新聞的重要程度 (1到5的整數，5為最重要，例如A1頭條等級)。
    2. "objectivity_analysis": 評估這篇報導的客觀性 (簡短的一句話)。
    3. "content": 將原文逐段翻譯成繁體中文。陣列元素包含 "en" (英文) 和 "zh" (繁中)。
    """
    
    response = client.chat.completions.create(
        model="meta/llama-3.1-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2500,
    )
    
    try:
        raw_text = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_text)
    except Exception as e:
        raise Exception(f"LLM 解析失敗: {str(e)}")

# ==========================================
# 3. 主程式執行邏輯
# ==========================================
def main():
    try:
        articles = fetch_and_parse_news()
        final_data = []
        
        for idx, article in enumerate(articles):
            print(f"⏳ [{idx+1}/{len(articles)}] 正在使用 AI 翻譯: {article['title']}")
            try:
                # 🌟 每次問完 AI 休息 5 秒，對 API 非常友善，絕對不會被擋
                time.sleep(5) 
                analysis_result = analyze_and_translate_with_llm(article['title'], article['content'])
                final_data.append({
                    "title": article['title'],
                    "url": article['link'],
                    "importance": analysis_result.get("importance", 3),
                    "objectivity": analysis_result.get("objectivity_analysis", "無"),
                    "paragraphs": analysis_result.get("content", [])
                })
                print(f"  ✔️ 翻譯成功！")
            except Exception as ai_e:
                print(f"  ❌ 翻譯失敗: {ai_e}")
                continue
                
        if not final_data:
            print("❌ 嚴重錯誤：所有新聞解析皆失敗")
            exit(1)

        # 取得今天的台灣日期 (UTC+8)
        tz_tpe = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_tpe).strftime("%Y-%m-%d")
        
        print("💾 正在將資料寫入 Firebase 資料庫...")
        doc_ref = db.collection('daily_news').document(today_str)
        doc_ref.set({
            'date': today_str,
            'timestamp': datetime.now(timezone.utc),
            'articles': final_data
        })
        
        print(f"🎉 任務圓滿完成！共 {len(final_data)} 篇新聞已成功存入資料庫 ({today_str})")

    except Exception as e:
        print(f"❌ 程式執行發生例外錯誤:")
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()
