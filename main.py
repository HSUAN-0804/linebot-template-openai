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
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from datetime import datetime

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

# === 小婕客服語氣設定 ===
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小婕，專門幫客人解答與機車燈具、安裝教學、改裝精品有關的問題。
請用「活潑熱情又專業的女生」語氣說話，回覆使用繁體中文，請勿出現簡體字與 emoji。

店家資訊如下：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四公休，週日18:00提早打烊）
連絡電話：03 433 3088
"""

# === 控制打招呼頻率（每天只打一次）===
greeted_users = {}

def is_first_message_today(user_id: str) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    if greeted_users.get(user_id) != today:
        greeted_users[user_id] = today
        return True
    return False

# === 查詢 Google Sheet ===
def search_google_sheet(user_input: str) -> str:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/16_oMf8gcXNU1-RLyztSDpAm6Po0xMHm4VVVUpMAhORs/")

    results = []
    for worksheet in sheet.worksheets():
        records = worksheet.get_all_records()
        for row in records:
            if any(user_input in str(v) for v in row.values()):
                results.append("｜".join(f"{k}：{v}" for k, v in row.items()))
    if results:
        return "以下是我從知識庫找到的資料：\n" + "\n\n".join(results)
    else:
        return ""

# === 呼叫 GPT-4o（支援圖片 + 文字） ===
def call_openai_combined(user_input: str, image_bytes: bytes = None, user_id: str = "") -> str:
    openai.api_key = OPENAI_API_KEY
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    context = search_google_sheet(user_input)
    if context:
        messages.append({"role": "system", "content": f"以下是知識庫中找到的資訊：{context}"})

    if is_first_message_today(user_id):
        messages.append({"role": "user", "content": f"哈囉～今天有什麼想問小婕的嗎？\n\n{user_input}"})
    else:
        messages.append({"role": "user", "content": user_input})

    if image_bytes:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        messages[-1] = {
            "role": "user",
            "content": [
                {"type": "text", "text": user_input or "請幫我看看這張圖片"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }

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
def handle_text(event):
    user_id = event.source.user_id
    reply = call_openai_combined(event.message.text, user_id=user_id)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# === 圖片訊息處理 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    reply = call_openai_combined("請幫我看看這張圖片", image_bytes=image_data, user_id=user_id)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
