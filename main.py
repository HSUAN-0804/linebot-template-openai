import os
import openai
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

app = FastAPI()

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        return JSONResponse(status_code=400, content={"message": "Invalid signature"})
    return JSONResponse(status_code=200, content={"message": "OK"})

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_message = event.message.text
    reply_text = call_openai_chat(user_message)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_id = event.message.id
    message_content = line_bot_api.get_message_content(message_id)
    image_bytes = b"".join(chunk for chunk in message_content.iter_content(chunk_size=1024))

    import base64
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "你是H.R燈藝的親切專業客服小姐姐，根據圖片內容協助解說或提供建議。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "請幫我看這張圖片的內容"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }
        ]
    )
    answer = response.choices[0].message.content
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=answer))

def call_openai_chat(user_message: str) -> str:
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是H.R燈藝的客服小姐姐，風格親切活潑又專業，提供店家資訊如下：\\n"
                    "店名：H.R燈藝\\n"
                    "地址：桃園市中壢區\\n"
                    "營業時間：10:30～21:00，週四公休，週日18:00提早打烊"
                )
            },
            {"role": "user", "content": user_message}
        ]
    )
    return response.choices[0].message.content
