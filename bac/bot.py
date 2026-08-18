import secrets
import time
import json
import os
import glob
import requests
import asyncio
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultPhoto, InlineQueryResultArticle,
    InputTextMessageContent, WebAppInfo, CallbackQuery,
    Message, InlineQuery
)
from aiogram.fsm.storage.memory import MemoryStorage

try:
    from .config import BOT_TOKEN, ADMIN_CHAT_ID, WITHDRAW_COMMISSION, COMA
    from .functions import (
        register_user, get_user_data, get_balance,
        update_user_balance, recalculate_statistik,
        add_referral, save_commission_safe, get_gram_balance,
        update_user_field, add_history_record,
        load_staking_data, save_staking_data,
    )
except ImportError:
    from config import BOT_TOKEN, ADMIN_CHAT_ID, WITHDRAW_COMMISSION, COMA
    from functions import (
        register_user, get_user_data, get_balance,
        update_user_balance, recalculate_statistik,
        add_referral, save_commission_safe, get_gram_balance,
        update_user_field, add_history_record,
        load_staking_data, save_staking_data,
    )

router = Router()

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Подключаем роутер с обработчиками
dp.include_router(router)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

TOTAL_POINTS = 1000
FLASK_URL = "http://127.0.0.1:5000"
USDT_MASTER_ADDRESS = "0:b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe"
CRYPTO_PAY_TOKEN = os.environ.get("CRYPTO_PAY_TOKEN", "")
TON_DECIMALS = 1_000_000_000
USDT_DECIMALS = 1_000_000

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def escape_html(text):
    """Экранирование HTML символов"""
    if text is None:
        return ''
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))


def find_request_file(request_id):
    """Ищет файл заявки во всех папках"""
    folders = [
        os.path.join(DATA_DIR, 'withdraw_requests_gram'),
        os.path.join(DATA_DIR, 'withdraw_requests_usdt'),
        os.path.join(DATA_DIR, 'withdraw_requests_crbot')
    ]

    # Пробуем найти по точному совпадению
    for folder in folders:
        if not os.path.exists(folder):
            continue
        files = glob.glob(os.path.join(folder, f'*{request_id}*.json'))
        if files:
            return files[0]

    # Если не нашли, пробуем найти по частичному совпадению (для случая с user_id)
    for folder in folders:
        if not os.path.exists(folder):
            continue
        for file_path in glob.glob(os.path.join(folder, '*.json')):
            filename = os.path.basename(file_path).replace('.json', '')
            # Проверяем, содержится ли request_id в имени файла
            if request_id in filename:
                return file_path

    return None

def load_request_data(request_id):
    """Загружает данные заявки"""
    file_path = find_request_file(request_id)
    if not file_path:
        return None, None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data, file_path
    except Exception as e:
        print(f"❌ Ошибка загрузки заявки {request_id}: {e}")
        return None, None

def save_request_data(file_path, data):
    """Сохраняет данные заявки"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения заявки: {e}")
        return False



def distribute_points():
    """
    Распределяет 1000 поинтов среди пользователей пропорционально их GRAM.
    Возвращает словарь с начисленными поинтами.
    """
    staking_data = load_staking_data()

    if not staking_data:
        print("📭 Нет данных стейкинга для распределения")
        return {}

    # Считаем общую сумму GRAM
    total_gram = 0
    users_gram = {}

    for user_id, data in staking_data.items():
        gram = data.get('gram', 0)
        if gram > 0:  # Учитываем только тех, у кого есть GRAM
            total_gram += gram
            users_gram[user_id] = gram

    if total_gram == 0:
        print("⚠️ Общая сумма GRAM = 0, распределение невозможно")
        return {}

    # Распределяем поинты
    distributed = {}
    for user_id, gram in users_gram.items():
        # (gram / total_gram) * TOTAL_POINTS
        points = (gram / total_gram) * TOTAL_POINTS
        # Округляем до 2 знаков
        points = round(points, 2)
        distributed[user_id] = points

        # Обновляем поинты пользователя в staking.json
        if user_id in staking_data:
            current_points = staking_data[user_id].get('points', 0)
            staking_data[user_id]['points'] = current_points + points

    # Сохраняем обновленные данные
    save_staking_data(staking_data)

    print(f"✅ Распределено {TOTAL_POINTS} поинтов между {len(distributed)} пользователями")
    for user_id, points in distributed.items():
        print(f"   👤 {user_id}: +{points} поинтов")

    return distributed


async def scheduler():
    """
    Запускает функцию distribute_points() каждый день в 00:00 UTC.
    """
    print("🕐 Планировщик запущен. Ожидание 00:00 UTC...")

    while True:
        now = datetime.now(timezone.utc)

        # Вычисляем время до следующего 00:00 UTC
        next_run = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now >= next_run:
            # Если уже прошло 00:00, переходим на следующий день
            next_run += timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()

        print(
            f"⏳ Следующий запуск в {next_run.strftime('%Y-%m-%d %H:%M:%S')} UTC (через {wait_seconds / 3600:.1f} часов)")

        # Ждем до следующего 00:00
        await asyncio.sleep(wait_seconds)

        # Запускаем распределение
        print("🔄 Запуск распределения поинтов...")
        try:
            result = distribute_points()
            print(f"✅ Распределение завершено: {len(result)} пользователей получили поинты")
        except Exception as e:
            print(f"❌ Ошибка распределения: {e}")
# ==================== INLINE QUERY ====================
@router.inline_query()
async def inline_query(query: InlineQuery):
    """Обрабатывает inline запросы — @бот ref (с изображением)"""

    # Проверяем, что запрос равен "ref"
    if query.query.lower() != "ref":
        await query.answer([], cache_time=1)
        return

    user_id = str(query.from_user.id)

    # Получаем данные пользователя
    user_data = get_user_data(user_id)
    if not user_data:
        await query.answer([], cache_time=1)
        return

    # Получаем username бота
    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}/app?startapp={user_id}"

    # Текст сообщения
    text = (
        f"<tg-emoji emoji-id='5411086132085562116'>🆓</tg-emoji> "
        f"<b>Получай 0.5</b> "
        f"<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji> "
        f"<b>ежедневно!</b>\n\n"
        f"<tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> "
        f"<i>Присоединяйся и получай бонусы!</i>"
    )

    # Клавиатура с кнопкой
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⬇️ Получить",
            url=referral_link
        )]
    ])

    image_url = "https://a39586-388f.z.d-f.pw/sticer/referral_banner.png"

    # Создаем результат с фото
    result = InlineQueryResultPhoto(
        id="1",
        photo_url=image_url,
        thumbnail_url=image_url,
        title="💰 Получай 0.5 gRAM",
        description="Реферальная ссылка для бонусов",
        caption=text,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    # Отвечаем на inline запрос
    await query.answer(
        [result],
        cache_time=300,
        is_personal=True
    )

# ==================== ПРОВЕРКА ПЛАТЕЖЕЙ ====================

def check_bot_api_version(bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    response = requests.get(url)
    data = response.json()
    print("🤖 Bot API версия:", data.get('result', {}).get('api_version', 'неизвестно'))
    return data


def save_prepared_inline_message(referral_link: str, bot_token: str, user_id: str):
    url = f"https://api.telegram.org/bot{bot_token}/savePreparedInlineMessage"

    text = (
        f"<b>✨ Получай 0.5 GRAM</b> "
        f"<b>ежедневно!</b>\n\n"
        f"<blockquote>Присоединяйся и получай бонусы!</blockquote>"
    )

    # ✅ ПРАВИЛЬНЫЙ ФОРМАТ КЛАВИАТУРЫ - ТОЛЬКО СЛОВАРЬ!
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "Получить",
                    "url": referral_link
                }
            ]
        ]
    }

    prepare_data = {
        "user_id": int(user_id),
        "result": {
            "type": "photo",
            "id": str(user_id) + "_ref_photo",
            "photo_url": "https://fgfe.online/sticer/referral_bannerrr.png",
            "thumbnail_url": "https://fgfe.online/sticer/referral_bannerrr.png",
            "photo_width": 512,
            "photo_height": 512,
            "title": "💎 Получай 0.5 GRAM ежедневно!",
            "description": "Пригласи друга и получи бонус",
            "caption": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard  # ← ТЕПЕРЬ ЭТО СЛОВАРЬ!
        },
        "allow_user_chats": True,
        "allow_group_chats": True,
        "allow_channel_chats": True
    }

    print("📤 Отправка запроса:", json.dumps(prepare_data, indent=2))

    response = requests.post(url, json=prepare_data)
    result = response.json()
    print("📤 Ответ savePreparedInlineMessage:", json.dumps(result, indent=2))

    if result.get('ok'):
        msg_id = result['result']['id']
        print(f"✅ PreparedInlineMessage ID: {msg_id}")
        return msg_id
    else:
        error = result.get('description', 'Unknown error')
        print(f"❌ Ошибка: {error}")
        raise Exception(f"Ошибка: {error}")


def send_message_sync(chat_id, text, parse_mode='HTML', reply_markup=None):
    """Синхронная отправка через requests"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode
        }

        if reply_markup:
            if hasattr(reply_markup, 'to_dict'):
                reply_markup = reply_markup.to_dict()
            payload['reply_markup'] = json.dumps(reply_markup)

        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200:
            print(f"✅ Сообщение отправлено пользователю {chat_id}")
            return response.json()
        else:
            print(f"❌ Ошибка {response.status_code}: {response.text}")
            return False

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


