import os
import base64
import httpx
import openai
import gspread
import datetime
import json

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

# === LINE 設定 ===
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# === FastAPI App ===
app = FastAPI()

# === 小婕客服語氣 System Prompt ===
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小婕，專門幫客人解答與機車燈具、安裝教學、改裝精品有關的問題。
請用「活潑熱情又專業的女生」語氣說話，回覆使用繁體中文，請勿使用簡體字與 emoji。

店家資訊如下：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四公休，週日18:00提早打烊）
電話：03 433 3088
"""

# === 控制打招呼 ===
last_greeting_date = {}

def should_greet(user_id: str) -> bool:
    today = datetime.date.today().isoformat()
    if last_greeting_date.get(user_id) != today:
        last_greeting_date[user_id] = today
        return True
    return False

# === 查詢 Google Sheet 所有分頁 ===
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
        return "以下是我從知識庫找到的資訊：\n" + "\n\n".join(all_results)
    else:
        return ""

# === 呼叫 GPT 處理訊息 ===
def call_openai_chat(user_id: str, user_text: str, image_desc: str = "") -> str:
    openai.api_key = OPENAI_API_KEY
    context = search_google_sheet(user_text)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if context:
        messages.append({"role": "system", "content": f"以下是產品知識庫查到的內容：{context}"})

    combined_input = user_text
    if image_desc:
        combined_input += f"\n（圖片描述：{image_desc}）"

    if should_greet(user_id):
        combined_input = f"哈囉～歡迎光臨 H.R 燈藝！我是客服小婕～\n{combined_input}"

    messages.append({"role": "user", "content": combined_input})

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=messages
    )
    return response.choices[0].message["content"]

# === 呼叫 GPT 處理圖片內容 ===
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
                    {"type": "text", "text": "請幫我描述這張圖片的內容"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
    )
    return response.choices[0].message["content"]

# === 處理 webhook ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === 儲存暫存圖片說明 ===
image_descriptions = {}

# === 處理圖片訊息 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    desc = call_openai_image(image_data)
    image_descriptions[event.source.user_id] = desc
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片收到，小婕幫您看看中～請告訴我這張圖片是關於什麼的～"))

# === 處理文字訊息 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    user_text = event.message.text
    image_desc = image_descriptions.pop(user_id, "")
    reply = call_openai_chat(user_id, user_text, image_desc)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
