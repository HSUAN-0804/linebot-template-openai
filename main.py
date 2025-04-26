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
                found_services = "\n".join([f"{m['服務名稱']} - {m['售價（元）']}元" for m in service_matches])
                reply_messages.append(TextSendMessage(text=f"這邊幫您找到相關服務喔～\n{found_services}"))
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
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"收到您的圖片囉～看起來像是：{description}"))

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