def check_payment_received(wallet_address, expected_amount, expected_comment=None, currency='GRAM'):
    print(f"🔍 НАЧАЛО ПРОВЕРКИ:")
    print(f"   Кошелек: {wallet_address}")
    print(f"   Сумма: {expected_amount} {currency}")
    print(f"   Комментарий: {expected_comment}")

    if currency == 'USDT':
        try:
            url = f"https://tonapi.io/v2/accounts/{wallet_address}/events?limit=20"
            response = requests.get(url, timeout=15)

            if response.status_code != 200:
                print(f"❌ Ошибка TonAPI: {response.status_code}")
                return False, None

            data = response.json()
            expected_nano = int(expected_amount * USDT_DECIMALS)

            for event in data.get('events', []):
                for action in event.get('actions', []):
                    if action.get('type') == 'JettonTransfer':
                        transfer = action.get('JettonTransfer', {})
                        if not transfer:
                            continue

                        jetton = transfer.get('jetton', {})
                        if jetton.get('address') != USDT_MASTER_ADDRESS:
                            continue

                        amount_nano = int(transfer.get('amount', 0))
                        if abs(amount_nano - expected_nano) > (expected_nano * 0.05):
                            continue

                        comment = transfer.get('comment', '')
                        if expected_comment:
                            if expected_comment == comment or expected_comment.lower() == comment.lower():
                                # ✅ ПОЛУЧАЕМ base_transactions[0]
                                base_transactions = action.get('base_transactions', [])
                                tx_hash = base_transactions[0] if base_transactions else None
                                print(f"✅ Найдена USDT транзакция с комментарием: {comment}, hash: {tx_hash}")
                                return True, tx_hash
                        else:
                            base_transactions = action.get('base_transactions', [])
                            tx_hash = base_transactions[0] if base_transactions else None
                            print(f"✅ Найдена USDT транзакция без комментария, hash: {tx_hash}")
                            return True, tx_hash

            print("❌ Транзакция не найдена")
            return False, None

        except Exception as e:
            print(f"❌ Ошибка проверки USDT: {e}")
            return False, None

    else:
        try:
            url = f"https://tonapi.io/v2/accounts/{wallet_address}/events?limit=10"
            response = requests.get(url, timeout=15)

            if response.status_code != 200:
                print(f"❌ Ошибка TonAPI: {response.status_code}")
                return False, None

            data = response.json()
            expected_nano = int(expected_amount * TON_DECIMALS)

            for event in data.get('events', []):
                for action in event.get('actions', []):
                    if action.get('type') == 'TonTransfer':
                        transfer = action.get('TonTransfer', {})
                        if not transfer:
                            continue

                        amount_nano = int(transfer.get('amount', 0))
                        if abs(amount_nano - expected_nano) > 10000000:
                            continue

                        comment = transfer.get('comment', '')
                        if expected_comment:
                            if expected_comment == comment or expected_comment.lower() == comment.lower():
                                # ✅ ПОЛУЧАЕМ base_transactions[0]
                                base_transactions = action.get('base_transactions', [])
                                tx_hash = base_transactions[0] if base_transactions else None
                                print(f"✅ Найдена транзакция с комментарием: {comment}, hash: {tx_hash}")
                                return True, tx_hash
                        else:
                            base_transactions = action.get('base_transactions', [])
                            tx_hash = base_transactions[0] if base_transactions else None
                            print(f"✅ Найдена транзакция без комментария, hash: {tx_hash}")
                            return True, tx_hash

            print("❌ Транзакция не найдена")
            return False, None

        except Exception as e:
            print(f"❌ Ошибка проверки TON: {e}")
            return False, None


