import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# === ЗАГРУЗКА ПЕРЕМЕННЫХ ИЗ .env ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
PROFILE_USERNAME = os.getenv("PROFILE_USERNAME")
GROUP_ID = int(os.getenv("GROUP_ID"))
SPAM_COOLDOWN = int(os.getenv("SPAM_COOLDOWN", 60))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL.upper()),
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

user_last_review = {}

# === КОМАНДА /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Пользователь {user_id} (@{update.effective_user.username}) запустил бота")

    # 🔥 ИСПРАВЛЕНО: УБРАНЫ ЛИШНИЕ ПРОБЕЛЫ В URL!
    keyboard = [
        [InlineKeyboardButton("📢 Канал с отзывами", url=f"https://t.me/{CHANNEL_USERNAME.strip('@')}")],
        [InlineKeyboardButton("👤 Основной профиль", url=f"https://t.me/{PROFILE_USERNAME.strip('@')}")],
        [InlineKeyboardButton("📝 Оставить отзыв", callback_data="leave_review")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Привет! 🙌\n\nВыберите действие:",
        reply_markup=reply_markup
    )

# === НАЖАТИЕ НА КНОПКУ "Оставить отзыв" ===
async def leave_review_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    last_time = user_last_review.get(user_id)
    if last_time and datetime.now() - last_time < timedelta(seconds=SPAM_COOLDOWN):
        remaining = SPAM_COOLDOWN - (datetime.now() - last_time).seconds
        await query.answer(f"⏳ Подождите {remaining} секунд перед следующим отзывом.", show_alert=True)
        return

    await query.answer()
    await query.edit_message_text(
        "✍️ Напишите свой отзыв — я сразу передам его в группу!\n\n"
        "💡 Не используйте маты, спам или ссылки — они будут удалены."
    )
    context.user_data['awaiting_review'] = True
    logger.info(f"Пользователь {user_id} начал процесс написания отзыва")

# === ПРОВЕРКА ОТЗЫВА НА СПАМ ===
def is_valid_review(text: str) -> tuple[bool, str]:
    text = text.strip()
    if not text:
        return False, "Отзыв не может быть пустым"
    if len(text) > 500:
        return False, "Отзыв слишком длинный (максимум 500 символов)"
    if "http://" in text or "https://" in text:
        return False, "Ссылки запрещены"
    if "@" in text and len(text.split("@")) > 2:
        return False, "Не разрешается указывать другие аккаунты"
    return True, ""

# === ОБРАБОТКА ТЕКСТА ОТЗЫВА ===
async def handle_review_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    message_text = update.message.text

    if not context.user_data.get('awaiting_review'):
        return

    is_valid, reason = is_valid_review(message_text)
    if not is_valid:
        await update.message.reply_text(f"❌ Невозможно отправить отзыв:\n{reason}\n\nПопробуйте ещё раз.")
        logger.warning(f"Пользователь {user_id} попытался отправить недопустимый отзыв: {reason}")
        return

    user_last_review[user_id] = datetime.now()

    username = f"@{user.username}" if user.username else user.first_name
    forwarded_review = (
        f"💬 *Новый отзыв от {username}* (`{user_id}`)\n\n"
        f"{message_text}\n\n"
        f"— Отправлено через бота • {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=forwarded_review,
            parse_mode='Markdown'
        )
        await update.message.reply_text(
            "✅ Спасибо за отзыв! Он уже отправлен в нашу группу.\n\n"
            "Если хотите ещё что-то — нажмите /start"
        )
        logger.info(f"Пользователь {user_id} успешно отправил отзыв: '{message_text[:50]}...'")

    except Exception as e:
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
        logger.error(f"Ошибка отправки отзыва: {e}")

    context.user_data['awaiting_review'] = False

# === ПРОВЕРКА ДОСТУПА К ГРУППЕ ===
async def check_group_access(application):
    try:
        await application.bot.get_chat(GROUP_ID)
        logger.info(f"✅ Успешно получена информация о группе {GROUP_ID}. Доступ есть.")
    except Exception as e:
        logger.critical(f"❌ Бот не имеет доступа к группе {GROUP_ID}. Ошибка: {e}")
        raise SystemExit("Бот не может работать без доступа к группе отзывов!")

# === ЗАПУСК БОТА ===
def main():
    if not BOT_TOKEN:
        logger.critical("❌ Токен бота не найден. Проверьте .env файл!")
        exit(1)

    logger.info("🚀 Запуск бота...")
    app = Application.builder().token(BOT_TOKEN).build()

    # Проверяем доступ к группе
    app.add_error_handler(lambda u, c: logger.error(f"Ошибка обработки: {c.error}"))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(leave_review_button, pattern="^leave_review$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_review_message))

    app.run_polling()

if __name__ == "__main__":
    main()