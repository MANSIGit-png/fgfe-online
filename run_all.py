#!/usr/bin/env python3
import subprocess
import threading
import time
import signal
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, 'bac')


def run_bot():
    subprocess.run(['python', os.path.join(BACKEND_DIR, 'bot.py')])


def run_webapp():
    subprocess.run(['python', os.path.join(BACKEND_DIR, 'app.py')])


def run_parser():
    subprocess.run(['python', os.path.join(BACKEND_DIR, 'price_collector.py')])


def signal_handler(signum, frame):
    print("\n🛑 Остановка всех сервисов...")
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)

    print("=" * 50)
    print("🚀 ЗАПУСК ВСЕХ СЕРВИСОВ")
    print("=" * 50)
    print(f"📁 Корень проекта: {BASE_DIR}")
    print(f"📁 Backend: {BACKEND_DIR}")
    print("=" * 50)

    parser_thread = threading.Thread(target=run_parser, daemon=True)
    parser_thread.start()
    print("✅ Парсер цен запущен")

    time.sleep(2)

    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("✅ Telegram бот запущен")

    time.sleep(2)

    print("🌐 Запуск веб-сервера на http://localhost:5000")
    print("=" * 50)
    run_webapp()
