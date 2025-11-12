import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackContext, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
from datetime import time, datetime, timedelta
import asyncio

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# مراحل ثبت دارو
MED_NAME, DOSAGE, TIME, FREQUENCY = range(4)

# --- راه‌اندازی دیتابیس ---
def init_db():
    conn = sqlite3.connect('medbot.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS medications
                 (med_id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_id INTEGER, 
                  name TEXT, 
                  dosage TEXT,
                  time TEXT,
                  frequency TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    conn.commit()
    conn.close()
    print("✅ دیتابیس راه‌اندازی شد")

# --- کیبورد شیشه‌ای اصلی ---
def create_main_keyboard():
    keyboard = [
        [KeyboardButton("💊 اضافه کردن دارو"), KeyboardButton("📋 داروهای من")],
        [KeyboardButton("🧪 تست یادآوری فوری"), KeyboardButton("ℹ️ راهنما")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def create_cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ لغو")]], resize_keyboard=True)

def create_time_suggestions():
    keyboard = [
        [KeyboardButton("08:00"), KeyboardButton("12:00"), KeyboardButton("18:00")],
        [KeyboardButton("08:30"), KeyboardButton("12:30"), KeyboardButton("18:30")],
        [KeyboardButton("09:00"), KeyboardButton("13:00"), KeyboardButton("19:00")],
        [KeyboardButton("❌ لغو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- زمان‌بندی یادآوری ---
def schedule_reminder(application: Application, user_id: int, med_name: str, dosage: str, time_str: str):
    try:
        print(f"⏰ در حال زمان‌بندی یادآوری برای {med_name} در {time_str}...")
        
        hour, minute = map(int, time_str.split(':'))
        trigger_time = time(hour, minute)
        
        # حذف یادآوری‌های قدیمی
        job_name = f"reminder_{user_id}_{med_name}"
        for job in application.job_queue.jobs():
            if job.name == job_name:
                job.schedule_removal()
                print(f"🗑️ یادآوری قدیمی حذف شد: {job_name}")
        
        # زمان‌بندی جدید
        application.job_queue.run_daily(
            send_reminder,
            time=trigger_time,
            days=tuple(range(7)),
            data={
                'user_id': user_id, 
                'med_name': med_name, 
                'dosage': dosage,
                'time': time_str
            },
            name=job_name
        )
        
        print(f"✅ یادآوری برای {med_name} در {time_str} تنظیم شد")
        logger.info(f"✅ یادآوری برای {med_name} در {time_str} تنظیم شد")
        
        # چک کن که job واقعاً اضافه شده
        for job in application.job_queue.jobs():
            if job.name == job_name:
                print(f"✅ Job فعال: {job.name} - زمان بعدی: {job.next_t}")
        
    except Exception as e:
        print(f"❌ خطا در زمان‌بندی: {e}")
        logger.error(f"❌ خطا در زمان‌بندی: {e}")

# --- ارسال یادآوری ---
async def send_reminder(context: CallbackContext):
    try:
        job = context.job
        user_id = job.data['user_id']
        med_name = job.data['med_name']
        dosage = job.data['dosage']
        time_str = job.data['time']
        
        print(f"🔔 ارسال یادآوری برای کاربر {user_id} - دارو: {med_name}")
        
        reminder_text = f"""
🔔 **یادآوری مصرف دارو از ash**

💊 دارو: {med_name}
📏 مقدار: {dosage}
🕒 زمان: {time_str}

⚠️ لطفاً فوراً داروی خود را مصرف کنید.
"""

        keyboard = [
            [InlineKeyboardButton("✅ تأیید مصرف", callback_data=f"confirm_{user_id}_{med_name}")],
            [InlineKeyboardButton("⏰ یادآوری بعدی (5 دقیقه)", callback_data=f"snooze_{user_id}_{med_name}")]
        ]
        
        await context.bot.send_message(
            chat_id=user_id, 
            text=reminder_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        print(f"✅ یادآوری برای کاربر {user_id} ارسال شد")
        logger.info(f"✅ یادآوری برای کاربر {user_id} ارسال شد")
        
    except Exception as e:
        print(f"❌ خطا در ارسال یادآوری: {e}")
        logger.error(f"❌ خطا در ارسال یادآوری: {e}")

# --- بارگذاری یادآوری‌های موجود ---
def load_existing_reminders(application: Application):
    try:
        conn = sqlite3.connect('medbot.db')
        c = conn.cursor()
        c.execute('''SELECT user_id, name, dosage, time, frequency FROM medications''')
        medicines = c.fetchall()
        conn.close()
        
        print(f"📥 در حال بارگذاری {len(medicines)} یادآوری از دیتابیس...")
        
        for user_id, med_name, dosage, time_str, frequency in medicines:
            schedule_reminder(application, user_id, med_name, dosage, time_str)
        
        print(f"✅ {len(medicines)} یادآوری از دیتابیس بارگذاری شد")
        
    except Exception as e:
        print(f"❌ خطا در بارگذاری یادآوری‌ها: {e}")

# --- دستور start ---
async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    name = update.effective_user.first_name
    
    conn = sqlite3.connect('medbot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, name, username) VALUES (?, ?, ?)", 
              (user_id, name, update.effective_user.username or ""))
    conn.commit()
    conn.close()
    
    welcome_text = f"""
👋 سلام {name} عزیز!

به ربات ash خوش آمدید! 🤖
من اینجام تا به شما در مصرف به موقع داروهایتان کمک کنم.

💊 **خدمات من:**
• یادآوری مصرف داروها
• مدیریت برنامه دارویی
• پیگیری مصرف روزانه

🛠️ **از کیبورد زیر استفاده کنید:**
"""

    await update.message.reply_text(welcome_text, reply_markup=create_main_keyboard())

# --- مدیریت پیام‌های متنی ---
async def handle_text_messages(update: Update, context: CallbackContext):
    text = update.message.text
    
    if text == "💊 اضافه کردن دارو":
        await start_add_medicine(update, context)
    
    elif text == "📋 داروهای من":
        await show_my_medicines_text(update, context)
    
    elif text == "🧪 تست یادآوری فوری":
        await test_reminder_instant(update, context)
    
    elif text == "ℹ️ راهنما":
        await show_help_text(update, context)
    
    elif text == "❌ لغو":
        await cancel_operation(update, context)
    
    elif text in ["08:00", "08:30", "09:00", "12:00", "12:30", "13:00", "18:00", "18:30", "19:00"]:
        context.user_data['time'] = text
        await update.message.reply_text(
            f"✅ زمان مصرف **{text}** ثبت شد.\n\nدارو با موفقیت ثبت شد! از این به بعد هر روز این زمان یادآوری دریافت می‌کنید.",
            reply_markup=create_main_keyboard()
        )
        return await save_medicine(update, context)
    
    else:
        # اگر زمان دستی وارد شده
        if 'waiting_for_time' in context.user_data:
            time_str = text
            try:
                hour, minute = map(int, time_str.split(':'))
                if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                    raise ValueError
                context.user_data['time'] = time_str
                await update.message.reply_text(
                    f"✅ زمان مصرف **{time_str}** ثبت شد.\n\nدارو با موفقیت ثبت شد! از این به بعد هر روز این زمان یادآوری دریافت می‌کنید.",
                    reply_markup=create_main_keyboard()
                )
                return await save_medicine(update, context)
            except:
                await update.message.reply_text(
                    "❌ فرمت زمان نامعتبر است. لطفاً به فرمت HH:MM وارد کنید (مثلاً: 08:00) یا از پیشنهادات انتخاب کنید:",
                    reply_markup=create_time_suggestions()
                )
                return TIME

# --- شروع ثبت داروی جدید ---
async def start_add_medicine(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "💊 **ثبت داروی جدید**\n\nلطفاً نام دارو را وارد کنید:",
        reply_markup=create_cancel_keyboard()
    )
    return MED_NAME

# --- دریافت نام دارو ---
async def get_med_name(update: Update, context: CallbackContext):
    med_name = update.message.text
    context.user_data['med_name'] = med_name
    await update.message.reply_text(
        f"✅ نام دارو **{med_name}** ثبت شد.\n\nلطفاً مقدار مصرف را وارد کنید (مثلاً: 1 قرص، 2 شربت):",
        reply_markup=create_cancel_keyboard()
    )
    return DOSAGE

# --- دریافت مقدار مصرف ---
async def get_dosage(update: Update, context: CallbackContext):
    dosage = update.message.text
    context.user_data['dosage'] = dosage
    context.user_data['waiting_for_time'] = True
    await update.message.reply_text(
        f"✅ مقدار مصرف **{dosage}** ثبت شد.\n\nلطفاً ساعت مصرف را وارد کنید یا از پیشنهادات زیر انتخاب کنید:",
        reply_markup=create_time_suggestions()
    )
    return TIME

# --- ذخیره دارو ---
async def save_medicine(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    med_name = context.user_data['med_name']
    dosage = context.user_data['dosage']
    time_str = context.user_data['time']
    
    conn = sqlite3.connect('medbot.db')
    c = conn.cursor()
    c.execute('''INSERT INTO medications (user_id, name, dosage, time, frequency) VALUES (?, ?, ?, ?, ?)''', 
              (user_id, med_name, dosage, time_str, "daily"))
    conn.commit()
    conn.close()
    
    # زمان‌بندی یادآوری
    schedule_reminder(context.application, user_id, med_name, dosage, time_str)
    
    # پاک کردن داده‌های موقت
    context.user_data.clear()
    
    return ConversationHandler.END

# --- نمایش داروها ---
async def show_my_medicines_text(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('medbot.db')
    c = conn.cursor()
    c.execute('''SELECT name, dosage, time, frequency FROM medications WHERE user_id = ?''', (user_id,))
    medicines = c.fetchall()
    conn.close()
    
    if not medicines:
        await update.message.reply_text(
            "📝 هنوز هیچ دارویی ثبت نکرده‌اید.",
            reply_markup=create_main_keyboard()
        )
        return
    
    medicines_text = "💊 **داروهای شما:**\n\n"
    for i, (name, dosage, time_str, freq) in enumerate(medicines, 1):
        medicines_text += f"{i}. **{name}**\n   📏 {dosage}\n   ⏰ {time_str}\n   🔄 روزانه\n\n"
    
    await update.message.reply_text(medicines_text, reply_markup=create_main_keyboard())

# --- تست یادآوری فوری ---
async def test_reminder_instant(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    print(f"🧪 درخواست تست یادآوری از کاربر {user_id}")
    
    # ارسال فوری یادآوری تستی
    test_text = "🧪 **یادآوری تستی از ash**\n\nاین یک یادآوری تست فوری است! ✅\n\nاگر این پیام رو می‌بینید، یادآوری کار می‌کند!"
    
    try:
        await context.bot.send_message(chat_id=user_id, text=test_text)
        await update.message.reply_text(
            "✅ یادآوری تستی ارسال شد! اگر پیام رو دریافت کردید، سیستم یادآوری کار می‌کند.",
            reply_markup=create_main_keyboard()
        )
        print(f"✅ تست یادآوری برای کاربر {user_id} ارسال شد")
    except Exception as e:
        await update.message.reply_text(
            "❌ خطا در ارسال تست یادآوری.",
            reply_markup=create_main_keyboard()
        )
        print(f"❌ خطا در تست یادآوری: {e}")

# --- راهنما ---
async def show_help_text(update: Update, context: CallbackContext):
    help_text = """
📖 **راهنمای ash**

💊 **مدیریت داروها:**
• اضافه کردن داروی جدید
• مشاهده همه داروها

⏰ **یادآوری:**
• ash هر روز سر وقت یادآوری می‌کند
• امکان تأیید مصرف دارو
• قابلیت به تعویق انداختن یادآوری

🛠️ **نکات مهم:**
• زمان را به فرمت 24 ساعته وارد کنید
• ربات باید همیشه در حال اجرا باشد
• برای تست از گزینه تست استفاده کنید

👨‍⚕️ **پشتیبانی: ash**
"""

    await update.message.reply_text(help_text, reply_markup=create_main_keyboard())

# --- لغو عملیات ---
async def cancel_operation(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "❌ عملیات لغو شد.",
        reply_markup=create_main_keyboard()
    )
    context.user_data.clear()
    return ConversationHandler.END

# --- تأیید مصرف ---
async def confirm_consumption(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✅ مصرف دارو تأیید شد. ash از شما تشکر می‌کند!")

# --- تعویق یادآوری ---
async def snooze_reminder(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    # ارسال یادآوری بعد از 5 دقیقه
    context.application.job_queue.run_once(
        send_reminder,
        300,
        data=context.job.data,
        name=f"snooze_{context.job.name}"
    )
    
    await query.edit_message_text("⏰ یادآوری برای 5 دقیقه دیگر تنظیم شد.")

# --- تابع اصلی ---
def main():
    TOKEN ="اره"
    
    print("🔧 ash در حال راه‌اندازی است...")
    
    # راه‌اندازی دیتابیس
    init_db()
    
    # ساخت اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # بارگذاری یادآوری‌های موجود
    load_existing_reminders(application)
    
    # ConversationHandler برای ثبت دارو
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💊 اضافه کردن دارو$"), start_add_medicine)],
        states={
            MED_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_med_name)],
            DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_dosage)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ لغو$"), cancel_operation)]
    )
    
    # اضافه کردن handlerها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    application.add_handler(CallbackQueryHandler(confirm_consumption, pattern="^confirm_"))
    application.add_handler(CallbackQueryHandler(snooze_reminder, pattern="^snooze_"))
    
    print("🤖 ash شروع به کار کرد!")
    print("🎯 حالا می‌توانید از کیبورد استفاده کنید")
    
    # اجرای ربات
    application.run_polling()

if __name__ == '__main__':
    main()