import os
import logging
from openai import OpenAI
# ### تغییر ۳: وارد کردن کیبورد ###
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
logging.getLogger("telegram.ext").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# گرفتن کلیدهای API از متغیرهای محیطی
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")

# راه‌اندازی کلاینت OpenAI برای اتصال به AvalAI
client = None
if AVALAI_API_KEY:
    try:
        client = OpenAI(
            api_key=AVALAI_API_KEY,
            base_url="https://api.avalai.ir/v1"
        )
        logger.info("کلاینت AvalAI با موفقیت ساخته شد.")
    except Exception as e:
        logger.error(f"امکان ساخت کلاینت OpenAI (AvalAI) وجود نداشت: {e}")
else:
    logger.error("متغیر AVALAI_API_KEY پیدا نشد.")

# تعریف حالت‌های مکالمه
ROLE_STATE, STORY_STATE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه و ایجاد زمینه داستانی + دکمه‌ها."""
    
    story_context = (
        "سلام! من نقال شاهنامه هستم و تو به قلب داستان‌های حماسی ایران پا گذاشته‌ای.\n\n"
        "هنگامه‌ای است بس شگرف! تورانیان به مرزهای ایران تاخته‌اند، "
        "دیو سپید در مازندران بند بر پای پهلوانان نهاده، و شاه کاووس در بند است.\n\n"
        "سرنوشت ایران‌زمین در دستان توست."
    )
    await update.message.reply_text(story_context)
    
    # ### تغییر ۳: تعریف دکمه‌های نقش ###
    reply_keyboard = [
        ["رستم", "سهراب", "گردآفرید"],
        ["سیاوش", "منیژه", "فرنگیس"],
    ]
    markup = ReplyKeyboardMarkup(
        reply_keyboard, 
        one_time_keyboard=True,  # کیبورد پس از انتخاب پنهان می‌شود
        resize_keyboard=True,    # اندازه دکمه‌ها بهینه‌ می‌شود
        input_field_placeholder="یکی از پهلوانان را انتخاب کن..."
    )

    await update.message.reply_text(
        "نقش تو در این داستان چیست؟\n"
        "از گزینه‌های زیر انتخاب کن، یا نام پهلوان محبوب خودت را تایپ کن:",
        reply_markup=markup  # ارسال دکمه‌ها به کاربر
    )
    
    return ROLE_STATE

async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ذخیره نقش انتخاب شده و شروع داستان."""
    if client is None:
        await update.message.reply_text("خطایی در اتصال به نقال (مدل هوش مصنوعی) رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

    user_role = update.message.text
    context.user_data["role"] = user_role
    logger.info(f"نقش انتخاب شده توسط کاربر: {user_role}")

    # ### تغییر ۳: حذف دکمه‌ها پس از انتخاب ###
    await update.message.reply_text(
        f"عالی! تو اکنون «{user_role}» هستی. بگذار داستان تو را آغاز کنم...\n\n"
        "(لطفا چند لحظه صبر کن تا اولین بخش از سرنوشت تو را روایت کنم...)",
        reply_markup=ReplyKeyboardRemove() # حذف دکمه‌های قبلی
    )

    # ### تغییر ۱: تغییر لحن به ساده و امروزی ###
    system_prompt = (
        "تو یک نقال داستان‌گو هستی. کاربر نقش یکی از شخصیت‌های شاهنامه را انتخاب کرده است. "
        "تو باید یک داستان تعاملی و جذاب برای او روایت کنی. "
        "داستان را با زبانی ساده، امروزی، و دوستانه بنویس (نه به زبان ادبیات کهن). "
        "هر بخش از داستان را با یک چالش یا یک انتخاب برای کاربر تمام کن."
    )
    
    first_prompt = f"داستان من را به عنوان «{user_role}» آغاز کن. اولین صحنه و اولین چالش من چه خواهد بود؟"
    
    context.user_data["history"] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": first_prompt}
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=context.user_data["history"],
            stream=True,
            # ### تغییر ۲: افزایش طول متن خروجی ###
            max_tokens=1500  # افزایش حداکثر طول پاسخ برای جلوگیری از قطع شدن
        )
        
        full_response = ""
        chunk_message = await update.message.reply_text("نقال در حال سرودن شعر است...")
        
        for chunk in response:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                full_response += chunk_content
                try:
                    # ویرایش پیام قبلی برای ایجاد افکت استریم
                    await context.bot.edit_message_text(text=full_response, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)
                except Exception:
                    pass # نادیده گرفتن خطای ویرایش مکرر

        context.user_data["history"].append({"role": "assistant", "content": full_response})
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در set_role: {e}")
        if "401" in str(e):
             await update.message.reply_text("خطا در ارتباط با نقال (ارور 401). کلید API شما در Railway اشتباه یا نامعتبر است.")
        else:
            await update.message.reply_text(f"خطایی در روایت داستان رخ داد: {e}")
        return ConversationHandler.END

    return STORY_STATE

async def handle_story(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ادامه داستان بر اساس ورودی کاربر."""
    user_input = update.message.text
    history = context.user_data["history"]

    history.append({"role": "user", "content": user_input})
    await update.message.reply_text("نقال در حال اندیشیدن به ادامه سرنوشت توست...")

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=history,
            stream=True,
            # ### تغییر ۲: افزایش طول متن خروجی ###
            max_tokens=1500 # افزایش حداکثر طول پاسخ برای جلوگیری از قطع شدن
        )
        
        full_response = ""
        chunk_message = await update.message.reply_text("...")

        for chunk in response:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                full_response += chunk_content
                try:
                    await context.bot.edit_message_text(text=full_response, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)
                except Exception:
                    pass # نادیده گرفتن خطای ویرایش مکرر

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
        reply_markup=ReplyKeyboardRemove() # حذف دکمه‌ها هنگام لغو
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
            # این بخش به طور خودکار هم متن تایپ شده و هم متن دکمه‌ها را می‌پذیرد
            ROLE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_role)],
            STORY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_story)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    logger.info("ربات در حال آغاز به کار است... (نسخه ۲: با دکمه و لحن ساده)")
    application.run_polling()

if __name__ == "__main__":
    main()