def send_withdraw_notification_sync(request_id, user_id, username, first_name, amount, receive_amount, wallet_address,currency='GRAM'):


    """Отправляет уведомление о заявке на вывод админу и пользователю (синхронно)"""
    safe_username = escape_html(username if username != 'unknown' else 'нет')
    safe_first_name = escape_html(first_name)
    safe_wallet = escape_html(wallet_address)

    receive_amount_num = float(receive_amount)
    amount_num = float(amount)

    if currency == 'CrBot':
        crbot_emoji = "<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji>"

        admin_message = (
            f"<b><tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji>Заявка на вывод <tg-emoji emoji-id='5411191101086276989'>👛</tg-emoji></b>\n\n"
            f"ID заявки: <code>{request_id}</code>\n\n"
            f"<blockquote><tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> Пользователь: {safe_first_name}\n"
            f" ├ User ID: <code>{user_id}</code>\n"
            f" └ Username: @{safe_username}</blockquote>\n\n"
            f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji>Списано: {amount_num:.2f} <tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>\n"
            f"<tg-emoji emoji-id='5418018703222543759'>⌛</tg-emoji> К получению: {receive_amount_num:.2f} <tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji>\n\n"
            f"<tg-emoji emoji-id='5411583656802162641'>⬇️</tg-emoji> Выберите валюту для отправки пользователю:"
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "Отправить GRAM",
                        "callback_data": f"send_crbot_gram_{request_id}",
                        "icon_custom_emoji_id": "5411228939748155514"
                    },
                    {
                        "text": "Отправить USDT",
                        "callback_data": f"send_crbot_usdt_{request_id}",
                        "icon_custom_emoji_id": "5411335450642127469"
                    }
                ],
                [
                    {
                        "text": "Отменить",
                        "callback_data": f"reject_crbot_{request_id}",
                        "icon_custom_emoji_id": "5411091552334289719"
                    },
                    {
                        "text": "Заблокировать",
                        "callback_data": f"block_crbot_{request_id}",
                        "icon_custom_emoji_id": "5413673957255586481"
                    }
                ]
            ]
        }

        user_message = (
            f"<tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji> "
            f"<b>Заявка на вывод</b><tg-emoji emoji-id='5411191101086276989'>👛</tg-emoji>\n\n"
            f"<tg-emoji emoji-id='5413573583869879994'>🪙</tg-emoji> "
            f"<b>К получению:</b> {receive_amount_num:.2f} {crbot_emoji}\n"
            f"<tg-emoji emoji-id='5411106498820480176'>📩</tg-emoji> "
            f"Заявка отправлена на обработку"
        )

    else:
        if currency == 'USDT':
            nano_amount = int(receive_amount_num * USDT_DECIMALS)
            tonkeeper_link = f"https://app.tonkeeper.com/transfer/{wallet_address}?amount={nano_amount}&jetton={USDT_MASTER_ADDRESS}&text=FGFE_{request_id}"
            currency_symbol = "USDT"
            currency_emoji = "<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji>"
        else:
            nano_amount = int(receive_amount_num * TON_DECIMALS)
            tonkeeper_link = f"https://app.tonkeeper.com/transfer/{wallet_address}?amount={nano_amount}&text=FGFE_{request_id}"
            currency_symbol = "GRAM"
            currency_emoji = "<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>"

        admin_message = (
            f"<b><tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji>Заявка на вывод {currency_symbol}</b>\n\n"
            f"<b>ID заявки:</b> <code>{request_id}</code>\n"
            f"<blockquote><tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> Пользователь: {safe_first_name}\n"
            f" ├ User ID: <code>{user_id}</code>\n"
            f" └ <tg-emoji emoji-id='5413360699520884043'>✨</tg-emoji> Username: @{safe_username}</blockquote>\n\n"
            f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji> Списано: {amount_num:.2f} <tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>\n"
            f"<tg-emoji emoji-id='5418018703222543759'>⏳</tg-emoji> К получению: {receive_amount_num:.2f} {currency_symbol}\n\n"
            f"<blockquote><tg-emoji emoji-id='5411075768329479880'>📎</tg-emoji> Кошелек: <code>{safe_wallet}</code></blockquote>\n\n"
            f"<tg-emoji emoji-id='5418018703222543759'>⏰</tg-emoji> Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": f"Отправить {currency_symbol}",
                        "url": tonkeeper_link,
                        "icon_custom_emoji_id": "5411335450642127469"
                    }
                ],
                [
                    {
                        "text": "Одобрить",
                        "callback_data": f"approve_{currency.lower()}_{request_id}",
                        "icon_custom_emoji_id": "5411267268036302635"
                    },
                    {
                        "text": "Отклонить",
                        "callback_data": f"reject_{currency.lower()}_{request_id}",
                        "icon_custom_emoji_id": "5411091552334289719"
                    }
                ],
                [
                    {
                        "text": "Заблокировать",
                        "callback_data": f"block_{currency.lower()}_{request_id}",
                        "icon_custom_emoji_id": "5413673957255586481"
                    }
                ]
            ]
        }

        user_message = (
            f"<tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji> "
            f"<b>Заявка на вывод</b>\n\n"
            f"<tg-emoji emoji-id='5413573583869879994'>🪙</tg-emoji> "
            f"<b>К получению:</b> {receive_amount_num:.2f} {currency_emoji}\n"
            f"<blockquote>{safe_wallet}</blockquote>\n\n"
            f"<tg-emoji emoji-id='5411106498820480176'>📩</tg-emoji> "
            f"Заявка отправлена на обработку"
        )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    admin_ok = False
    try:
        response = requests.post(
            url,
            json={
                'chat_id': ADMIN_CHAT_ID,
                'text': admin_message,
                'parse_mode': 'HTML',
                'reply_markup': keyboard  # В aiogram это работает так же
            },
            timeout=10
        )
        admin_ok = response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка админу {currency}: {e}")

    user_ok = False
    if str(user_id) != str(ADMIN_CHAT_ID):
        try:
            response = requests.post(
                url,
                json={
                    'chat_id': user_id,
                    'text': user_message,
                    'parse_mode': 'HTML'
                },
                timeout=10
            )
            user_ok = response.status_code == 200
        except Exception as e:
            print(f"❌ Ошибка пользователю {currency}: {e}")
    else:
        user_ok = True

    return admin_ok and user_ok

def send_user_notification(user_chat_id, amount, status, currency='GRAM', tx_hash=None):
    try:
        amount = float(amount)
    except:
        amount = 0

    # Выбираем эмодзи для валюты
    if currency == 'USDT':
        currency_emoji = "<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji>"
    elif currency == 'CrBot':
        currency_emoji = "<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji>"
    else:
        currency_emoji = "<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>"

    if status == 'approve':
        text = (
            f"<tg-emoji emoji-id='5411267268036302635'>✔️</tg-emoji> "
            f"<b>Ваша заявка на вывод {amount:.2f} {currency_emoji} одобрена!</b>\n\n"
            f"<tg-emoji emoji-id='5411191101086276989'>👛</tg-emoji>Средства отправлены на ваш кошелек."
        )
        # ✅ Добавляем ссылку ТОЛЬКО для GRAM и USDT (не для CrBot)
        if tx_hash and currency != 'CrBot':
            short_hash = f"{tx_hash[:4]}...{tx_hash[-4:]}"
            tx_link = f"https://tonscan.org/tx/{tx_hash}"
            text += f"\n\n<tg-emoji emoji-id='5411075768329479880'>📎</tg-emoji> <a href='{tx_link}'>{short_hash}</a>"

    elif status == 'reject':
        text = (
            f"<tg-emoji emoji-id='5411091552334289719'>❌</tg-emoji> "
            f"<b>Ваша заявка на вывод {amount:.2f} {currency_emoji} отклонена.</b>\n\n"
            f"Средства возвращены на баланс."
        )
    else:
        text = (
            f"<tg-emoji emoji-id='5413673957255586481'>🔒</tg-emoji> "
            f"<b>Ваша заявка на вывод {amount:.2f} {currency_emoji} заблокирована.</b>\n\n"
            f"Обратитесь в поддержку."
        )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={'chat_id': user_chat_id, 'text': text, 'parse_mode': 'HTML'}, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка уведомления {currency}: {e}")
        return False


# ==================== CRYPTO PAY ====================

def send_crypto_pay_transfer(user_id, asset, amount):
    url = "https://pay.crypt.bot/api/transfer"

    headers = {
        'Crypto-Pay-API-Token': CRYPTO_PAY_TOKEN,
        'Content-Type': 'application/json'
    }

    spend_id = f"{user_id}_{int(time.time())}_{secrets.token_hex(4)}"

    data = {
        'user_id': int(user_id),
        'asset': asset,
        'amount': str(amount),
        'spend_id': spend_id
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=30)
        result = response.json()

        if result.get('ok'):
            print(f"✅ Перевод {amount} {asset} пользователю {user_id} выполнен!")
            return {'success': True, 'result': result['result']}
        else:
            print(f"❌ Ошибка: {result.get('error')}")
            return {'success': False, 'error': result.get('error')}

    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")
        return {'success': False, 'error': str(e)}


# ==================== ЗАЯВКИ ====================

def get_pending_withdraw_requests():
    pending_requests = []

    folders = [
        os.path.join(DATA_DIR, 'withdraw_requests_gram'),
        os.path.join(DATA_DIR, 'withdraw_requests_usdt'),
        os.path.join(DATA_DIR, 'withdraw_requests_crbot')
    ]

    for folder in folders:
        if not os.path.exists(folder):
            continue

        files = glob.glob(os.path.join(folder, '*.json'))

        for file_path in files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    request_data = json.load(f)

                if request_data.get('status', 'pending') == 'pending':
                    filename = os.path.basename(file_path)
                    request_id = filename.replace('.json', '')

                    currency = request_data.get('currency', 'GRAM')
                    amount = float(request_data.get('amount', 0))
                    receive_amount = float(request_data.get('receive_amount', amount))

                    pending_requests.append({
                        'request_id': request_id,
                        'file_path': file_path,
                        'user_id': request_data.get('user_id'),
                        'username': request_data.get('username', 'unknown'),
                        'first_name': request_data.get('first_name', 'User'),
                        'amount': amount,
                        'receive_amount': receive_amount,
                        'wallet_address': request_data.get('wallet_address', ''),
                        'created_at': request_data.get('created_at', ''),
                        'currency': currency
                    })
            except Exception as e:
                print(f"Ошибка чтения {file_path}: {e}")

    pending_requests.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return pending_requests


# ==================== КОМАНДЫ БОТА ====================

