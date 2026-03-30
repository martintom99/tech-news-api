# 請將這段替換掉你原本 api/index.py 裡面的 fetch_and_parse_news 與 get_daily_news 函數

def fetch_and_parse_news():
    """抓取 RSS 並擷取前 5 篇新聞的內文"""
    feed = feedparser.parse(RSS_FEED_URL)
    if not feed.entries:
        raise Exception("無法從 RSS 獲取新聞列表")
    
    articles = []
    # 限制最多抓取 5 篇 (避免 Vercel 超時)
    for top_article in feed.entries[:5]:
        title = top_article.title
        link = top_article.link
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(link, headers=headers, timeout=5)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        paragraphs = soup.find_all('p')
        # 每篇只取前 3 段翻譯，縮短 AI 處理時間
        content_text = "\n\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20][:3])
        
        articles.append({"title": title, "link": link, "content": content_text})
        
    return articles

@app.route('/api/news', methods=['GET'])
def get_daily_news():
    debug_info = {}
    try:
        if not api_key or not client:
            raise Exception("伺服器遺失 NVIDIA_API_KEY")
            
        articles = fetch_and_parse_news()
        final_data = []
        
        # 逐篇交給 AI 分析 (這部分會花點時間，建議維持 5 篇就好)
        for idx, article in enumerate(articles):
            debug_info[f"step_2_{idx}"] = f"Analyzing: {article['title']}"
            try:
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
                continue # 若單篇失敗，跳過繼續下一篇
        
        return jsonify({
            "status": "success",
            "data": final_data, # 這裡變成了一個陣列 [{}, {}, ...]
            "debug": debug_info
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "debug": traceback.format_exc()
        }), 500
