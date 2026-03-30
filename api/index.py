# ... existing code ...
import requests
import feedparser
from bs4 import BeautifulSoup
from openai import OpenAI
import os
import json
import traceback

app = Flask(__name__)
# 第一重保險：Python 端的 CORS
CORS(app)

# 設定 NVIDIA API (需在 Vercel 後台設定環境變數 NVIDIA_API_KEY)
api_key = os.environ.get("NVIDIA_API_KEY")
if api_key:
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key
    )

# 選擇值得信賴的 RSS 來源 (這裡以 TechCrunch 為例，也可以換成 Reuters Tech 等)
# ... existing code ...
    # 只取前 5 段避免 Token 過多或超時
    content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20][:5])
    
    return title, link, content_text

def analyze_and_translate_with_llm(title, content):
    """將內容送給 NVIDIA LLM 進行分析與翻譯"""
    prompt = f"""
    你是一個專業、中立的科技新聞編譯。請閱讀以下英文新聞標題與內文。
    新聞標題: {title}
    新聞內文:
    {content}
    
    請幫我完成以下任務，並**嚴格遵守 JSON 格式回傳**（不要包含 ```json 標籤，純粹的 JSON 字串）：
    1. "importance": 評估這則新聞的重要程度 (1到5的整數，5為最重要，例如A1頭條等級)。
    2. "objectivity_analysis": 評估這篇報導的客觀性 (簡短的一句話，例如"報導基於官方財報，無明顯主觀情緒")。
    3. "content": 將原文逐段翻譯成繁體中文。這必須是一個陣列，每個元素包含 "en" (英文原文段落) 和 "zh" (繁體中文翻譯)。
    
    預期回傳格式範例:
    {{
        "importance": 4,
        "objectivity_analysis": "引述官方聲明，客觀性高。",
        "content": [
            {{"en": "Apple announced new chips today.", "zh": "蘋果今日發表了新晶片。"}},
            {{"en": "The performance is 20% faster.", "zh": "效能提升了20%。"}}
        ]
    }}
    """
    
    # 使用相容 OpenAI 的語法呼叫 NVIDIA API，選擇你要的模型
    response = client.chat.completions.create(
        model="meta/llama-3.1-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1024,
    )
    
    # 嘗試解析回傳的 JSON 字串
    try:
        raw_text = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
        result_json = json.loads(raw_text)
        return result_json
    except Exception as e:
        raise Exception(f"LLM 回傳格式解析失敗: {str(e)}。原始回傳: {response.choices[0].message.content}")

@app.route('/api/news', methods=['GET'])
def get_daily_news():
    debug_info = {}
    try:
        # 1. 檢查 API Key
        if not api_key:
            raise Exception("伺服器遺失 NVIDIA_API_KEY 環境變數")
            
        debug_info["step_1"] = "API Key checked"
        
        # 2. 抓取新聞
        title, link, original_content = fetch_and_parse_news()
        debug_info["step_2"] = f"Fetched article: {title}"
        
        # 3. AI 分析與翻譯
        analysis_result = analyze_and_translate_with_llm(title, original_content)
        debug_info["step_3"] = "AI Analysis completed"
        
        # 4. 組合最終資料
# ... existing code ...
