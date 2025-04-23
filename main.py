import openai
import os
import sys
import json
import aiohttp
from fastapi import FastAPI, Request
from linebot import (
    AsyncLineBotApi, WebhookParser
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage
)
from linebot.exceptions import (
    InvalidSignatureError
)
from dotenv import load_dotenv, find_dotenv

_ = load_dotenv(find_dotenv())

openai.api_key = os.getenv("OPENAI_API_KEY")
channel_secret = os.getenv("LINE_CHANNEL_SECRET")
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if channel_secret is None:
    print("請設定 LINE_CHANNEL_SECRET")
    sys.exit(1)
if channel_access_token is None:
    print("請設定 LINE_CHANNEL_ACCESS_TOKEN")
    sys.exit(1)

app = FastAPI()
session = aiohttp.ClientSession()
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client=session)
parser = WebhookParser(channel_secret)

# 回應函式：繁體中文、GPT-4o、活潑親切專業語氣
def call_openai_chat_api(user_message):
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": (
                "你是 H.R燈藝的客服小姊姊，說話活潑親切又專業，請用繁體中文回答用戶問題。"
                "H.R燈藝是一間位在桃園中壢的機車燈具專賣與改裝店，營業時間為每天早上10:30到晚上9:00，"
                "週四固定公休，週日18:00提早打烊，若有客戶詢問相關資訊，請主動告知。"
            )},
            {"role": "user", "content": user_message}
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
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("Invalid signature", status_code=400)

    for event in events:
        if not isinstance(event, MessageEvent) or not isinstance(event.message, TextMessage):
            continue

        user_message = event.message.text
        reply = call_openai_chat_api(user_message)

        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )

    return "OK"
