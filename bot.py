import asyncio
import logging
from os import getenv

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from helpers import (
    execute_bq_sql,
    get_google_sheet_config,
    get_data_from_config,
    split_long_message,
)
from agent import generate_sql, analyze_data_with_agent


# --- НАСТРОЙКА  ЛОГОВ ---
# Пишут только в консоль сервера. Формат: Дата | Уровень | Текст
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"), # Сохраняет всё в файл bot.log
        logging.StreamHandler()                           # Выводит всё в консоль (терминал)
    ]
)
# Отключаем избыточный спам (логи подключений) от сторонних библиотек
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("google").setLevel(logging.WARNING)
# -------------------------------


load_dotenv('config.env')

BOT_TOKEN = getenv('BOT_TOKEN')

dp = Dispatcher()


@dp.message(Command("start"))
async def command_start(message: Message) -> None:
    user_name = message.from_user.first_name if message.from_user else "друг"
    await message.answer(
        f"Привет, {user_name}! Я ваш AI-аналитик 📊\n"
        f"Задайте мне вопрос по бизнес-показателям, используя команду /ask.\n\n"
        f"Пример: `/ask Какая сумма чистых оплат за этот месяц?`",
        parse_mode="Markdown",
    )

@dp.message(Command("ask"))
async def command_ask(message: Message) -> None:
    text_payload = message.text or ""
    message_chat_id = message.chat.id
    question = text_payload.replace("/ask", "").strip()

    if not question:
        logging.warning(f"Пустой вопрос от chat_id={message_chat_id}")
        await message.answer("Пожалуйста, введите вопрос после команды /ask.")
        return

    logging.info(f"Новый вопрос от chat_id={message_chat_id}: {question}")
    status_msg = await message.answer("⏳ Вопрос получен. Обрабатываю...")

    configs = get_google_sheet_config()

    user_config = get_data_from_config(configs, message_chat_id)
    if not user_config:
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass
        await message.answer("❌ У вас нет доступа к этому боту.")
        return
    
    source_table = user_config["source_table"]
    gemini_version = user_config["gemini_version"]
    prompt_prefix = user_config["prompt_prefix"]

    try:
        await status_msg.edit_text("🧠 Генерирую SQL-запрос...")
        sql_code = await asyncio.to_thread(generate_sql, question, source_table, gemini_version)

        if "Ошибка" in sql_code or "⚠️" in sql_code or "Бот попытался" in sql_code:
            try:
                await status_msg.delete()
            except TelegramBadRequest:
                pass
            await message.answer("Не удалось сгенерировать запрос. Попробуйте переформулировать вопрос.")
            return

        await status_msg.edit_text("📊 Извлекаю данные из BigQuery...")
        raw_data = await asyncio.to_thread(execute_bq_sql, sql_code, source_table)

        if "Ошибка" in raw_data:
            try:
                await status_msg.delete()
            except TelegramBadRequest:
                pass
            await message.answer("Ошибка при получении данных.")
            return

        await status_msg.edit_text("💡 Анализирую результаты...")
        analysis = await asyncio.to_thread(
            analyze_data_with_agent,
            question=question,
            target_table=source_table,
            sql_code=sql_code,
            raw_data=raw_data,
            gemini_version=gemini_version,
            prompt_prefix=prompt_prefix
        )

        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass

        chunks = split_long_message(analysis)
        for part in chunks:
            await message.answer(part)

    except Exception as e:
        logging.exception(f"Критическая ошибка конвейера: {e}")
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass
        await message.answer("❌ Произошла непредвиденная ошибка.")


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    logging.info("🤖 Бот успешно запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())