import os
import logging
from openai import OpenAI  # <--- کلید حل مشکل: استفاده از کتابخانه رسمی OpenAI
from telegram import Update
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
# کاهش لاگ‌های اضافه کتابخانه‌ها
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# --- گرفتن کلیدهای API از متغیرهای محیطی ---
# اینها باید در داشبورد Railway در تب "Variables" تنظیم شوند
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")

# --- راه‌اندازی کلاینت OpenAI برای اتصال به AvalAI ---
# این بخش دقیقاً طبق مستندات AvalAI عمل می‌کند
client = None
if AVALAI_API_KEY:
    try:
        client = OpenAI(
            api_key=AVALAI_API_KEY,
            base_url="https://api.avalai.ir/v1"  # <--- آدرس API یکپارچه AvalAI
        )
        logger.info("کلاینت AvalAI با موفقیت ساخته شد.")
    except Exception as e:
        logger.error(f"امکان ساخت کلاینت OpenAI (AvalAI) وجود نداشت: {e}")
else:
    logger.error("متغیر AVALAI_API_KEY پیدا نشد.")
# ===============================================================

# تعریف حالت‌های مکالمه
ROLE_STATE, STORY_STATE = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه و ایجاد زمینه داستانی (نسخه اصلاح شده شما)."""
    
    # ۱. ایجاد زمینه داستانی
    story_context = (
        "سلام! من نقال شاهنامه هستم و تو به قلب داستان‌های حماسی ایران پا گذاشته‌ای.\n\n"
        "هنگامه‌ای است بس شگرف! تورانیان به مرزهای ایران تاخته‌اند، "
        "دیو سپید در مازندران بند بر پای پهلوانان نهاده، و شاه کاووس در بند است.\n\n"
        "سرنوشت ایران‌زمین در دستان توست."
    )
    await update.message.reply_text(story_context)
    
    # ۲. درخواست نقش با مثال‌های متنوع (کلمه "مانند" حذف شد)
    await update.message.reply_text(
        "نقش تو در این داستان چیست؟\n"
        "نام یکی از پهلوانان، شاهان، یا دلیران شاهنامه را انتخاب کن تا داستان اختصاصی تو را آغاز کنم.\n\n"
        "مثلاً: رستم، سهراب، گودرز، فرنگیس، گردآفرید، سیاوش، منیژه"
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

    await update.message.reply_text(
        f"عالی! تو اکنون «{user_role}» هستی. بگذار داستان تو را آغاز کنم...\n\n"
        "(لطفا چند لحظه صبر کن تا اولین بخش از سرنوشت تو را روایت کنم...)"
    )

    # ساخت اولین پیام برای مدل (فرمت جدید OpenAI)
    system_prompt = (
        "تو یک نقال حماسی شاهنامه هستی. کاربر نقش یکی از شخصیت‌های شاهنامه را انتخاب کرده است. "
        "تو باید یک داستان تعاملی کوتاه بر اساس آن نقش برای او روایت کنی. "
        "داستان باید پر از توصیفات حماسی و به زبان ادبیات کهن ایران باشد. "
        "هر بخش از داستان را با یک چالش یا یک انتخاب برای کاربر تمام کن."
    )
    
    first_prompt = f"داستان من را به عنوان «{user_role}» آغاز کن. اولین صحنه و اولین چالش من چه خواهد بود؟"
    
    # تاریخچه گفتگو (فرمت جدید OpenAI)
    context.user_data["history"] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": first_prompt}
    ]

    # ارسال درخواست به API (روش جدید OpenAI)
    try:
        # ما از مدل gpt-4o-mini استفاده می‌کنیم که در لیست AvalAI ارزان و سریع بود
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=context.user_data["history"],
            stream=True  # فعال کردن حالت استریم (تایپ کردن)
        )
        
        full_response = ""
        # یک پیام موقت خالی ارسال می‌کنیم تا بعداً آن را ویرایش کنیم
        chunk_message = await update.message.reply_text("نقال در حال سرودن شعر است...")
        
        for chunk in response:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                full_response += chunk_content
                # ویرایش پیام قبلی برای ایجاد افکت استریم
                await context.bot.edit_message_text(text=full_response, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)

        # ذخیره پاسخ کامل در تاریخچه
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

    # افزودن پاسخ کاربر به تاریخچه
    history.append({"role": "user", "content": user_input})
    await update.message.reply_text("نقال در حال اندیشیدن به ادامه سرنوشت توست...")

    # ارسال تاریخچه به API
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=history,
            stream=True
        )
        
        full_response = ""
        chunk_message = await update.message.reply_text("...")

        for chunk in response:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                full_response += chunk_content
                await context.bot.edit_message_text(text=full_response, chat_id=update.effective_chat.id, message_id=chunk_message.message_id)

        # افزودن پاسخ مدل به تاریخچه
        history.append({"role": "assistant", "content": full_response})
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در handle_story: {e}")
        await update.message.reply_text(f"خطایی در ادامه داستان رخ داد: {e}")
        return ConversationHandler.END

    return STORY_STATE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پایان دادن به مکالمه."""
    await update.message.reply_text(
        "بدرود! باشد که در داستانی دیگر تو را ببینم."
    )
    return ConversationHandler.END

def main() -> None:
    """اجرای ربات."""
    
    # بررسی نهایی متغیرها قبل از اجرا
    if not TELEGRAM_BOT_TOKEN:
        logger.fatal("متغیر TELEGRAM_BOT_TOKEN پیدا نشد. ربات متوقف می‌شود.")
        return
        
    if not AVALAI_API_KEY:
        logger.fatal("متغیر AVALAI_API_KEY پیدا نشد. ربات متوقف می‌شود.")
        return
        
    if client is None:
        logger.fatal("کلاینت AvalAI (OpenAI) به درستی ساخته نشد. ربات متوقف می‌شود.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # تعریف ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ROLE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_role)],
            STORY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_story)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # نمایش لاگ آغاز به کار
    logger.info("ربات در حال آغاز به کار است... (با استفاده از کتابخانه OpenAI)")
    
    # اجرای ربات
    application.run_polling()

if __name__ == "__main__":
    main()