@router.message(Command("start"))
async def start(message: Message):
    user = message.from_user
    user_id = str(user.id)

    args = message.text.split()
    referrer_id = args[1] if len(args) > 1 else None

    is_new = register_user(user.id, user.username or "unknown", user.first_name or "")

    if referrer_id and referrer_id != user_id and is_new:
        add_referral(user_id, referrer_id)

    # ✅ Получаем данные пользователя
    user_data = get_user_data(user.id)
    # ✅ Берем ton_balance (реальный баланс в GRAM)
    balance = float(user_data.get('ton_balance', 0))

    if is_new:
        welcome_msg = (
            f"<tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> "
            f"Добро пожаловать, <b>{user.first_name}!</b>"
        )
        await message.answer(welcome_msg, parse_mode='HTML')

        info_msg = (
            f"<tg-emoji emoji-id='5413360699520884043'>✨</tg-emoji> Наш канал - @FGFEofficial\n\n"
            f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji> <b>Баланс: {balance:.2f}</b> <tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>\n\n"
            f"<blockquote><tg-emoji emoji-id='5411086132085562116'>🆓</tg-emoji> Бесплатные 0.5 <tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji> <b>каждый день</b></blockquote>"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Играть",
                web_app=WebAppInfo(url="https://fgfe.online"),
                style="primary",
                icon_custom_emoji_id="5411123103164046669"
            )]
        ])

        await message.answer(info_msg, parse_mode='HTML', reply_markup=keyboard)

    else:
        info_msg = (
            f"<tg-emoji emoji-id='5413360699520884043'>✨</tg-emoji> Наш канал - @FGFEofficial\n\n"
            f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji> <b>Баланс: {balance:.2f}</b> <tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>\n\n"
            f"<blockquote><tg-emoji emoji-id='5411086132085562116'>🆓</tg-emoji> Бесплатные 0.5 <tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji> <b>каждый день</b></blockquote>"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Играть",
                web_app=WebAppInfo(url="https://fgfe.online"),
                style="primary",
                icon_custom_emoji_id="5411123103164046669"
            )]
        ])

        await message.answer(info_msg, parse_mode='HTML', reply_markup=keyboard)

@router.message(Command("post"))
async def post_command(message: Message):
    """Отправляет пост с изображением в канал"""
    user_id = message.from_user.id

    # Проверка прав админа
    if user_id != ADMIN_CHAT_ID:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    channel_id = "-1003923363941"  # ID канала

    # Текст поста
    text = (
        f"<tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> "
        f"<b>What Is FGFE?</b>\n"
        f"<tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> "
        f"<b>Free Gram For Everyone</b>\n\n"
        f"<tg-emoji emoji-id='5411371914914473558'>🥇</tg-emoji> "
        f"<b>FGFE</b> - is a meme token on the TON blockchain, as well as a casino project with various pvp and pve games\n\n"
        f"<tg-emoji emoji-id='5411086132085562116'>🆓</tg-emoji> <b>Bonuses</b>\n"
        f"<tg-emoji emoji-id='5427095085810490858'>✅</tg-emoji> Daily reward of 0.5 GRAM\n"
        f"<tg-emoji emoji-id='5427095085810490858'>✅</tg-emoji> Weekly and daily draws\n"
        f"<tg-emoji emoji-id='5427095085810490858'>✅</tg-emoji> Gram stacking system\n"
        f"<tg-emoji emoji-id='5427095085810490858'>✅</tg-emoji> Referral rewards"
    )

    # Кнопка
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Open FGFE",
            url="https://t.me/fgramfe_bot/app"
        )]
    ])

    # URL изображения
    image_url = "https://fgfe.online/sticer/post.jpg"

    try:
        await bot.send_photo(
            chat_id=channel_id,
            photo=image_url,
            caption=text,
            parse_mode='HTML',
            reply_markup=keyboard
        )
        await message.answer("✅ Пост успешно опубликован в канале!")
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {str(e)}")

@router.message(Command("balance"))
async def balance(message: Message):
    bal = get_balance(message.from_user.id)
    await message.answer(f"💰 Ваш баланс: {bal} FGFE")


@router.message(Command("profile"))
async def profile(message: Message):
    user_data = get_user_data(message.from_user.id)
    profile_text = f"""
📱 **Ваш профиль**
ID: {user_data['id']}
👤 Имя: {user_data['name']}
📝 Username: {user_data['username']}
💰 Баланс: {user_data['balans']} FGFE
🔗 Кошелек: {user_data['kosh']}
🏆 Уровень: {user_data['lvl']}
    """
    await message.answer(profile_text, parse_mode='Markdown')

@router.message(Command("zarre"))
async def show_pending_requests(message: Message):
    user_id = message.from_user.id

    if user_id != ADMIN_CHAT_ID:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    pending_requests = get_pending_withdraw_requests()

    if not pending_requests:
        await message.answer("📭 Нет активных заявок на вывод.")
        return

    count = len(pending_requests)

    keyboard = []
    for req in pending_requests[:20]:
        created_time = req.get('created_at', '').replace('T', ' ')[:16]
        currency = req.get('currency', 'GRAM')

        # Выбираем эмодзи в зависимости от валюты
        if currency == 'USDT':
            emoji = '💵'
            emoji_id = "5411335450642127469"
        elif currency == 'CrBot':
            emoji = '👛'
            emoji_id = "5411191101086276989"
        else:
            emoji = '💎'
            emoji_id = "5411228939748155514"

        button_text = f"{emoji} {req['amount']:.2f} | {created_time}"
        keyboard.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"view_{req['request_id']}",
                icon_custom_emoji_id=emoji_id  # ✅ КАСТОМНЫЙ ЭМОДЗИ
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data="refresh_requests",
            icon_custom_emoji_id="5418018703222543759"  # ⌛️
        )
    ])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    # Считаем по всем валютам
    total_gram = sum(r['amount'] for r in pending_requests if r.get('currency') == 'GRAM')
    total_usdt = sum(r['amount'] for r in pending_requests if r.get('currency') == 'USDT')
    total_crbot = sum(r['amount'] for r in pending_requests if r.get('currency') == 'CrBot')
    total = total_crbot + total_gram + total_usdt
    total_receive = total * (100 - WITHDRAW_COMMISSION) / 100

    message_text = (
        f"<b><tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji> Активные заявки на вывод</b>\n\n"
        f"<tg-emoji emoji-id='5411106498820480176'>✉️</tg-emoji> <b>Количество:</b> {count}\n\n"
        f"<blockquote><tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji> <b>GRAM:</b> {total_gram:.2f} GRAM\n"
        f"<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji> <b>USDT:</b> {total_usdt:.2f} USDT\n"
        f"<tg-emoji emoji-id='5411191101086276989'>👛</tg-emoji> <b>CrBot:</b> {total_crbot:.2f} GRAM</blockquote>\n\n"
        f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji> <b>Всего к выдаче:</b> {total_receive:.2f} (с комиссией)\n\n"
    )

    await message.answer(message_text, parse_mode='HTML', reply_markup=reply_markup)

@router.message(Command("bonus"))
async def bonus_command(message: Message):
    user_id = message.from_user.id

    if user_id != ADMIN_CHAT_ID:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /bonus user_id\nПример: /bonus 123456789")
        return

    target_user_id = args[1]

    if not target_user_id.isdigit():
        await message.answer("❌ ID должен быть числом. Пример: /bonus 123456789")
        return

    token = secrets.token_hex(16)

    bonus_data_file = os.path.join(DATA_DIR, 'bonus_tokens.json')
    os.makedirs(os.path.dirname(bonus_data_file), exist_ok=True)

    bonus_tokens = {}
    if os.path.exists(bonus_data_file):
        try:
            with open(bonus_data_file, 'r', encoding='utf-8') as f:
                bonus_tokens = json.load(f)
        except:
            bonus_tokens = {}

    bonus_tokens[token] = {
        'user_id': target_user_id,
        'created_at': time.time(),
        'used': False
    }

    with open(bonus_data_file, 'w', encoding='utf-8') as f:
        json.dump(bonus_tokens, f, indent=2, ensure_ascii=False)

    bot_username = (await bot.get_me()).username
    bonus_url = f"https://t.me/{bot_username}/app?startapp=bonus_page_{token}&mode=compact"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Забрать",
            url=bonus_url,
            style="success",
            icon_custom_emoji_id="5413360699520884043"

        )]
    ])

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=(
                "<tg-emoji emoji-id='5411086132085562116'>🆓</tg-emoji> "
                "<b>Тебе начислили бонус 0.5</b> "
                "<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>\n\n"
                "<blockquote><tg-emoji emoji-id='5411267268036302635'>✔️</tg-emoji>Нажми на кнопку ниже, чтобы получить</blockquote>"
            ),
            parse_mode='HTML',
            reply_markup=keyboard
        )
        await message.answer(f"✅ Бонусное сообщение отправлено пользователю {target_user_id}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {str(e)}")

