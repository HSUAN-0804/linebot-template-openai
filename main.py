import os
import openai
import aiohttp
from fastapi import FastAPI, Request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from dotenv import load_dotenv, find_dotenv
import base64

load_dotenv(find_dotenv())

openai.api_key = os.getenv("OPENAI_API_KEY")
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

app = FastAPI()

async def call_openai_chat(user_message):
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "你是 H.R燈藝的智慧客服，語氣活潑親切又專業。店家在桃園中壢，營業時間為10:30～21:00，週四公休，週日提早到18:00。"},
            {"role": "user", "content": user_message}
        ]
    )
    return response.choices[0].message.content

async def call_openai_vision(base64_image):
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "你是 H.R燈藝的智慧客服，請分析這張圖片的內容並提供幫助，語氣活潑親切。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "請幫我看看這是什麼圖片"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
    )
    return response.choices[0].message.content

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        return "Invalid signature"
    return "OK"

@handler.add(MessageEvent)
def handle_message(event):
    from linebot.models import ImageSendMessage
    if isinstance(event.message, TextMessage):
        reply_text = aiohttp.run(call_openai_chat(event.message.text))
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    elif isinstance(event.message, ImageMessage):
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b''.join(chunk for chunk in message_content.iter_content())
        base64_image = base64.b64encode(image_bytes).decode()
        reply_text = aiohttp.run(call_openai_vision(base64_image))
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
