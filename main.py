import os
import base64
import openai
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 初始化 LINE Bot
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# FastAPI App
app = FastAPI()

# 活潑熱情客服「小潔」的語氣設定
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小姐姐，名字叫做小潔，是一位活潑熱情又專業的門市人員，擅長機車燈具改裝與安裝教學。你說話自然、充滿熱情，就像在門市接待客人那樣，讓人感覺親切又信任。

請用繁體中文回覆，不要使用簡體字、emoji，也不要說你是 AI。你可以適度使用語助詞或口語化用語（例如：「哇～這個我超推薦的！」、「小潔來幫你看看嘿～」）來讓語氣更自然活潑。

遇到圖片時，請主動分析內容並提供安裝建議或搭配產品。顧客若詢問營業資訊或產品用途，請主動協助。

店家資訊如下：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四固定公休，週日18:00提前打烊）
電話：03-433-3088
"""

# Webhook
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return PlainTextResponse("Invalid signature", status_code=400)
    return PlainTextResponse("OK", status_code=200)

# 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    reply = call_openai_chat(event.message.text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 處理圖片訊息
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_bytes = b"".join(chunk for chunk in message_content.iter_content())
    reply = call_openai_vision(image_bytes)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# GPT-4o 處理文字訊息
def call_openai_chat(user_text: str) -> str:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text}
        ]
    )
    return response.choices[0].message.content.strip()

# GPT-4o 處理圖片訊息
def call_openai_vision(image_bytes: bytes) -> str:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
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
    return response.choices[0].message.content.strip()
