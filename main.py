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
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

# === 環境變數 ===
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")

# === LINE 設定 ===
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# === FastAPI App ===
app = FastAPI()

# === 每日問候紀錄 ===
greeted_users = {}

# === 小婕的系統設定 ===
SYSTEM_PROMPT = """
你是來自「H.R燈藝」的客服女孩「小婕」，個性活潑熱情又專業，專門回答與機車燈具、安裝方式、改裝精品有關的問題。
請使用繁體中文回答，語氣要像真人客服一樣自然有禮貌，請勿使用簡體字與 emoji。請將「哪一款機車」統一說法為「哪一款車種」。

請注意：如果 Google Sheet 中有對應的尾燈商品價格，就要直接明確回覆，不要模糊帶過；若商品有多版本，請列出選項；若只有一個版本就直接說明，並且在提供資訊後加上這句提醒：
「有希望什麼時候安裝嗎？可以為您查詢貨況喔！也歡迎多多善用我們的預約系統自行挑選時段預約！」
"""

# === 查詢 Google Sheet 內容 ===
def search_google_sheet(user_input: str) -> str:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs")
    all_results = []
    for worksheet in sheet.worksheets():
        records = worksheet.get_all_records()
        for row in records:
            if any(user_input in str(value) for value in row.values()):
                info = "｜".join(f"{k}：{v}" for k, v in row.items())
                all_results.append(info)
    if all_results:
        result_text = "以下是我從知識庫幫您找到的資料：\n" + "\n\n".join(all_results)
        if len(all_results) == 1:
            result_text += "\n\n有希望什麼時候安裝嗎？可以為您查詢貨況喔！也歡迎多多善用我們的預約系統自行挑選時段預約！"
        return result_text
    else:
        return ""

# === 呼叫 OpenAI Chat ===
def call_openai_chat(user_input: str, image_context: str = None) -> str:
    openai.api_key = OPENAI_API_KEY
    context = search_google_sheet(user_input)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    today = str(datetime.date.today())
    if greeted_users.get(today) is None:
        greeted_users.clear()
        greeted_users[today] = set()
    if user_input not in greeted_users[today]:
        messages.append({"role": "assistant", "content": "您好～這裡是 H.R燈藝，我是小婕！很高興為您服務！"})
        greeted_users[today].add(user_input)
    if context:
        messages.append({"role": "system", "content": f"以下是知識庫內容：\n{context}"})
    if image_context:
        messages.append({"role": "user", "content": f"這是圖片內容分析：{image_context}"})
    messages.append({"role": "user", "content": user_input})
    response = openai.chat.completions.create(model="gpt-4o", messages=messages)
    return response.choices[0].message.content.strip()

# === 處理圖片內容 ===
def call_openai_image(image_bytes: bytes) -> str:
    openai.api_key = OPENAI_API_KEY
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    response = openai.chat.completions.create(
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
    return response.choices[0].message.content.strip()

# === FastAPI Webhook ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === 訊息緩衝區（圖片 + 文字一起理解）===
message_cache = {}

# === 處理文字訊息 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    user_input = event.message.text
    try:
        if user_id in message_cache:
            image_context = message_cache.pop(user_id)
            reply = call_openai_chat(user_input, image_context)
        else:
            reply = call_openai_chat(user_input)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except LineBotApiError as e:
        print(f"LineBotApiError: {e}")

# === 處理圖片訊息 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b''.join(chunk for chunk in message_content.iter_content())
        image_context = call_openai_image(image_data)
        user_id = event.source.user_id
        message_cache[user_id] = image_context
    except LineBotApiError as e:
        print(f"LineBotApiError (image): {e}")
