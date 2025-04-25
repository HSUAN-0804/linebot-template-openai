import os
import base64
import openai
import json
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage,
    TextSendMessage
)

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")

# FastAPI 與 LINE 初始化
app = FastAPI()
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 小潔語氣設定
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小潔，專門幫客人解答與機車燈具、安裝教學、改裝精品有關的問題。
請用「活潑熱情又專業的女生」口吻說話，回覆使用繁體中文，請勿出現簡體字與 emoji。
店家資訊如下：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四公休，週日18:00提早打烊）
連絡電話：03 433 3088
"""

# 記錄使用者今日是否已打招呼
greeted_users = {}

# 自動讀取整份 Sheet 所有工作表進行查詢
def search_google_sheet(user_input: str) -> str:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1_UcrJvkiX8z4qVKZ9cDqxmOAXzggS5Gl")

    results = []
    for worksheet in sheet.worksheets():
        try:
            records = worksheet.get_all_records()
            for row in records:
                if any(user_input.lower() in str(value).lower() for value in row.values()):
                    result = "｜".join(f"{k}：{v}" for k, v in row.items())
                    results.append(result)
        except Exception:
            continue

    if results:
        return "以下是我從內部資料查到的資訊：\n" + "\n\n".join(results)
    else:
        return ""

# OpenAI 處理圖片 + 文字 + Sheet 整合
def call_openai_combined(user_id: str, user_text: str = "", image_bytes: bytes = None) -> str:
    openai.api_key = OPENAI_API_KEY
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 判斷是否需要打招呼
    today = datetime.now().strftime("%Y-%m-%d")
    if greeted_users.get(user_id) != today:
        messages.append({"role": "user", "content": "請記得對今天第一次傳訊息的客人打招呼～"})
        greeted_users[user_id] = today

    # 整合 Google Sheet 查詢結果
    sheet_result = search_google_sheet(user_text or "")
    if sheet_result:
        messages.append({"role": "system", "content": f"以下是產品資料庫內容：{sheet_result}"})

    # 加入使用者輸入
    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_text or "請幫我看看這張圖片"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        })
    elif user_text:
        messages.append({"role": "user", "content": user_text})

    # 呼叫 GPT-4o
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=messages
    )
    return response.choices[0].message["content"]

# LINE Webhook
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    user_text = event.message.text
    reply = call_openai_combined(user_id, user_text=user_text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 處理圖片訊息
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    reply = call_openai_combined(user_id, image_bytes=image_data)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
