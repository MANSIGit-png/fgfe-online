# config.py - файл конфигурации

import os

# ============ НАСТРОЙКИ БОТА ============
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
NAME = "fgramfe_bot"
ADMIN_CHAT_ID = 7845678167
# ============ НАСТРОЙКИ WEBAPP ============
WEBAPP_URL = "fgfe.online"
DEBUG = True
COMA = 5
CHANNEL_ID = "-1003923363941"
CHAT_ID = "-1004360731939"
# ============ НАСТРОЙКИ БАЗЫ ДАННЫХ ============
DATABASE_FILE = "data/aka.txt"

# ============ БОНУСЫ ============
WELCOME_BONUS = 100
DAILY_BONUS = 50

# ============ НАСТРОЙКИ TON КОШЕЛЬКА ============
MERCHANT_WALLET = "UQCiPnG0mf7npCpHchKp_UvE2f2cWRwZZ2OLFQy2YSPqFdLI"
WITHDRAW_COMMISSION = 5

# ============ НАСТРОЙКИ ПАРСЕРА ЦЕН ============
TOKEN_ADDRESS = "EQDuGgqZU7_AEgiOwEe-abozIefuoairTWLOyd7c_f8GhzMf"
TOKEN_URL = f"https://api.geckoterminal.com/api/v2/networks/ton/tokens/{TOKEN_ADDRESS}"
HISTORY_FILE = "price_history.json"
CHECK_INTERVAL = 300

# ============ НАСТРОЙКИ ИГРЫ MINES ============
MINES_CONFIG = {
    "rtp": 0.948,
    "total_cells": 25
}
