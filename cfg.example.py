"""
Конфигурационный файл для CryptoPay
ИНСТРУКЦИЯ: Скопируйте этот файл как cfg.py и заполните своими данными
"""

import os

# Базовые настройки
APP_NAME = "CryptoPay"
DEBUG = True
SECRET_KEY = 'your-secret-key-change-in-production'

# База данных
DATABASE_PATH = "cryptopay.db"

# Telegram Bot
TELEGRAM_BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'
TELEGRAM_BOT_USERNAME = 'your_bot_username'

# Solana настройки
SOLANA_NETWORK = "devnet"  # "mainnet" или "devnet"
SOLANA_RPC_URL = "https://api.devnet.solana.com"
SOLANA_MAINNET_RPC = "https://api.mainnet-beta.solana.com"

# Переменные для удобства
IS_MAINNET = SOLANA_NETWORK == "mainnet"
IS_DEVNET = SOLANA_NETWORK == "devnet"

# Дополнительные RPC провайдеры для надежности
SOLANA_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-api.projectserum.com",
    "https://rpc.ankr.com/solana"
]

# Кошелек админа для получения комиссий
ADMIN_WALLET = "YOUR_WALLET_ADDRESS_HERE"
ADMIN_PRIVATE_KEY = "YOUR_PRIVATE_KEY_HERE"

# Комиссии
TOTAL_COMMISSION = 10.0  # Общая комиссия 10%
WORKER_COMMISSION = 5.0  # 5% воркеру
ADMIN_COMMISSION = 5.0   # 5% админу

MIN_PAYMENT_AMOUNT_RUB = 250
MAX_PAYMENT_AMOUNT_RUB = 10000

# Комиссия для отображения
COMMISSION_MARKUP = 10.0

# Курс по умолчанию
DEFAULT_SOL_TO_RUB_RATE = 11500.0

# Веб-сервер
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000

# Таймеры
PAYMENT_TIMEOUT = 180  # 3 минуты
PENALTY_AMOUNT_USD = 1.0  # Штраф $1

# Администраторы (Telegram ID)
ADMIN_IDS = [123456789]

# Воркеры (Telegram ID)
WORKER_IDS = [987654321]

# Настройки PWA
PWA_NAME = "CryptoPay"
PWA_SHORT_NAME = "CryptoPay"
PWA_THEME_COLOR = "#6366f1"
PWA_BACKGROUND_COLOR = "#0f172a"

# Логирование
LOG_LEVEL = "INFO"
LOG_FILE = "cryptopay.log"