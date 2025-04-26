import os
import json
import openai
import gspread
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz

app = Flask(__name__)

# === 環境變數設定 ===
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
openai.api_key = os.getenv("OPENAI_API_KEY")

# === Google Sheets 設定 ===
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")
SERVICE_ACCOUNT_INFO = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
SCOPES = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(creds)
SHEET_URL = "https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs"
spreadsheet = gc.open_by_url(SHEET_URL)

# === 小婕每日招呼語記憶 ===
greeting_memory = {}

def has_greeted_today(user_id):
    today = datetime.now(pytz.timezone('Asia/Taipei')).date()
    return greeting_memory.get(user_id) == today

def mark_greeted(user_id):
    today = datetime.now(pytz.timezone('Asia/Taipei')).date()
    greeting_memory[user_id] = today

# === 查詢 Google Sheets ===
def search_google_sheets(query):
    results = []
    for sheet in spreadsheet.worksheets():
        try:
            records = sheet.get_all_records()
            for row in records:
                if any(query in str(value) for value in row.values()):
                    results.append(row)
        except Exception:
            continue
    return results

# === 呼叫 OpenAI 文字聊天（可搭配圖片）===
def ask_gpt(user_message, image_url=None):
    client = openai.OpenAI()
    messages = [
        {
            "role": "system",
            "content": "你是來自 H.R燈藝機車精品改裝店的客服小婕，個性活潑熱情又專業，請使用繁體中文回答，且不要使用簡體字或emoji。"
        }
    ]
    if image_url:
        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": user_message}
            ]
        })
    else:
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": user_message}]
        })
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    return response.choices[0].message.content

# === FastAPI Callback ===
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# === 文字訊息處理 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    sheet_results = search_google_sheets(user_message)

    if sheet_results:
        if len(sheet_results) == 1:
            item = sheet_results[0]
            name = item.get("商品名稱", "未命名")
            price = item.get("售價", "未定價")
            msg = f"我們有販售「{name}」，售價是 {price} 元喔！\n有希望什麼時候安裝嗎？可以幫您查詢貨況喔！\n也歡迎多多善用我們的預約系統自行挑選時段預約！"
        else:
            names = [item.get("商品名稱", "未命名") for item in sheet_results]
            msg = "我們有以下幾個相關商品可以參考：\n" + "\n".join(f"- {n}" for n in names)
    else:
        msg = ask_gpt(user_message)

    if not has_greeted_today(user_id):
        msg = f"哈囉您好～這裡是 H.R燈藝，小婕為您服務！\n{msg}"
        mark_greeted(user_id)

    try:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
    except:
        pass

# === 圖片訊息處理 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    image_content = line_bot_api.get_message_content(event.message.id)
    image_path = f"/tmp/{event.message.id}.jpg"
    with open(image_path, 'wb') as f:
        for chunk in image_content.iter_content():
            f.write(chunk)

    image_url = upload_to_imgbb(image_path)
    if not image_url:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片上傳失敗，請稍後再試喔！"))
        return

    reply = ask_gpt("請幫我分析這張圖片的內容並提供建議", image_url=image_url)
    try:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except:
        pass

# === 上傳圖片到 ImgBB ===
def upload_to_imgbb(image_path):
    api_key = os.getenv("IMGBB_API_KEY")
    with open(image_path, "rb") as file:
        response = requests.post(
            "https://api.imgbb.com/1/upload",
            params={"key": api_key},
            files={"image": file}
        )
    if response.status_code == 200:
        return response.json()['data']['url']
    return None

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
