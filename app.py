from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# Google Sheets 認證
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet_record = client.open(os.getenv("GOOGLE_SHEET_NAME")).worksheet("記帳紀錄")
sheet_budget = client.open(os.getenv("GOOGLE_SHEET_NAME")).worksheet("預算設定")

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print(e)
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    parts = msg.split(",")

    if len(parts) != 6:
        reply = "請使用格式：分類,付款工具,付款方式,+或-,金額,備註"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    category, tool, method, inout, amount_str, note = [p.strip() for p in parts]

    if inout not in ("+", "-"):
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請填入 + 表示收入，- 表示支出"))
        return

    try:
        amount = int(amount_str)
    except ValueError:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="金額需為數字"))
        return

    now = datetime.now()
    formatted_time = now.strftime("%Y年%m月%d日 %H:%M")
    sheet_record.append_row([formatted_time, category, tool, method, inout, amount, note])

    # 預算邏輯：只針對「支出」才減少分類預算
    remaining_msg = ""
    if inout == "-":
        try:
            budget_cells = sheet_budget.get_all_records()
            budget_map = {row["分類"]: int(row["每月預算"]) for row in budget_cells}
            monthly_budget = budget_map.get(category, None)

            if monthly_budget is not None:
                this_month = now.strftime("%Y年%m月")
                all_rows = sheet_record.get_all_records()
                monthly_spent = sum(
                    int(row["金額"]) for row in all_rows
                    if row["分類"] == category and row["收入支出"] == "-" and row["日期時間"].startswith(this_month)
                )
                remaining = monthly_budget - monthly_spent
                remaining_msg = f'📉「{category}」本月剩餘預算：{remaining:,} 元（預算 {monthly_budget:,} - 累計支出 {monthly_spent:,}）'
            else:
                remaining_msg = f'⚠️「{category}」沒有在預算設定中，無法計算剩餘預算'
        except Exception as e:
            print("預算計算錯誤：", e)
            remaining_msg = "⚠️ 預算計算失敗，請稍後再試"

    reply = (
        f"""✅ 已記錄：{category} {amount} 元
"""
        f"""💳 工具：{tool}／{method}
"""
        f"""📌 備註：{note}
"""
        f"""{remaining_msg}
"""
        f"""🕒 {formatted_time}"""
    )
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    app.run()
