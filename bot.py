import logging
import tempfile
import subprocess
import os
import time
from pydub import AudioSegment
import io
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import requests
from openai import OpenAI, OpenAIError
from telegram.error import TelegramError
from dotenv import load_dotenv
from telegram import __version__ as TG_VER
from telegram.request import HTTPXRequest

# Проверка версии python-telegram-bot
try:
    from telegram.ext import ApplicationBuilder
except ImportError:
    raise ImportError(f"Unsupported python-telegram-bot version: {TG_VER}. Please install version 20.x or higher.")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
DEEP_API_KEY = os.getenv('DEEP_API_KEY')
TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_API_ID = os.getenv('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')

# Проверка ключей
if not all([DEEP_API_KEY, TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH]):
    logger.error("Один или несколько ключей не указаны в .env")
    raise ValueError("Ключи не указаны в .env")

# Инициализация OpenAI клиента
# openai_client = OpenAI(api_key=DEEP_API_KEY, base_url="https://api.deep-foundation.tech/v1/")
openai_client = OpenAI(
    api_key=DEEP_API_KEY,
    base_url="https://api.deep-foundation.tech/v1/",
)

# Запуск локального сервера Telegram Bot API
def start_telegram_api_server():
    server_path = os.path.join(os.getcwd(), "telegram-bot-api", "build", "telegram-bot-api")
    if not os.path.exists(server_path):
        logger.error(f"Файл telegram-bot-api не найден по пути: {server_path}")
        raise FileNotFoundError("telegram-bot-api не собран или отсутствует")
    
    cmd = [
        server_path,
        "--local",
        "--api-id", TELEGRAM_API_ID,
        "--api-hash", TELEGRAM_API_HASH
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    logger.info("Локальный сервер Telegram Bot API запущен")
    time.sleep(2)  # Даем серверу время на запуск
    return process

request = HTTPXRequest()
application = ApplicationBuilder().token(TOKEN).base_url("http://localhost:8081/bot").request(request).build()

# Состояния ConversationHandler
MAIN_REQUIREMENTS, ADD_MATERIALS = range(2)

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("Создать новый сценарий", callback_data='new_scenario')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        'Привет! Нажмите кнопку, чтобы создать новый сценарий.',
        reply_markup=reply_markup
    )
    logger.info("Команда /start выполнена")

# Обработчик кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.info(f"Обработан каллбек: {query.data}")
    if query.data == 'new_scenario':
        await query.message.reply_text('Укажите основные требования для сценария.')
        return MAIN_REQUIREMENTS
    elif query.data == 'add_materials':
        await query.message.reply_text('Отправьте текст, голосовое сообщение или аудиофайл.')
        return ADD_MATERIALS
    elif query.data == 'generate_scenario':
        return await generate_scenario(update, context)
    return ConversationHandler.END

