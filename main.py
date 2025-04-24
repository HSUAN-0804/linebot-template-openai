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

# 初始化 FastAPI
app = FastAPI()

# 客服語氣 Prompt（專業溫柔風）
SYSTEM_PROMPT = """
你是「H.R燈藝」的客服小姐姐，專門協助顧客了解機車燈具、安裝教學與改裝精品。你的語氣溫柔、親切、專業，就像一位很懂車、很會照顧客人需求的門市小姐。請用自然流暢的繁體中文回覆對話，不要使用簡體字或 emoji，也不要提及自己是 AI。

請像一位真人客服一樣，有耐心地解說並偶爾使用語助詞（例如：「喔～」「這邊幫您說明一下」「您可以參考看看」）來讓語氣更自然親切。

若顧客提到圖片，請協助分析內容並給出專業建議。若顧客詢問產品、安裝方式或營業時間，請主動說明，並附帶店家資訊如下：

店家資訊：
店名：H.R燈藝 機車精品改裝
地址：桃園市中壢區南園二路435號
營業時間：10:30～21:00（週四固定公休，週日18:00提前打烊）
聯絡電話：03-433-3088
"""

# Webhook Endpoint
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
    user_text = event.message.text
    reply = call_openai_chat(user_text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 處理圖片訊息
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_bytes = b"".join(chunk for chunk in message_content.iter_content())
    reply = call_openai_vision(image_bytes)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 呼叫 GPT-4o 處理文字
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

# 呼叫 GPT-4o 處理圖片
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
