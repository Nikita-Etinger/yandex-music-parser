import asyncio
import json
import os
import re
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder


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

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ----------------- Бот -----------------
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# Храним активные задачи парсинга
active_parsers = {}  # user_id: task


def create_files_from_json(user_id: int, json_path: str) -> dict:
    """Создает TXT и JSON файлы из данных парсера"""
    # Читаем JSON файл
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_filename = f"playlist_{user_id}_{timestamp}"

    files = {}

    # 1. Оригинальный JSON (как есть от парсера)
    json_filename = f"{base_filename}_original.json"
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    files['json'] = json_filename

    # 2. Простой TXT (только названия треков)
    txt_filename = f"{base_filename}.txt"
    with open(txt_filename, 'w', encoding='utf-8') as f:
        # Заголовок
        f.write("=" * 50 + "\n")
        f.write(f"Плейлист Яндекс.Музыки\n")
        f.write(f"Ссылка: {data.get('playlist_url', '')}\n")
        f.write(f"Всего треков: {len(data.get('tracks', []))}\n")
        f.write(f"Дата экспорта: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        f.write("=" * 50 + "\n\n")

        # Список треков
        for i, track in enumerate(data.get('tracks', []), 1):
            f.write(f"{i}. {track}\n")

    files['txt'] = txt_filename

    # 3. Упрощенный JSON (только треки)
    simple_json_filename = f"{base_filename}_simple.json"
    with open(simple_json_filename, 'w', encoding='utf-8') as f:
        json.dump(data['tracks'], f, ensure_ascii=False, indent=2)
    files['simple_json'] = simple_json_filename

    return files


def cleanup_files(filepaths: list):
    """Удаляет временные файлы"""
    for filepath in filepaths:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.debug(f"Удален файл: {filepath}")
        except Exception as e:
            logger.error(f"Ошибка удаления файла {filepath}: {e}")


def get_file_keyboard() -> types.InlineKeyboardMarkup:
    """Создает клавиатуру для выбора формата"""
    builder = InlineKeyboardBuilder()

    builder.button(text="📄 JSON (полный)", callback_data="format_json")
    builder.button(text="📝 TXT (список)", callback_data="format_txt")
    builder.button(text="🎵 JSON (только треки)", callback_data="format_simple_json")
    builder.button(text="📦 Все файлы", callback_data="format_all")

    builder.adjust(2, 2)
    return builder.as_markup()


@dp.message(CommandStart())
async def start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "🎵 *Бот для экспорта плейлистов Яндекс.Музыки*\n\n"
        "Просто пришли мне ссылку на плейлист, и я выгружу все треки в удобном формате!\n\n"
        "📋 *Поддерживаемые форматы:*\n"
        "• TXT — простой список треков\n"
        "• JSON — структурированные данные\n\n"
        "⚡ *Примеры ссылок:*\n"
        "• `https://music.yandex.ru/playlists/lk.12345678`\n"
        "• `https://music.yandex.com/playlists/12345678-1234-1234-1234-123456789012`",
        parse_mode="Markdown"
    )


@dp.message(Command("help"))
async def help_command(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 *Помощь*\n\n"
        "Просто отправьте ссылку на плейлист Яндекс.Музыки.\n\n"
        "После парсинга вы сможете выбрать формат файла:\n"
        "• 📝 TXT — простой список с номерами\n"
        "• 📄 JSON — полные данные (ссылка, количество треков)\n"
        "• 🎵 JSON — только список треков\n"
        "• 📦 Все файлы сразу\n\n"
        "❌ Чтобы отменить парсинг, используйте /cancel",
        parse_mode="Markdown"
    )


@dp.message(Command("cancel"))
async def cancel_command(message: types.Message):
    """Обработчик команды /cancel"""
    user_id = message.from_user.id

    if user_id in active_parsers:
        try:
            active_parsers[user_id].cancel()
            await message.answer("✅ Парсинг отменен.")
        except:
            pass
        finally:
            if user_id in active_parsers:
                del active_parsers[user_id]
    else:
        await message.answer("❌ У вас нет активных задач парсинга.")


