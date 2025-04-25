import os
import re
import openai
import gspread
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from difflib import get_close_matches

app = FastAPI()

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("google-credentials.json", scope)
client = gspread.authorize(creds)
sheet_url = os.getenv("GOOGLE_SHEET_URL")
sheet = client.open_by_url(sheet_url)
worksheet_list = sheet.worksheets()

greeted_users = {}

class LineEvent(BaseModel):
    events: list

def search_product(keyword):
    for ws in worksheet_list:
        try:
            records = ws.get_all_records()
            for record in records:
                if keyword == str(record.get("品名", "")).strip():
                    return record
        except Exception:
            continue
    for ws in worksheet_list:
        try:
            records = ws.get_all_records()
            for record in records:
                name = str(record.get("品名", "")).strip()
                keywords = str(record.get("關鍵字", "")).strip()
                if keyword in name or keyword in keywords:
                    return record
        except Exception:
            continue
    return None

def generate_reply(user_id, message_text):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    greet = ""
    if greeted_users.get(user_id) != today:
        greet = "您好，我是來自 H.R燈藝的客服小婕～今天有什麼我可以為您服務的嗎？\n"
        greeted_users[user_id] = today

    product = search_product(message_text)
    if product and product.get("品名") and product.get("售價"):
        name = product["品名"]
        price = product["售價"]
        return f"""{greet}我們有販售「{name}」，售價是 {price} 元喔！有希望什麼時候安裝嗎？可以為您查詢貨況喔！
也歡迎多多善用我們的預約系統自行挑選時段預約！"""

    system_prompt = (
        "你是 H.R燈藝的客服小婕，語氣要活潑親切又專業。"
        "店內專營機車燈具與改裝精品，請針對客人問題給予協助，"
        "如果對方詢問商品但 Google Sheet 中找不到，就委婉說明無資料並引導詢問其他商品。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message_text}
    ]
    chat_response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7
    )
    reply = chat_response.choices[0].message.content.strip()
    return greet + reply

@app.post("/callback")
async def callback(req: Request):
    try:
        body = await req.body()
        handler.handle(body.decode('utf-8'), req.headers.get('X-Line-Signature'))
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    return JSONResponse(content={"status": "ok"})

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_id = event.source.user_id
        message_text = event.message.text.strip()
        reply_text = generate_reply(user_id, message_text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    except Exception as e:
        print("處理訊息時發生錯誤：", e)
