import os
import base64
import json
import datetime
import httpx
import openai
import gspread
from difflib import SequenceMatcher
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

# === 環境變數 ===
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
app = FastAPI()

# === 系統提示語設定 ===
SYSTEM_PROMPT = """
你是 H.R燈藝 的客服女孩「小婕」，個性活潑熱情又專業，專門回答與機車燈具、安裝方式、改裝精品有關的問題。
請使用繁體中文回答，語氣要像真人客服一樣自然親切，請勿使用簡體字與 emoji。
回答時不需要重複店家地址、電話與營業時間等資訊，除非客人主動詢問。
"""

# === 每日招呼紀錄 ===
greeted_users = {}

# === 文字與圖片訊息暫存區 ===
message_cache = {}

# === Google Sheet 查詢（模糊比對）===
def search_google_sheet(user_input: str) -> str:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs")

    best_matches = []
    for worksheet in sheet.worksheets():
        records = worksheet.get_all_records()
        for row in records:
            for value in row.values():
                ratio = SequenceMatcher(None, user_input, str(value)).ratio()
                if ratio > 0.6 or user_input in str(value):
                    best_matches.append(row)
                    break

    if not best_matches:
        return ""

    products = {}
    for row in best_matches:
        name = row.get("商品名稱", "")
        price = row.get("售價", "")
        if name and price:
            products.setdefault(name, set()).add(str(price))

    if not products:
        return ""

    if len(products) == 1:
        name, prices = next(iter(products.items()))
        price_str = "、".join(prices)
        return f"我們有販售「{name}」，售價是 {price_str} 元喔！有希望什麼時候安裝嗎？可以為您查詢貨況喔！也歡迎多多善用我們的預約系統自行挑選時段預約！"

    response = "我們有以下幾款相關商品可供選擇：\n"
    for name, prices in products.items():
        price_str = "、".join(prices)
        response += f"- {name}：{price_str} 元\n"
    response += "\n請問您有想特別了解哪一款嗎？我可以幫您提供建議！"
    return response

# === 呼叫 GPT 聊天（含圖片） ===
def call_openai_chat(user_input: str, image_context: str = None) -> str:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    today = str(datetime.date.today())
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if greeted_users.get(today) is None:
        greeted_users.clear()
        greeted_users[today] = set()

    if user_input not in greeted_users[today]:
        messages.append({"role": "assistant", "content": "您好～這裡是 H.R燈藝，我是小婕！很高興為您服務！"})
        greeted_users[today].add(user_input)

    sheet_info = search_google_sheet(user_input)
    if sheet_info:
        messages.append({"role": "assistant", "content": sheet_info})
        return sheet_info

    if image_context:
        messages.append({"role": "user", "content": f"這是圖片內容分析：{image_context}"})
    messages.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    return response.choices[0].message.content.strip()

# === 處理圖片內容 ===
def call_openai_image(image_bytes: bytes) -> str:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    response = client.chat.completions.create(
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

# === FastAPI 接收 LINE 訊息 ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === 處理文字訊息 ===
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

# === 處理圖片訊息 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    image_context = call_openai_image(image_data)
    user_id = event.source.user_id
    message_cache[user_id] = image_context
