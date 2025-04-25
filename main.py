import os
import base64
import json
import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage,
    TextSendMessage
)

# === 環境變數 ===
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")  # JSON 字串

# === LINE 設定 ===
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# === FastAPI App ===
app = FastAPI()

# === 小婕客服語氣 ===
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小婕，專門幫客人解答與機車燈具、安裝教學、改裝精品有關的問題。
請用「活潑熱情又專業的女生」語氣說話，回覆使用繁體中文，禁止出現簡體字與 emoji。禁止說自己是 AI。

以下是店家資訊：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四公休，週日18:00提早打烊）
電話：03 433 3088
"""

# === 控制每日打招呼只出現一次 ===
greeted_users = {}

# === Webhook ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === Google Sheet 查詢邏輯 ===
def search_google_sheet(user_input: str) -> str:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1J5PUZZLjCJ2R4rYCTc-MX7LEjwuL5eunswYsf7Xce74")

    results = []
    for ws in sheet.worksheets():
        records = ws.get_all_records()
        for row in records:
            if any(user_input in str(v) for v in row.values()):
                result = "｜".join(f"{k}：{v}" for k, v in row.items())
                results.append(result)
    return "\n\n".join(results)

# === 呼叫 GPT 處理訊息（整合圖片與文字） ===
def call_openai_combined(user_input: str, image_bytes: bytes = None) -> str:
    openai.api_key = OPENAI_API_KEY
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # 加入 Google Sheet 查詢結果
    sheet_info = search_google_sheet(user_input)
    if sheet_info:
        messages.append({"role": "system", "content": f"以下是從內部知識庫查到的資料：{sheet_info}"})

    # 加入使用者訊息內容
    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_input or "請幫我看看這張圖片的內容"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        })
    else:
        messages.append({"role": "user", "content": user_input})

    response = openai.ChatCompletion.create(model="gpt-4o", messages=messages)
    return response.choices[0].message["content"]

# === 處理文字訊息 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    uid = event.source.user_id
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    need_greet = greeted_users.get(uid) != today
    greeted_users[uid] = today

    reply = call_openai_combined(event.message.text)
    if need_greet:
        reply = f"哈囉！我是小婕～今天有什麼需要幫忙的嗎？\n\n{reply}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# === 處理圖片訊息 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    reply = call_openai_combined("這是我收到的圖片，請幫我判斷", image_bytes=image_data)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )
