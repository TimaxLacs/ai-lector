# ai-lector

Вот краткая и понятная документация по установке репозитория и запуску вашего Telegram-бота на основе предоставленного кода и алгоритма действий. Документация предназначена для пользователей с базовыми знаниями Linux.

---

# Документация по установке и запуску Telegram-бота

Эта инструкция описывает процесс установки зависимостей, сборки локального сервера Telegram Bot API и запуска бота из репозитория `ai-lector`.

## Требования
- ОС: Linux (например, Ubuntu)
- Установленные инструменты:
  - `git`
  - `python3` (версия 3.10 или выше)
  - `pip3`
  - `cmake` и `make` для сборки Telegram Bot API
- Доступ к терминалу с правами `root` или `sudo`.

## Установка

### 1. Клонирование репозитория и Telegram Bot API
1. Перейдите в рабочую директорию:
   ```bash
   cd ~/ai-lector
   ```
2. Склонируйте репозиторий Telegram Bot API:
   ```bash
   git clone https://github.com/tdlib/telegram-bot-api.git
   ```
3. Перейдите в директорию `telegram-bot-api`:
   ```bash
   cd telegram-bot-api
   ```
4. Инициализируйте и обновите субмодули:
   ```bash
   git submodule init
   git submodule update
   ```

### 2. Сборка Telegram Bot API
1. Создайте директорию для сборки:
   ```bash
   mkdir build
   cd build
   ```
2. Выполните конфигурацию и сборку:
   ```bash
   cmake ..
   cmake --build .
   ```
   После завершения сборки в директории `build` появится исполняемый файл `telegram-bot-api`.

3. Вернитесь в корневую директорию проекта:
   ```bash
   cd ../..
   ```

### 3. Установка Python-зависимостей
1. Установите необходимые Python-пакеты:
   ```bash
   pip3 install python-telegram-bot==20.7 pydub openai==1.17.0 requests==2.31.0 python-dotenv==1.0.0
   ```

### 4. Настройка окружения
1. Создайте файл `.env` в директории `~/ai-lector` и добавьте следующие переменные:
   ```
   TELEGRAM_TOKEN=
   DEEP_API_KEY=
   TELEGRAM_API_ID=
   TELEGRAM_API_HASH=
   ```
   - Замените значения на свои, если они отличаются:
     - `TELEGRAM_TOKEN` — токен вашего бота от BotFather.
     - `DEEP_API_KEY` — ключ API для Deep Foundation.
     - `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` — данные от Telegram API (получаются через my.telegram.org).

## Запуск бота

1. Убедитесь, что вы находитесь в директории `~/ai-lector`:
   ```bash
   cd ~/ai-lector
   ```
2. Запустите бота:
   ```bash
   python3 bot.py
   ```
   - Скрипт автоматически запустит локальный сервер Telegram Bot API на порту `8081` и начнет работу бота.
   - Логи будут отображаться в терминале (уровень `INFO` и `ERROR`).


