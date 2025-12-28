import asyncio
import threading
import json
import os
import sqlite3
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile


from core.driver.get_playlist_tracks import Startparser

# ----------------- Конфиг -----------------
TG_TOKEN = "BOT TOKEN"

# Регулярка для ссылок Яндекс Музыки
YANDEX_LINK_PATTERN = re.compile(
    r'https?://music\.yandex\.(ru|com)/playlists/'
    r'(?:lk\.[a-f0-9\-]+|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'
    r'(?:\?.*)?$',
    re.IGNORECASE
)


# ----------------- SQLite для прогресса -----------------
def init_db():
    conn = sqlite3.connect('bot_progress.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id INTEGER PRIMARY KEY,
            current_index INTEGER DEFAULT 0,
            total_tracks INTEGER DEFAULT 0,
            json_file TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_messages (
            user_id INTEGER,
            bot_message_id INTEGER,
            PRIMARY KEY (user_id, bot_message_id)
        )
    ''')
    conn.commit()
    conn.close()


def get_progress(user_id):
    conn = sqlite3.connect('bot_progress.db')
    c = conn.cursor()
    c.execute('SELECT current_index, total_tracks, json_file FROM user_progress WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def update_progress(user_id, index, total, json_file):
    conn = sqlite3.connect('bot_progress.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO user_progress (user_id, current_index, total_tracks, json_file)
        VALUES (?, ?, ?, ?)
    ''', (user_id, index, total, json_file))
    conn.commit()
    conn.close()


def reset_progress(user_id):
    conn = sqlite3.connect('bot_progress.db')
    c = conn.cursor()
    c.execute('DELETE FROM user_progress WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM user_messages WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


def save_bot_message(user_id, message_id):
    conn = sqlite3.connect('bot_progress.db')
    c = conn.cursor()
    c.execute('INSERT INTO user_messages (user_id, bot_message_id) VALUES (?, ?)', (user_id, message_id))
    conn.commit()
    conn.close()


def get_bot_messages(user_id):
    conn = sqlite3.connect('bot_progress.db')
    c = conn.cursor()
    c.execute('SELECT bot_message_id FROM user_messages WHERE user_id = ?', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]


def clear_bot_messages(user_id):
    conn = sqlite3.connect('bot_progress.db')
    c = conn.cursor()
    c.execute('DELETE FROM user_messages WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


# ----------------- Бот -----------------
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# Храним активные задачи парсинга
active_parsers = {}  # теперь это dict[user_id] = asyncio.Task


def escape_md2(text: str) -> str:
    """ Экранирует специальные символы для MarkdownV2 """
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + c if c in escape_chars else c for c in text])


async def send_track(user_id: int, chat_id: int, index: int):
    """Отправляет трек по индексу и сохраняет ID сообщения"""
    progress = get_progress(user_id)
    if not progress:
        return None

    current_index, total_tracks, json_file = progress

    if index >= total_tracks:
        await bot.send_message(chat_id, "🎉 Плейлист окончен! Все треки отправлены.")
        reset_progress(user_id)
        return None

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    track = data["tracks"][index]
    text = f"Трек {index + 1} из {total_tracks}\n\n`@song {track}`"

    # Отправляем сообщение
    message = await bot.send_message(chat_id, text, parse_mode="MarkdownV2")

    # Сохраняем ID сообщения бота
    save_bot_message(user_id, message.message_id)

    # Обновляем прогресс
    update_progress(user_id, index + 1, total_tracks, json_file)

    return message.message_id


