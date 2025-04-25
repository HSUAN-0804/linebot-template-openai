import os
import json
import openai
import requests
import re
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import datetime
import pytz
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# 環境變數設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")
SHEET_URL = "https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs/"
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 建立 Google Sheet 客戶端
def get_sheet():
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_url(SHEET_URL)
    return sh.sheet1

# 取得台灣時區的現在時間字串
def get_today_key():
    now = datetime.datetime.now(pytz.timezone("Asia/Taipei"))
    return now.strftime("%Y-%m-%d")

# 上下文記憶（每日）
recent_users = {}

# 模糊比對商品資料
def find_product(sheet, user_input):
    data = sheet.get_all_records()
    matches = []
    input_lower = user_input.lower()

    for row in data:
        full_name = str(row.get("商品名稱", "")).lower()
        keyword = str(row.get("關鍵字", "")).lower()

        if input_lower in full_name or input_lower in keyword:
            matches.append(row)

    return matches

# 傳送訊息封裝（避免 token 過期錯誤）
def safe_reply(reply_token, messages):
    try:
        line_bot_api.reply_message(reply_token, messages)
    except LineBotApiError as e:
        print(f"LineBotApiError: {e}")

# 將文字或圖片送給 GPT-4o
def ask_gpt(prompt_messages):
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=prompt_messages,
        temperature=0.5
    )
    return response.choices[0].message.content

# 接收 LINE Webhook
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

# 文字與圖片訊息處理
@handler.add(MessageEvent, message=(TextMessage, ImageMessage))
def handle_message(event):
    user_id = event.source.user_id
    message_type = event.message.type
    today_key = get_today_key()
    show_greeting = recent_users.get(user_id) != today_key
    recent_users[user_id] = today_key

    sheet = get_sheet()
    prompt_messages = []

    if show_greeting:
        greeting = "你好！我是 H.R 燈藝的客服小婕～很高興為您服務！請問有什麼需要幫忙的呢？"
    else:
        greeting = ""

    if message_type == "text":
        user_text = event.message.text.strip()
        found = find_product(sheet, user_text)

        if found and len(found) == 1:
            item = found[0]
            name = item["商品名稱"]
            price = item["售價"]
            response_text = f"我們有販售「{name}」，售價是 {price} 元唷！有希望什麼時候安裝嗎？可以為您查詢貨況喔！也歡迎多多善用我們的預約系統自行挑選時段預約！"
        elif found and len(found) > 1:
            options = "\n".join([f"- {item['商品名稱']}" for item in found])
            response_text = f"我們有多款符合您的描述，請問您想詢問的是哪一個呢？\n{options}"
        else:
            system_prompt = {
                "role": "system",
                "content": (
                    "你是活潑熱情又專業的女生客服，來自 H.R 燈藝機車精品改裝店，專營機車燈具、改裝品安裝等。"
                    "請根據客戶問題，用親切自然的語氣回覆，如需進一步資訊可以提醒客戶提供車種或型號。"
                )
            }
            prompt_messages = [system_prompt, {"role": "user", "content": user_text}]
            response_text = ask_gpt(prompt_messages)

        full_reply = f"{greeting}\n{response_text}" if greeting else response_text
        safe_reply(event.reply_token, TextSendMessage(text=full_reply))

    elif message_type == "image":
        image_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = image_content.content
        base64_image = f"data:image/jpeg;base64,{image_bytes.encode('base64') if hasattr(image_bytes, 'encode') else image_bytes.decode('utf-8')}"

        prompt_messages = [
            {"role": "system", "content": "你是 H.R 燈藝的客服小婕，請協助判斷圖片內容並提供機車改裝建議，語氣要親切活潑。"},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": base64_image}}]}
        ]

        response_text = ask_gpt(prompt_messages)
        final_reply = f"{greeting}\n{response_text}" if greeting else response_text
        safe_reply(event.reply_token, TextSendMessage(text=final_reply))

if __name__ == "__main__":
    app.run()
