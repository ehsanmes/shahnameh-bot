import os
import re
import logging
import asyncio 
from openai import OpenAI
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# فعال‌سازی لاگ‌گیری
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- گرفتن کلیدهای API از متغیرهای محیطی ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")

# --- راه‌اندازی کلاینت OpenAI برای اتصال به AvalAI ---
client = None
if AVALAI_API_KEY:
    try:
        client = OpenAI(
            api_key=AVALAI_API_KEY,
            base_url="https://api.avalai.ir/v1"
        )
    except Exception as e:
        logger.error(f"امکان ساخت کلاینت OpenAI (AvalAI) وجود نداشت: {e}")

# تعریف حالت‌های مکالمه
ROLE_STATE, STORY_STATE = range(2)

# =========================================================
# تابع کمکی برای استخراج دکمه‌ها از متن هوش مصنوعی
# =========================================================
def extract_options(text: str) -> tuple[str, list[str]]:
    """
    متن داستان را تجزیه کرده و گزینه‌های انتخابی را استخراج می‌کند تا برای دکمه‌ها استفاده شود.
    """
    options = []
    # الگوی رگولار اکسپرشن برای پیدا کردن گزینه های [عدد. متن]
    pattern = re.compile(r"\[(\d+)\.\s*(.+?)\]")
    
    matches = pattern.findall(text)
    
    if matches:
        # ساخت لیست گزینه‌ها: فقط متن داخل براکت‌ها را برای استفاده در دکمه‌ها می‌گیریم
        options = [match[1].strip() for match in matches]
        # حذف گزینه‌ها از متن اصلی داستان برای نمایش تمیز
        story_text = pattern.sub(r"", text).strip()
    else:
        story_text = text

    # اگر هوش مصنوعی پایان داستان را مشخص کند
    if "پایان داستان" in story_text or "داستان به پایان رسید" in story_text:
         options.append("/start")
    
    return story_text, options

# =========================================================
# توابع مکالمه
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه و ایجاد دکمه‌های نقش."""
    
    reply_keyboard = [
        ["رستم", "سهراب", "گردآفرید"],
        ["سیاوش", "منیژه", "فرنگیس"],
    ]
    markup = ReplyKeyboardMarkup(
        reply_keyboard, 
        one_time_keyboard=True,
        resize_keyboard=True,
        input_field_placeholder="یکی از پهلوانان را انتخاب کن..."
    )
    
    full_prompt = (
        "سلام! من نقال شاهنامه هستم و تو به قلب داستان‌های حماسی ایران پا گذاشته‌ای.\n\n"
        "هنگامه‌ای است بس شگرف! سرنوشت ایران‌زمین در دستان توست.\n\n"
        "**نقش تو در این داستان چیست؟**\n"
        "از گزینه‌های زیر انتخاب کن، یا نام پهلوان محبوب خودت را تایپ کن:"
    )
    
    await update.message.reply_text(full_prompt, reply_markup=markup)
    
    return ROLE_STATE

async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ذخیره نقش انتخاب شده و شروع داستان."""
    if client is None:
        await update.message.reply_text("خطایی در اتصال به نقال رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

    user_role = update.message.text
    context.user_data["role"] = user_role
    
    await update.message.reply_text(
        f"عالی! تو اکنون «{user_role}» هستی. بگذار داستان تو را آغاز کنم...\n\n"
        "(لطفا چند لحظه صبر کن تا اولین بخش از سرنوشت تو را روایت کنم...)",
        reply_markup=ReplyKeyboardRemove() # حذف دکمه‌های نقش
    )

    # دستورالعمل سیستمی نهایی: ادبیات روان و اجبار به دکمه‌های کوتاه
    system_prompt = (
        "تو یک نقال حماسی و باوفا به شاهنامه هستی. "
        "داستان را به صورت یک داستان‌گوی حرفه‌ای و با **ادبیاتی ساده، روان و کاملاً روایت‌گونه مبتنی بر زبان شاهنامه** روایت کن. "
        "فقط از وقایع، شخصیت‌ها، و مکان‌های مرتبط با جهان شاهنامه استفاده کن. "
        "با **تمرکز بر مخاطب (تو/شما)** داستان را پیش ببر. "
        "**هر بخش داستان باید بسیار مختصر باشد (حداکثر ۴ جمله).** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. متن داخل براکت‌ها باید بسیار کوتاه (حداکثر ۵ کلمه) باشد تا در دکمه‌های تلگرام جا شود.**"
    )
    
    first_prompt = f"داستان من را به عنوان «{user_role}» آغاز کن. اولین صحنه و اولین چالش من چه خواهد بود؟"
    
    context.user_data["history"] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": first_prompt}
    ]

    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=context.user_data["history"],
            stream=True,
            max_tokens=2000 
        )
        
        full_response = ""
        chunk_message = await update.message.reply_text("نقال در حال سرودن شعر است...")
        
        await asyncio.sleep(1) # مکث برای پایداری شبکه
        
        for chunk in response:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                full_response += chunk_content
                try:
                    await context.bot.edit_message_text(text=full_response, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)
                except Exception:
                    pass

        story_text, options = extract_options(full_response)
        
        # ویرایش نهایی متن (فقط داستان)
        await context.bot.edit_message_text(text=story_text, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)
        
        # نمایش دکمه‌ها
        if options and options != ["/start"]:
            reply_keyboard = [[opt] for opt in options]
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=False)
            await update.message.reply_text("تصمیم تو چیست؟", reply_markup=markup)
        else:
            final_message = story_text + ("\n\nبرای شروع دوباره /start را بزنید." if "/start" in options else "")
            await update.message.reply_text(final_message, reply_markup=ReplyKeyboardRemove())
        
        context.user_data["history"].append({"role": "assistant", "content": full_response})
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در set_role: {e}")
        await update.message.reply_text(f"خطایی در روایت داستان رخ داد: {e}")
        return ConversationHandler.END

    return STORY_STATE

