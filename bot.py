# bot.py
import os
import requests
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- تنظیمات اصلی ---

# [مهم] این دو متغیر از هاست (Render.com) خوانده می‌شوند
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
AVALAI_API_KEY = os.environ.get('AVALAI_API_KEY')

# آدرس API که از AvalAI استفاده می‌کند
AVALAI_API_URL = "https://api.avalai.ir/v1/chat/completions"

# مدلی که برای MVP استفاده می‌کنیم
AI_MODEL = "gpt-4o-mini"

# دیکشنری برای نگهداری "حافظه" داستان هر کاربر
user_sessions = {}

# تنظیمات لاگ‌گیری (برای خطایابی)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- پرامپت اصلی و شخصیت‌ها ---

SYSTEM_PROMPT = """
تو یک داستان‌گوی متخصص شاهنامه هستی. نام تو 'نقّال' است. کاربر یکی از نقش‌ها را انتخاب کرده است. وظیفه تو تولید یک داستان پویا و حماسی بر اساس انتخاب‌های کاربر است.

قوانین اکید:
۱. لحن تو باید حماسی، ادبی ولی قابل فهم (مانند شاهنامه) باشد.
۲. داستان باید در دنیای اساطیری ایران (شاهنامه) رخ دهد.
۳. در هر مرحله، تو باید یک پاراگراف روایت (narrative) و سپس دقیقاً ۳ گزینه (choices) برای ادامه به کاربر بدهی.
۴. هرگز از نقش خود خارج نشوی.

قالب خروجی تو باید دقیقاً یک JSON به شکل زیر باشد و هیچ متنی قبل یا بعد از آن نباشد:
{
  "narrative": "متن روایت تو در اینجا قرار می‌گیرد.",
  "choices": [
    { "id": "A", "text": "متن گزینه اول" },
    { "id": "B", "text": "متن گزینه دوم" },
    { "id": "C", "text": "متن گزینه سوم" }
  ]
}
"""

CHARACTERS = {
    "pehlevan": "پهلوان‌زاده‌ای جوان از زابلستان (مانند رستم)",
    "mobed": "موبدی خردمند در دربار شاه (مانند جاماسپ)",
    "shahzadeh": "شاهزاده‌ای تورانی با قلبی دوگانه (مانند سیاوش)"
}

# --- بخش منطق ربات (Handlers) ---

# 1. دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    logger.info(f"کاربر {user_id} ربات را شروع کرد.")

    user_sessions[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    keyboard = [
        [InlineKeyboardButton(text, callback_data=key)] for key, text in CHARACTERS.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "به نام خداوند جان و خرد.\n\nای جوینده راه، خوش آمدی. تو در آستانه ورود به داستان خود در شاهنامه هستی.\n\nنخست، نقش خود را برگزین:",
        reply_markup=reply_markup
    )

# 2. مدیریت تمام دکمه‌های شیشه‌ای
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    choice = query.data

    if user_id not in user_sessions:
        await query.edit_message_text("خطا: حافظه داستان یافت نشد. لطفاً با /start مجدد شروع کنید.")
        return

    if choice in CHARACTERS:
        character_name = CHARACTERS[choice].split(" (")[0]
        logger.info(f"کاربر {user_id} نقش {character_name} را انتخاب کرد.")
        user_message = f"من نقش '{character_name}' را برمی‌گزینم. داستان مرا آغاز کن."
        user_sessions[user_id].append({"role": "user", "content": user_message})
        await query.edit_message_text("نقش تو برگزیده شد... نقّال در حال بافتن تار و پود داستان توست. شکیبا باش...")
    else:
        logger.info(f"کاربر {user_id} گزینه {choice} را انتخاب کرد.")
        user_message = f"من گزینه '{choice}' را انتخاب می‌کنم."
        user_sessions[user_id].append({"role": "user", "content": user_message})
        await query.edit_message_text(f"گزینه {choice} انتخاب شد... نقّال در حال نگریستن به ادامه راه است...")

    await send_story_step(query, user_id)

# 3. تابع اصلی: تماس با AvalAI و ارسال مرحله بعدی
async def send_story_step(query_or_update, user_id):
    history = user_sessions.get(user_id, [])
    if not history: return

    headers = {
        "Authorization": f"Bearer {AVALAI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": AI_MODEL,
        "messages": history,
        "response_format": {"type": "json_object"}
    }

    try:
        response = requests.post(AVALAI_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        ai_response_json = response.json()
        ai_message_content = ai_response_json['choices'][0]['message']['content']

        user_sessions[user_id].append({"role": "assistant", "content": ai_message_content})

        import json
        story_data = json.loads(ai_message_content)
        narrative = story_data['narrative']
        choices = story_data['choices']

        keyboard = [
            [InlineKeyboardButton(choice['text'], callback_data=choice['id'])] for choice in choices
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if hasattr(query_or_update, 'edit_message_text'):
            await query_or_update.edit_message_text(narrative, reply_markup=reply_markup)
        else:
            await query_or_update.message.reply_text(narrative, reply_markup=reply_markup)

    except requests.exceptions.RequestException as e:
        logger.error(f"خطا در ارتباط با AvalAI: {e}")
        error_message = f"خطا در ارتباط با نقّال. (Error: {e})"
        if hasattr(query_or_update, 'edit_message_text'):
            await query_or_update.edit_message_text(error_message)
        else:
            await query_or_update.message.reply_text(error_message)

    except Exception as e:
        logger.error(f"خطای ناشناخته در پردازش داستان: {e}")
        if hasattr(query_or_update, 'edit_message_text'):
            await query_or_update.edit_message_text("نقّال در کلام خود دچار لکنت شد. لطفاً با /start مجدد امتحان کنید.")
        else:
            await query_or_update.message.reply_text("خطای داخلی. /start")
        if user_id in user_sessions:
            del user_sessions[user_id]


# --- راه‌اندازی ربات ---
def main():
    if not TELEGRAM_BOT_TOKEN or not AVALAI_API_KEY:
        logger.error("خطای حیاتی: توکن‌های تلگرام یا AvalAI در متغیرهای محیطی تنظیم نشده‌اند.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("ربات در حال آغاز به کار است...")
    application.run_polling()

if __name__ == "__main__":
    main()
