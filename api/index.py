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

app = Flask(__name__)
CORS(app)

api_key = os.environ.get("NVIDIA_API_KEY")
client = None
if api_key:
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key
    )

RSS_FEED_URL = "https://techcrunch.com/feed/"

def fetch_and_parse_news():
    feed = feedparser.parse(RSS_FEED_URL)
    if not feed.entries:
        raise Exception("無法從 RSS 獲取新聞列表")
    
    articles = []
    # 這裡設定抓取前 5 篇
    for top_article in feed.entries[:5]:
        title = top_article.title
        link = top_article.link
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(link, headers=headers, timeout=5)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        paragraphs = soup.find_all('p')
        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20][:3])
        articles.append({"title": title, "link": link, "content": content_text})
        
    return articles

def analyze_and_translate_with_llm(title, content):
    prompt = f"""
    你是一個專業、中立的科技新聞編譯。請閱讀以下英文新聞標題與內文。
    新聞標題: {title}
    新聞內文:
    {content}
    
    請幫我完成以下任務，並**嚴格遵守 JSON 格式回傳**（不要包含 ```json 標籤，純粹的 JSON 字串）：
    1. "importance": 評估這則新聞的重要程度 (1到5的整數，5為最重要，例如A1頭條等級)。
    2. "objectivity_analysis": 評估這篇報導的客觀性 (簡短的一句話，例如"報導基於官方財報，無明顯主觀情緒")。
    3. "content": 將原文逐段翻譯成繁體中文。這必須是一個陣列，每個元素包含 "en" (英文原文段落) 和 "zh" (繁體中文翻譯)。
    """
    
    response = client.chat.completions.create(
        model="meta/llama-3.1-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1024,
    )
    
    try:
        raw_text = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_text)
    except Exception as e:
        raise Exception(f"LLM 回傳格式解析失敗: {str(e)}")

@app.route('/', methods=['GET'])
@app.route('/api', methods=['GET'])
@app.route('/api/news', methods=['GET'])
def get_daily_news():
    debug_info = {}
    try:
        if not api_key or not client:
            raise Exception("伺服器遺失 NVIDIA_API_KEY 環境變數")
            
        articles = fetch_and_parse_news()
        final_data = []
        
        # 使用迴圈處理 5 篇新聞
        for idx, article in enumerate(articles):
            debug_info[f"step_2_{idx}"] = f"Analyzing: {article['title']}"
            try:
                # ⚠️ 關鍵防護：暫停 2 秒，避免被 NVIDIA 封鎖 API
                time.sleep(2)
                
                analysis_result = analyze_and_translate_with_llm(article['title'], article['content'])
                final_data.append({
                    "title": article['title'],
                    "url": article['link'],
                    "importance": analysis_result.get("importance", 3),
                    "objectivity": analysis_result.get("objectivity_analysis", "無法評估"),
                    "paragraphs": analysis_result.get("content", [])
                })
            except Exception as ai_e:
                print(f"解析 {article['title']} 失敗: {ai_e}")
                continue
        
        return jsonify({
            "status": "success",
            "data": final_data,
            "debug": debug_info
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "debug": traceback.format_exc()
        }), 500
