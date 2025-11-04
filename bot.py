import os
import re
import logging
import asyncio 
from openai import OpenAI
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton # <-- دکمه‌های شیشه‌ای
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler, # <-- مدیریت دکمه‌های شیشه‌ای
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
            base_url="https://api.avalai.ir/v1",
            timeout=20.0 # <-- تغییر نهایی: افزایش زمان‌بندی به ۲۰ ثانیه
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
    متن داستان را تجزیه کرده و گزینه‌های انتخابی را استخراج می‌کند.
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
# توابع مکالمه اصلی
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه و ایجاد دکمه‌های نقش."""
    
    # دکمه‌های اولیه انتخاب نقش از نوع ReplyKeyboardMarkup باقی می‌مانند
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
    
    # 1. ارسال پیام خوش‌آمدگویی نهایی و حذف دکمه‌های Reply
    await update.message.reply_text(
        f"عالی! تو اکنون «{user_role}» هستی. بگذار داستان تو را آغاز کنم...",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # 2. ارسال پیام موقت مجزا برای شروع ویرایش
    initial_message = await update.message.reply_text(
        "(لطفا چند لحظه صبر کن تا اولین بخش از سرنوشت تو را روایت کنم...)"
    )

    # ### اصلاحیه نهایی ادبیات: استفاده از عبارت 'داستان‌گویی امروزی' برای لحن روانتر ###
    system_prompt = (
        "تو یک نقال حماسی و باوفا به شاهنامه هستی. "
        "داستان را به صورت یک داستان‌گوی حرفه‌ای و با **ادبیاتی ساده، روان و روایت‌گونه (مثل داستان‌گویی امروزی با تم حماسی)** روایت کن. "
        "فقط از وقایع، شخصیت‌ها، و مکان‌های مرتبط با جهان شاهنامه استفاده کن. "
        "با **تمرکز بر مخاطب (تو/شما)** داستان را پیش ببر. "
        "**هر بخش داستان باید بسیار مختصر باشد (حداکثر ۴ جمله).** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. متن داخل براکت‌ها باید بسیار کوتاه (حداکثر ۵ کلمه) باشد.**"
    )
    
    first_prompt = f"داستان من را به عنوان «{user_role}» آغاز کن. اولین صحنه و اولین چالش من چه خواهد بود؟"
    
    context.user_data["history"] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": first_prompt}
    ]

    try:
        # درخواست به API (بدون استریم برای پایداری)
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=context.user_data["history"],
            stream=False, 
            max_tokens=2000 
        )
        
        full_response = response.choices[0].message.content
        
        story_text, options = extract_options(full_response)
        
        # نمایش دکمه‌ها (از نوع شیشه‌ای)
        if options and options != ["/start"]:
            keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in options]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # ویرایش پیام موقت به متن داستان
            await initial_message.edit_text(story_text)
            
            # ارسال پیام جدید برای دکمه‌های شیشه‌ای
            await update.message.reply_text("تصمیم تو چیست؟", reply_markup=reply_markup)
        else:
            final_message = story_text + ("\n\nبرای شروع دوباره /start را بزنید." if "/start" in options else "")
            
            # ویرایش پیام موقت به متن داستان نهایی
            await initial_message.edit_text(final_message, reply_markup=None)
        
        context.user_data["history"].append({"role": "assistant", "content": full_response})
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در set_role: {e}")
        # ویرایش پیام موقت به پیام خطا
        await initial_message.edit_text(f"خطایی در روایت داستان رخ داد: {e}", reply_markup=None)
        return ConversationHandler.END

    return STORY_STATE

# =========================================================
# تابع جدید: مدیریت کلیک روی دکمه شیشه‌ای
# =========================================================
async def handle_inline_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """مدیریت انتخاب گزینه از دکمه‌های شیشه‌ای."""
    query = update.callback_query
    await query.answer() # حذف حالت loading از دکمه

    user_choice = query.data
    
    # 1. حذف دکمه‌های شیشه‌ای پس از کلیک (بسیار مهم)
    await query.edit_message_reply_markup(reply_markup=None)
    
    # 2. ارسال انتخاب کاربر به عنوان پیام جدید
    await context.bot.send_message(query.message.chat_id, f"تو انتخاب کردی: {user_choice}")
    
    # 3. آماده‌سازی تاریخچه و ارسال پیام موقت
    history = context.user_data.get("history")
    if not history:
        await context.bot.send_message(query.message.chat_id, "متاسفانه تاریخچه گفتگو پیدا نشد. لطفا /start را بزنید.")
        return ConversationHandler.END

    history.append({"role": "user", "content": user_choice})
    initial_message = await context.bot.send_message(query.message.chat_id, "نقال در حال اندیشیدن به ادامه سرنوشت توست...")

    # 4. به‌روزرسانی دستورالعمل سیستمی
    current_system_prompt = (
        "تو یک نقال حماسی و باوفا به شاهنامه هستی. "
        "داستان را به صورت یک داستان‌گوی حرفه‌ای و با **ادبیاتی ساده، روان و کاملاً روایت‌گونه مبتنی بر زبان شاهنامه** روایت کن. "
        "فقط از وقایع، شخصیت‌ها، و مکان‌های مرتبط با جهان شاهنامه استفاده کن. "
        "با **تمرکز بر مخاطب (تو/شما)** داستان را پیش ببر. "
        "**هر بخش داستان باید بسیار مختصر باشد (حداکثر ۴ جمله).** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. متن داخل براکت‌ها باید بسیار کوتاه (حداکثر ۵ کلمه) باشد.**"
    )
    if history[0]["role"] == "system":
        history[0]["content"] = current_system_prompt

    # 5. درخواست به API
    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=history,
            stream=False, 
            max_tokens=2000
        )
        
        full_response = response.choices[0].message.content
        
        story_text, options = extract_options(full_response)
        
        # 6. نمایش نهایی متن و دکمه‌ها
        if options and options != ["/start"]:
            keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in options]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await initial_message.edit_text(story_text)
            
            await context.bot.send_message(query.message.chat_id, "تصمیم تو چیست؟", reply_markup=reply_markup)
        else:
            final_message = story_text + ("\n\nبرای شروع دوباره /start را بزنید." if "/start" in options else "")
            await initial_message.edit_text(final_message, reply_markup=None)

        history.append({"role": "assistant", "content": full_response})
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در handle_inline_button: {e}")
        await initial_message.edit_text(f"خطایی در روایت داستان رخ داد: {e}", reply_markup=None)
        return ConversationHandler.END

    return STORY_STATE

async def handle_story(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ادامه داستان بر اساس ورودی کاربر (فقط برای متن‌های تایپ شده)."""
    
    if client is None:
        await update.message.reply_text("خطایی در اتصال به نقال رخ داده است. لطفا دوباره تلاش کنید.")
        return ConversationHandler.END

    user_input = update.message.text
    history = context.user_data["history"]

    history.append({"role": "user", "content": user_input})
    
    # پیام موقت برای شروع
    initial_message = await update.message.reply_text("نقال در حال اندیشیدن به ادامه سرنوشت توست...", reply_markup=ReplyKeyboardRemove()) 

    # به‌روزرسانی دستورالعمل سیستمی برای حفظ فشار بر هوش مصنوعی
    current_system_prompt = (
        "تو یک نقال حماسی و باوفا به شاهنامه هستی. "
        "داستان را به صورت یک داستان‌گوی حرفه‌ای و با **ادبیاتی ساده، روان و کاملاً روایت‌گونه مبتنی بر زبان شاهنامه** روایت کن. "
        "فقط از وقایع، شخصیت‌ها، و مکان‌های مرتبط با جهان شاهنامه استفاده کن. "
        "با **تمرکز بر مخاطب (تو/شما)** داستان را پیش ببر. "
        "**هر بخش داستان باید بسیار مختصر باشد (حداکثر ۴ جمله).** "
        "**پس از اتمام داستان، حتماً ۳ گزینه انتخابی جدید برای ادامه داستان به صورت [1. متن گزینه] [2. متن گزینه] [3. متن گزینه] ارائه کن. متن داخل براکت‌ها باید بسیار کوتاه (حداکثر ۵ کلمه) باشد.**"
    )
    if history[0]["role"] == "system":
        history[0]["content"] = current_system_prompt
    
    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=history,
            stream=False,
            max_tokens=2000
        )
        
        full_response = response.choices[0].message.content

        story_text, options = extract_options(full_response)
        
        if options and options != ["/start"]:
            keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in options]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await initial_message.edit_text(story_text)
            
            await update.message.reply_text("تصمیم تو چیست؟", reply_markup=reply_markup)
        else:
            final_message = story_text + ("\n\nبرای شروع دوباره /start را بزنید." if "/start" in options else "")
            await initial_message.edit_text(final_message, reply_markup=None)

        history.append({"role": "assistant", "content": full_response})
        
    except Exception as e:
        logger.error(f"خطا در ارتباط با API در handle_story: {e}")
        await initial_message.edit_text(f"خطایی در روایت داستان رخ داد: {e}", reply_markup=None)
        return ConversationHandler.END

    return STORY_STATE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پایان دادن به مکالمه."""
    await update.message.reply_text(
        "بدرود! باشد که در داستانی دیگر تو را ببینم.",
        reply_markup=ReplyKeyboardRemove()
    )
    # حذف دکمه‌های شیشه‌ای (اگر وجود دارند)
    try:
        await context.bot.edit_message_reply_markup(update.effective_chat.id, update.effective_message.message_id, reply_markup=None)
    except Exception:
        pass
        
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
            STORY_STATE: [
                CallbackQueryHandler(handle_inline_button), # <-- مدیریت دکمه‌های شیشه‌ای
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_story), # برای پاسخ‌های تایپی
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    logger.info("ربات در حال آغاز به کار است... (نسخه نهایی: Inline Keyboard)")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
