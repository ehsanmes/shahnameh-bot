import os
import logging
from avalai.llms import LLM, AvAITChat, PromptMessage, PromptMessageRole
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
# تنظیم لاگر کتابخانه تلگرام روی سطح بالاتر برای جلوگیری از اسپم لاگ
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# گرفتن کلیدهای API از متغیرهای محیطی
# این کلیدها باید در Railway در بخش "Variables" تنظیم شوند
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")

# تعریف حالت‌های مکالمه
ROLE_STATE, STORY_STATE = range(2)

# ========== تابع شروع (بازنویسی شده طبق درخواست شما) ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه و ایجاد زمینه داستانی."""
    
    # ۱. ایجاد زمینه داستانی
    story_context = (
        "سلام! من نقال شاهنامه هستم و تو به قلب داستان‌های حماسی ایران پا گذاشته‌ای.\n\n"
        "هنگامه‌ای است بس شگرف! تورانیان به مرزهای ایران تاخته‌اند، "
        "دیو سپید در مازندران بند بر پای پهلوانان نهاده، و شاه کاووس در بند است.\n\n"
        "سرنوشت ایران‌زمین در دستان توست."
    )
    await update.message.reply_text(story_context)
    
    # ۲. درخواست نقش با مثال‌های متنوع
    await update.message.reply_text(
        "نقش تو در این داستان چیست؟\n"
        "نام یکی از پهلوانان، شاهان، یا دلیران شاهنامه را برای من بنویس تا داستان اختصاصی تو را آغاز کنم.\n\n"
        "مثلاً: رستم، سهراب، گودرز، فرنگیس، گردآفرید، سیاوش، منیژه"
    )
    
    return ROLE_STATE
# =========================================================

async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ذخیره نقش انتخاب شده و شروع داستان."""
    user_role = update.message.text
    context.user_data["role"] = user_role
    
    logger.info(f"نقش انتخاب شده توسط کاربر: {user_role}")

    # ایجاد یک نمونه از مدل زبان
    try:
        model = AvAITChat(api_key=AVALAI_API_KEY)
    except Exception as e:
        logger.error(f"خطا در ساخت مدل AvalAI: {e}")
        await update.message.reply_text("خطایی در اتصال به نقال (مدل هوش مصنوعی) رخ داد. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

    context.user_data["model"] = model
    context.user_data["history"] = [] # تاریخچه گفتگو

    await update.message.reply_text(
        f"عالی! تو اکنون «{user_role}» هستی. بگذار داستان تو را آغاز کنم...\n\n"
        "پرده اول: در اعماق داستان...\n\n"
        "(لطفا چند لحظه صبر کن تا اولین بخش از سرنوشت تو را روایت کنم...)",
        reply_markup=ReplyKeyboardRemove(),
    )

    # ساخت اولین پیام برای مدل
    system_prompt = (
        "تو یک نقال حماسی شاهنامه هستی. کاربر نقش یکی از شخصیت‌های شاهنامه را انتخاب کرده است. "
        "تو باید یک داستان تعاملی کوتاه بر اساس آن نقش برای او روایت کنی. "
        "داستان باید پر از توصیفات حماسی و به زبان ادبیات کهن ایران باشد. "
        "هر بخش از داستان را با یک چالش یا یک انتخاب برای کاربر تمام کن."
    )
    
    first_prompt = f"داستان من را به عنوان «{user_role}» آغاز کن. اولین صحنه و اولین چالش من چه خواهد بود؟"
    
    # افزودن به تاریخچه
    context.user_data["history"].append(PromptMessage(role=PromptMessageRole.SYSTEM, content=system_prompt))
    context.user_data["history"].append(PromptMessage(role=PromptMessageRole.USER, content=first_prompt))

    # ارسال درخواست به API
    try:
        response_stream = model.chat_stream(
            system=system_prompt,
            prompt=first_prompt
        )
        
        full_response = ""
        for chunk in response_stream:
            full_response += chunk

        context.user_data["history"].append(PromptMessage(role=PromptMessageRole.ASSISTANT, content=full_response))
        await update.message.reply_text(full_response)
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در set_role: {e}")
        # بررسی خطای 401 به صورت مشخص
        if "401" in str(e):
             await update.message.reply_text("خطا در ارتباط با نقال (ارور 401). به نظر می‌رسد کلید API معتبر نیست.")
        else:
            await update.message.reply_text(f"خطایی در روایت داستان رخ داد: {e}")
        return ConversationHandler.END

    return STORY_STATE

async def handle_story(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ادامه داستان بر اساس ورودی کاربر."""
    user_input = update.message.text
    model = context.user_data["model"]
    history = context.user_data["history"]

    # افزودن پاسخ کاربر به تاریخچه
    history.append(PromptMessage(role=PromptMessageRole.USER, content=user_input))

    await update.message.reply_text("نقال در حال اندیشیدن به ادامه سرنوشت توست...")

    # ارسال تاریخچه به API
    try:
        response_stream = model.chat_stream_history(history=history)
        
        full_response = ""
        for chunk in response_stream:
            full_response += chunk

        # افزودن پاسخ مدل به تاریخچه
        history.append(PromptMessage(role=PromptMessageRole.ASSISTANT, content=full_response))
        await update.message.reply_text(full_response)
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در handle_story: {e}")
        await update.message.reply_text(f"خطایی در ادامه داستان رخ داد: {e}")
        return ConversationHandler.END

    return STORY_STATE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پایان دادن به مکالمه."""
    await update.message.reply_text(
        "بدرود! باشد که در داستانی دیگر تو را ببینم.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main() -> None:
    """اجرای ربات."""
    
    # بررسی وجود توکن‌ها قبل از اجرا
    if not TELEGRAM_BOT_TOKEN:
        logger.fatal("متغیر TELEGRAM_BOT_TOKEN پیدا نشد. ربات نمی‌تواند اجرا شود.")
        return
        
    if not AVALAI_API_KEY:
        logger.fatal("متغیر AVALAI_API_KEY پیدا نشد. ربات نمی‌تواند اجرا شود.")
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
    logger.info("ربات در حال آغاز به کار است...")
    application.run_polling()

if __name__ == "__main__":
    main()
