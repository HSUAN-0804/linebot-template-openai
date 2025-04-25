import os
import json
import openai
import requests
import gspread
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# LINE 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# OpenAI 設定（新版）
openai_api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=openai_api_key)

# Google Sheets 設定
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client_gs = gspread.authorize(creds)

# 你的 Google Sheet 連結
SHEET_URL = "https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs"
sheet = client_gs.open_by_url(SHEET_URL)

@app.route("/")
def home():
    return "LINE Bot is running."

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

def search_google_sheet(keyword):
    matched_rows = []
    for worksheet in sheet.worksheets():
        try:
            records = worksheet.get_all_records()
            for row in records:
                for value in row.values():
                    if isinstance(value, str) and keyword.lower() in value.lower():
                        matched_rows.append(row)
                        break
        except Exception as e:
            continue
    return matched_rows

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_input = event.message.text.strip()
    reply_token = event.reply_token

    if not user_input:
        return

    try:
        # 查詢 Google Sheet
        sheet_result = search_google_sheet(user_input)
        if sheet_result:
            if len(sheet_result) == 1:
                row = sheet_result[0]
                response = f"{row.get('商品名稱', '查無名稱')}，售價 {row.get('價格', '未知')} 元。有希望什麼時候安裝嗎？可以為您查詢貨況喔！也歡迎多多善用我們的預約系統自行挑選時段預約！"
            else:
                names = [r.get('商品名稱', '') for r in sheet_result]
                response = f"我們有以下幾款：\n" + "\n".join(names) + "\n請問您想詢問哪一款呢？"
        else:
            response = call_gpt(user_input)

        line_bot_api.reply_message(reply_token, TextSendMessage(text=response))

    except LineBotApiError:
        # reply token 已過期，忽略
        pass

@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    reply_token = event.reply_token

    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b"".join(chunk for chunk in message_content.iter_content())

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "你是H.R燈藝的客服小婕，專業活潑地協助用戶解答問題。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_bytes.decode("latin1")}},
                        {"type": "text", "text": "請幫我分析這張機車的圖片，看看適合推薦什麼尾燈產品。"}
                    ]
                },
            ],
        )
        msg = response.choices[0].message.content.strip()
        line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))

    except LineBotApiError:
        # reply token 過期
        pass

def call_gpt(prompt):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "你是H.R燈藝的客服小婕，專業、親切、活潑，會用繁體中文回答問題。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip()

if __name__ == "__main__":
    app.run()
