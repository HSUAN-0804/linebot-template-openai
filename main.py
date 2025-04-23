import os
import base64
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
from linebot.v3.messaging import (
    AsyncLineBotApi, ReplyMessageRequest, TextMessage, ImageMessage
)
from PIL import Image
from io import BytesIO
import openai

# === 環境變數 ===
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# === LINE設定 ===
line_bot_api = AsyncLineBotApi(channel_access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# === FastAPI ===
app = FastAPI()

# === H.R燈藝介紹 prompt ===
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小姐姐，專門幫客人解答與機車燈具、安裝教學、改裝精品有關的問題。語氣要活潑親切又專業，回覆文字請使用「繁體中文」，不要使用簡體字、emoji，也不要提到你是 AI。

店家資訊如下：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四公休，週日18:00提早打烊）
連絡電話：03 433 3088
"""

# === Webhook ===
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["x-line-signature"]
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# === GPT 文字回覆邏輯 ===
async def call_openai_chat(user_input: str):
    openai.api_key = OPENAI_API_KEY
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
    )
    return response.choices[0].message["content"]

# === GPT 圖片辨識邏輯 ===
async def call_openai_image(image_bytes: bytes):
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
            },
        ],
    )
    return response.choices[0].message["content"]

# === 處理訊息事件 ===
@handler.add(MessageEvent, message=TextMessageContent)
async def handle_text_message(event: MessageEvent):
    user_message = event.message.text
    reply_text = await call_openai_chat(user_message)
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_text)]
        )
    )

@handler.add(MessageEvent, message=ImageMessageContent)
async def handle_image_message(event: MessageEvent):
    message_id = event.message.id
    content = await line_bot_api.get_message_content(message_id)
    image_data = b"".join([chunk async for chunk in content.iter_content()])
    reply_text = await call_openai_image(image_data)
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_text)]
        )
    )
