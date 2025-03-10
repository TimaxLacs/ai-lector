import logging
import tempfile
from pydub import AudioSegment
import io
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import requests
from openai import OpenAI, OpenAIError
from telegram.error import TelegramError
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
DEEP_API_KEY = os.getenv('DEEP_API_KEY')
TOKEN = os.getenv('TELEGRAM_TOKEN')

# Проверка ключей
if not DEEP_API_KEY or not TOKEN:
    logger.error("Ключи DEEP_API_KEY или TELEGRAM_TOKEN не указаны в .env")
    raise ValueError("Ключи не указаны в .env")

# Инициализация OpenAI клиента
openai_client = OpenAI(api_key=DEEP_API_KEY, base_url="https://api.deep-foundation.tech/v1/")

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

# Обработчик каллбеков
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

# Обработка текста для доп. материалов
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
    transcription = transcribe_audio(voice_bytes)
    if not transcription:
        await update.message.reply_text("Ошибка транскрибации голосового сообщения. Проверьте API-ключ и доступ к интернету.")
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
    audio_file = await update.message.audio.get_file()
    audio_bytes = await audio_file.download_as_bytearray()
    transcription = transcribe_audio(audio_bytes)
    if not transcription:
        await update.message.reply_text("Ошибка транскрибации аудиофайла. Проверьте API-ключ и доступ к интернету.")
        logger.error("Ошибка транскрибации аудиофайла")
    else:
        context.user_data['materials'].append({'type': 'audio', 'content': transcription})
        logger.info(f"Транскрибация аудиофайла: {transcription}")
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

# Транскрибация аудио
def transcribe_audio(audio_bytes):
    try:
        # Конвертация OGG в MP3
        logger.info("Конвертация OGG в MP3")
        ogg_audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="ogg")
        
        # Сохранение MP3 во временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
            ogg_audio.export(temp_file.name, format="mp3")
            temp_file_path = temp_file.name
        
        # Чтение MP3 файла
        with open(temp_file_path, 'rb') as mp3_file:
            mp3_bytes = mp3_file.read()
        logger.info(f"Размер MP3 файла: {len(mp3_bytes)} байт")

        # Отправка запроса
        url = "https://api.deep-foundation.tech/v1/audio/transcriptions"
        logger.info("Отправка запроса на транскрибацию")
        files = {'file': ('audio.mp3', mp3_bytes, 'audio/mpeg')}
        data = {'model': 'whisper-1', 'language': 'ru'}  # Исправлено с 'RU' на 'ru'
        headers = {'Authorization': f'Bearer {DEEP_API_KEY}'}
        response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        
        # Логирование ответа
        logger.info(f"Статус ответа от API: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Текст ошибки от API: {response.text}")
        response.raise_for_status()
        
        transcription = response.json().get('text', '')
        if transcription:
            logger.info(f"Успешная транскрибация: {transcription}")
        else:
            logger.warning("Транскрибация вернула пустой текст")
        
        # Удаление временного файла
        os.remove(temp_file_path)
        logger.info(f"Временный файл удалён: {temp_file_path}")
        return transcription
    
    except requests.RequestException as e:
        logger.error(f"Ошибка транскрибации: {e}, Текст ошибки: {str(e)}")
        return ""
    except ValueError as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        return ""
    except Exception as e:
        logger.error(f"Ошибка конвертации аудио: {e}")
        return ""
                
# Генерация сценария по частям
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
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Ты опытный лектор и сценарист."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.7
            )
            part_text = response.choices[0].message.content.strip()
            full_script += f"## {part}\n\n{part_text}\n\n"
            await query.message.reply_text(f"Часть {i} — {part}:\n\n{part_text}", parse_mode='Markdown')
            logger.info(f"Сгенерирована часть {i}: {part}")
        except OpenAIError as e:
            logger.error(f"Ошибка генерации {part}: {e}")
            await query.message.reply_text(f"Ошибка генерации {part}: {str(e)}")

    # Отправка только файла, без повторного текста
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
    context.user_data.clear()  # Очистка данных после завершения
    return ConversationHandler.END

# Разбиение текста на части (оставлено для совместимости, хотя не используется)
def split_text(text, max_length):
    lines = text.split('\n')
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_length:
            yield current_chunk
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        yield current_chunk

# Основная функция
def main() -> None:
    try:
        application = Application.builder().token(TOKEN).build()
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
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()