@dp.message(F.text.regexp(YANDEX_LINK_PATTERN))
async def handle_playlist_link(message: types.Message):
    """Обработчик ссылок на плейлисты"""
    url = message.text.strip()
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Проверяем, не парсит ли пользователь уже что-то
    if user_id in active_parsers:
        try:
            active_parsers[user_id].cancel()
        except:
            pass

    # Отправляем сообщение о начале парсинга
    status_msg = await message.answer(
        "🔄 *Начинаю парсинг плейлиста...*\n\n"
        "Это может занять от 30 секунд до 5 минут в зависимости от размера плейлиста.\n"
        "Пожалуйста, подождите ⏳",
        parse_mode="Markdown"
    )

    async def parse_playlist():
        """Функция парсинга в фоновом режиме"""
        try:
            # Запускаем парсер
            await asyncio.to_thread(Startparser, url, user_id)

            # Проверяем созданные файлы
            json_file = f"playlist_tracks_{user_id}.json"

            if not os.path.exists(json_file):
                await message.answer("❌ Не удалось создать файл с треками.")
                return

            # Читаем данные для отображения статистики
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            track_count = len(data.get('tracks', []))

            # Создаем файлы для отправки
            files = create_files_from_json(user_id, json_file)

            # Сохраняем пути к файлам
            if not hasattr(bot, 'user_files'):
                bot.user_files = {}
            bot.user_files[user_id] = files

            # Удаляем временный файл парсера
            try:
                os.remove(json_file)
            except:
                pass

            # Отправляем сообщение со статистикой
            stats_text = (
                f"✅ *Плейлист успешно обработан!*\n\n"
                f"📊 *Статистика:*\n"
                f"• Треков найдено: {track_count}\n"
                f"• Ссылка: {data.get('playlist_url', url)}\n\n"
                f"📁 *Выберите формат файла:*"
            )

            await message.answer(stats_text, parse_mode="Markdown", reply_markup=get_file_keyboard())

        except asyncio.CancelledError:
            await message.answer("❌ Парсинг отменен пользователем.")
        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}", exc_info=True)
            await message.answer(f"❌ Ошибка при парсинге: {str(e)}")
        finally:
            # Удаляем задачу из активных
            if user_id in active_parsers:
                del active_parsers[user_id]

    # Создаем и запускаем задачу
    task = asyncio.create_task(parse_playlist())
    active_parsers[user_id] = task


@dp.callback_query(F.data.startswith("format_"))
async def handle_format_selection(callback: types.CallbackQuery):
    """Обработчик выбора формата файла"""
    user_id = callback.from_user.id
    format_type = callback.data.replace("format_", "")

    await callback.answer("⏳ Подготавливаю файл...")

    # Проверяем, есть ли файлы для этого пользователя
    if not hasattr(bot, 'user_files') or user_id not in bot.user_files:
        await callback.message.answer("❌ Файлы не найдены. Возможно, сессия истекла. Начните заново.")
        return

    files = bot.user_files[user_id]
    files_to_send = []

    # Определяем какие файлы отправлять
    if format_type == "all":
        files_to_send = list(files.values())
    elif format_type in files:
        files_to_send = [files[format_type]]
    else:
        await callback.message.answer("❌ Неизвестный формат файла.")
        return

    # Отправляем файлы
    for filepath in files_to_send:
        if not os.path.exists(filepath):
            logger.error(f"Файл не найден: {filepath}")
            continue

        try:
            # Читаем файл
            with open(filepath, 'rb') as f:
                file_data = f.read()

            # Проверяем размер файла (лимит Telegram: 50MB)
            file_size = len(file_data)
            if file_size > 50 * 1024 * 1024:
                await callback.message.answer(
                    f"❌ Файл слишком большой ({file_size / 1024 / 1024:.1f} MB). "
                    f"Лимит Telegram: 50 MB."
                )
                continue

            # Получаем красивое имя формата
            format_names = {
                'json': 'JSON (полный)',
                'txt': 'TXT (список)',
                'simple_json': 'JSON (только треки)'
            }
            file_key = [k for k, v in files.items() if v == filepath][0]
            format_name = format_names.get(file_key, file_key)

            # Отправляем файл
            filename = os.path.basename(filepath)
            await callback.message.answer_document(
                document=BufferedInputFile(file_data, filename=filename),
                caption=f"📁 Формат: {format_name}"
            )

            logger.info(f"Отправлен файл {filename} пользователю {user_id}")

        except Exception as e:
            logger.error(f"Ошибка отправки файла {filepath}: {e}")
            await callback.message.answer(f"❌ Ошибка при отправке файла: {str(e)}")

    # Удаляем временные файлы
    try:
        cleanup_files(list(files.values()))
        del bot.user_files[user_id]
    except Exception as e:
        logger.error(f"Ошибка при очистке файлов: {e}")


@dp.message(F.text)
async def handle_other_messages(message: types.Message):
    """Обработчик всех остальных текстовых сообщений"""
    if message.text.startswith('/'):
        return  # Команды обрабатываются отдельно

    await message.answer(
        "🎵 *Отправьте ссылку на плейлист Яндекс.Музыки*\n\n"
        "Примеры:\n"
        "• `https://music.yandex.ru/playlists/lk.12345678`\n"
        "• `https://music.yandex.com/playlists/12345678-1234-1234-1234-123456789012`\n\n"
        "Используйте /help для справки.",
        parse_mode="Markdown"
    )


@dp.message()
async def handle_other_content(message: types.Message):
    """Обработчик всего остального (фото, видео и т.д.)"""
    await message.answer("Пожалуйста, отправьте ссылку на плейлист Яндекс.Музыки.")


async def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота для экспорта плейлистов...")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        # Отменяем все активные задачи при завершении
        for user_id, task in list(active_parsers.items()):
            try:
                task.cancel()
            except:
                pass

        # Очищаем временные файлы
        if hasattr(bot, 'user_files'):
            for files in bot.user_files.values():
                cleanup_files(list(files.values()))


if __name__ == "__main__":
    asyncio.run(main())