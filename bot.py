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
# تابع کمکی برای استخراج گزینه‌ها از متن هوش مصنوعی
# =========================================================
def extract_options(text: str) -> tuple[str, str]:
    """
    متن داستان را تجزیه کرده و گزینه‌های انتخابی را (که با [1.]، [2.] و [3.] مشخص شده‌اند) استخراج می‌کند.
    """
    
    # الگوی رگولار اکسپرشن برای پیدا کردن گزینه های [عدد. متن]
    # ما همچنان این الگو را نگه می‌داریم تا گزینه‌هایی که هوش مصنوعی تولید می‌کند را از بدنه متن جدا کنیم.
    pattern = re.compile(r"\[(\d+)\.\s*(.+?)\]")
    
    matches = pattern.findall(text)
    
    options_list = []
    
    if matches:
        # ساخت لیست گزینه‌ها به صورت رشته متنی شماره‌دار با خط جدید
        for num, opt in matches:
            options_list.append(f"{num}- {opt.strip()}")
            
        # حذف گزینه‌ها از متن اصلی داستان
        story_text = pattern.sub(r"", text).strip()
        
        # ترکیب گزینه‌ها در یک رشته برای نمایش (با خط جدید)
        options_text = "\n" + "\n".join(options_list)
    else:
        story_text = text
        options_text = ""

    # اگر هوش مصنوعی پایان داستان را مشخص کند
    if "پایان داستان" in story_text or "داستان به پایان رسید" in story_text:
         options_text += "\n\n داستان به پایان رسید. برای شروع دوباره /start را بزنید."
         
    return story_text, options_text

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

    # دستورالعمل سیستمی نهایی: وفاداری به شاهنامه و اجبار به فرمت دکمه و کوتاهی
    system_prompt = (
        "تو یک نقال حماسی و باوفا به شاهنامه هستی. "
        "داستان را با **ادبیاتی ساده و روان مبتنی بر زبان شاهنامه** روایت کن. "
        "فقط از وقایع، شخصیت‌ها، و مکان‌های مرتبط با جهان شاهنامه استفاده کن. "
        "با **تمرکز بر مخاطب (تو/شما)** داستان را پیش ببر. "
        "**هر بخش داستان باید بسیار مختصر باشد (حداکثر ۴ جمله).** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. این فرمت [1. ] الزامی است. کاربر با ارسال عدد مربوطه انتخاب می‌کند.**"
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

        story_text, options_text = extract_options(full_response)
        
        # ویرایش نهایی متن با گزینه‌های متنی شماره‌دار
        final_text = story_text
        if options_text:
            final_text += "\n\nتصمیم تو چیست؟ (فقط عدد را بفرست)\n"
            final_text += options_text
            
        await context.bot.edit_message_text(text=final_text, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)
        
        context.user_data["history"].append({"role": "assistant", "content": full_response})
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در set_role: {e}")
        await update.message.reply_text(f"خطایی در روایت داستان رخ داد: {e}")
        return ConversationHandler.END

    return STORY_STATE

async def handle_story(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ادامه داستان بر اساس ورودی کاربر (پاسخ عددی یا متنی)."""
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
        "داستان را با **ادبیاتی ساده و روان مبتنی بر زبان شاهنامه** روایت کن. "
        "فقط از وقایع، شخصیت‌ها، و مکان‌های مرتبط با جهان شاهنامه استفاده کن. "
        "با **تمرکز بر مخاطب (تو/شما)** داستان را پیش ببر. "
        "**هر بخش داستان باید بسیار مختصر باشد (حداکثر ۴ جمله).** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. این فرمت [1. ] الزامی است. کاربر با ارسال عدد مربوطه انتخاب می‌کند.**"
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

        story_text, options_text = extract_options(full_response)
        
        # ویرایش نهایی متن با گزینه‌های متنی شماره‌دار
        final_text = story_text
        if options_text:
            final_text += "\n\nتصمیم تو چیست؟ (فقط عدد را بفرست)\n"
            final_text += options_text
            
        await context.bot.edit_message_text(text=final_text, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)

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
            # فیلتر برای حالت داستان‌گویی برای پذیرش عدد یا متن
            STORY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_story)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    logger.info("ربات در حال آغاز به کار است... (نسخه نهایی: تعاملی و بهینه‌سازی شده)")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
