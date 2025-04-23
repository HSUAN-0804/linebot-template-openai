import os
import openai
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookParser
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.messaging.models import MessageAction
import httpx
import base64

# 初始化 LINE 與 OpenAI 設定
openai.api_key = os.getenv("OPENAI_API_KEY")
channel_secret = os.getenv("LINE_CHANNEL_SECRET")
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

configuration = Configuration(access_token=channel_access_token)
app = FastAPI()
parser = WebhookParser(channel_secret)

# 系統提示語
SYSTEM_PROMPT = """
你是 H.R燈藝 的智慧客服，一位活潑親切又專業的女生，請用繁體中文回答客戶問題。
我們專門販售與改裝機車燈具，地址：桃園市中壢區南園二路435號，
營業時間為每天 10:30～21:00，週四固定公休，週日18:00關門。
請根據客戶的提問，自然地回覆。
"""

# 呼叫 GPT-4o，支援圖文理解
async def call_openai_chat(messages):
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=messages
    )
    return response.choices[0].message.content.strip()

# 圖片下載並轉為 base64 (送給 GPT-4o 使用)
async def fetch_image_as_base64(api: MessagingApi, message_id: str) -> str:
    stream = await api.get_message_content(message_id)
    image_bytes = b"".join([chunk async for chunk in stream.iter_bytes()])
    encoded = base64.b64encode(image_bytes).decode('utf-8')
    return f"data:image/jpeg;base64,{encoded}"

# LINE Webhook 接收端點
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("x-line-signature", "")
    body = await request.body()
    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    async with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        for event in events:
            if isinstance(event, MessageEvent):
                reply_token = event.reply_token

                # 使用者訊息內容
                if isinstance(event.message, TextMessageContent):
                    user_input = event.message.text
                elif isinstance(event.message, ImageMessageContent):
                    image_base64 = await fetch_image_as_base64(line_bot_api, event.message.id)
                    user_input = f"請幫我看這張圖片：{image_base64}"
                else:
                    user_input = "收到非文字/圖片訊息，請傳文字或圖片給我喔！"

                # 組合對話訊息
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_input}
                ]

                try:
                    reply_text = await call_openai_chat(messages)
                except Exception as e:
                    reply_text = f"發生錯誤：{str(e)}"

                # 回傳給使用者
                await line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )

    return "OK"
