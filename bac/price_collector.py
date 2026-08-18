# price_collector_simple.py
import json
import os
import asyncio
import aiohttp
from datetime import datetime, timezone

try:
    from .functions import recalculate_statistik
    from .config import TOKEN_ADDRESS, HISTORY_FILE, CHECK_INTERVAL
except ImportError:
    from functions import recalculate_statistik
    from config import TOKEN_ADDRESS, HISTORY_FILE, CHECK_INTERVAL

TOKEN_URL = f"https://api.geckoterminal.com/api/v2/networks/ton/tokens/{TOKEN_ADDRESS}"


def get_utc_time():
    return datetime.now(timezone.utc)


def load_history():
    history_path = os.path.join(os.path.dirname(__file__), HISTORY_FILE)
    if not os.path.exists(history_path):
        return []
    try:
        with open(history_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            return json.loads(content) if content else []
    except Exception as e:
        print(f"Ошибка загрузки истории: {e}")
        return []


def save_history(history):
    history_path = os.path.join(os.path.dirname(__file__), HISTORY_FILE)
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"💾 Сохранено {len(history)} записей в {HISTORY_FILE}")


def format_fdv(fdv):
    fdv = float(fdv)
    if fdv >= 1_000_000_000:
        return f"${fdv / 1_000_000_000:.2f}B"
    elif fdv >= 1_000_000:
        return f"${fdv / 1_000_000:.2f}M"
    elif fdv >= 1_000:
        return f"${fdv / 1_000:.2f}K"
    return f"${fdv:.2f}"


async def get_fdv_from_geckoterminal():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(TOKEN_URL, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'data' in data and 'attributes' in data['data']:
                        fdv = data['data']['attributes'].get('fdv_usd')
                        if fdv and float(fdv) > 0:
                            return float(fdv)
                        print("  ⚠️ FDV не найден в ответе API")
                        return None
                    print("  ⚠️ Неверный формат ответа API")
                    return None
                print(f"  ❌ Ошибка API: статус {response.status}")
                return None
        except asyncio.TimeoutError:
            print("  ⏰ Таймаут соединения")
            return None
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
            return None


async def collect_fdv():
    print("=" * 60)
    print("🚀 ПАРСЕР FDV + ПЕРЕСЧЕТ СТАТИСТИКИ (каждые 5 минут)")
    print("=" * 60)
    print(f"📍 Адрес токена: {TOKEN_ADDRESS}")
    print(f"🔗 API URL: {TOKEN_URL}")
    print(f"💾 Файл истории: {HISTORY_FILE}")
    print(f"⏱️  Интервал: {CHECK_INTERVAL // 60} минут")
    print("🕐 Часовой пояс: UTC (Гринвич)")
    print("=" * 60)

    while True:
        try:
            utc_now = get_utc_time()
            utc_time_str = utc_now.strftime('%H:%M:%S')
            utc_date_str = utc_now.strftime('%d.%m.%Y')

            print(f"\n📊 [{utc_time_str} UTC] Пересчет статистики...")
            stats = recalculate_statistik()
            print("✅ Статистика пересчитана:")
            print(f"  ├ 🎮 Майнсвипер: {stats.get('mine', 0):.4f} TON")
            print(f"  ├ ⚔️ PVP Куб: {stats.get('pvp_kub', 0):.4f} TON")
            print(f"  └ ⚓ PVP Корабли: {stats.get('pvp_ship', 0):.4f} TON")

            print(f"\n🔄 [{utc_time_str} UTC] Запрос FDV...")
            fdv = await get_fdv_from_geckoterminal()

            if fdv and fdv > 0:
                new_data = {
                    "timestamp": utc_now.isoformat(),
                    "fdv": fdv,
                    "fdv_formatted": format_fdv(fdv),
                    "source": "geckoterminal",
                    "token_address": TOKEN_ADDRESS
                }
                history = load_history()
                history.append(new_data)
                save_history(history)
                print(f"✅ ЗАПИСАНО: {new_data['fdv_formatted']}")
                print(f"🕐 Время по UTC: {utc_date_str} {utc_time_str}")
                if len(history) > 1:
                    prev_fdv = history[-2].get('fdv')
                    if prev_fdv and prev_fdv != fdv:
                        change = ((fdv - prev_fdv) / prev_fdv) * 100
                        print(f"📈 Изменение: {change:+.2f}%")
            else:
                print("❌ Не удалось получить FDV")
                error_data = {
                    "timestamp": utc_now.isoformat(),
                    "fdv": None,
                    "fdv_formatted": "N/A",
                    "source": "geckoterminal",
                    "token_address": TOKEN_ADDRESS,
                    "error": True
                }
                history = load_history()
                history.append(error_data)
                save_history(history)
                print("⚠️ Записана ошибка в историю")

            print(f"\n⏳ Следующий сбор через {CHECK_INTERVAL // 60} минут...")
            print("=" * 60)
            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"\n❌ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
            print("⏳ Перезапуск через 60 секунд...")
            await asyncio.sleep(60)


def auto_install_packages():
    import subprocess
    import sys
    packages = ['aiohttp']
    for package in packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✅ {package} уже установлен")
        except ImportError:
            print(f"📦 Устанавливаю {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"✅ {package} установлен")


if __name__ == "__main__":
    print("🔄 Проверка зависимостей...")
    auto_install_packages()
    print()
    asyncio.run(collect_fdv())