# ==================== ГЛАВНЫЙ ОБРАБОТЧИК CALLBACK ====================


@router.callback_query()
async def handle_callback(callback: CallbackQuery):
    """Главный обработчик всех callback'ов"""
    callback_data = callback.data
    if callback_data.startswith("join_game_"):
        await callback.answer()

        chat_id = int(callback_data.replace("join_game_", ""))

        if chat_id not in games:
            await bot.send_message(
                chat_id=callback.from_user.id,
                text="❌ Игра уже завершена или отменена.",
                parse_mode='HTML'
            )
            return

        game = games[chat_id]
        user_id = callback.from_user.id

        # Проверяем, кто нажал
        if user_id == game['creator_id']:
            if game['creator_joined']:
                await callback.answer("❌ Вы уже присоединились!", show_alert=True)
                return
            game['creator_joined'] = True
        else:
            if game['player2_joined']:
                await callback.answer("❌ Второй игрок уже присоединился!", show_alert=True)
                return
            if game['player2_id'] is None:
                game['player2_id'] = user_id
                game['player2_name'] = callback.from_user.first_name
                game['player2_username'] = callback.from_user.username or "нет"
            game['player2_joined'] = True

        # Проверяем баланс
        balance = get_gram_balance(user_id)
        bet = game['bet']

        if balance < bet:
            await bot.send_message(
                chat_id=user_id,
                text=f"❌ Недостаточно средств! Ваш баланс: {balance:.2f} GRAM",
                parse_mode='HTML'
            )
            if user_id == game['creator_id']:
                game['creator_joined'] = False
            else:
                game['player2_joined'] = False
                game['player2_id'] = None
            return

        # Списываем ставку
        user_data = get_user_data(user_id)
        current_balance = float(user_data.get('ton_balance', 0))
        new_balance = current_balance - bet

        update_user_field(user_id, 'ton_balance', new_balance)

        add_history_record(
            user_id,
            -bet,
            'GRAM',
            f'Ставка в игре Кости',
            new_balance,
            'Ставка'
        )

        print(f"💰 Снято {bet} GRAM с игрока {user_id}")

        # ====== ОТПРАВЛЯЕМ УВЕДОМЛЕНИЕ В ЛИЧКУ ТОМУ, КТО НАЖАЛ ======
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"<tg-emoji emoji-id='5411267268036302635'>✅</tg-emoji> "
                f"<b>Вы присоединились к игре!</b>\n\n"
                f"<tg-emoji emoji-id='5411335450642127469'>💰</tg-emoji> "
                f"<b>Ставка:</b> {game['bet']:.2f} GRAM\n"
                f"<tg-emoji emoji-id='5411228939748155514'>🏦</tg-emoji> "
                f"<b>Банк:</b> {game['bank']:.2f} GRAM\n\n"
                f"<tg-emoji emoji-id='5418018703222543759'>⏳</tg-emoji> "
                f"<b>Ожидаем второго игрока...</b>"
            ),
            parse_mode='HTML'
        )

        # ====== ЕСЛИ ОБА ПРИСОЕДИНИЛИСЬ ======
        if game['creator_joined'] and game['player2_joined']:
            # ✅ ОТПРАВЛЯЕМ В ЛИЧКУ СОЗДАТЕЛЮ
            await bot.send_message(
                chat_id=game['creator_id'],
                text=(
                    f"<tg-emoji emoji-id='5411267268036302635'>🎉</tg-emoji> "
                    f"<b>Игра началась!</b>\n\n"
                    f"<tg-emoji emoji-id='5413360699520884043'>👤</tg-emoji> "
                    f"<b>Противник:</b> {game['player2_name']}\n"
                    f"<tg-emoji emoji-id='5411335450642127469'>💰</tg-emoji> "
                    f"<b>Ставка:</b> {game['bet']:.2f} GRAM\n"
                    f"<tg-emoji emoji-id='5411228939748155514'>🏦</tg-emoji> "
                    f"<b>Банк:</b> {game['bank']:.2f} GRAM\n\n"
                    f"<i>Удачи! 🍀</i>"
                ),
                parse_mode='HTML'
            )

            # ✅ ОТПРАВЛЯЕМ В ЛИЧКУ ВТОРОМУ ИГРОКУ
            await bot.send_message(
                chat_id=game['player2_id'],
                text=(
                    f"<tg-emoji emoji-id='5411267268036302635'>🎉</tg-emoji> "
                    f"<b>Игра началась!</b>\n\n"
                    f"<tg-emoji emoji-id='5413360699520884043'>👤</tg-emoji> "
                    f"<b>Создатель:</b> {game['creator_name']}\n"
                    f"<tg-emoji emoji-id='5411335450642127469'>💰</tg-emoji> "
                    f"<b>Ставка:</b> {game['bet']:.2f} GRAM\n"
                    f"<tg-emoji emoji-id='5411228939748155514'>🏦</tg-emoji> "
                    f"<b>Банк:</b> {game['bank']:.2f} GRAM\n\n"
                    f"<i>Удачи! 🍀</i>"
                ),
                parse_mode='HTML'
            )

            # ❌ В ОБЩИЙ ЧАТ НИЧЕГО НЕ ОТПРАВЛЯЕМ!

            games.pop(chat_id, None)
            return

        return

    await callback.answer()

    callback_data = callback.data
    user_id = callback.from_user.id

    print(f"🔍 Получен callback: {callback_data}")

    # Проверка прав для админских действий
    if user_id != ADMIN_CHAT_ID:
        await callback.answer("❌ У вас нет прав для этого действия.", show_alert=True)
        return

    # ========== ОБНОВЛЕНИЕ СПИСКА ==========
    if callback_data == 'refresh_requests':
        pending_requests = get_pending_withdraw_requests()

        if not pending_requests:
            await callback.message.edit_text("📭 Нет активных заявок на вывод.")
            return

        count = len(pending_requests)

        keyboard = []
        for req in pending_requests[:20]:
            created_time = req.get('created_at', '').replace('T', ' ')[:16]
            currency = req.get('currency', 'GRAM')

            # Выбираем эмодзи и ID для валюты
            if currency == 'USDT':
                emoji = '💵'
                emoji_id = "5411335450642127469"
            elif currency == 'CrBot':
                emoji = '👛'
                emoji_id = "5411191101086276989"
            else:
                emoji = '💎'
                emoji_id = "5411228939748155514"

            button_text = f"{req['amount']:.2f} {currency} | {created_time}"
            keyboard.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"view_{req['request_id']}",
                    icon_custom_emoji_id=emoji_id
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                text="Обновить",
                callback_data="refresh_requests",
                icon_custom_emoji_id="5418018703222543759"
            )
        ])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        total_gram = sum(r['amount'] for r in pending_requests if r.get('currency') == 'GRAM')
        total_usdt = sum(r['amount'] for r in pending_requests if r.get('currency') == 'USDT')
        total_crbot = sum(r['amount'] for r in pending_requests if r.get('currency') == 'CrBot')
        total = total_crbot + total_gram + total_usdt
        total_receive = total * (100 - WITHDRAW_COMMISSION) / 100

        message_text = (
            f"<b><tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji> Активные заявки на вывод</b>\n\n"
            f"<tg-emoji emoji-id='5411106498820480176'>✉️</tg-emoji> <b>Количество:</b> {count}\n\n"
            f"<blockquote><tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji> <b>GRAM:</b> {total_gram:.2f} GRAM\n"
            f"<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji> <b>USDT:</b> {total_usdt:.2f} USDT\n"
            f"<tg-emoji emoji-id='5411191101086276989'>👛</tg-emoji> <b>CrBot:</b> {total_crbot:.2f} GRAM</blockquote>\n\n"
            f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji> <b>Всего к выдаче:</b> {total_receive:.2f} (с комиссией)"
        )

        await callback.message.edit_text(message_text, parse_mode='HTML', reply_markup=reply_markup)
        return

    # ========== ПРОСМОТР ЗАЯВКИ ==========
    if callback_data.startswith('view_'):
        request_id = callback_data.replace('view_', '')

        print(f"🔍 Ищем заявку {request_id} во всех папках...")

        request_data, file_path = load_request_data(request_id)
        if not request_data:
            await callback.message.edit_text(f"❌ Заявка {request_id} не найдена")
            return

        currency = request_data.get('currency', 'GRAM')
        currency_lower = currency.lower()

        amount = float(request_data.get('amount', 0))
        receive_amount = float(request_data.get('receive_amount', amount))
        created_at = request_data.get('created_at', '').replace('T', ' ')[:19]

        detail_text = (
            f"<b><tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji> Детали заявки</b>\n\n"
            f"<b>ID:</b> <code>{request_id}</code>\n\n"
            f"<blockquote><tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> Пользователь: {escape_html(request_data.get('first_name', 'User'))}\n"
            f" ├ User ID: <code>{request_data.get('user_id')}</code>\n"
            f" └ <tg-emoji emoji-id='5413360699520884043'>✨</tg-emoji> Username: @{escape_html(request_data.get('username', 'unknown'))}</blockquote>\n\n"
        )

        if currency in ['USDT', 'CrBot']:
            detail_text += (
                f"<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji> GRAM (списано): {amount:.2f} GRAM\n"
                f"<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji> К получению: {receive_amount:.2f} {currency}\n\n"
            )
        else:
            detail_text += (
                f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji> Сумма вывода: {amount:.2f} {currency}\n"
                f"<tg-emoji emoji-id='5418018703222543759'>⏳</tg-emoji> Комиссия ({WITHDRAW_COMMISSION}%): {amount * (WITHDRAW_COMMISSION / 100):.2f} {currency}\n"
                f"<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji> К получению: {receive_amount:.2f} {currency}\n\n"
            )

        if currency != 'CrBot':
            detail_text += (
                f"<blockquote><tg-emoji emoji-id='5411075768329479880'>📎</tg-emoji> Кошелек: <code>{escape_html(request_data.get('wallet_address', ''))}</code></blockquote>\n\n"
            )

        detail_text += (
            f"<tg-emoji emoji-id='5413360699520884043'>✨</tg-emoji> Время: {created_at}\n"
            f"<tg-emoji emoji-id='5341715473882955310'>⚙️</tg-emoji> Статус: {request_data.get('status', 'pending').upper()}"
        )

        # КНОПКИ
        if currency == 'CrBot':
            action_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отправить GRAM",
                        callback_data=f"send_crbot_gram_{request_id}",
                        icon_custom_emoji_id="5411228939748155514"
                    ),
                    InlineKeyboardButton(
                        text="Отправить USDT",
                        callback_data=f"send_crbot_usdt_{request_id}",
                        icon_custom_emoji_id="5411335450642127469"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Отменить",
                        callback_data=f"reject_crbot_{request_id}",
                        icon_custom_emoji_id="5411091552334289719"
                    ),
                    InlineKeyboardButton(
                        text="Заблокировать",
                        callback_data=f"block_crbot_{request_id}",
                        icon_custom_emoji_id="5413673957255586481"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Назад к списку",
                        callback_data="refresh_requests",
                        icon_custom_emoji_id="5411583656802162641"
                    )
                ]
            ])
        else:
            if currency == 'USDT':
                nano_amount = int(receive_amount * USDT_DECIMALS)
                tonkeeper_link = f"https://app.tonkeeper.com/transfer/{request_data.get('wallet_address')}?amount={nano_amount}&jetton={USDT_MASTER_ADDRESS}&text=FGFE_{request_id}"
            else:
                nano_amount = int(receive_amount * TON_DECIMALS)
                tonkeeper_link = f"https://app.tonkeeper.com/transfer/{request_data.get('wallet_address')}?amount={nano_amount}&text=FGFE_{request_id}"

            action_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Отправить {currency}",
                        url=tonkeeper_link,
                        icon_custom_emoji_id="5411335450642127469"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Одобрить",
                        callback_data=f"approve_{currency_lower}_{request_id}",
                        icon_custom_emoji_id="5411267268036302635"
                    ),
                    InlineKeyboardButton(
                        text="Отклонить",
                        callback_data=f"reject_{currency_lower}_{request_id}",
                        icon_custom_emoji_id="5411091552334289719"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Заблокировать",
                        callback_data=f"block_{currency_lower}_{request_id}",
                        icon_custom_emoji_id="5413673957255586481"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Назад к списку",
                        callback_data="refresh_requests",
                        icon_custom_emoji_id="5411583656802162641"
                    )
                ]
            ])

        await callback.message.edit_text(detail_text, parse_mode='HTML', reply_markup=action_keyboard)
        return

    # ========== ОБРАБОТКА ДЕЙСТВИЙ С ЗАЯВКОЙ ==========
    parts = callback_data.split('_')
    action = parts[0]

    # ====== CRBOT ======
    if len(parts) >= 2 and parts[1] == 'crbot':
        sub_action = parts[0]

        if sub_action in ['send', 'approve']:
            if len(parts) >= 4:
                send_currency = parts[2].upper() if len(parts) > 2 else 'GRAM'
                request_id = '_'.join(parts[3:]) if len(parts) > 3 else ''
            else:
                send_currency = 'GRAM'
                request_id = '_'.join(parts[2:]) if len(parts) > 2 else ''
        else:
            send_currency = 'GRAM'
            request_id = '_'.join(parts[2:]) if len(parts) > 2 else ''

        print(f"🟣 CrBot: action={sub_action}, request_id={request_id}, send_currency={send_currency}")

        request_data, file_path = load_request_data(request_id)
        if not request_data:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return

        if sub_action == 'send':
            if send_currency == 'GRAM':
                send_amount = float(request_data.get('amount', 0))
                display_text = f"<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji> Сумма: {send_amount:.2f} GRAM (эквивалент {request_data.get('receive_amount', 0):.2f} CrBot)"
            elif send_currency == 'USDT':
                send_amount = float(request_data.get('receive_amount', 0))
                display_text = f"<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji> Сумма: {send_amount:.2f} USDT (эквивалент {request_data.get('receive_amount', 0):.2f} CrBot)"
            else:
                send_amount = float(request_data.get('amount', 0))
                display_text = f"<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji> Сумма: {send_amount:.2f} {send_currency}"

            admin_message = (
                f"<b><tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji> Отправка {send_currency}</b>\n\n"
                f"<b>Заявка:</b> <code>{request_id}</code>\n"
                f"<blockquote><tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> Пользователь: {request_data.get('first_name', 'User')}\n"
                f"{display_text}</blockquote>\n\n"
                f"<tg-emoji emoji-id='5411583656802162641'>⬇️</tg-emoji> Нажмите кнопку ниже, чтобы отправить {send_currency} через Crypto Pay."
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Отправить {send_currency}",
                        callback_data=f"approve_crbot_{send_currency.lower()}_{request_id}",
                        icon_custom_emoji_id="5411267268036302635"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Назад",
                        callback_data=f"back_crbot_{request_id}",
                        icon_custom_emoji_id="5411583656802162641"
                    )
                ]
            ])

            await callback.message.edit_text(admin_message, parse_mode='HTML', reply_markup=keyboard)
            return

        if sub_action == 'back':
            admin_message = (
                f"<b><tg-emoji emoji-id='5411081098383893968'>🔔</tg-emoji> Заявка на вывод <tg-emoji emoji-id='5411191101086276989'>👛</tg-emoji></b>\n\n"
                f"<b>ID заявки:</b> <code>{request_id}</code>\n"
                f"<blockquote><tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> Пользователь: {request_data.get('first_name', 'User')}\n"
                f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji> Сумма: {request_data.get('receive_amount', 0):.2f} CrBot</blockquote>\n\n"
                f"<tg-emoji emoji-id='5411583656802162641'>⬇️</tg-emoji> Выберите валюту для отправки пользователю:"
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отправить GRAM",
                        callback_data=f"send_crbot_gram_{request_id}",
                        icon_custom_emoji_id="5411228939748155514"
                    ),
                    InlineKeyboardButton(
                        text="Отправить USDT",
                        callback_data=f"send_crbot_usdt_{request_id}",
                        icon_custom_emoji_id="5411335450642127469"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Отменить",
                        callback_data=f"reject_crbot_{request_id}",
                        icon_custom_emoji_id="5411091552334289719"
                    ),
                    InlineKeyboardButton(
                        text="Заблокировать",
                        callback_data=f"block_crbot_{request_id}",
                        icon_custom_emoji_id="5413673957255586481"
                    )
                ]
            ])

            await callback.message.edit_text(admin_message, parse_mode='HTML', reply_markup=keyboard)
            return

        if sub_action == 'approve':
            user_id = request_data.get('user_id')
            username = request_data.get('username', 'unknown')

            if send_currency == 'GRAM':
                send_amount = float(request_data.get('amount', 0))
            elif send_currency == 'USDT':
                send_amount = float(request_data.get('receive_amount', 0))
            else:
                send_amount = float(request_data.get('amount', 0))

            receive_amount = float(request_data.get('receive_amount', 0))

            print(f"✅ CrBot approve: отправка {send_amount} {send_currency} пользователю {user_id}")

            await callback.message.edit_text(
                f"⏳ Отправка {send_amount:.2f} {send_currency} пользователю...",
                parse_mode='HTML'
            )

            try:
                asset = 'TON' if send_currency == 'GRAM' else 'USDT'
                transfer_result = send_crypto_pay_transfer(user_id=user_id, asset=asset, amount=send_amount)

                if transfer_result.get('success'):
                    request_data['status'] = 'approved'
                    request_data['processed_at'] = datetime.now().isoformat()
                    request_data['processed_by'] = ADMIN_CHAT_ID
                    request_data['sent_currency'] = send_currency
                    request_data['transfer_id'] = transfer_result.get('result', {}).get('transfer_id')
                    save_request_data(file_path, request_data)

                    send_user_notification(user_id, receive_amount, 'approve', 'CrBot')

                    await callback.message.edit_text(
                        f"<tg-emoji emoji-id='5411267268036302635'>✔️</tg-emoji> Заявка {request_id} <b>ПОДТВЕРЖДЕНА</b>!\n\n"
                        f"<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji> Отправлено: {send_amount:.2f} {send_currency}\n"
                        f"<tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> Пользователь: @{username}",
                        parse_mode='HTML'
                    )
                    await callback.answer(f"✅ {send_amount:.2f} {send_currency} отправлено!", show_alert=True)

                    try:
                        await bot.send_message(
                            chat_id=ADMIN_CHAT_ID,
                            text=(
                                f"<tg-emoji emoji-id='5411267268036302635'>✔️</tg-emoji> <b>Автоматическая отправка выполнена!</b>\n\n"
                                f"<tg-emoji emoji-id='5411075768329479880'>📎</tg-emoji> Заявка: <code>{request_id}</code>\n"
                                f"<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji> Отправлено: {send_amount:.2f} {send_currency}\n"
                                f"<tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> Пользователь: @{username}"
                            ),
                            parse_mode='HTML'
                        )
                    except:
                        pass
                else:
                    error = transfer_result.get('error', 'Неизвестная ошибка')
                    await callback.message.edit_text(
                        f"❌ Ошибка отправки!\nЗаявка: {request_id}\nОшибка: {error}",
                        parse_mode='HTML'
                    )
                    await callback.answer(f"❌ Ошибка: {error}", show_alert=True)
            except Exception as e:
                print(f"❌ Ошибка CrBot approve: {e}")
                import traceback
                traceback.print_exc()
                await callback.message.edit_text(f"❌ Ошибка: {str(e)}", parse_mode='HTML')
                await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
            return

        if sub_action in ['reject', 'block']:
            is_reject = sub_action == 'reject'
            if is_reject:
                user_id = request_data.get('user_id')
                amount = float(request_data.get('amount', 0))
                update_user_balance(user_id, amount, 'Возврат при отмене вывода CrBot', 'Отменено')
                send_user_notification(user_id, amount, 'reject', 'GRAM')

            request_data['status'] = 'rejected' if is_reject else 'blocked'
            request_data['processed_at'] = datetime.now().isoformat()
            request_data['processed_by'] = ADMIN_CHAT_ID
            save_request_data(file_path, request_data)

            status_text = "❌ ОТМЕНЕНА" if is_reject else "🔒 ЗАБЛОКИРОВАНА"
            await callback.message.edit_text(f"✅ Заявка {request_id} {status_text}", parse_mode='HTML')
            await callback.answer(f"Заявка {status_text}", show_alert=True)
            return

    # ====== GRAM / USDT ======
    if action in ['approve', 'reject', 'block'] and len(parts) >= 2:
        currency = parts[1].upper() if parts[1].lower() in ['gram', 'usdt'] else None
        request_id = '_'.join(parts[2:]) if len(parts) > 2 else ''

        if not currency:
            await callback.answer("❌ Неизвестная валюта", show_alert=True)
            return

        print(f"💎 {currency}: action={action}, request_id={request_id}")

        if action == 'approve':
            request_data, file_path = load_request_data(request_id)
            if not request_data:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            wallet_address = request_data.get('wallet_address')
            receive_amount = float(request_data.get('receive_amount', 0))
            amount = float(request_data.get('amount', 0))

            await callback.message.edit_text(
                f"<tg-emoji emoji-id='5418018703222543759'>⏳</tg-emoji> <b>Проверка транзакции...</b>\n\n"
                f"<blockquote><tg-emoji emoji-id='5411075768329479880'>📎</tg-emoji> Кошелек: <code>{wallet_address}</code></blockquote>\n"
                f"<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji> Сумма: {receive_amount:.2f} {currency}",
                parse_mode='HTML'
            )

            payment_received, tx_hash = check_payment_received(
                wallet_address=wallet_address,
                expected_amount=receive_amount,
                expected_comment=f"FGFE_{request_id}",
                currency=currency
            )

            if payment_received:
                commission_ton = amount * (WITHDRAW_COMMISSION / 100)
                save_commission_safe('vivod', commission_ton)
                print(f"💰 Записана комиссия вывода: {commission_ton:.2f} TON")

                await callback.message.edit_text(
                    f"<tg-emoji emoji-id='5411267268036302635'>✔️</tg-emoji> <b>Транзакция подтверждена!</b>\n\n"
                    f"<tg-emoji emoji-id='5411075768329479880'>📎</tg-emoji> Заявка <code>{request_id}</code> <b>одобрена</b>.",
                    parse_mode='HTML'
                )

                endpoint = f"{FLASK_URL}/api/withdraw_callback_usdt" if currency == 'USDT' else f"{FLASK_URL}/api/withdraw_callback"
                response = requests.post(endpoint, json={'request_id': request_id, 'action': 'approve'}, timeout=10)

                if tx_hash:
                    short_hash = f"{tx_hash[:4]}...{tx_hash[-4:]}"
                    tx_link = f"https://tonscan.org/tx/{tx_hash}"
                    if currency == 'USDT':
                        currency_emoji = "<tg-emoji emoji-id='5411335450642127469'>💵</tg-emoji>"
                    else:
                        currency_emoji = "<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>"

                    await bot.send_message(
                        chat_id=request_data.get('user_id'),
                        text=(
                            f"<tg-emoji emoji-id='5411267268036302635'>✔️</tg-emoji> "
                            f"<b>Ваша заявка на вывод {receive_amount:.2f} {currency_emoji} одобрена!</b>\n\n"
                            f"<tg-emoji emoji-id='5411156449290134104'>👛</tg-emoji>Средства отправлены на ваш кошелек.\n"
                            f"<tg-emoji emoji-id='5411075768329479880'>📎</tg-emoji> "
                            f"<a href='{tx_link}'>{short_hash}</a>"
                        ),
                        parse_mode='HTML'
                    )

                await callback.answer("✅ Заявка одобрена!", show_alert=True)
            else:
                await callback.message.edit_text(
                    f"❌ Транзакция не найдена!\n\n"
                    f"Убедитесь, что вы отправили {receive_amount:.2f} {currency}\n"
                    f"на кошелек: <code>{wallet_address}</code>\n\n"
                    f"Если вы уже отправили, подождите несколько минут\n"
                    f"и нажмите кнопку ✅ еще раз.",
                    parse_mode='HTML'
                )
                await callback.answer("❌ Транзакция не найдена", show_alert=True)
            return

        try:
            endpoint = f"{FLASK_URL}/api/withdraw_callback_usdt" if currency == 'USDT' else f"{FLASK_URL}/api/withdraw_callback"
            response = requests.post(endpoint, json={'request_id': request_id, 'action': action}, timeout=10)

            if response.status_code == 200 and response.json().get('success'):
                status_text = {
                    'reject': f"❌ Заявка {currency} отклонена",
                    'block': f"🔒 Заявка {currency} заблокирована"
                }.get(action, "Обработано")

                if action == 'reject':
                    request_data, _ = load_request_data(request_id)
                    if request_data:
                        amount = float(request_data.get('amount', 0))
                        user_id = request_data.get('user_id')
                        update_user_balance(user_id, amount, f'Возврат при отмене вывода {currency}', 'Отменено')
                        send_user_notification(user_id, amount, 'reject', currency)

                await callback.answer(status_text, show_alert=True)
                await callback.message.edit_text(f"✅ Заявка {request_id} {status_text}", parse_mode='HTML')
            else:
                error_msg = response.json().get('error', 'Неизвестная ошибка')
                await callback.answer(f"❌ Ошибка: {error_msg}", show_alert=True)
        except Exception as e:
            print(f"❌ Ошибка GRAM/USDT: {e}")
            await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)

