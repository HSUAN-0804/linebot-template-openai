import os
import json
import base64
import datetime
import httpx
import gspread
from dotenv import load_dotenv
from openai import OpenAI
from oauth2client.service_account import ServiceAccountCredentials
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

load_dotenv()
app = FastAPI()

# === 設定 ===
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
greeted_users = {}

SYSTEM_PROMPT = """
你是來自「H.R燈藝」的客服女孩「小婕」，個性活潑熱情又專業，專門回答與機車燈具、安裝方式、改裝精品有關的問題。
請使用繁體中文回答，語氣要像真人客服一樣自然有禮貌又活潑，請勿使用簡體字與 emoji。
請避免每句都重複營業資訊，詢問客人是哪一款車種即可。
"""

# === Google Sheet 模糊查詢 ===
def search_google_sheet(user_input: str) -> list:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY"))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs")
    
    results = []
    for ws in sheet.worksheets():
        records = ws.get_all_records()
        for row in records:
            row_text = "｜".join(str(v) for v in row.values())
            if any(keyword.lower() in row_text.lower() for keyword in user_input.split()):
                results.append(row)
    return results

# === Chat 生成 ===
def call_openai_chat(user_input: str, image_context: str = None) -> str:
    today = str(datetime.date.today())
    if greeted_users.get(today) is None:
        greeted_users.clear()
        greeted_users[today] = set()
    is_first_message = user_input not in greeted_users[today]
    greeted_users[today].add(user_input)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if is_first_message:
        messages.append({"role": "assistant", "content": "您好～這裡是 H.R燈藝，我是小婕！請問今天有什麼我可以幫忙的嗎？"})

    # 查詢商品
    search_results = search_google_sheet(user_input)
    if search_results:
        if len(search_results) == 1:
            row = search_results[0]
            product = row.get("商品名稱", "")
            price = row.get("售價", "")
            car = row.get("適用車種", "")
            reply = f"這款「{product}」適用於 {car}，售價是 {price} 元唷！"
            reply += "\n\n有希望什麼時候安裝嗎？可以為您查詢貨況喔！也歡迎多多善用我們的預約系統自行挑選時段預約！"
            return reply
        else:
            options = "\n".join([f"- {row.get('商品名稱', '')}：{row.get('售價', '')} 元" for row in search_results])
            messages.append({"role": "system", "content": f"使用者詢問商品，以下是可能符合的商品列表：\n{options}"})

    if image_context:
        messages.append({"role": "user", "content": f"這是圖片內容分析：{image_context}"})
    messages.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    return response.choices[0].message.content

# === 圖片內容分析 ===
def call_openai_image(image_bytes: bytes) -> str:
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
    return response.choices[0].message.content

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

# === 訊息快取處理 ===
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
