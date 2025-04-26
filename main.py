import os
import json
import re
import pytz
import requests
import gspread
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from google.oauth2.service_account import Credentials
import openai
from io import BytesIO
from PIL import Image

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
openai_client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

google_credentials = Credentials.from_service_account_info(
    json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")),
    scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
)
gs_client = gspread.authorize(google_credentials)

sheet_url = os.environ.get("SHEET_URL")
sheet = gs_client.open_by_url(sheet_url)

user_greeting_memory = {}
faq_sheet_name = "FAQ"
service_sheet_name = "烤漆服務"
system_prompt = (
    "你是H.R燈藝的小婕，一位活潑熱情又專業的女生客服，請使用繁體中文回答。"
    "遇到新客人時請用：哈囉～我是 H.R燈藝的小婕！很高興為您服務~✨。"
    "回覆中禁止使用簡體字。"
)

def get_today_date():
    tz = pytz.timezone('Asia/Taipei')
    return datetime.now(tz).date()

def has_greeted_today(user_id):
    today = get_today_date()
    return user_greeting_memory.get(user_id) == today

def update_greeted_today(user_id):
    today = get_today_date()
    user_greeting_memory[user_id] = today

def find_faq_reply(user_message):
    try:
        faq_sheet = sheet.worksheet(faq_sheet_name)
        data = faq_sheet.get_all_records()
        for row in data:
            keywords = row['客戶提問關鍵字'].split('、')
            for keyword in keywords:
                if keyword.strip() in user_message:
                    return row['小婕的建議回覆方向']
        return None
    except Exception:
        return None
def search_service_table(user_message):
    try:
        service_sheet = sheet.worksheet(service_sheet_name)
        data = service_sheet.get_all_records()
        matches = []
        for row in data:
            if any(kw in user_message for kw in row['服務名稱'].split()):
                matches.append(row)
        return matches
    except Exception:
        return []

def detect_vehicle_and_color(user_message):
    vehicle_keywords = ["JETS", "JETSR", "JETSL", "SL125", "SL158", "SR"]
    color_keywords = ["紅", "橙", "黃", "綠", "藍", "紫", "白", "黑", "帝王黑", "星空黑", "銀河黑"]
    vehicle = next((v for v in vehicle_keywords if v in user_message), None)
    color = next((c for c in color_keywords if c in user_message), None)
    return vehicle, color

def build_greeting(user_id):
    if not has_greeted_today(user_id):
        update_greeted_today(user_id)
        return "哈囉～我是 H.R燈藝的小婕！很高興為您服務~✨"
    else:
        return None

def process_image(image_content):
    image = Image.open(BytesIO(image_content))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    buffer.seek(0)
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [{"type": "text", "text": "請描述這張圖片"}, {"type": "image", "image": buffer.getvalue()}]}
        ]
    )
    description = response.choices[0].message.content.strip()
    return description

def generate_paint_reply(vehicle, color):
    try:
        service_sheet = sheet.worksheet(service_sheet_name)
        data = service_sheet.get_all_records()

        base_price = None
        special_price = None
        special_found = False

        for row in data:
            name = row['服務名稱']
            if vehicle and color:
                if vehicle in name and "基本色" in name:
                    if "消光" in color and "消光" in name:
                        base_price = row['售價（元）']
                    elif ("亮光" in color or "光" not in color) and "亮光" in name:
                        base_price = row['售價（元）']
                if "特殊色" in name and color.replace("消光", "").replace("亮光", "") in name:
                    special_price = row['售價（元）']
                    special_found = True

        if base_price:
            if special_found:
                total = int(base_price) + int(special_price)
                return f"幫您查到了～基本色烤漆價格是{base_price}元，選擇特殊色 {color} 需加價，共約{total}元喔！✨（實際價格以現場確認為主，雙色以上建議現場洽詢！）"
            else:
                return f"幫您查到了～基本色烤漆價格是{base_price}元喔！✨（若選特殊色會另外加價，歡迎提供顏色讓小婕幫您試算！）"
        else:
            return None
    except Exception:
        return None

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=(TextMessage, ImageMessage))
def handle_message(event):
    try:
        user_id = event.source.user_id
        reply_token = event.reply_token

        if isinstance(event.message, TextMessage):
            user_message = event.message.text
            greeting = build_greeting(user_id)
            faq_reply = find_faq_reply(user_message)
            vehicle, color = detect_vehicle_and_color(user_message)
            paint_reply = generate_paint_reply(vehicle, color)
            service_matches = search_service_table(user_message)

            reply_messages = []
            if greeting:
                reply_messages.append(TextSendMessage(text=greeting))
            if faq_reply:
                reply_messages.append(TextSendMessage(text=faq_reply))
            elif paint_reply:
                reply_messages.append(TextSendMessage(text=paint_reply))
            elif service_matches:
                found_services = "\\n".join([f\"{m['服務名稱']} - {m['售價（元）']}元\" for m in service_matches])
                reply_messages.append(TextSendMessage(text=f\"這邊幫您找到相關服務喔～\\n{found_services}\")) 
            else:
                prompt = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ]
                response = openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=prompt
                )
                reply = response.choices[0].message.content.strip()
                reply_messages.append(TextSendMessage(text=reply))

            line_bot_api.reply_message(reply_token, reply_messages)

        elif isinstance(event.message, ImageMessage):
            image_content = line_bot_api.get_message_content(event.message.id).content
            description = process_image(image_content)
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f\"收到您的圖片囉～看起來像是：{description}\"))

    except Exception as e:
        print(f\"Error: {e}\")

if __name__ == \"__main__\":
    app.run(host=\"0.0.0.0\", port=int(os.environ.get(\"PORT\", 5000)))
