import os
import json
import pytz
import datetime
import io
import base64
import openai
import requests
import gspread
from PIL import Image
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)
openai.api_key = os.environ.get("OPENAI_API_KEY")
line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))

# Google Sheet 授權
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# 讀取工作表
sheet_url = "https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs"
spreadsheet = client.open_by_url(sheet_url)

# 上下文記憶與每日打招呼狀態
user_context = {}
daily_greeted = {}

@app.route("/", methods=["GET"])
def home():
    return "H.R 燈藝機器人小婕運作中！"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=(TextMessage, ImageMessage))
def handle_message(event):
    user_id = event.source.user_id
    message_text = ""
    image_content = None

    if isinstance(event.message, TextMessage):
        message_text = event.message.text.strip()
    elif isinstance(event.message, ImageMessage):
        image_data = line_bot_api.get_message_content(event.message.id).content
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        image_content = base64.b64encode(buffered.getvalue()).decode("utf-8")

    now = datetime.datetime.now(pytz.timezone("Asia/Taipei"))
    today_key = f"{user_id}_{now.date()}"
    show_greeting = today_key not in daily_greeted
    daily_greeted[today_key] = True

    prompt = build_prompt(user_id, message_text, image_content, show_greeting)
    response = ask_gpt(prompt)
    user_context[user_id] = message_text

    try:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))
    except:
        pass

def build_prompt(user_id, message_text, image_content, show_greeting):
    intro = "你是 H.R 燈藝的 LINE 客服機器人「小婕」，擁有親切又活潑的女生語氣，專門協助機車燈具與改裝精品的諮詢。請用繁體中文回答。"

    context = user_context.get(user_id, "")
    greeting = "哈囉！我是 H.R 燈藝的客服小婕～很高興為您服務！\n" if show_greeting else ""

    content_blocks = []
    if context:
        content_blocks.append(f"前一句對話是：「{context}」")
    if message_text:
        content_blocks.append(f"客戶說：「{message_text}」")
    if image_content:
        content_blocks.append("以下是客戶傳來的圖片，請根據圖片與對話內容一併判斷：")
        content_blocks.append({"image": {"image_base64": image_content, "detail": "high"}})

    sheet_data = extract_sheet_data(message_text)
    if sheet_data:
        content_blocks.append(sheet_data)

    final_prompt = {
        "role": "system",
        "content": intro
    }, {
        "role": "user",
        "content": [greeting] + content_blocks
    }

    return final_prompt

def extract_sheet_data(query):
    for sheet in spreadsheet.worksheets():
        records = sheet.get_all_records()
        for row in records:
            name = row.get("商品名稱", "")
            keyword = row.get("關鍵字", "")
            if query in name or query in keyword:
                if row.get("售價"):
                    price = row["售價"]
                    return f"查到商品「{name}」，售價是 {price} 元。\n有希望什麼時候安裝嗎？可以為您查詢貨況喔！\n也歡迎多多善用我們的預約系統自行挑選時段預約！"
    return ""

def ask_gpt(messages):
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=list(messages),
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