async def handle_story(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ادامه داستان بر اساس ورودی کاربر."""
    if client is None:
        await update.message.reply_text("خطایی در اتصال به نقال رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

    user_input = update.message.text
    history = context.user_data["history"]

    # افزودن پاسخ کاربر به تاریخچه
    history.append({"role": "user", "content": user_input})
    await update.message.reply_text("نقال در حال اندیشیدن به ادامه سرنوشت توست...", reply_markup=ReplyKeyboardRemove()) 

    # به‌روزرسانی دستورالعمل سیستمی (برای اطمینان از حفظ دستورات)
    current_system_prompt = (
        "تو یک نقال حماسی و باوفا به شاهنامه هستی. "
        "داستان را به صورت یک داستان‌گوی حرفه‌ای و با **ادبیاتی ساده، روان و کاملاً روایت‌گونه مبتنی بر زبان شاهنامه** روایت کن. "
        "فقط از وقایع، شخصیت‌ها، و مکان‌های مرتبط با جهان شاهنامه استفاده کن. "
        "با **تمرکز بر مخاطب (تو/شما)** داستان را پیش ببر. "
        "**هر بخش داستان باید بسیار مختصر باشد (حداکثر ۴ جمله).** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. متن داخل براکت‌ها باید بسیار کوتاه (حداکثر ۵ کلمه) باشد تا در دکمه‌های تلگرام جا شود.**"
    )
    if history[0]["role"] == "system":
        history[0]["content"] = current_system_prompt
    
    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=history,
            stream=True,
            max_tokens=2000
        )
        
        full_response = ""
        chunk_message = await update.message.reply_text("...")

        await asyncio.sleep(1) # مکث برای پایداری شبکه
        
        for chunk in response:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                full_response += chunk_content
                try:
                    await context.bot.edit_message_text(text=full_response, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)
                except Exception:
                    pass

        story_text, options = extract_options(full_response)
        
        # ویرایش نهایی متن
        await context.bot.edit_message_text(text=story_text, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)

        # نمایش دکمه‌ها
        if options and options != ["/start"]:
            reply_keyboard = [[opt] for opt in options]
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=False)
            await update.message.reply_text("تصمیم تو چیست؟", reply_markup=markup)
        else:
            final_message = story_text + ("\n\nبرای شروع دوباره /start را بزنید." if "/start" in options else "")
            await update.message.reply_text(final_message, reply_markup=ReplyKeyboardRemove())

        history.append({"role": "assistant", "content": full_response})
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در handle_story: {e}")
        await update.message.reply_text(f"خطایی در ادامه داستان رخ داد: {e}")
        return ConversationHandler.END

    return STORY_STATE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پایان دادن به مکالمه."""
    await update.message.reply_text(
        "بدرود! باشد که در داستانی دیگر تو را ببینم.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main() -> None:
    """اجرای ربات."""
    if not TELEGRAM_BOT_TOKEN or not AVALAI_API_KEY or client is None:
        logger.fatal("یکی از متغیرهای محیطی (تلگرام، AvalAI) به درستی تنظیم نشده است. ربات متوقف می‌شود.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ROLE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_role)],
            STORY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_story)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    logger.info("ربات در حال آغاز به کار است... (نسخه نهایی: تعاملی و بهینه‌سازی شده)")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
