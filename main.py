import os
import base64
import httpx
import openai
import json
import gspread
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from oauth2client.service_account import ServiceAccountCredentials

# === 環境變數 ===
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")  # JSON 格式

# === LINE 設定 ===
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# === FastAPI App ===
app = FastAPI()

# === 記錄每天是否已打招呼 ===
greeted_users = {}

# === System Prompt ===
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小婕，專門幫客人解答與機車燈具、安裝教學、改裝精品有關的問題。
請用「活潑熱情又專業的女生」口吻說話，回覆使用繁體中文，請勿出現簡體字或 emoji。
若客人有附上圖片與文字，請結合兩者內容整合回應。

【店家資訊】
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四公休，週日18:00提早打烊）
連絡電話：03 433 3088
"""

# === Google Sheet 查詢 ===
def search_google_sheet(user_input: str) -> str:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1_UcrJvkiX8z4qVKZ9cDqxmOAXzggS5Gl")

    all_results = []
    for worksheet in sheet.worksheets():
        records = worksheet.get_all_records()
        for row in records:
            if any(user_input in str(value) for value in row.values()):
                info = "｜".join(f"{k}：{v}" for k, v in row.items())
                all_results.append(info)

    if all_results:
        return "以下是我從資料庫找到的內容：\n" + "\n\n".join(all_results)
    else:
        return ""

# === 判斷是否要打招呼 ===
def get_greeting(user_id: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    if greeted_users.get(user_id) != today:
        greeted_users[user_id] = today
        return "哈囉～這裡是 H.R燈藝，我是小婕！有什麼需要幫忙的嗎？\n\n"
    return ""

# === 回應：文字 或 圖片＋文字整合 ===
def call_openai_combined(prompt_text: str, image_bytes: bytes = None) -> str:
    openai.api_key = OPENAI_API_KEY
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    sheet_data = search_google_sheet(prompt_text)
    if sheet_data:
        messages.append({"role": "system", "content": f"以下是知識庫內容：{sheet_data}"})

    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        })
    else:
        messages.append({"role": "user", "content": prompt_text})

    response = openai.ChatCompletion.create(model="gpt-4o", messages=messages)
    return response.choices[0].message["content"]

# === Webhook 接收 ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === 文字訊息處理 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    greeting = get_greeting(event.source.user_id)
    reply = call_openai_combined(event.message.text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=greeting + reply))

# === 圖片訊息處理 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    greeting = get_greeting(event.source.user_id)
    reply = call_openai_combined("請幫我看看這張圖片的內容，並根據圖片給我建議或說明", image_data)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=greeting + reply))
