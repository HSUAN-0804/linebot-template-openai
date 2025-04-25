import os
import json
import base64
import openai
import gspread
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from google.oauth2.service_account import Credentials
from datetime import datetime

app = Flask(__name__)

# LINE 設定
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# OpenAI 設定
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Google Sheets 認證與連線
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds_dict = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY"))
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
gc = gspread.authorize(creds)

# Google Sheet ID
SHEET_ID = "16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs"

# 打招呼紀錄
greeted_users = {}

# 快取圖片訊息
image_cache = {}

def search_sheet(keyword):
    try:
        sh = gc.open_by_key(SHEET_ID)
        results = []

        for worksheet in sh.worksheets():
            records = worksheet.get_all_records()
            for row in records:
                name = str(row.get("品名", "")).strip()
                keyword_list = str(row.get("關鍵字", "")).strip().split("、")
                keywords = [name] + keyword_list

                if any(k.lower() in keyword.lower() or keyword.lower() in k.lower() for k in keywords):
                    results.append(row)

        return results
    except Exception as e:
        print(f"Google Sheet 查詢錯誤: {e}")
        return []

def format_product_info(product):
    name = product.get("品名", "")
    price = product.get("價格", "")
    return f"我們有販售「{name}」，售價是 {price} 元喔！有希望什麼時候安裝嗎？可以為您查詢貨況喔！也歡迎多多善用我們的預約系統自行挑選時段預約！"

def ask_for_details():
    return "想請問您是哪一款車種想要詢問尾燈呢？這樣我才能更準確地幫您確認喔！"

def analyze_image(image_bytes):
    try:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "請你專業地分析機車相關圖片，並提供建議，不要用簡體字。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "請幫我看看這張圖片內容，並提供建議。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"圖片辨識失敗: {e}")
        return ""

def handle_combined_message(user_input, user_id):
    today = datetime.now().date()
    greeting = ""

    if greeted_users.get(user_id) != today:
        greeted_users[user_id] = today
        greeting = "您好！這裡是 H.R 燈藝的客服小婕～"

    matched_products = search_sheet(user_input)

    if len(matched_products) == 1:
        product = matched_products[0]
        response = format_product_info(product)
    elif len(matched_products) > 1:
        names = [f"・{p.get('品名')}" for p in matched_products]
        response = "有以下幾個選擇唷：\n" + "\n".join(names) + "\n請問您是要詢問哪一個呢？"
    else:
        response = ask_for_details()

    return f"{greeting} {response}".strip()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    try:
        text = event.message.text
        user_id = event.source.user_id

        if user_id in image_cache:
            image_context = image_cache.pop(user_id)
            combined_prompt = f"圖片內容說明：{image_context}\n\n用戶詢問：{text}"
            reply = handle_combined_message(combined_prompt, user_id)
        else:
            reply = handle_combined_message(text, user_id)

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except LineBotApiError as e:
        print("LineBotApiError:", e)

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b''.join(chunk for chunk in message_content.iter_content())
        image_context = analyze_image(image_data)
        user_id = event.source.user_id
        image_cache[user_id] = image_context
    except LineBotApiError as e:
        print("LineBotApiError:", e)

if __name__ == "__main__":
    app.run()
