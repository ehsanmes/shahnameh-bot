import os
import re
import logging
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
    متن داستان را تجزیه کرده و گزینه‌های انتخابی را (که با [1.]، [2.] و [3.] مشخص شده‌اند) استخراج می‌کند.
    """
    options = []
    # الگوی رگولار اکسپرشن برای پیدا کردن گزینه های [عدد. متن]
    # این الگو با توجه به سختگیری کد AI تنظیم شده است.
    pattern = re.compile(r"\[(\d+)\.\s*(.+?)\]")
    
    # پیدا کردن همه گزینه‌ها
    matches = pattern.findall(text)
    
    if matches:
        # ساخت لیست گزینه‌ها
        options = [match[1].strip() for match in matches]
        # حذف گزینه‌ها از متن اصلی داستان برای نمایش تمیز
        # این کار از تداخل متن با دکمه جلوگیری می‌کند.
        story_text = pattern.sub(r"", text).strip()
    else:
        # اگر گزینه‌ای پیدا نشد، متن اصلی داستان را برمی‌گرداند.
        story_text = text

    # اگر هوش مصنوعی پایان داستان را مشخص کند، دکمه /start اضافه می‌شود.
    if "پایان داستان" in story_text or "داستان به پایان رسید" in story_text:
         options.append("/start")
    
    return story_text, options

# =========================================================
# توابع مکالمه
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه و ایجاد دکمه‌های نقش."""
    
    story_context = (
        "سلام! من نقال شاهنامه هستم و تو به قلب داستان‌های حماسی ایران پا گذاشته‌ای.\n\n"
        "هنگامه‌ای است بس شگرف! تورانیان به مرزهای ایران تاخته‌اند، "
        "دیو سپید در مازندران بند بر پای پهلوانان نهاده، و شاه کاووس در بند است.\n\n"
        "سرنوشت ایران‌زمین در دستان توست."
    )
    await update.message.reply_text(story_context)
    
    # تعریف دکمه‌های نقش
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

    await update.message.reply_text(
        "نقش تو در این داستان چیست؟\n"
        "از گزینه‌های زیر انتخاب کن، یا نام پهلوان محبوب خودت را تایپ کن:",
        reply_markup=markup
    )
    
    return ROLE_STATE

async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ذخیره نقش انتخاب شده و شروع داستان."""
    if client is None:
        await update.message.reply_text("خطایی در اتصال به نقال (مدل هوش مصنوعی) رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

    user_role = update.message.text
    context.user_data["role"] = user_role
    
    await update.message.reply_text(
        f"عالی! تو اکنون «{user_role}» هستی. بگذار داستان تو را آغاز کنم...\n\n"
        "(لطفا چند لحظه صبر کن تا اولین بخش از سرنوشت تو را روایت کنم...)",
        reply_markup=ReplyKeyboardRemove()
    )

    # ### اصلاحیه نهایی System Prompt برای القای نقش اول و اجبار به فرمت دکمه ###
    system_prompt = (
        "تو یک نقال داستان‌گو هستی. داستان را با زبانی ساده و دوستانه و با **تمرکز بر مخاطب (استفاده از ضمیر تو/شما)** بنویس. "
        "**هر بخش داستان باید مختصر و در نهایت به یک چالش ختم شود.** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. این فرمت [1. ] برای شناسایی دکمه‌ها توسط ربات الزامی است.**"
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
            max_tokens=2000 # افزایش بیشتر برای اطمینان از کامل شدن
        )
        
        full_response = ""
        chunk_message = await update.message.reply_text("نقال در حال سرودن شعر است...")
        
        for chunk in response:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                full_response += chunk_content
                try:
                    await context.bot.edit_message_text(text=full_response, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)
                except Exception:
                    pass

        story_text, options = extract_options(full_response)
        
        # ویرایش نهایی متن بدون گزینه‌های [1.] و [2.]
        await context.bot.edit_message_text(text=story_text, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)
        
        # نمایش دکمه‌ها
        if options:
            reply_keyboard = [[opt] for opt in options]
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=False)
            await update.message.reply_text("تصمیم تو چیست؟", reply_markup=markup)
        else:
            await update.message.reply_text("نقال منتظر پاسخ شماست! پاسخ خود را تایپ کنید یا /cancel را بزنید.", reply_markup=ReplyKeyboardRemove())
        
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
    if client is None:
        await update.message.reply_text("خطایی در اتصال به نقال (مدل هوش مصنوعی) رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

    user_input = update.message.text
    history = context.user_data["history"]

    # افزودن پاسخ کاربر به تاریخچه
    history.append({"role": "user", "content": user_input})
    await update.message.reply_text("نقال در حال اندیشیدن به ادامه سرنوشت توست...", reply_markup=ReplyKeyboardRemove()) # دکمه‌های قبلی را بردار

    # ### به‌روزرسانی دستورالعمل سیستمی برای حفظ فشار بر هوش مصنوعی ###
    current_system_prompt = (
        "تو یک نقال داستان‌گو هستی. داستان را با زبانی ساده و دوستانه و با **تمرکز بر مخاطب (استفاده از ضمیر تو/شما)** ادامه بده. "
        "**هر بخش داستان باید مختصر و در نهایت به یک چالش ختم شود.** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. این فرمت [1. ] برای شناسایی دکمه‌ها توسط ربات الزامی است.**"
    )
    # جایگزین کردن پیام سیستم قدیمی در تاریخچه
    if history[0]["role"] == "system":
        history[0]["content"] = current_system_prompt
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=history,
            stream=True,
            max_tokens=2000
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
                    pass

        story_text, options = extract_options(full_response)
        
        # ویرایش نهایی متن بدون گزینه‌های [1.] و [2.]
        await context.bot.edit_message_text(text=story_text, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)

        # نمایش دکمه‌ها
        if options:
            reply_keyboard = [[opt] for opt in options]
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=False)
            await update.message.reply_text("تصمیم تو چیست؟", reply_markup=markup)
        else:
            await update.message.reply_text("لطفاً پاسخ خود را تایپ کنید تا داستان ادامه یابد.", reply_markup=ReplyKeyboardRemove())

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
    logger.info("ربات در حال آغاز به کار است... (نسخه نهایی: تعاملی با دکمه)")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
