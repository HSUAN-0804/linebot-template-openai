import os
import sys
import openai
import aiohttp
from fastapi import FastAPI, Request, HTTPException
from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import (
    AsyncLineBotApi,
    TextMessage,
    ImageMessage,
    TextSendMessage
)
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.models import MessageEvent
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

openai.api_key = os.getenv("OPENAI_API_KEY")
channel_secret = os.getenv("LINE_CHANNEL_SECRET")
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if channel_secret is None or channel_access_token is None:
    print("請設定 LINE_CHANNEL_SECRET 和 LINE_CHANNEL_ACCESS_TOKEN")
    sys.exit(1)

app = FastAPI()
session = aiohttp.ClientSession()
parser = WebhookParser(channel_secret)
line_bot_api = AsyncLineBotApi(channel_access_token=channel_access_token, async_http_client=session)

async def call_openai_chat_api(user_message):
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "你是 H.R燈藝的智慧客服，語氣活潑親切又專業，店家地址在桃園中壢，營業時間為早上10:30～21:00，週四固定公休，週日18:00提早關門，請協助客戶解決所有問題。"
            },
            {"role": "user", "content": user_message}
        ]
    )
    return response.choices[0].message.content

async def call_openai_vision(image_url):
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "你是 H.R燈藝的智慧客服，語氣活潑親切又專業，請協助客戶分析圖片內容並提供建議。"
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "請幫我看看這張圖片是什麼"},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]
    )
    return response.choices[0].message.content

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent):
            msg = event.message
            token = event.reply_token

            if isinstance(msg, TextMessage):
                reply = await call_openai_chat_api(msg.text)
                await line_bot_api.reply_message(token, [TextSendMessage(text=reply)])

            elif isinstance(msg, ImageMessage):
                content = await line_bot_api.get_message_content(msg.id)
                image_data = await content.read()
                import base64
                base64_image = base64.b64encode(image_data).decode()
                data_url = f"data:image/jpeg;base64,{base64_image}"
                reply = await call_openai_vision(data_url)
                await line_bot_api.reply_message(token, [TextSendMessage(text=reply)])

    return "OK"
