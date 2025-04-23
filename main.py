# -*- coding: utf-8 -*-
import os
import json
import openai
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv, find_dotenv
from linebot import (
    AsyncLineBotApi, WebhookParser
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage
)
from linebot.exceptions import InvalidSignatureError
import aiohttp

load_dotenv(find_dotenv())

# 初始化
app = FastAPI()
session = aiohttp.ClientSession()
line_bot_api = AsyncLineBotApi(channel_access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
parser = WebhookParser(channel_secret=os.getenv("LINE_CHANNEL_SECRET"))
openai.api_key = os.getenv("OPENAI_API_KEY")

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
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessage):
            continue
        user_message = event.message.text
        reply = await chatgpt_reply(user_message)
        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
    return "OK"

async def chatgpt_reply(user_message):
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位語氣活潑親切又專業的女生，是 H.R燈藝 的 LINE 客服助理。"
                    "請使用繁體中文回覆，不要使用 emoji。"
                    "品牌資訊：H.R燈藝，地址：桃園市中壢區南園二路435號，營業時間為 10:30～21:00，週四公休，週日18:00提早打烊。"
                    "請根據客戶提問，自然融入這些資訊並提供親切清楚的回答。"
                )
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    )
    return response.choices[0].message.content
