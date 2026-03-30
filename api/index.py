from flask import Flask, jsonify
from flask_cors import CORS
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

app = Flask(__name__)
CORS(app)

# ==========================================
# 1. 初始設定 (NVIDIA & Firebase)
# ==========================================
nvidia_api_key = os.environ.get("NVIDIA_API_KEY")
client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nvidia_api_key) if nvidia_api_key else None

firebase_sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
if firebase_sa_json and not firebase_admin._apps:
    try:
        # 將 Vercel 裡的環境變數字串轉換為 JSON 字典並初始化 Firebase Admin
        cred_dict = json.loads(firebase_sa_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"Firebase 初始化失敗: {e}")

db = firestore.client() if firebase_admin._apps else None

RSS_FEED_URL = "https://techcrunch.com/feed/"

# ==========================================
# 2. 爬蟲與 AI 翻譯函數
# ==========================================
def fetch_and_parse_news():
    feed = feedparser.parse(RSS_FEED_URL)
    if not feed.entries:
        raise Exception("無法從 RSS 獲取新聞列表")
    
    articles = []
    # 抓取 5 篇
    for top_article in feed.entries[:5]:
        title = top_article.title
        link = top_article.link
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(link, headers=headers, timeout=5)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        paragraphs = soup.find_all('p')
        # 取前 5 段確保內容足夠
        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20][:5])
        articles.append({"title": title, "link": link, "content": content_text})
        
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
        max_tokens=2048,
    )
    
    try:
        raw_text = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_text)
    except Exception as e:
        raise Exception(f"LLM 解析失敗: {str(e)}")

# ==========================================
# 3. 觸發路由：專門給 Vercel Cron Job 呼叫
# ==========================================
@app.route('/api/cron', methods=['GET', 'POST'])
def run_daily_batch():
    try:
        if not client or not db:
            raise Exception("環境變數 (NVIDIA 或 Firebase) 未設定正確")
            
        articles = fetch_and_parse_news()
        final_data = []
        
        for idx, article in enumerate(articles):
            try:
                time.sleep(3) # 休息 3 秒避免被擋
                analysis_result = analyze_and_translate_with_llm(article['title'], article['content'])
                final_data.append({
                    "title": article['title'],
                    "url": article['link'],
                    "importance": analysis_result.get("importance", 3),
                    "objectivity": analysis_result.get("objectivity_analysis", "無"),
                    "paragraphs": analysis_result.get("content", [])
                })
            except Exception as ai_e:
                print(f"解析失敗: {ai_e}")
                continue
                
        if not final_data:
            raise Exception("所有新聞解析皆失敗")

        # 取得今天的台灣日期 (UTC+8)
        tz_tpe = timezone(timedelta(hours=8))
        today_str = datetime.now(tz_tpe).strftime("%Y-%m-%d")
        
        # 將資料存入 Firebase Firestore
        doc_ref = db.collection('daily_news').document(today_str)
        doc_ref.set({
            'date': today_str,
            'timestamp': datetime.now(timezone.utc),
            'articles': final_data
        })
        
        return jsonify({"status": "success", "message": f"{today_str} 新聞已成功存入資料庫！", "count": len(final_data)}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500

@app.route('/', methods=['GET'])
@app.route('/api', methods=['GET'])
@app.route('/api/news', methods=['GET'])
def hello():
    return jsonify({"message": "後端已升級為定時批次模式。前端請直接連接 Firebase 讀取資料。"})
