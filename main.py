import os
import base64
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from openai import OpenAI

# === 環境變數 ===
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# === LINE 設定 ===
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# === FastAPI App ===
app = FastAPI()

# === OpenAI 客戶端 ===
client = OpenAI(api_key=OPENAI_API_KEY)

# === 客服系統提示 ===
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小姐姐，專門幫客人解答與機車燈具、安裝教學、改裝精品有關的問題。
語氣要活潑親切又專業，回覆文字請使用「繁體中文」，不要使用簡體字、emoji，也不要提到你是 AI。

店家資訊如下：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四公休，週日18:00提早打烊）
連絡電話：03 433 3088
"""

# === Webhook ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === GPT：處理文字 ===
def call_openai_chat(user_input: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input}
        ]
    )
    return response.choices[0].message.content

# === GPT：處理圖片 ===
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

# === 處理文字訊息 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    reply = call_openai_chat(event.message.text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# === 處理圖片訊息 ===
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())
    reply = call_openai_image(image_data)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
