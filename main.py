import os
import base64
import json
import datetime
import httpx
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
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
app = FastAPI()

# === 啟動歡迎語控制 ===
greeted_users = {}

# === 小婕的人格設定 ===
SYSTEM_PROMPT = """
你是來自「H.R燈藝」的客服女孩「小婕」，個性活潑熱情又專業，專門回答與機車燈具、安裝方式、改裝精品有關的問題。
請使用繁體中文回答，語氣要自然親切，像真人客服一樣，請勿使用簡體字與 emoji。
回答中不用每次重複店家地址、電話與營業時間，除非使用者特別詢問。
請記得用詞統一為「車種」。
若資料庫中有找到明確價格資訊，請直接清楚列出。
若商品有多種版本，請列出選項；若只有單一款，請明確說明。
價格回覆後請加上：「有希望什麼時候安裝嗎？可以為您查詢貨況喔！」以及「也歡迎多多善用我們的預約系統自行挑選時段預約！」。
"""

# === 查詢 Google Sheet 關鍵字（模糊比對） ===
def search_google_sheet(user_input: str) -> str:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs")

    matched_rows = []
    for worksheet in sheet.worksheets():
        records = worksheet.get_all_records()
        for row in records:
            for value in row.values():
                if user_input.lower() in str(value).lower():
                    matched_rows.append(row)
                    break

    if not matched_rows:
        return ""

    if len(matched_rows) == 1:
        row = matched_rows[0]
        return f"商品名稱：{row.get('品名', '未提供')}\n價格：{row.get('售價', '未提供')} 元"
    else:
        options = []
        for row in matched_rows:
            name = row.get("品名", "未提供")
            price = row.get("售價", "未提供")
            options.append(f"{name}：{price} 元")
        return "我們有以下幾個版本可以參考喔：\n" + "\n".join(options)

# === 呼叫 GPT 回覆（整合上下文與知識庫） ===
def call_openai_chat(user_input: str, image_context: str = None) -> str:
    openai.api_key = OPENAI_API_KEY
    today = str(datetime.date.today())

    if today not in greeted_users:
        greeted_users.clear()
        greeted_users[today] = set()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if user_input not in greeted_users[today]:
        messages.append({"role": "assistant", "content": "您好，我是 H.R 燈藝的小婕，很高興為您服務。請問今天有什麼我可以幫忙的嗎？"})
        greeted_users[today].add(user_input)

    context = search_google_sheet(user_input)
    if context:
        messages.append({"role": "system", "content": f"以下是商品資料查詢結果：\n{context}"})
        messages.append({"role": "system", "content": "請記得回覆時簡潔清楚地告知價格，並補上詢問安裝與預約提醒語句。"})

    if image_context:
        messages.append({"role": "user", "content": f"這是圖片內容分析：{image_context}"})

    messages.append({"role": "user", "content": user_input})

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=messages
    )
    return response.choices[0].message["content"]

# === 處理圖片辨識 ===
def call_openai_image(image_bytes: bytes) -> str:
    openai.api_key = OPENAI_API_KEY
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "請幫我看看這張圖片的內容，並根據圖片給我建議或說明"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
    )
    return response.choices[0].message["content"]

# === LINE Webhook ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === 訊息緩衝區：圖片與文字整合用 ===
message_cache = {}

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    user_input = event.message.text
    if user_id in message_cache:
        image_context = message_cache.pop(user_id)
        reply = call_openai_chat(user_input, image_context)
    else:
        reply = call_openai_chat(user_input)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    image_context = call_openai_image(image_data)
    user_id = event.source.user_id
    message_cache[user_id] = image_context
