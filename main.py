import os
import base64
import json
import datetime
import httpx
import gspread
import openai
from openai import OpenAI
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")

# LINE 設定
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# FastAPI 應用
app = FastAPI()

# 每日問候紀錄
greeted_users = {}

# 小婕的人設 prompt
SYSTEM_PROMPT = """
你是來自「H.R燈藝」的客服女孩「小婕」，個性活潑熱情又專業，專門回答與機車燈具、安裝方式、改裝精品有關的問題。
請使用繁體中文回答，語氣要像真人客服一樣自然有禮貌，請勿使用簡體字與 emoji。
"""

# 讀取 Google Sheet 並模糊搜尋
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
            row_text = json.dumps(row, ensure_ascii=False)
            if any(keyword in row_text for keyword in user_input.split()):
                result = "｜".join(f"{k}：{v}" for k, v in row.items() if v)
                all_results.append(result)

    if all_results:
        extra = "\n\n有希望什麼時候安裝嗎？可以為您查詢貨況喔！也歡迎多多善用我們的預約系統自行挑選時段預約！"
        return "以下是我從資料庫幫您找到的商品資訊：\n" + "\n\n".join(all_results) + extra
    else:
        return ""

# 呼叫 GPT 回覆文字
def call_openai_chat(user_input: str, image_context: str = None) -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)
    today = str(datetime.date.today())
    if greeted_users.get(today) is None:
        greeted_users.clear()
        greeted_users[today] = set()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if user_input not in greeted_users[today]:
        messages.append({"role": "assistant", "content": "您好～這裡是 H.R燈藝，我是小婕！很高興為您服務！"})
        greeted_users[today].add(user_input)

    context = search_google_sheet(user_input)
    if context:
        messages.append({"role": "system", "content": f"以下是查詢結果：\n{context}"})
    if image_context:
        messages.append({"role": "user", "content": f"這是圖片內容分析：{image_context}"})
    messages.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(model="gpt-4o", messages=messages)
    return response.choices[0].message.content.strip()

# 圖片辨識
def call_openai_image(image_bytes: bytes) -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)
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

# 快取圖片用戶資訊
message_cache = {}

# LINE webhook 接收
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
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
    user_input = event.message.text
    if user_id in message_cache:
        image_context = message_cache.pop(user_id)
        reply = call_openai_chat(user_input, image_context)
    else:
        reply = call_openai_chat(user_input)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 處理圖片訊息
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    image_context = call_openai_image(image_data)
    user_id = event.source.user_id
    message_cache[user_id] = image_context