games = {}


@router.guest_message()
async def handle_guest_message(message: types.Message):
    """
    Обрабатывает гостевые сообщения.
    Формат: @fgramfe_bot сумма 🎲
    Пример: @fgramfe_bot 100 🎲
    """
    user = message.from_user
    text = message.text or ""

    if not message.guest_query_id:
        print("❌ Нет guest_query_id")
        return

    # Парсим сообщение: ищем число и эмодзи 🎲
    parts = text.split()
    bet = None

    for part in parts:
        if part.isdigit():
            bet = float(part)
            break

    # Проверяем наличие 🎲
    has_dice = "🎲" in text

    if not bet or bet <= 0 or not has_dice:
        response_text = (
            f"<b>❌ Неправильный формат!</b>\n\n"
            f"Используйте: <code>@fgramfe_bot (сумма) 🎲</code>\n"
            f"Пример: <code>@fgramfe_bot 100 🎲</code>"
        )
        result = InlineQueryResultArticle(
            id="1",
            title="Ошибка",
            input_message_content=InputTextMessageContent(
                message_text=response_text,
                parse_mode="HTML"
            )
        )
        await message.answer_guest_query(result=result)
        return

    # Получаем баланс пользователя
    balance = get_gram_balance(user.id)

    print(f"💰 Баланс пользователя {user.id}: {balance} GRAM")

    if balance < bet:
        response_text = (
            f"<b>❌ Недостаточно средств!</b>\n\n"
            f"Ваш баланс: {balance:.2f} GRAM\n"
            f"Ставка: {bet:.2f} GRAM"
        )
        result = InlineQueryResultArticle(
            id="1",
            title="Ошибка",
            input_message_content=InputTextMessageContent(
                message_text=response_text,
                parse_mode="HTML"
            )
        )
        await message.answer_guest_query(result=result)
        return

    # Банк = ставка + ставка - комиссия
    bank = bet * 2 - COMA

    # Сохраняем игру
    chat_id = message.chat.id
    games[chat_id] = {
        'creator_id': user.id,
        'creator_name': user.first_name,
        'creator_username': user.username or "нет",
        'creator_joined': False,  # ✅ ДОБАВЛЕНО
        'player2_id': None,
        'player2_name': None,
        'player2_username': None,
        'player2_joined': False,  # ✅ ДОБАВЛЕНО
        'bet': bet,
        'bank': bank,
        'status': 'waiting',
        'rolls': {},
        'guest_query_id': message.guest_query_id,
        'message_id': None
    }

    # ОБНОВЛЕННОЕ СООБЩЕНИЕ С ПРЕМИУМ ЭМОДЗИ
    response_text = (
        f"<tg-emoji emoji-id='5413739511341425163'>🎲</tg-emoji> "
        f"<b>Игра - Кости!</b>\n\n"
        f"<tg-emoji emoji-id='5411335450642127469'>💰</tg-emoji> "
        f"<b>Ставка:</b> {bet:.2f} GRAM <tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>\n\n"
        f"<tg-emoji emoji-id='5418018703222543759'>⏳</tg-emoji> "
        f"<b>Статус:</b> Ожидание игроков\n\n"
        f"<i>Нажмите кнопку ниже, чтобы присоединиться!</i>"
    )

    # КНОПКА "ПРИСОЕДИНИТЬСЯ" - ЗЕЛЕНАЯ
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Присоединиться",
                callback_data=f"join_game_{chat_id}",
                style="success"
            )
        ]
    ])

    result = InlineQueryResultArticle(
        id="1",
        title="🎲 Игра в кости",
        input_message_content=InputTextMessageContent(
            message_text=response_text,
            parse_mode="HTML"
        ),
        description=f"Ставка: {bet:.2f} GRAM",
        reply_markup=keyboard
    )

    try:
        await message.answer_guest_query(result=result)
        print(f"✅ Игра создана в чате {chat_id}, ставка {bet:.2f} GRAM")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

        games.pop(chat_id, None)