async def delete_previous_bot_messages(user_id: int, chat_id: int):
    """Удаляет все предыдущие сообщения бота для этого пользователя"""
    message_ids = get_bot_messages(user_id)

    if not message_ids:
        return

    try:
        for message_id in message_ids:
            try:
                await bot.delete_message(chat_id, message_id)
            except Exception as e:
                # Игнорируем ошибки удаления (сообщение может быть уже удалено)
                pass
    finally:
        # Очищаем записи о сообщениях
        clear_bot_messages(user_id)


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Пришли мне ссылку на любой плейлист Яндекс Музыки (классический или lk....)\n"
        "Я соберу все треки и буду отправлять их по одному.\n\n"
        "🎵 Используй функцию '@song' чтобы превратить трек в аудио, и я пришлю следующий!\n\n"
        "Как это работает:\n"
        "1. Я пришлю трек в формате '@song Название'\n"
        "2. Ты нажимаешь на этот текст\n"
        "3. Вставляешь этот текст в чат\n"
        "4. Выбираешь трек из выпадающего списка\n"
        "5. Я вижу это и автоматически отправляю следующий трек!\n"
        "Внимание!. Не все треки могут быть в базе бота @song!"
    )


@dp.message(F.text.regexp(YANDEX_LINK_PATTERN))
async def handle_link(message: types.Message):
    url = message.text.strip()
    user_id = message.from_user.id
    chat_id = message.chat.id

    if user_id in active_parsers:
        active_parsers[user_id].cancel()  # Отменяем старую задачу
        await message.answer("⏳ Предыдущий парсинг отменён. Запускаю новый...")

    await message.answer("🔄 Начинаю парсинг плейлиста...\nЭто может занять 1–5 минут.")

    async def parse_and_start():
        try:
            # Очищаем предыдущие сообщения
            await delete_previous_bot_messages(user_id, chat_id)

            await asyncio.to_thread(Startparser, url, user_id)

            json_file = f"playlist_tracks_{user_id}.json"
            if os.path.exists(json_file):
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                total = len(data["tracks"])

                # Сбрасываем прогресс и начинаем с первого трека
                update_progress(user_id, 0, total, json_file)

                # Отправляем первый трек
                await send_track(user_id, chat_id, 0)

                await bot.send_message(
                    chat_id,
                    "✅ Плейлист готов!\n\n"
                    "🎵 Теперь используй функцию '@song' (другого бота) на тексте выше,\n"
                    "чтобы получить аудиофайл. Как только я увижу аудио-сообщение,\n"
                    "я автоматически отправлю следующий трек!\n\n"
                    "❌ Удалять предыдущие сообщения не нужно — я сделаю это автоматически."
                )
            else:
                await message.answer("❌ Файл с треками не создан.")
        except Exception as e:
            await message.answer(f"❌ Ошибка парсинга: {e}")
        finally:
            # Удаляем задачу из активных
            if user_id in active_parsers:
                del active_parsers[user_id]

    task = asyncio.create_task(parse_and_start())
    active_parsers[user_id] = task


@dp.message(F.audio | F.voice)
async def handle_audio_reply(message: types.Message):
    """Обработка аудио-сообщений (результат работы @song бота)"""
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Получаем текущий прогресс
    progress = get_progress(user_id)
    if not progress:
        # Если прогресса нет, возможно плейлист еще не парсился
        # Или пользователь просто отправляет аудио вне контекста плейлиста
        return

    current_index, total_tracks, json_file = progress

    # Проверяем, не закончился ли плейлист
    if current_index >= total_tracks:
        await message.answer("🎉 Плейлист окончен! Все треки отправлены.")
        reset_progress(user_id)
        return

    # Удаляем предыдущие сообщения бота
    await delete_previous_bot_messages(user_id, chat_id)

    # Отправляем следующий трек
    await send_track(user_id, chat_id, current_index)


@dp.message()
async def other(message: types.Message):
    user_id = message.from_user.id

    # Проверяем, есть ли активный плейлист у пользователя
    progress = get_progress(user_id)
    if progress and progress[0] < progress[1]:
        # Если есть незаконченный плейлист, напоминаем о формате
        await message.answer(
            "🎵 Используй функцию '@song' на предыдущем сообщении,\n"
            "чтобы получить аудиофайл. Как только ты отправишь аудио,\n"
            "я автоматически пришлю следующий трек!\n\n"
            "Не нужно ничего писать вручную — просто используй @song бота!"
        )
    else:
        await message.answer("Пришли ссылку на плейлист Яндекс Музыки 😊")


# ----------------- Запуск -----------------
async def main():
    init_db()
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())