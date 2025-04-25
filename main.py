import os
import json
import base64
import datetime
import openai
import gspread
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
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT")

# === LINE 設定 ===
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# === FastAPI App ===
app = FastAPI()

# === 啟用每日問候功能 ===
greeted_users = {}

# === 小婕語氣設定 ===
SYSTEM_PROMPT = """
你是來自「H.R燈藝」的客服女孩「小婕」，個性活潑熱情又專業，專門回答與機車燈具、安裝方式、改裝精品有關的問題。
請使用繁體中文回答，語氣要像真人客服一樣自然有禮貌，請勿使用簡體字與 emoji。

店家資訊如下：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四公休，週日18:00提早打烊）
連絡電話：03 433 3088
"""

# === Google Sheet 查詢 ===
def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_url("https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs")

def search_google_sheet(user_input: str) -> str:
    sheet = get_sheet()
    results = []
    for ws in sheet.worksheets():
        records = ws.get_all_records()
        for row in records:
            if any(user_input in str(v) for v in row.values()):
                info = "｜".join(f"{k}：{v}" for k, v in row.items() if v)
                results.append(info)
    return "\n\n".join(results) if results else ""

# === 呼叫 OpenAI Chat ===
def call_openai_chat(user_input: str, image_context: str = None) -> str:
    openai.api_key = OPENAI_API_KEY
    today = datetime.date.today().isoformat()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if greeted_users.get(today) is None:
        greeted_users.clear()
        greeted_users[today] = set()
    if user_input not in greeted_users[today]:
        messages.append({"role": "assistant", "content": "您好～這裡是 H.R燈藝，我是小婕！很高興為您服務！"})
        greeted_users[today].add(user_input)

    context = search_google_sheet(user_input)
    if context:
        messages.append({"role": "system", "content": f"以下是知識庫中找到的資料：\n{context}"})
    if image_context:
        messages.append({"role": "user", "content": f"這是圖片內容分析：{image_context}"})
    messages.append({"role": "user", "content": user_input})

    response = openai.ChatCompletion.create(model="gpt-4o", messages=messages)
    reply = response.choices[0].message["content"]

    # 若為商品資訊回覆，加上提問安裝提醒
    if context:
        reply += "\n\n有希望什麼時候安裝嗎？可以為您查詢貨況喔！\n也歡迎多多善用我們的預約系統自行挑選時段預約！"
    return reply

# === 處理圖片內容 ===
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

# === 處理 LINE Webhook ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === 圖片 + 文字整合處理 ===
message_cache = {}

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

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    image_context = call_openai_image(image_data)
    user_id = event.source.user_id
    message_cache[user_id] = image_context