# Обработка основного запроса
async def main_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.text.strip():
        await update.message.reply_text("Требования не могут быть пустыми.")
        return MAIN_REQUIREMENTS
    context.user_data['main_requirements'] = update.message.text.strip()
    logger.info(f"Получен основной запрос: {context.user_data['main_requirements']}")
    keyboard = [
        [InlineKeyboardButton("Добавить доп. материалы", callback_data='add_materials')],
        [InlineKeyboardButton("Приступить к генерации", callback_data='generate_scenario')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        'Требования сохранены. Добавьте материалы или приступите к генерации.',
        reply_markup=reply_markup
    )
    return ADD_MATERIALS

# Обработка текста
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'materials' not in context.user_data:
        context.user_data['materials'] = []
    context.user_data['materials'].append({'type': 'text', 'content': update.message.text.strip()})
    logger.info(f"Добавлен текст: {update.message.text.strip()}")
    keyboard = [
        [InlineKeyboardButton("Добавить доп. материалы", callback_data='add_materials')],
        [InlineKeyboardButton("Приступить к генерации", callback_data='generate_scenario')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        'Текст добавлен. Добавьте ещё или приступите к генерации.',
        reply_markup=reply_markup
    )
    return ADD_MATERIALS

# Обработка голосовых сообщений
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'materials' not in context.user_data:
        context.user_data['materials'] = []
    voice_file = await update.message.voice.get_file()
    voice_bytes = await voice_file.download_as_bytearray()
    transcription = await transcribe_audio(voice_bytes)
    if not transcription:
        await update.message.reply_text("Ошибка транскрибации голосового сообщения.")
        logger.error("Ошибка транскрибации голосового сообщения")
    else:
        context.user_data['materials'].append({'type': 'voice', 'content': transcription})
        logger.info(f"Транскрибация голосового сообщения: {transcription}")
        keyboard = [
            [InlineKeyboardButton("Добавить доп. материалы", callback_data='add_materials')],
            [InlineKeyboardButton("Приступить к генерации", callback_data='generate_scenario')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f'Транскрибация: "{transcription}". Добавьте ещё или приступите к генерации.',
            reply_markup=reply_markup
        )
    return ADD_MATERIALS

# Обработка аудиофайлов
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'materials' not in context.user_data:
        context.user_data['materials'] = []
    try:
        audio_file = await update.message.audio.get_file()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
            await audio_file.download_to_drive(temp_file.name)
            logger.info(f"Аудиофайл скачан: {temp_file.name}")
            transcription = await transcribe_audio(temp_file.name)
            if not transcription:
                await update.message.reply_text("Ошибка транскрибации аудиофайла.")
                logger.error("Ошибка транскрибации аудиофайла")
            else:
                context.user_data['materials'].append({'type': 'audio', 'content': transcription})
                logger.info(f"Транскрибация аудиофайла: {transcription}")
                transcription_file = io.BytesIO(transcription.encode('utf-8'))
                transcription_file.name = 'transcription.txt'
                await update.message.reply_document(document=transcription_file, filename='transcription.txt')
                keyboard = [
                    [InlineKeyboardButton("Добавить доп. материалы", callback_data='add_materials')],
                    [InlineKeyboardButton("Приступить к генерации", callback_data='generate_scenario')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    'Добавьте ещё или приступите к генерации.',
                    reply_markup=reply_markup
                )
            os.remove(temp_file.name)
            logger.info(f"Временный файл удален: {temp_file.name}")
    except Exception as e:
        logger.error(f"Ошибка обработки аудио: {str(e)}")
        await update.message.reply_text(f"Произошла ошибка при обработке аудио: {str(e)}")
    return ADD_MATERIALS

# Функция транскрибации
async def transcribe_audio(file_path) -> str:
    try:
        url = "https://api.deep-foundation.tech/v1/audio/transcriptions"
        logger.info("Отправка запроса на транскрибацию")
        with open(file_path, "rb") as audio_file:
            files = {'file': ('audio.mp3', audio_file, 'audio/mpeg')}
            data = {'model': 'whisper-1', 'language': 'ru'}
            headers = {'Authorization': f'Bearer {DEEP_API_KEY}'}
            response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        logger.info(f"Статус ответа от API: {response.status_code}")
        response.raise_for_status()
        transcription = response.json().get('text', '')
        if transcription:
            logger.info(f"Успешная транскрибация: {transcription}")
        else:
            logger.warning("Транскрибация вернула пустой текст")
        return transcription
    except Exception as e:
        logger.error(f"Ошибка транскрибации: {str(e)}")
        return ""

# Генерация сценария
async def generate_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text('Начинаю генерацию сценария...')
    logger.info("Начата генерация сценария")
    main_requirements = context.user_data.get('main_requirements', '')
    materials = context.user_data.get('materials', [])
    if not main_requirements:
        await query.message.reply_text("Ошибка: нет основных требований.")
        return ConversationHandler.END
    materials_text = "\n".join([m['content'] for m in materials]) if materials else "Нет материалов."
    parts = ["Введение", "Основная часть 1", "Основная часть 2", "Заключение", "Дополнительные заметки"]
    full_script = ""
    for i, part in enumerate(parts, 1):
        prompt = (
            f"Сгенерируй сценарий лекции, разделённый на 5 равных частей: {', '.join(parts)}. "
            f"Основные требования: {main_requirements}. Дополнительные материалы: {materials_text}. "
            f"Сейчас мне нужна только часть {i} — '{part}'. Сделай текст структурированным и логичным."
        )
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты опытный лектор и сценарист."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.7
            )
            part_text = response.choices[0].message.content.strip()
            full_script += f"## {part}\n\n{part_text}\n\n"
            max_length = 4096
            if len(part_text) > max_length:
                for i in range(0, len(part_text), max_length):
                    part_message = part_text[i:i + max_length]
                    await query.message.reply_text(part_message)
            else:
                await query.message.reply_text(f"Часть {i} — {part}:\n\n{part_text}", parse_mode='Markdown')
            logger.info(f"Сгенерирована часть {i}: {part}")
        except OpenAIError as e:
            logger.error(f"Ошибка генерации {part}: {e}")
            await query.message.reply_text(f"Ошибка генерации {part}: {str(e)}")
    script_file = io.BytesIO(full_script.encode('utf-8'))
    script_file.name = 'lecture_script.md'
    await query.message.reply_document(document=script_file, filename='lecture_script.md')
    keyboard = [[InlineKeyboardButton("Создать новый сценарий", callback_data='new_scenario')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(
        'Сценарий готов! Нажмите кнопку для нового сценария.',
        reply_markup=reply_markup
    )
    logger.info("Сценарий успешно сгенерирован и отправлен")
    context.user_data.clear()
    return ConversationHandler.END

# Главная функция
def main() -> None:
    try:
        # Запуск локального сервера
        server_process = start_telegram_api_server()
        
        # Настройка обработчиков
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern='new_scenario')],
            states={
                MAIN_REQUIREMENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_requirements)],
                ADD_MATERIALS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                    MessageHandler(filters.VOICE, handle_voice),
                    MessageHandler(filters.AUDIO, handle_audio),
                    CallbackQueryHandler(button_handler, pattern='add_materials|generate_scenario')
                ],
            },
            fallbacks=[],
            per_message=False
        )
        application.add_handler(CommandHandler("start", start))
        application.add_handler(conv_handler)
        application.add_handler(CallbackQueryHandler(button_handler))
        logger.info("Бот запущен")
        application.run_polling(timeout=30)
        
        # Завершение сервера при остановке бота
        server_process.terminate()
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        if 'server_process' in locals():
            server_process.terminate()

if __name__ == '__main__':
    main()