# ==================== ОБРАБОТЧИК КНОПКИ "НАЧАТЬ" ====================


@router.message(Command("recalc"))
async def recalc_command(message: Message):
    """Команда для пересчета статистики комиссии"""
    user_id = message.from_user.id

    # Проверка прав админа
    if user_id != ADMIN_CHAT_ID:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    # Показываем, что идет обработка
    await message.answer("⏳ Пересчет статистики...")

    try:
        # Вызываем пересчет
        stats = recalculate_statistik()

        # Формируем сообщение с результатами
        message_text = (
            f"<b>📊 ПЕРЕСЧЕТ СТАТИСТИКИ ВЫПОЛНЕН</b>\n\n"
            f"<b>🎮 Майнсвипер (mine):</b> {stats.get('mine', 0):.4f} TON\n"
            f"<b>⚔️ PVP Куб (pvp_kub):</b> {stats.get('pvp_kub', 0):.4f} TON\n"
            f"<b>⚓ PVP Корабли (pvp_ship):</b> {stats.get('pvp_ship', 0):.4f} TON\n\n"
            f"<i>📝 Лог-файл очищен. Новый период начат.</i>"
        )

        await message.answer(message_text, parse_mode='HTML')

        # Дополнительно отправляем JSON с данными
        stats_json = json.dumps(stats, indent=2, ensure_ascii=False)

    except Exception as e:
        await message.answer(f"❌ Ошибка пересчета: {str(e)}")
# ==================== MAIN ====================

async def main():
    """Главная функция запуска бота"""
    print("🤖 Бот запущен!")

    # Запускаем планировщик в фоновом режиме
    asyncio.create_task(scheduler())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
