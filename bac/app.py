from flask import Flask, render_template, request, jsonify, send_from_directory, make_response, redirect
import os
from datetime import datetime,timezone,timedelta

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from functions import get_user_data, add_balance, connect_wallet,recalculate_statistik,save_commission_safe, register_user,update_user_balance,build_jetton_transfer_payload,add_history_record,update_vager,update_referral_earnings,update_user_field,get_language,update_language,get_referral_earnings,get_referral_count,get_notifications,update_notifications,add_referral,get_history_stats,get_staking_user,update_staking_gram
import secrets
import time
import requests
import re
from bot import send_withdraw_notification_sync
from config import MERCHANT_WALLET, WITHDRAW_COMMISSION,NAME,ADMIN_CHAT_ID,BOT_TOKEN,COMA,CHANNEL_ID,CHAT_ID
from tonsdk.utils import Address
import random
import string
from PIL import Image, ImageDraw, ImageFont
import io
import base64
import sys
import hashlib
import hmac
import json
import uuid
from flask_socketio import SocketIO, emit, join_room, leave_room
from bot import save_prepared_inline_message,send_message_sync
# ========== ОПРЕДЕЛЕНИЕ РЕЖИМА ASYNC ==========
ASYNC_MODE = 'threading'  # Значение по умолчанию

print("🔍 Проверка доступных async режимов...")


app = Flask(__name__, template_folder='../web', static_folder='../web')

# ========== ПУТИ К ПАПКАМ ==========
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Корень проекта

TASKS_FILE = os.path.join(BASE_DIR, 'data', 'user_tasks.json')
HISTORY_DIR = os.path.join(BASE_DIR, 'data', 'history')
PVE_LOBBY_FILE = os.path.join(BASE_DIR, 'data', 'pve_lobby.json')
STAT_LOG_FILE = os.path.join(BASE_DIR, 'data', 'statistik_log.txt')
STAT_FILE = os.path.join(BASE_DIR, 'data', 'statistik.json')
PROMO_FILE = os.path.join(BASE_DIR, 'data', 'promo.json')

os.makedirs(HISTORY_DIR, exist_ok=True)
CRYPTO_PAY_URL = "https://pay.crypt.bot/api/"
os.makedirs(HISTORY_DIR, exist_ok=True)

CRYPTO_PAY_TOKEN = os.environ.get('CRYPTO_PAY_TOKEN', '')
# Путь к папке с языками в корне проекта
LOCALES_DIR = os.path.join(BASE_DIR, 'locales')
AUTH_LOG_FILE = os.path.join(BASE_DIR, 'data', 'authorization.json')
# Хранилище для payload TON Connect

TON_PROOF_STORAGE = {}
# ========== ИНИЦИАЛИЗАЦИЯ SOCKETIO ==========
print(f"🔌 Инициализация SocketIO с режимом: {ASYNC_MODE}")
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',  # ← threading работает стабильнее
    ping_timeout=60,
    ping_interval=25
)
lobby_rooms = {}  # lobby_hash -> {players: set(sids), last_data: {}}

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С PVE ЛОББИ ==========
def load_pve_lobbies():
    """Загружает лобби из файла"""
    if not os.path.exists(PVE_LOBBY_FILE):
        return {"lobbies": []}
    try:
        with open(PVE_LOBBY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"lobbies": []}

def save_pve_lobbies(data):
    """Сохраняет лобби в файл"""
    os.makedirs(os.path.dirname(PVE_LOBBY_FILE), exist_ok=True)
    with open(PVE_LOBBY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ========== ФУНКЦИЯ ЗАПИСИ ЛОГОВ В ФАЙЛ ==========
def write_log(level, message, data=None, user_id=None):
    """Записывает логи в файл logs.txt"""
    try:
        with open('logs.txt', 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"\n{'=' * 70}\n")
            f.write(f"[{timestamp}] [{level.upper()}] {message}\n")
            if user_id:
                f.write(f"👤 User: {user_id}\n")
            if data:
                f.write(f"📦 Data: {json.dumps(data, indent=2, ensure_ascii=False)}\n")
            f.write(f"{'=' * 70}\n")
        print(f"[LOG] {level.upper()}: {message}")
    except Exception as e:
        print(f"❌ Ошибка записи лога: {e}")


def log_authorization(user_id, ip, user_agent, device_type):
    """Записывает информацию о входе пользователя в authorization.json"""
    try:
        os.makedirs(os.path.dirname(AUTH_LOG_FILE), exist_ok=True)

        # Загружаем существующие данные или создаём новые
        if os.path.exists(AUTH_LOG_FILE):
            try:
                with open(AUTH_LOG_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                    else:
                        data = {"authorizations": []}
            except json.JSONDecodeError:
                # Если файл повреждён - пересоздаём
                data = {"authorizations": []}
        else:
            data = {"authorizations": []}

        entry = {
            "user_id": user_id,
            "ip": ip or "unknown",
            "user_agent": user_agent or "unknown",
            "device_type": device_type or "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        data["authorizations"].append(entry)

        # Ограничиваем размер файла (оставляем последние 10000 записей)
        if len(data["authorizations"]) > 10000:
            data["authorizations"] = data["authorizations"][-10000:]

        with open(AUTH_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"📝 Авторизация: {user_id} @ {entry['timestamp']} [{device_type}]")
        return True
    except Exception as e:
        print(f"❌ Ошибка записи авторизации: {e}")
        return False
# ========== СОЗДАНИЕ ИНВОЙСА CRBOT ==========
@app.route('/api/crbot/create_invoice', methods=['POST'])
def create_crbot_invoice():
    try:
        data = request.json
        user_id = data.get('user_id')
        amount_usd = float(data.get('amount', 0))  # ← Сумма в USD

        if not user_id or amount_usd <= 0:
            return jsonify({'success': False, 'error': 'Неверные параметры'}), 400

        # ✅ СОЗДАЕМ FIAT-ИНВОЙС В USD
        response = requests.post(
            CRYPTO_PAY_URL + 'createInvoice',
            headers={
                'Crypto-Pay-API-Token': CRYPTO_PAY_TOKEN,
                'Content-Type': 'application/json'
            },
            json={
                'currency_type': 'fiat',  # ← FIAT!
                'fiat': 'USD',  # ← В ДОЛЛАРАХ
                'amount': str(amount_usd),  # ← Сумма в USD
                'accepted_assets': 'USDT,TON,BTC,ETH,LTC,BNB,TRX',  # ← ВСЕ ВАЛЮТЫ!
                'description': f'Пополнение баланса FTFE ({amount_usd} USD)',
                'payload': json.dumps({
                    'user_id': user_id,
                    'amount_usd': amount_usd
                }),
                'expires_in': 3600,
                'allow_comments': False,
                'allow_anonymous': False
            }
        )

        result = response.json()
        print(f"📦 Ответ Crypto Pay: {result}")

        if result.get('ok'):
            invoice = result['result']
            return jsonify({
                'success': True,
                'invoice_url': invoice['bot_invoice_url'],
                'invoice_id': invoice['invoice_id'],
                'amount_usd': amount_usd,
                'currency_type': 'fiat'
            })
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Ошибка создания инвойса')}), 500

    except Exception as e:
        print(f"❌ Ошибка create_crbot_invoice: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== WEBHOOK ДЛЯ ПРИЕМА ОПЛАТ ==========
@app.route('/api/crbot/webhook', methods=['POST'])
def crbot_webhook():
    try:
        signature = request.headers.get('crypto-pay-api-signature')
        if not signature:
            return jsonify({'ok': False, 'error': 'No signature'}), 400

        secret = hashlib.sha256(CRYPTO_PAY_TOKEN.encode()).digest()
        body = request.get_data(as_text=True)
        hmac_signature = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()

        if hmac_signature != signature:
            print(f"❌ Неверная подпись!")
            return jsonify({'ok': False, 'error': 'Invalid signature'}), 403

        data = request.json
        print(f"📦 Webhook получен: {data}")

        if data.get('update_type') == 'invoice_paid':
            invoice = data.get('payload', {})
            if invoice.get('status') == 'paid':
                # ✅ ПОЛУЧАЕМ ДАННЫЕ ИЗ PAYLOAD
                payload_data = json.loads(invoice.get('payload', '{}'))
                user_id = payload_data.get('user_id')
                amount_usd = float(payload_data.get('amount_usd', 0))

                # ✅ ПОЛУЧАЕМ ФАКТИЧЕСКУЮ ОПЛАЧЕННУЮ СУММУ В КРИПТОВАЛЮТЕ
                paid_asset = invoice.get('paid_asset', 'TON')  # USDT, TON, BTC и т.д.
                paid_amount = float(invoice.get('paid_amount', 0))

                print(f"💰 Оплачено: {paid_amount} {paid_asset}")

                # ✅ КОНВЕРТИРУЕМ В TON ЧЕРЕЗ BINANCE
                try:
                    # Получаем курс выбранной криптовалюты к TON
                    if paid_asset == 'TON':
                        amount_ton = paid_amount
                    else:
                        # Получаем курс paid_asset → USDT
                        response = requests.get(f'https://api.binance.com/api/v3/ticker/price?symbol={paid_asset}USDT',
                                                timeout=5)
                        if response.status_code == 200:
                            data_price = response.json()
                            asset_usdt_price = float(data_price['price'])
                            # Конвертируем в TON (через USDT)
                            ton_response = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT',
                                                        timeout=5)
                            ton_price = float(ton_response.json()['price'])
                            amount_ton = round((paid_amount * asset_usdt_price) / ton_price, 2)
                        else:
                            # Если не удалось получить курс, используем amount_usd
                            ton_response = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT',
                                                        timeout=5)
                            ton_price = float(ton_response.json()['price'])
                            amount_ton = round(amount_usd / ton_price, 2)
                except Exception as e:
                    print(f"⚠️ Ошибка конвертации: {e}")
                    # Запасной вариант
                    ton_response = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT', timeout=5)
                    ton_price = float(ton_response.json()['price'])
                    amount_ton = round(amount_usd / ton_price, 2)

                print(f"💰 Начисляем {amount_ton} TON (эквивалент {amount_usd} USD)")

                # ✅ НАЧИСЛЯЕМ В TON
                result = update_user_balance(
                    user_id,
                    amount_ton,
                    f'Пополнение {amount_usd} USD ({paid_amount} {paid_asset})',
                    'Успешно'
                )

                if result['success']:
                    update_referral_earnings(user_id, amount_ton)
                    update_vager(user_id, amount_ton)
                    print(f"✅ Баланс пополнен на {amount_ton} TON")
                    return jsonify({'ok': True})
                else:
                    return jsonify({'ok': False, 'error': 'Failed to update balance'}), 500

        return jsonify({'ok': True})

    except Exception as e:
        print(f"❌ Ошибка webhook: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

# ========== ПРОВЕРКА СТАТУСА ИНВОЙСА ==========
@app.route('/api/crbot/check_invoice', methods=['POST'])
def check_crbot_invoice():
    try:
        data = request.json
        invoice_id = data.get('invoice_id')

        if not invoice_id:
            return jsonify({'success': False, 'error': 'No invoice_id'}), 400

        response = requests.post(
            CRYPTO_PAY_URL + 'getInvoices',
            headers={
                'Crypto-Pay-API-Token': CRYPTO_PAY_TOKEN,
                'Content-Type': 'application/json'
            },
            json={'invoice_ids': str(invoice_id)}
        )

        result = response.json()
        print(f"📦 Проверка инвойса {invoice_id}: {result}")

        if result.get('ok') and result.get('result'):
            invoices = result['result']['items']
            if invoices:
                invoice = invoices[0]
                return jsonify({
                    'success': True,
                    'status': invoice.get('status'),
                    'paid': invoice.get('status') == 'paid',
                    'amount_usd': invoice.get('amount'),
                    'paid_asset': invoice.get('paid_asset'),
                    'paid_amount': invoice.get('paid_amount')
                })

        return jsonify({'success': False, 'error': 'Invoice not found'}), 404

    except Exception as e:
        print(f"❌ Ошибка check_crbot_invoice: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def detect_device(user_agent):
    """Определяет тип устройства по User-Agent"""
    if not user_agent:
        return 'desktop'
    ua = user_agent.lower()
    if any(p in ua for p in ['ipad', 'tablet', 'kindle', 'silk', 'playbook', 'nexus 7']):
        return 'tablet'
    if any(p in ua for p in
           ['mobile', 'android', 'iphone', 'ipod', 'blackberry', 'windows phone', 'opera mini', 'iemobile', 'phone']):
        return 'mobile'
    return 'desktop'

# ========== TON CONNECT MANIFEST ==========
@app.route('/api/config', methods=['GET'])
def get_config():
    """Возвращает конфигурацию для клиента"""
    return jsonify({
        'withdraw_commission': WITHDRAW_COMMISSION,  # ✅ БЕРЁТ ИЗ config.py
        'merchant_wallet': MERCHANT_WALLET  # ✅ БЕРЁТ ИЗ config.py
    })

# ========== API ЭНДПОИНТ ДЛЯ ПОЛУЧЕНИЯ PAYLOAD ==========
@app.route('/api/usdt/prepare_payload', methods=['POST'])
def prepare_usdt_payload():
    try:
        data = request.json
        user_id = data.get('user_id')
        amount_usdt = float(data.get('amount', 0))
        user_address = data.get('user_address')  # ← ПОЛУЧАЕМ АДРЕС ПОЛЬЗОВАТЕЛЯ

        if not user_id or amount_usdt <= 0:
            return jsonify({'success': False, 'error': 'Неверные параметры'}), 400

        if not user_address:
            return jsonify({'success': False, 'error': 'Не указан адрес пользователя'}), 400

        jetton_amount = int(amount_usdt * 1_000_000)

        # ✅ ПЕРЕДАЕМ user_address В ФУНКЦИЮ
        result = build_jetton_transfer_payload(
            jetton_amount=jetton_amount,
            user_address=user_address,  # ← ПЕРЕДАЕМ АДРЕС
            query_id=int(datetime.now().timestamp() * 1000)
        )

        if not result:
            return jsonify({'success': False, 'error': 'Ошибка формирования payload'}), 500

        return jsonify({
            'success': True,
            'jetton_wallet': result['jetton_wallet'],
            'payload': result['payload'],
            'jetton_amount': result['jetton_amount'],
            'amount_usdt': amount_usdt,
            'user_address': user_address  # ← для отладки
        })

    except Exception as e:
        print(f"❌ Ошибка prepare_usdt_payload: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== ПОДТВЕРЖДЕНИЕ USDT ТРАНЗАКЦИИ ==========
@app.route('/api/usdt/confirm', methods=['POST'])
def confirm_usdt_transaction():
    try:
        data = request.json
        user_id = data.get('user_id')
        transaction_hash = data.get('transaction_hash')

        if not user_id or not transaction_hash:
            return jsonify({'success': False, 'error': 'Неверные параметры'}), 400

        # Загружаем pending
        pending_file = 'data/pending_usdt.json'
        if not os.path.exists(pending_file):
            return jsonify({'success': False, 'error': 'Нет pending платежей'}), 404

        with open(pending_file, 'r', encoding='utf-8') as f:
            pending_data = json.load(f)

        user_id_str = str(user_id)
        if user_id_str not in pending_data:
            return jsonify({'success': False, 'error': 'Нет pending платежа'}), 404

        payment_data = pending_data[user_id_str]
        amount_usdt = payment_data['amount']

        # Начисляем средства пользователю
        result = update_user_balance(
            user_id,
            amount_usdt,
            'Пополнение USDT',
            'Успешно',
            skip_history=False
        )

        if not result['success']:
            return jsonify({'success': False, 'error': result.get('error', 'Ошибка начисления')}), 500

        # Записываем в историю
        add_history_record(
            user_id,
            amount_usdt,
            'GRAM',
            'Пополнение USDT через TonConnect',
            result['new_balance'],
            f'Хеш: {transaction_hash}'
        )

        # Обновляем реферальный заработок
        update_referral_earnings(user_id, amount_usdt)

        # Увеличиваем Vager
        update_vager(user_id, amount_usdt)

        # Удаляем из pending
        del pending_data[user_id_str]
        with open(pending_file, 'w', encoding='utf-8') as f:
            json.dump(pending_data, f, ensure_ascii=False, indent=2)

        return jsonify({
            'success': True,
            'amount': amount_usdt,
            'hash': transaction_hash,
            'new_balance': result['new_balance']
        })

    except Exception as e:
        print(f"❌ Ошибка confirm_usdt_transaction: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/ton/confirm_payment', methods=['POST'])
def confirm_payment():
    try:
        data = request.json
        user_id = data.get('user_id')
        amount = float(data.get('amount', 0))
        currency = data.get('currency', 'TON')  # ← "TON" или "USDT"
        transaction_hash = data.get('transaction_hash')
        description = data.get('description', 'Пополнение баланса')
        status = data.get('status', 'Успешно')

        if not user_id or not amount:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        # ✅ ЕСЛИ USDT - КОНВЕРТИРУЕМ
        if currency == 'USDT':
            try:
                response = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT', timeout=5)
                data_price = response.json()
                ton_price = float(data_price['price'])
                amount_ton = round(amount / ton_price, 2)
                description = f'Пополнение USDT'
            except Exception as e:
                return jsonify({'success': False, 'error': 'Не удалось получить курс TON'}), 500
        else:
            # ✅ ЕСЛИ TON - НАЧИСЛЯЕМ КАК ЕСТЬ
            amount_ton = round(amount, 2)
            description = f'Пополнение {amount} TON'

        # ✅ НАЧИСЛЯЕМ В TON
        result = update_user_balance(
            user_id,
            amount_ton,
            description,
            status
        )

        if result['success']:
            update_referral_earnings(user_id, amount_ton)
            update_vager(user_id, amount_ton)

            return jsonify({
                'success': True,
                'new_balance': result['new_balance'],
                'amount_ton': amount_ton,
                'currency': currency
            })
        else:
            return jsonify({'success': False, 'error': result.get('error')}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ========== ЭНДПОИНТ ДЛЯ USDT ==========
@app.route('/api/withdraw_callback_usdt', methods=['POST'])
def withdraw_callback_usdt():
    """Обрабатывает USDT заявки"""
    data = request.json
    request_id = data.get('request_id')
    action = data.get('action')

    if not request_id or not action:
        return jsonify({'success': False, 'error': 'Missing fields'}), 400

    filepath = os.path.join('data', 'withdraw_requests_usdt', f'{request_id}.json')

    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'Request not found'}), 404

    with open(filepath, 'r', encoding='utf-8') as f:
        req = json.load(f)

    req['status'] = action
    req['processed_at'] = datetime.now().isoformat()

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(req, f, indent=2, ensure_ascii=False)

    return jsonify({'success': True})

@app.route('/tonconnect-manifest.json')
def serve_ton_manifest():
    """Serve TON Connect manifest file"""
    base_url = request.host_url.rstrip('/')

    manifest = {
        "url": base_url,
        "name": "FTFE App",
        "iconUrl": f"{base_url}/sticer/app-icon.png",
        "termsOfUseUrl": f"{base_url}/terms",
        "privacyPolicyUrl": f"{base_url}/privacy"
    }

    response = make_response(jsonify(manifest))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

# ========== API ДЛЯ ЛОГОВ С КЛИЕНТА ==========
@app.route('/api/log', methods=['POST'])
def save_client_log():
    """Получение логов с клиента (браузера) и запись в файл"""
    try:
        data = request.json
        write_log(
            level=data.get('level', 'info'),
            message=data.get('message', ''),
            data=data.get('data'),
            user_id=data.get('user_id')
        )
        return jsonify({'status': 'ok'})
    except Exception as e:
        print(f"❌ Ошибка сохранения лога: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ========== TON CONNECT API ==========

@app.route('/api/ton/generate_payload', methods=['POST'])
def generate_ton_payload():
    data = request.json
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    payload = secrets.token_hex(32)

    TON_PROOF_STORAGE[user_id] = {
        'payload': payload,
        'created_at': time.time()
    }

    # Очистка старых записей
    for uid, data in list(TON_PROOF_STORAGE.items()):
        if time.time() - data['created_at'] > 600:
            del TON_PROOF_STORAGE[uid]

    write_log('info', f'Сгенерирован payload для пользователя', user_id=user_id)
    print(f"🔐 Generated payload for user {user_id}")
    return jsonify({'payload': payload})

def get_tonviewer_address(raw_address):
    """Получает адрес, который реально показывает Tonviewer"""

    # Получаем адрес от API
    resp = requests.get('https://toncenter.com/api/v2/packAddress',
                        params={'address': raw_address}, timeout=10)
    api_address = resp.json()['result']

    # Формируем URL для проверки (используем EQ версию, так как Tonviewer на неё даёт правильный адрес)
    test_url = f"https://tonviewer.com/{api_address}"

    try:
        html = requests.get(test_url, timeout=10).text
        match = re.search(r'UQ[A-Za-z0-9_\-]{46}', html)
        if match:
            return match.group()
    except Exception as e:
        print(f"Ошибка: {e}")

    return None

@app.route('/api/ton/verify_proof', methods=['POST'])
def verify_ton_proof():
    data = request.json
    user_id = data.get('user_id')
    wallet_address = data.get('wallet_address')
    proof = data.get('proof')

    if not user_id or not wallet_address or not proof:
        return jsonify({'error': 'Missing required fields'}), 400

    stored_data = TON_PROOF_STORAGE.get(user_id)
    if not stored_data:
        return jsonify({'error': 'No payload found'}), 400

    if stored_data['payload'] != proof.get('payload'):
        return jsonify({'error': 'Invalid payload'}), 403

    if time.time() - stored_data['created_at'] > 300:
        del TON_PROOF_STORAGE[user_id]
        return jsonify({'error': 'Payload expired'}), 403

    del TON_PROOF_STORAGE[user_id]

    # НЕ КОНВЕРТИРУЕМ! Сохраняем raw адрес как есть
    # wallet_address уже в формате 0:ec52ba3c...
    user_friendly_address = wallet_address  # raw адрес

    write_log('info', f'Верификация кошелька',
              data={'raw_address': wallet_address, 'user_friendly': user_friendly_address},
              user_id=user_id)

    print(f"📝 Raw адрес: {wallet_address}")
    print(f"✅ Сохраняем raw адрес: {user_friendly_address}")

    if connect_wallet(user_id, user_friendly_address):
        update_user_field(user_id, 'wallet_verified_at', datetime.now().isoformat())
        write_log('info', f'Кошелек успешно сохранен в БД',
                  data={'address': user_friendly_address}, user_id=user_id)
        print(f"✅ Сохранен кошелек: {user_friendly_address}")
        return jsonify({'success': True, 'address': user_friendly_address})
    else:
        write_log('error', f'Ошибка сохранения кошелька в БД',
                  data={'address': user_friendly_address}, user_id=user_id)
        return jsonify({'error': 'Failed to save wallet'}), 500


# ========== API ДЛЯ ЯЗЫКОВ ==========

@app.route('/api/locales/<lang>.json')
def get_locale(lang):
    """Возвращает языковой файл из папки locales в корне проекта"""
    locale_file = os.path.join(LOCALES_DIR, f'{lang}.json')
    if not os.path.exists(locale_file):
        return jsonify({'error': 'Language not found'}), 404
    with open(locale_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    response = make_response(jsonify(data))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@app.route('/api/user_language', methods=['GET', 'POST'])
def user_language():

    if request.method == 'POST':
        data = request.json
        user_id = data.get('user_id')
        language = data.get('language')

        print(f"📝 СОХРАНЕНИЕ ЯЗЫКА: user_id={user_id}, language={language}")

        if not user_id:
            return jsonify({'error': 'No user_id'}), 400
        if language in ['ru', 'en']:
            update_language(user_id, language)

            new_lang = get_language(user_id)
            write_log('info', f'Язык изменен', data={'language': language}, user_id=user_id)
            print(f"✅ Язык сохранён: {new_lang}")

            return jsonify({'success': True, 'language': language})
        return jsonify({'error': 'Invalid language'}), 400

    # GET - получаем язык
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400
    lang = get_language(user_id)
    print(f"📖 ЗАГРУЗКА ЯЗЫКА: user_id={user_id}, language={lang}")
    return jsonify({'language': lang})

@app.route('/api/mines_config', methods=['GET'])
def get_mines_config():
    """Возвращает конфигурацию игры Mines из config.py"""
    try:
        from config import MINES_CONFIG
        return jsonify({
            'rtp': MINES_CONFIG.get('rtp', 0.948),
            'total_cells': MINES_CONFIG.get('total_cells', 25)
        })
    except ImportError:
        # Если файл config.py не найден, возвращаем значения по умолчанию
        return jsonify({
            'rtp': 0.948,
            'total_cells': 25
        })

@app.route('/game_mines')
def game_mines():
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    user_id = request.args.get('user_id')
    return render_template('game_mines.html', device_type=device_type, user_id=user_id)

@app.route('/api/register_user', methods=['POST'])
def api_register_user():
    """Регистрирует нового пользователя"""
    data = request.json
    user_id = data.get('user_id')
    username = data.get('username', 'unknown')
    first_name = data.get('first_name', 'User')

    if not user_id:
        return jsonify({'error': 'No user_id'}), 400

    is_new = register_user(user_id, username, first_name)

    write_log('info', f'Регистрация пользователя',
              data={'username': username, 'first_name': first_name, 'is_new': is_new},
              user_id=user_id)

    if is_new:
        user_data = get_user_data(user_id)
        return jsonify({
            'success': True,
            'is_new': True,
            'balance': user_data['balans'],
            'message': 'Добро пожаловать!'
        })
    else:
        user_data = get_user_data(user_id)
        return jsonify({
            'success': True,
            'is_new': False,
            'balance': user_data['balans']
        })

@app.route('/api/languages')
def get_languages():
    """Возвращает список доступных языков"""
    languages = []
    if os.path.exists(LOCALES_DIR):
        for file in os.listdir(LOCALES_DIR):
            if file.endswith('.json'):
                lang_code = file.replace('.json', '')
                with open(os.path.join(LOCALES_DIR, file), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    languages.append({
                        'code': lang_code,
                        'name': data.get('langSubtitle', lang_code)
                    })
    return jsonify(languages)

def load_bonus_tokens():
    """Загружает токены с проверкой на пустой файл"""
    bonus_data_file = os.path.join('data', 'bonus_tokens.json')
    if not os.path.exists(bonus_data_file):
        return {}

    try:
        with open(bonus_data_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        print(f"⚠️ Ошибка JSON в {bonus_data_file}, создаем новый")
        return {}
    except Exception as e:
        print(f"❌ Ошибка загрузки: {e}")
        return {}
# ========== СТРАНИЦЫ ==========
@app.route('/api/log_auth', methods=['POST'])
def log_auth():
    """Логирует авторизацию пользователя из Telegram WebApp"""
    try:
        data = request.json
        user_id = data.get('user_id')
        user_agent = data.get('user_agent', 'unknown')
        device_type = data.get('device_type', 'unknown')

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        log_authorization(
            user_id=user_id,
            ip=ip,
            user_agent=user_agent,
            device_type=device_type
        )

        return jsonify({'success': True})
    except Exception as e:
        print(f"❌ Ошибка логирования: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/staking/stake', methods=['POST'])
def stake():
    """Пополнение стейкинга - проверка баланса, списание и добавление в стейкинг в одном запросе"""
    try:
        data = request.json
        user_id = data.get('user_id')
        amount = float(data.get('amount', 0))

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        if amount <= 0:
            return jsonify({'success': False, 'error': 'Сумма должна быть больше 0'}), 400

        # ===== 1. ПРОВЕРЯЕМ БАЛАНС ПОЛЬЗОВАТЕЛЯ =====
        user_data = get_user_data(user_id)
        if not user_data:
            return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404

        current_balance = float(user_data.get('ton_balance', 0))
        print(f"💰 Текущий баланс пользователя: {current_balance} GRAM")
        print(f"💰 Запрос на стейкинг: {amount} GRAM")

        if current_balance < amount:
            return jsonify({
                'success': False,
                'error': f'Недостаточно средств. Доступно: {current_balance:.2f} GRAM, нужно: {amount:.2f} GRAM'
            }), 400

        # ===== 2. СПИСЫВАЕМ С БАЛАНСА =====
        balance_result = update_user_balance(
            user_id,
            -amount,
            f'Стейкинг FGFE',
            'Застейкано',
            skip_history=True
        )

        if not balance_result['success']:
            return jsonify({
                'success': False,
                'error': balance_result.get('error', 'Ошибка списания средств')
            }), 500

        # ===== 3. ДОБАВЛЯЕМ В СТЕЙКИНГ =====
        staking_result = update_staking_gram(user_id, amount)

        if not staking_result:
            # Возвращаем деньги при ошибке
            update_user_balance(
                user_id,
                amount,
                'Возврат при ошибке стейкинга',
                'Ошибка',
                skip_history=True
            )
            return jsonify({'success': False, 'error': 'Ошибка сохранения стейкинга'}), 500

        # ===== 4. ПОЛУЧАЕМ ОБНОВЛЕННЫЕ ДАННЫЕ =====
        updated_data = get_staking_user(user_id)
        new_balance = balance_result.get('new_balance', 0)
        total_staked = updated_data.get('gram', 0)

        # ===== 5. ЗАПИСЫВАЕМ В ИСТОРИЮ =====
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')
        history_file = os.path.join('data', 'history', f'{user_id}.txt')
        os.makedirs(os.path.dirname(history_file), exist_ok=True)

        with open(history_file, 'a', encoding='utf-8') as f:
            f.write(f"{date_str}|{time_str}|-{amount:.2f}|GRAM|Стейкинг FGFE|Застейкано|{new_balance:.2f}\n")

        # ===== 6. ОТПРАВЛЯЕМ УВЕДОМЛЕНИЕ АДМИНУ =====
        try:
            username = user_data.get('username', 'User')
            first_name = user_data.get('name', 'User')

            # Формируем имя пользователя
            if username and username != 'unknown':
                user_display = f"@{username}"
            else:
                user_display = first_name

            # ===== СООБЩЕНИЕ КАК ВЫ ПРОСИЛИ =====
            message_text = (
                f"<tg-emoji emoji-id='5411397813567264865'>🔼</tg-emoji> "
                f"<b>Пополнение пула стейкинга</b>\n\n"
                f"{user_display} на {amount:.2f} GRAM <tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>"
            )

            # Отправляем админу
            try:
                from bot import send_message_sync
                send_message_sync(
                    chat_id=ADMIN_CHAT_ID,
                    text=message_text,
                    parse_mode='HTML'
                )
                print(f"✅ Уведомление о стейкинге отправлено админу")
            except:
                # Если bot.py не доступен - отправляем через requests
                import requests
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                payload = {
                    'chat_id': ADMIN_CHAT_ID,
                    'text': message_text,
                    'parse_mode': 'HTML'
                }
                requests.post(url, json=payload, timeout=5)
                print(f"✅ Уведомление о стейкинге отправлено админу (через requests)")

        except Exception as e:
            print(f"⚠️ Ошибка отправки уведомления админу: {e}")

        # ===== 7. ЛОГГИРУЕМ =====
        write_log('info', f'Стейкинг пополнен',
                  data={
                      'user_id': user_id,
                      'amount': amount,
                      'total_staked': total_staked,
                      'new_balance': new_balance
                  })

        return jsonify({
            'success': True,
            'message': f'Застейкано {amount:.2f} GRAM',
            'staked_amount': amount,
            'total_staked': total_staked,
            'points': updated_data.get('points', 0),
            'new_balance': new_balance
        })

    except Exception as e:
        print(f"❌ Ошибка стейкинга: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/')
def index():
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    user_id = request.args.get('user_id')

    # ===== ОБРАБОТКА STARTAPP =====
    start_param = request.args.get('tgWebAppStartParam')

    # ===== 1. ЕСЛИ startapp=batl_{lobby_hash} — РЕДИРЕКТ НА СТРАНИЦУ ЛОББИ =====
    if start_param and start_param.startswith('batl_'):
        lobby_hash = start_param.replace('batl_', '')

        # Проверяем, существует ли лобби
        data = load_pve_lobbies()
        lobby_exists = any(l['hash'] == lobby_hash for l in data['lobbies'])

        if not lobby_exists:
            # Если лобби не существует — показываем главную с ошибкой
            return render_template('index.html', device_type=device_type, error='Лобби не найдено')

        if user_id:
            return redirect(f'/games/Batl/lobby/{lobby_hash}?user_id={user_id}')
        else:
            return redirect(f'/games/Batl/lobby/{lobby_hash}')

    # ===== 2. ЕСЛИ startapp=bonus_page_{token} — РЕДИРЕКТ НА БОНУСНУЮ СТРАНИЦУ =====
    if start_param and start_param.startswith('bonus_page_'):
        token = start_param.replace('bonus_page_', '')

        bonus_data_file = os.path.join('data', 'bonus_tokens.json')
        if os.path.exists(bonus_data_file):
            with open(bonus_data_file, 'r', encoding='utf-8') as f:
                bonus_tokens = json.load(f)

            if token in bonus_tokens:
                bonus_data = bonus_tokens[token]

                if bonus_data.get('used', False):
                    return render_template('index.html', device_type=device_type)

                if not user_id:
                    user_id = bonus_data['user_id']

                if bonus_data['user_id'] == user_id:
                    created_at = bonus_data.get('created_at')
                    if created_at is None:
                        created_at = time.time()
                        bonus_data['created_at'] = created_at
                        with open(bonus_data_file, 'w', encoding='utf-8') as f:
                            json.dump(bonus_tokens, f, indent=2, ensure_ascii=False)

                    user_data = get_user_data(user_id)
                    tame = user_data.get('tame', 60) if user_data else 60

                    return redirect(
                        f'/bonus_page?token={token}&user_id={user_id}&created_at={int(created_at)}&tame={int(tame)}')

    # ===== 3. ОБЫЧНАЯ ГЛАВНАЯ СТРАНИЦА =====
    return render_template('index.html', device_type=device_type)

@app.route('/api/referral_data', methods=['GET'])
def get_referral_data():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400

    return jsonify({
        'referral_count': get_referral_count(user_id),
        'total_referral_earnings': get_referral_earnings(user_id)
    })

@app.route('/settings')
def settings():
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    return render_template('settings.html', device_type=device_type)

@app.route('/webapp/profile/wallet-block.html')
def serve_wallet_block():
    return send_from_directory('../web/profile', 'wallet-block.html')

@app.route('/api/bot_name', methods=['GET'])
def get_bot_name():
    """Возвращает имя бота из config.py"""
    try:
        # Правильный импорт из корневого bac
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import NAME
        return jsonify({'bot_name': NAME})
    except Exception as e:
        print(f"Ошибка получения имени бота: {e}")
        return jsonify({'bot_name': 'FTFE_Bot'})
# ========== СТАТИЧЕСКИЕ ФАЙЛЫ ==========

@app.route('/style.css')
def serve_css():
    return send_from_directory('../web', 'style.css')

@app.route('/script.js')
def serve_js():
    return send_from_directory('../web', 'script.js')

@app.route('/chart.js')
def serve_chart_js():
    return send_from_directory('../web', 'chart.js')

@app.route('/navigation.js')
def serve_navigation_js():
    return send_from_directory('../web', 'navigation.js')

@app.route('/carousel.js')
def serve_carousel_js():
    return send_from_directory('../web', 'carousel.js')

@app.route('/webapp/content.json')
def serve_content_json():
    return send_from_directory('../web', 'content.json')

@app.route('/sticer/<path:filename>')
def serve_sticer(filename):
    return send_from_directory('../web/sticer', filename)

# ========== API ==========

@app.route('/api/price_history', methods=['GET'])
def get_price_history():
    price_file = os.path.join(os.path.dirname(__file__), 'price_history.json')
    if not os.path.exists(price_file):
        return jsonify({'error': 'File not found'}), 404
    with open(price_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    response = make_response(jsonify(data))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

@app.route('/api/user', methods=['GET'])
def api_get_user():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400
    user_data = get_user_data(user_id)
    if user_data:
        # НЕ КОНВЕРТИРУЕМ - возвращаем как есть из файла
        return jsonify(user_data)
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/add_balance', methods=['POST'])
def api_add_balance():
    data = request.json
    user_id = data.get('user_id') or request.args.get('user_id')
    amount = data.get('amount', 0)
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400
    new_balance = add_balance(user_id, amount)
    write_log('info', f'Баланс изменен', data={'amount': amount, 'new_balance': new_balance}, user_id=user_id)
    return jsonify({'success': True, 'new_balance': new_balance})

@app.route('/api/connect_wallet', methods=['POST'])
def api_connect_wallet():
    data = request.json
    user_id = data.get('user_id')
    wallet = data.get('wallet')

    # Конвертируем raw в user-friendly
    if wallet and wallet.startswith('0:'):
        addr = Address(wallet)
        wallet = addr.to_string(True, True, False)  # UQ...
        print(f"🔄 Конвертация: {data.get('wallet')} → {wallet}")

    # Сохраняем user-friendly адрес в БД
    connect_wallet(user_id, wallet)
    return jsonify({'success': True})

@app.route('/api/save_history', methods=['POST'])
def save_history():
    data = request.json
    user_id = data.get('user_id')
    date = data.get('date')
    balance = data.get('balance')
    ton_balance = data.get('ton_balance', 0)
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400
    history_file = os.path.join(HISTORY_DIR, f'{user_id}.txt')
    with open(history_file, 'a', encoding='utf-8') as f:
        f.write(f"{date}|{balance}|{ton_balance}\n")
    return jsonify({'success': True})


@app.route('/api/user_notifications', methods=['GET', 'POST'])
def user_notifications():

    if request.method == 'POST':
        data = request.json
        user_id = data.get('user_id')
        enabled = data.get('enabled', True)
        if not user_id:
            return jsonify({'error': 'No user_id'}), 400
        update_notifications(user_id, enabled)
        write_log('info', f'Уведомления изменены', data={'enabled': enabled}, user_id=user_id)
        return jsonify({'success': True, 'enabled': enabled})

    # GET
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400
    enabled = get_notifications(user_id)
    return jsonify({'enabled': enabled})


@app.route('/api/user_stats', methods=['GET'])
def get_user_stats():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400

    history_file = os.path.join('data', 'history', f'{user_id}.txt')

    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            turnovers = []
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split('|')
                    if len(parts) >= 3:
                        try:
                            turnovers.append(float(parts[1]))
                        except:
                            pass
    user_data = get_user_data(user_id)
    return jsonify({
        'stats': {
            'total_turnover': user_data.get('total_turnover', 0),
            'record_balance': user_data.get('record_balance', 0),
            'total_withdrawn': user_data.get('total_withdrawn', 0)
        }
    })


@app.route('/api/history_stats', methods=['GET'])
def api_history_stats():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400

    stats = get_history_stats(user_id)

    return jsonify({'stats': stats})


@app.route('/api/ton/wallet_data', methods=['POST'])
def save_wallet_data():
    """Сохранение ВСЕХ данных кошелька от TON Connect"""
    try:
        data = request.json
        user_id = data.get('user_id')
        wallet_type = data.get('type')
        wallet_data = data.get('data')

        # Сохраняем в отдельный файл
        wallet_data_file = os.path.join('data', 'wallet_data', f'{user_id}.json')
        os.makedirs(os.path.dirname(wallet_data_file), exist_ok=True)

        with open(wallet_data_file, 'w', encoding='utf-8') as f:
            json.dump({
                'user_id': user_id,
                'type': wallet_type,
                'data': wallet_data,
                'timestamp': data.get('timestamp')
            }, f, indent=2, ensure_ascii=False)

        print(f"✅ Сохранены данные кошелька для {user_id}, тип: {wallet_type}")
        return jsonify({'success': True})
    except Exception as e:
        print(f"❌ Ошибка сохранения данных кошелька: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user_history', methods=['GET'])
def get_user_history_route():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400

    history_file = os.path.join('data', 'history', f'{user_id}.txt')
    history = []

    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split('|')
                    if len(parts) >= 5:
                        history.append({
                            'date': parts[0],
                            'time': parts[1] if len(parts) > 1 else '',
                            'amount': parts[2] if len(parts) > 2 else '0',
                            'token': parts[3] if len(parts) > 3 else 'FTFE',
                            'description': parts[4] if len(parts) > 4 else '',
                            'status': parts[5] if len(parts) > 5 else ''
                        })
                    elif len(parts) >= 4:
                        history.append({
                            'date': parts[0],
                            'time': parts[1] if len(parts) > 1 else '',
                            'amount': parts[2] if len(parts) > 2 else '0',
                            'token': parts[3] if len(parts) > 3 else 'FTFE',
                            'description': parts[4] if len(parts) > 4 else '',
                            'status': ''
                        })

    return jsonify({'history': history[-50:]})

# СОЗДАНИЕ ИНВОЙСА
@app.route('/api/ton/create_invoice', methods=['POST'])
def create_invoice():
    try:
        data = request.json
        user_id = data.get('user_id')
        amount = float(data.get('amount'))

        invoice_id = f"inv_{user_id}_{int(time.time())}"

        # Кошелек куда будут приходить деньги (твой/сервисный)
        merchant_wallet = MERCHANT_WALLET  # Замени на свой

        return jsonify({
            'success': True,
            'invoice_id': invoice_id,
            'wallet_address': merchant_wallet,
            'amount': str(amount),
            'payload': invoice_id  # или любой уникальный идентификатор
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/update_balance', methods=['POST'])
def update_balance():
    try:
        data = request.json
        user_id = data.get('user_id')
        amount = data.get('amount')
        currency = data.get('currency', 'TON')
        description = data.get('description', 'Игра Mines')
        status = data.get('status', '')
        skip_history = data.get('skip_history', False)  # ДОБАВЛЕНО

        # Логируем входящий запрос
        write_log('info', f'Получен запрос на обновление баланса',
                  data={'user_id': user_id, 'amount': amount, 'currency': currency, 'description': description, 'status': status, 'skip_history': skip_history})

        print(f"\n{'=' * 60}")
        print(f"📢 ЗАПРОС /api/update_balance")
        print(f"📌 user_id: {user_id}")
        print(f"📌 amount: {amount}")
        print(f"📌 currency: {currency}")
        print(f"📌 description: {description}")
        print(f"📌 status: {status}")
        print(f"📌 skip_history: {skip_history}")
        print(f"{'=' * 60}\n")

        if not user_id or amount is None:
            write_log('error', 'Не указан user_id или сумма')
            return jsonify({'success': False, 'error': 'Не указан user_id или сумма'}), 400

        if currency == 'TON':
            # ПЕРЕДАЁМ description, status И skip_history
            result = update_user_balance(user_id, amount, description, status, skip_history)

            write_log('info', f'Результат обновления баланса', data=result)
            print(f"📢 РЕЗУЛЬТАТ: {result}")

            if result['success']:
                return jsonify({
                    'success': True,
                    'new_balance': result['new_balance'],
                    'old_balance': result['old_balance'],
                    'change': result['change']
                })
            else:
                return jsonify({'success': False, 'error': result['error']}), 404
        else:
            return jsonify({'success': False, 'error': 'Неподдерживаемая валюта'}), 400

    except Exception as e:
        write_log('error', f'Исключение в update_balance', data={'error': str(e)})
        print(f"🔴 ИСКЛЮЧЕНИЕ: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
# ========== БЛОКИ ДЛЯ СТРАНИЦЫ ПРОФИЛЯ ==========

@app.route('/webapp/profile/stats-block.html')
def serve_stats_block():
    """Возвращает блок статистики"""
    return send_from_directory('../web/profile', 'stats-block.html')

@app.route('/webapp/profile/referral-block.html')
def serve_referral_block():
    """Возвращает блок реферальной системы"""
    return send_from_directory('../web/profile', 'referral-block.html')

@app.route('/webapp/profile/history-block.html')
def serve_history_block():
    """Возвращает блок истории операций"""
    return send_from_directory('../web/profile', 'history-block.html')

# ========== SPA API ==========

@app.route('/api/page/<page_name>')
def api_get_page_content(page_name):
    """Возвращает страницу для SPA"""
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    user_id = request.args.get('user_id')

    if page_name == 'index' or page_name == 'home':
        return render_template('index', device_type=device_type, user_id=user_id)
    elif page_name == 'profile':
        return render_template('profile', device_type=device_type, user_id=user_id)
    elif page_name == 'settings':
        return render_template('settings', device_type=device_type, user_id=user_id)
    else:
        return jsonify({'error': 'Page not found'}), 404

# ========== ВЫВОД СРЕДСТВ ==========

@app.route('/api/withdraw_request', methods=['POST'])
def withdraw_request():
    try:
        data = request.json
        user_id = data.get('user_id')
        username = data.get('username', 'unknown')
        first_name = data.get('first_name', 'User')
        amount = float(data.get('amount', 0))
        receive_amount = data.get('receive_amount')
        commission = data.get('commission', WITHDRAW_COMMISSION)
        wallet_address = data.get('wallet_address')
        currency = data.get('currency', 'GRAM')  # ← GRAM, USDT, CrBot

        # ========== ОТЛАДОЧНЫЙ ВЫВОД ==========
        print(f"\n{'='*60}")
        print(f"📢 ПОЛУЧЕНА ЗАЯВКА НА ВЫВОД")
        print(f"{'='*60}")
        print(f"📌 user_id: {user_id}")
        print(f"📌 username: {username}")
        print(f"📌 first_name: {first_name}")
        print(f"📌 amount: {amount}")
        print(f"📌 receive_amount: {receive_amount}")
        print(f"📌 commission: {commission}")
        print(f"📌 wallet_address: {wallet_address}")
        print(f"📌 currency: {currency}")
        print(f"{'='*60}\n")

        # ========== ПРОВЕРКА МИНИМАЛЬНОЙ СУММЫ ==========
        min_withdraw = 5
        if amount < min_withdraw:
            print(f"❌ Ошибка: сумма {amount} меньше минимальной {min_withdraw}")
            return jsonify({'success': False, 'error': f'Минимальная сумма вывода: {min_withdraw} {currency}'}), 400

        # ========== ПРОВЕРКА БАЛАНСА ==========
        user_data = get_user_data(user_id)
        current_balance = float(user_data.get('ton_balance', 0))
        print(f"💰 Текущий баланс пользователя: {current_balance} TON")

        if amount > current_balance:
            print(f"❌ Ошибка: сумма {amount} превышает баланс {current_balance}")
            return jsonify({'success': False, 'error': f'Недостаточно TON'}), 400

        # ========== СПИСЫВАЕМ БАЛАНС (всегда в TON) ==========
        result = update_user_balance(user_id, -amount, f'Вывод {currency}', 'Обработка вывода')
        print(f"📊 Результат списания: {result}")

        if not result['success']:
            print(f"❌ Ошибка списания: {result['error']}")
            return jsonify({'success': False, 'error': result['error']}), 500

        # ========== ОПРЕДЕЛЯЕМ ПАПКУ ==========
        if currency == 'USDT':
            folder = 'data/withdraw_requests_usdt'
        elif currency == 'CrBot':
            folder = 'data/withdraw_requests_crbot'
        else:
            folder = 'data/withdraw_requests_gram'

        os.makedirs(folder, exist_ok=True)

        # ========== СОХРАНЯЕМ ЗАЯВКУ ==========
        request_id = f"{user_id}_{int(time.time())}"
        withdraw_requests_file = os.path.join(folder, f'{request_id}.json')

        request_data = {
            'request_id': request_id,
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'amount': float(amount),  # Сумма в TON
            'receive_amount': float(receive_amount),  # Сумма в валюте вывода
            'commission': commission,
            'wallet_address': wallet_address,
            'currency': currency,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }

        with open(withdraw_requests_file, 'w', encoding='utf-8') as f:
            json.dump(request_data, f, indent=2, ensure_ascii=False)

        print(f"📄 ID заявки: {request_id}")
        print(f"📁 Папка: {folder}")

        # ========== ОТПРАВКА УВЕДОМЛЕНИЙ ==========
        print(f"\n{'='*50}")
        print(f"📤 ОТПРАВКА УВЕДОМЛЕНИЙ")
        print(f"📌 request_id: {request_id}")
        print(f"📌 user_id: {user_id}")
        print(f"📌 amount: {amount}")
        print(f"📌 currency: {currency}")
        print(f"{'='*50}\n")

        notification_result = send_withdraw_notification_sync(
            request_id=request_id,
            user_id=user_id,
            username=username,
            first_name=first_name,
            amount=amount,
            receive_amount=receive_amount,
            wallet_address=wallet_address,
            currency=currency  # ← Передаем валюту (GRAM, USDT, CrBot)
        )

        print(f"📤 Результат отправки уведомлений: {notification_result}")

        return jsonify({
            'success': True,
            'new_balance': result['new_balance'],
            'currency': currency,
            'request_id': request_id
        })

    except Exception as e:
        print(f"🔴 ИСКЛЮЧЕНИЕ в withdraw_request: {e}")
        import traceback
        traceback.print_exc()
        write_log('error', f'Ошибка в withdraw_request', data={'error': str(e)})
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/referral', methods=['POST'])
def handle_referral():
    data = request.json
    user_id = data.get('user_id')
    referrer_id = data.get('referrer_id')

    if user_id and referrer_id:
        add_referral(user_id, referrer_id)

    return jsonify({'success': True})
# ========== API ДЛЯ PVE ЛОББИ ==========

@app.route('/api/pve/lobbies', methods=['GET'])
def get_pve_lobbies():
    data = load_pve_lobbies()
    # Добавляем комиссию в каждое лобби
    for lobby in data['lobbies']:
        if 'commission' not in lobby:
            lobby['commission'] = COMA  # ← БЕРЕМ ИЗ КОНФИГА
    return jsonify(data)

@app.route('/api/pve/lobby/create', methods=['POST'])
def create_pve_lobby():
    try:
        req = request.json
        user_id = req.get('user_id')
        username = req.get('username', 'Player')
        bet_amount = float(req.get('bet_amount', 1.0))
        max_players = int(req.get('max_players', 4))
        game_type = req.get('game_type', 'Batl')
        games_queue = req.get('games_queue', [])

        # Если username начинается с @ — убираем
        if username.startswith('@'):
            username = username[1:]

        # ========== ✅ ПРОВЕРЯЕМ БАЛАНС ==========
        user_data = get_user_data(user_id)
        if not user_data:
            return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404

        current_balance = float(user_data.get('ton_balance', 0))
        if current_balance < bet_amount:
            return jsonify({
                'success': False,
                'error': f'Недостаточно средств. Нужно {bet_amount} GRAM'
            }), 400

        # ========== ✅ СПИСЫВАЕМ СТАВКУ (VAGER ОБНОВИТСЯ АВТОМАТИЧЕСКИ) ==========
        result = update_user_balance(
            user_id,
            -bet_amount,
            f'Создание лобби Batl',
            'Ожидание игроков',
            skip_history=True  # ← НЕ ПИШЕМ В ИСТОРИЮ ДО НАЧАЛА ИГРЫ
        )

        if not result['success']:
            return jsonify({'success': False, 'error': 'Ошибка списания средств'}), 500

        lobby_hash = str(uuid.uuid4())[:8]

        lobby = {
            'hash': lobby_hash,
            'game_type': game_type,
            'bet_amount': bet_amount,
            'max_players': max_players,
            'current_players': 1,
            'players': [{
                'user_id': user_id,
                'username': username,
                'ready': False,
                'joined_at': time.time()
            }],
            'games_queue': games_queue,
            'results': {},
            'status': 'waiting',
            'created_at': time.time(),
            'created_by': user_id,
            'version': 1,
            'commission': COMA
        }

        data = load_pve_lobbies()
        data['lobbies'].append(lobby)
        save_pve_lobbies(data)

        return jsonify({'success': True, 'lobby': lobby})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/games/Batl')
def game_batl():
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    user_id = request.args.get('user_id')
    return render_template('game_batl.html', device_type=device_type, user_id=user_id)

@app.route('/api/withdraw_callback', methods=['POST'])
def withdraw_callback():
    """Callback для обработки кнопок админа (GRAM/USDT/CrBot)"""
    try:
        data = request.json
        request_id = data.get('request_id')
        action = data.get('action')

        print(f"📤 Получен callback: request_id={request_id}, action={action}")

        if not request_id or not action:
            return jsonify({'success': False, 'error': 'Missing fields'}), 400

        # ========== ИЩЕМ ЗАЯВКУ ВО ВСЕХ ПАПКАХ ==========
        import glob
        folders = [
            'data/withdraw_requests_gram',
            'data/withdraw_requests_usdt',
            'data/withdraw_requests_crbot'
        ]

        files = []
        for folder in folders:
            if not os.path.exists(folder):
                continue
            found = glob.glob(os.path.join(folder, f'*{request_id}*.json'))
            if found:
                files = found
                print(f"✅ Найдено в папке: {folder}")
                break

        if not files:
            print(f"❌ Заявка {request_id} не найдена")
            return jsonify({'success': False, 'error': 'Заявка не найдена'}), 404

        with open(files[0], 'r', encoding='utf-8') as f:
            request_data = json.load(f)

        user_id = request_data.get('user_id')
        amount = request_data.get('amount', 0)
        receive_amount = request_data.get('receive_amount', amount)
        first_name = request_data.get('first_name', 'User')
        currency = request_data.get('currency', 'GRAM')
        wallet_address = request_data.get('wallet_address', '')

        # ========== КОНВЕРТИРУЕМ В ЧИСЛА ==========
        try:
            amount = float(amount)
        except:
            amount = 0

        try:
            receive_amount_num = float(receive_amount)
        except:
            receive_amount_num = amount

        print(f"📊 Заявка: ID={request_id}, user={user_id}, amount={amount}, currency={currency}, action={action}")

        # ========== ОБНОВЛЯЕМ СТАТУС В ИСТОРИИ ==========
        history_file = os.path.join('data', 'history', f'{user_id}.txt')
        os.makedirs(os.path.dirname(history_file), exist_ok=True)

        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Ищем последнюю запись о выводе
            for i in range(len(lines) - 1, -1, -1):
                if 'Вывод' in lines[i] and f"-{amount}" in lines[i]:
                    if action == 'approve':
                        lines[i] = lines[i].replace('Обработка вывода', 'Одобрено')
                    elif action == 'reject':
                        lines[i] = lines[i].replace('Обработка вывода', 'Отклонено')
                        # Возвращаем баланс при отклонении
                    else:
                        lines[i] = lines[i].replace('Обработка вывода', 'Заблокировано')
                    break

            with open(history_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

        # ========== УВЕДОМЛЯЕМ ПОЛЬЗОВАТЕЛЯ ==========
        from bot import send_user_notification

        if action == 'approve':
            # ✅ УВЕЛИЧИВАЕМ total_withdrawn ПРИ ПОДТВЕРЖДЕНИИ
            try:
                from functions import update_withdrawn_stats
                update_withdrawn_stats(user_id, receive_amount_num)
                print(f"💰 Обновлена статистика вывода: +{receive_amount_num}")
            except Exception as e:
                print(f"⚠️ Ошибка update_withdrawn_stats: {e}")

        elif action == 'reject':
            send_user_notification(user_id, amount, 'reject', 'TON')
            # Возвращаем баланс
        else:
            send_user_notification(user_id, amount, 'block', 'TON')

        # ========== СОХРАНЯЕМ СТАТУС ЗАЯВКИ ==========
        if action == 'approve':
            request_data['status'] = 'approved'
        elif action == 'reject':
            request_data['status'] = 'rejected'
        else:
            request_data['status'] = 'blocked'

        request_data['processed_at'] = datetime.now().isoformat()
        request_data['processed_by'] = ADMIN_CHAT_ID

        with open(files[0], 'w', encoding='utf-8') as f:
            json.dump(request_data, f, indent=2, ensure_ascii=False)

        # ========== ОТПРАВЛЯЕМ ПОДТВЕРЖДЕНИЕ АДМИНУ ==========
        if action == 'approve':
            status_text = f"✅ ОДОБРЕНО (выведено {receive_amount_num:.2f} {currency})"
        elif action == 'reject':
            status_text = "❌ ОТМЕНЕНО (средства возвращены)"
        else:
            status_text = "🔒 ЗАБЛОКИРОВАНО"

        confirm_message = f"Заявка {request_id}: {status_text}\nПользователь: {first_name}\nСумма: {amount:.2f} TON"

        from bot import send_message_sync
        send_message_sync(chat_id=ADMIN_CHAT_ID, text=confirm_message, parse_mode='HTML')

        return jsonify({'success': True})

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"🔴 ОШИБКА в withdraw_callback:")
        print(error_trace)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/prepare_referral_message', methods=['POST'])
def prepare_referral_message():
    try:
        data = request.json
        referral_link = data.get('referral_link')
        user_id = data.get('user_id')

        if not referral_link:
            return jsonify({'success': False, 'error': 'Missing referral_link'}), 400

        if not user_id:
            return jsonify({'success': False, 'error': 'Missing user_id'}), 400

        msg_id = save_prepared_inline_message(referral_link, BOT_TOKEN, user_id)

        if msg_id:
            return jsonify({'success': True, 'msg_id': msg_id})
        else:
            return jsonify({'success': False, 'error': 'Не удалось создать сообщение'}), 500

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_vager', methods=['POST'])
def api_update_vager():
    """Обновляет vager пользователя (может быть + или -)"""
    try:
        data = request.json
        user_id = data.get('user_id')
        amount = data.get('amount', 0)

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        result = update_vager(user_id, amount)

        if result:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'User not found'}), 404

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/claim_bonus', methods=['POST'])
def claim_bonus():
    """Отмечает бонус как полученный"""
    try:
        data = request.json
        token = data.get('token')
        user_id = data.get('user_id')

        if not token or not user_id:
            return jsonify({'success': False, 'error': 'Missing parameters'}), 400

        bonus_data_file = os.path.join('data', 'bonus_tokens.json')
        if not os.path.exists(bonus_data_file):
            return jsonify({'success': False, 'error': 'Bonus not found'}), 404

        with open(bonus_data_file, 'r', encoding='utf-8') as f:
            bonus_tokens = json.load(f)

        if token not in bonus_tokens:
            return jsonify({'success': False, 'error': 'Invalid token'}), 404

        bonus_data = bonus_tokens[token]

        if bonus_data['user_id'] != user_id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        if bonus_data['used']:
            return jsonify({'success': False, 'error': 'Bonus already claimed'}), 400

        # Отмечаем как использованный
        bonus_data['used'] = True
        bonus_data['claimed_at'] = time.time()

        with open(bonus_data_file, 'w', encoding='utf-8') as f:
            json.dump(bonus_tokens, f, indent=2, ensure_ascii=False)

        # Здесь можно начислить бонус пользователю
        # update_user_balance(user_id, 0.5, 'Бонус', 'Начисление')

        return jsonify({'success': True, 'message': 'Bonus claimed successfully'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== Страница бонуса ==========
@app.route('/bonus_page')
def bonus_page():
    """Страница бонуса с таймером"""
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    token = request.args.get('token')
    user_id = request.args.get('user_id')
    created_at = request.args.get('created_at')
    tame = request.args.get('tame')

    if not token or not user_id:
        return "❌ Неверная ссылка", 400

    bonus_data_file = os.path.join('data', 'bonus_tokens.json')
    if not os.path.exists(bonus_data_file):
        return "❌ Бонус не найден", 404

    with open(bonus_data_file, 'r', encoding='utf-8') as f:
        bonus_tokens = json.load(f)

    if token not in bonus_tokens:
        return "❌ Бонус не найден", 404

    bonus_data = bonus_tokens[token]

    if bonus_data['user_id'] != user_id:
        return "❌ Доступ запрещен", 403

    # ✅ ЕСЛИ БОНУС УЖЕ ПОЛУЧЕН — РЕДИРЕКТ НА ГЛАВНУЮ
    if bonus_data.get('used', False):
        return redirect('/')

    # Если created_at не передан - берем из файла
    if created_at is None:
        created_at = bonus_data.get('created_at')
        if created_at is None:
            created_at = time.time()
            bonus_data['created_at'] = created_at
            with open(bonus_data_file, 'w', encoding='utf-8') as f:
                json.dump(bonus_tokens, f, indent=2, ensure_ascii=False)

    # Получаем tame пользователя из БД
    if tame is None:
        user_data = get_user_data(user_id)
        tame = user_data.get('tame', 60) if user_data else 60

    return render_template('bonus_page.html',
                           device_type=device_type,
                           token=token,
                           user_id=user_id,
                           created_at=int(created_at),
                           tame=int(tame) if tame else 60)

@app.route('/api/check_bonus', methods=['GET'])
def check_bonus():
    """Проверяет, доступен ли ещё бонус для пользователя"""
    token = request.args.get('token')
    user_id = request.args.get('user_id')

    if not token or not user_id:
        return jsonify({'available': False, 'error': 'Missing parameters'}), 400

    bonus_data_file = os.path.join('data', 'bonus_tokens.json')
    if not os.path.exists(bonus_data_file):
        return jsonify({'available': False, 'error': 'Bonus not found'}), 404

    try:
        with open(bonus_data_file, 'r', encoding='utf-8') as f:
            bonus_tokens = json.load(f)

        if token not in bonus_tokens:
            return jsonify({'available': False, 'error': 'Invalid token'}), 404

        bonus_data = bonus_tokens[token]

        # Проверяем, принадлежит ли токен пользователю
        if bonus_data.get('user_id') != user_id:
            return jsonify({'available': False, 'error': 'Access denied'}), 403

        # Если бонус уже использован - недоступен
        if bonus_data.get('used', False):
            return jsonify({'available': False, 'message': 'Bonus already claimed'})

        # Бонус доступен
        return jsonify({'available': True})

    except Exception as e:
        print(f"❌ Ошибка проверки бонуса: {e}")
        return jsonify({'available': False, 'error': str(e)}), 500
# ========== капча ==========
# Хранилище для капч
CAPTCHA_STORAGE = {}

def generate_captcha():
    """Генерирует капчу и возвращает текст и изображение в base64"""
    captcha_text = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

    # Увеличенный размер
    width, height = 260, 80
    image = Image.new('RGB', (width, height), color=(20, 20, 40))
    draw = ImageDraw.Draw(image)

    # Шум (линии)
    for _ in range(8):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line((x1, y1, x2, y2), fill=(random.randint(40, 120), random.randint(40, 120), random.randint(40, 120)),
                  width=1)

    # Шум (точки)
    for _ in range(120):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(random.randint(80, 180), random.randint(80, 180), random.randint(80, 180)))

    # Шрифт
    try:
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
            '/System/Library/Fonts/Helvetica.ttc',
            'C:/Windows/Fonts/Arial.ttf'
        ]
        font = None
        for path in font_paths:
            if os.path.exists(path):
                font = ImageFont.truetype(path, 38)
                break
        if font is None:
            font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()

    # Текст - смещаем вниз, чтобы буквы были в нижней части
    for i, char in enumerate(captcha_text):
        y = height - 42 + random.randint(-4, 4)
        x = 18 + i * 52 + random.randint(-4, 4)
        draw.text((x, y), char, fill=(random.randint(200, 255), random.randint(200, 255), random.randint(200, 255)),
                  font=font)

    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()

    return captcha_text, f"data:image/png;base64,{img_str}"

@app.route('/api/generate_captcha', methods=['POST'])
def generate_captcha_api():
    """Генерирует капчу для бонуса"""
    try:
        data = request.json
        token = data.get('token')

        if not token:
            return jsonify({'success': False, 'error': 'No token'}), 400

        captcha_text, captcha_image = generate_captcha()

        # Сохраняем капчу
        CAPTCHA_STORAGE[token] = {
            'text': captcha_text,
            'created_at': time.time()
        }

        return jsonify({
            'success': True,
            'captcha_image': captcha_image
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/verify_captcha', methods=['POST'])
def verify_captcha():
    """Проверяет капчу и начисляет бонус"""
    try:
        data = request.json
        token = data.get('token')
        user_id = data.get('user_id')
        captcha_input = data.get('captcha', '').strip().upper()

        if not token or not user_id:
            return jsonify({'success': False, 'error': 'Missing parameters'}), 400

        # Проверяем капчу
        if token not in CAPTCHA_STORAGE:
            return jsonify({'success': False, 'error': 'Капча не найдена. Обновите страницу.'}), 400

        captcha_data = CAPTCHA_STORAGE[token]

        # Проверяем время (капча действительна 5 минут)
        if time.time() - captcha_data['created_at'] > 300:
            del CAPTCHA_STORAGE[token]
            return jsonify({'success': False, 'error': 'Капча устарела. Обновите страницу.'}), 400

        # Проверяем текст
        if captcha_input != captcha_data['text']:
            return jsonify({'success': False, 'error': 'Неверный код. Попробуйте снова.'}), 400

        # Удаляем использованную капчу
        del CAPTCHA_STORAGE[token]

        # ========== ПРОВЕРЯЕМ БОНУС-ТОКЕН ==========
        bonus_data_file = os.path.join('data', 'bonus_tokens.json')
        if not os.path.exists(bonus_data_file):
            return jsonify({'success': False, 'error': 'Bonus not found'}), 404

        with open(bonus_data_file, 'r', encoding='utf-8') as f:
            bonus_tokens = json.load(f)

        if token not in bonus_tokens:
            return jsonify({'success': False, 'error': 'Invalid token'}), 404

        bonus_data = bonus_tokens[token]

        # Проверяем пользователя
        if bonus_data['user_id'] != user_id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        # Проверяем, не использован ли уже
        if bonus_data.get('used', False):
            return jsonify({'success': False, 'error': 'Bonus already claimed'}), 400

        # ========== НАЧИСЛЯЕМ БОНУС ==========
        try:
            # 1. Начисляем 0.5 TON
            result = update_user_balance(
                user_id=user_id,
                amount_change=0.5,
                description='Бонус за капчу',
                status='Начисление'
            )

            if not result['success']:
                return jsonify({'success': False, 'error': result.get('error', 'Ошибка начисления TON')}), 500

            # 2. Начисляем +5 VAGER
            vager_result = update_vager(user_id, 5)
            if not vager_result:
                return jsonify({'success': False, 'error': 'Ошибка начисления VAGER'}), 500

            # 3. Отмечаем бонус как использованный
            bonus_data['used'] = True
            bonus_data['claimed_at'] = time.time()

            with open(bonus_data_file, 'w', encoding='utf-8') as f:
                json.dump(bonus_tokens, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"❌ Ошибка начисления бонуса: {e}")
            return jsonify({
                'success': False,
                'error': 'Ошибка при начислении бонуса. Попробуйте позже.'
            }), 500

        return jsonify({
            'success': True,
            'message': '🎉 Бонус 0.5 TON и 5 VAGER успешно начислены!'
        })

    except Exception as e:
        print(f"❌ Ошибка в verify_captcha: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500


def load_user_tasks():
    if not os.path.exists(TASKS_FILE):
        return {}
    try:
        with open(TASKS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}


def save_user_tasks(data):
    os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ========== УНИВЕРСАЛЬНЫЙ ЭНДПОИНТ ДЛЯ ЗАДАНИЙ ==========
@app.route('/api/tasks', methods=['GET', 'POST'])
def handle_tasks():
    try:
        user_id = request.args.get('user_id') if request.method == 'GET' else request.json.get('user_id')

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        user_id_str = str(user_id)
        tasks_data = load_user_tasks()

        # GET - получить все задания пользователя
        if request.method == 'GET':
            return jsonify({
                'success': True,
                'tasks': tasks_data.get(user_id_str, {})
            })

        # POST - отметить задание как выполненное
        data = request.json
        task_id = data.get('task_id')

        if not task_id:
            return jsonify({'success': False, 'error': 'No task_id'}), 400

        if user_id_str not in tasks_data:
            tasks_data[user_id_str] = {}

        tasks_data[user_id_str][task_id] = {
            'completed': True,
            'completed_at': datetime.now().isoformat()
        }

        save_user_tasks(tasks_data)
        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ==========
@app.route('/api/check_subscription', methods=['POST'])
def check_subscription():
    try:
        data = request.json
        user_id = data.get('user_id')

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        user_id_str = str(user_id)
        tasks = load_user_tasks()

        # ===== ПРОВЕРЯЕМ НА СЕРВЕРЕ, НЕ ВЫПОЛНЕНО ЛИ УЖЕ =====
        if tasks.get(user_id_str, {}).get('subscribe_channel', {}).get('completed', False):
            # ✅ ДОБАВЛЯЕМ already_completed!
            return jsonify({
                'success': True,
                'is_subscribed': True,
                'already_completed': True  # ← ДОБАВИТЬ ЭТО!
            })

        # Проверяем подписку через Telegram API
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
        response = requests.get(url, params={
            'chat_id': CHANNEL_ID,
            'user_id': user_id
        }, timeout=5)

        data = response.json()
        is_subscribed = False

        if data.get('ok'):
            status = data['result'].get('status')
            is_subscribed = status in ['creator', 'administrator', 'member']

        if not is_subscribed:
            return jsonify({
                'success': True,
                'is_subscribed': False
            })

        # ===== ПОДПИСАН! Начисляем бонус =====
        user_data = get_user_data(user_id)
        current_tame = float(user_data.get('tame', 0))
        new_tame = current_tame + 5
        update_user_field(user_id, 'tame', new_tame)

        # Отмечаем задание выполненным
        if user_id_str not in tasks:
            tasks[user_id_str] = {}
        tasks[user_id_str]['subscribe_channel'] = {
            'completed': True,
            'completed_at': datetime.now().isoformat()
        }
        save_user_tasks(tasks)

        return jsonify({
            'success': True,
            'is_subscribed': True,
            'already_completed': False  # ← ТОЖЕ ДОБАВЛЯЕМ ДЛЯ ЯСНОСТИ
        })

    except Exception as e:
        print(f"❌ Ошибка check_subscription: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/check_chat_subscription', methods=['POST'])
def check_chat_subscription():
    try:
        data = request.json
        user_id = data.get('user_id')

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        user_id_str = str(user_id)
        tasks = load_user_tasks()

        # ===== ПРОВЕРЯЕМ НА СЕРВЕРЕ, НЕ ВЫПОЛНЕНО ЛИ УЖЕ =====
        if tasks.get(user_id_str, {}).get('subscribe_chat', {}).get('completed', False):
            # ✅ УЖЕ ЕСТЬ already_completed
            return jsonify({
                'success': True,
                'is_subscribed': True,
                'already_completed': True  # ← ЭТО УЖЕ ЕСТЬ
            })

        # Проверяем подписку через Telegram API
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
        response = requests.get(url, params={
            'chat_id': CHAT_ID,
            'user_id': user_id
        }, timeout=5)

        data = response.json()
        is_subscribed = False

        if data.get('ok'):
            status = data['result'].get('status')
            is_subscribed = status in ['creator', 'administrator', 'member']

        if not is_subscribed:
            return jsonify({
                'success': True,
                'is_subscribed': False
            })

        # ===== ПОДПИСАН! Начисляем бонус =====
        user_data = get_user_data(user_id)
        current_tame = float(user_data.get('tame', 0))
        new_tame = current_tame + 5
        update_user_field(user_id, 'tame', new_tame)

        if user_id_str not in tasks:
            tasks[user_id_str] = {}
        tasks[user_id_str]['subscribe_chat'] = {
            'completed': True,
            'completed_at': datetime.now().isoformat()
        }
        save_user_tasks(tasks)

        return jsonify({
            'success': True,
            'is_subscribed': True,
            'already_completed': False  # ← ДОБАВЛЯЕМ ДЛЯ ЯСНОСТИ
        })

    except Exception as e:
        print(f"❌ Ошибка check_chat_subscription: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== PVP игры ==========
@app.route('/games/Batl/<lobby_hash>')
def game_batl_with_hash(lobby_hash):
    """Страница игры Batl с хешем в URL"""
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    user_id = request.args.get('user_id')

    # Проверяем, существует ли лобби
    data = load_pve_lobbies()
    lobby = None
    for l in data['lobbies']:
        if l['hash'] == lobby_hash:
            lobby = l
            break

    if not lobby:
        return "Лобби не найдено или уже завершено", 404

    # Если пользователь не в лобби и лобби в статусе waiting - добавляем
    if user_id and lobby['status'] == 'waiting':
        is_in_lobby = any(p['user_id'] == user_id for p in lobby['players'])
        if not is_in_lobby:
            # Получаем имя пользователя
            user_data = get_user_data(user_id)
            username = user_data.get('username', 'Player') if user_data else 'Player'

            lobby['players'].append({
                'user_id': user_id,
                'username': username,
                'ready': False,
                'joined_at': time.time()
            })
            lobby['current_players'] += 1
            save_pve_lobbies(data)

    return render_template('game_batl.html',
                           device_type=device_type,
                           user_id=user_id,
                           lobby_hash=lobby_hash)

@app.route('/api/pve/lobby/leave', methods=['POST'])
def leave_pve_lobby():
    """Покинуть лобби с возвратом ставки"""
    try:
        req = request.json
        lobby_hash = req.get('lobby_hash')
        user_id = req.get('user_id')

        if not lobby_hash or not user_id:
            return jsonify({'success': False, 'error': 'Missing parameters'}), 400

        data = load_pve_lobbies()
        lobby = None
        lobby_index = -1

        for i, l in enumerate(data['lobbies']):
            if l['hash'] == lobby_hash:
                lobby = l
                lobby_index = i
                break

        if not lobby:
            return jsonify({'success': False, 'error': 'Лобби не найдено'}), 404

        # Проверяем, есть ли игрок в лобби
        player_found = False
        for player in lobby['players']:
            if player['user_id'] == user_id:
                player_found = True
                break

        if not player_found:
            return jsonify({'success': False, 'error': 'Вы не в этом лобби'}), 400

        # Если игра уже началась - нельзя выйти
        if lobby['status'] == 'playing':
            return jsonify({'success': False, 'error': 'Игра уже началась, выйти нельзя'}), 400

        # Если лобби уже завершено
        if lobby['status'] == 'finished':
            return jsonify({'success': False, 'error': 'Лобби уже завершено'}), 400

        # Возвращаем ставку игроку
        bet_amount = float(lobby.get('bet_amount', 0))
        if bet_amount > 0:
            result = update_user_balance(
                user_id,
                bet_amount,
                f'Возврат ставки из лобби {lobby_hash}',
                'Возврат',
                skip_history=True
            )
            if not result['success']:
                print(f"⚠️ Не удалось вернуть ставку игроку {user_id}")

        # Удаляем игрока из лобби
        lobby['players'] = [p for p in lobby['players'] if p['user_id'] != user_id]
        lobby['current_players'] = len(lobby['players'])
        lobby['version'] = lobby.get('version', 0) + 1

        # Если игроков не осталось - удаляем лобби
        if lobby['current_players'] == 0:
            data['lobbies'].pop(lobby_index)
            save_pve_lobbies(data)
            return jsonify({
                'success': True,
                'message': 'Лобби удалено (нет игроков)'
            })

        # Если создатель вышел - назначаем нового
        if lobby['created_by'] == user_id and lobby['players']:
            lobby['created_by'] = lobby['players'][0]['user_id']

        data['lobbies'][lobby_index] = lobby
        save_pve_lobbies(data)

        return jsonify({
            'success': True,
            'message': 'Вы вышли из лобби'
        })

    except Exception as e:
        print(f"❌ Ошибка leave_pve_lobby: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/pve/lobby/join', methods=['POST'])
def join_pve_lobby():
    try:
        req = request.json
        lobby_hash = req.get('lobby_hash')
        user_id = req.get('user_id')
        username = req.get('username', 'Player')

        if username.startswith('@'):
            username = username[1:]

        data = load_pve_lobbies()

        for lobby in data['lobbies']:
            if lobby['hash'] == lobby_hash:
                if lobby['current_players'] >= lobby['max_players']:
                    return jsonify({'success': False, 'error': 'Лобби заполнено'}), 400

                for player in lobby['players']:
                    if player['user_id'] == user_id:
                        return jsonify({'success': False, 'error': 'Вы уже в этом лобби'}), 400

                user_data = get_user_data(user_id)
                if not user_data:
                    return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404

                current_balance = float(user_data.get('ton_balance', 0))
                bet_amount = float(lobby.get('bet_amount', 1.0))

                if current_balance < bet_amount:
                    return jsonify({
                        'success': False,
                        'error': f'Недостаточно средств. Нужно {bet_amount} GRAM'
                    }), 400

                result = update_user_balance(
                    user_id,
                    -bet_amount,
                    f'Игра Batl',
                    'Ожидание игроков',
                    skip_history=True
                )

                if not result['success']:
                    return jsonify({'success': False, 'error': 'Ошибка списания средств'}), 500

                lobby['players'].append({
                    'user_id': user_id,
                    'username': username,
                    'ready': False,
                    'joined_at': time.time()
                })
                lobby['current_players'] += 1
                lobby['version'] = lobby.get('version', 0) + 1

                if lobby['current_players'] >= lobby['max_players']:
                    # ✅ ОЧИЩАЕМ РЕЗУЛЬТАТЫ ПЕРЕД НАЧАЛОМ ИГРЫ
                    lobby['results'] = {}

                    lobby['status'] = 'playing'
                    lobby['started_at'] = time.time()
                    lobby['version'] = lobby.get('version', 0) + 1
                    save_pve_lobbies(data)

                    # ===== ОТПРАВЛЯЕМ УВЕДОМЛЕНИЯ =====
                    bot_username = NAME
                    external_url = f"https://t.me/{bot_username}/app?startapp=batl_{lobby_hash}"
                    internal_url = f"/games/Batl/lobby/{lobby_hash}?user_id={user_id}"

                    games_list = lobby.get('games_queue', ['Batl'])

                    # ЭМОДЗИ ДЛЯ ИГР
                    game_emojis = {
                        'Дартс': '🎯',
                        'Кегли': '🎳',
                        'Кости': '🎲',
                        'Batl': '⚔️'
                    }

                    games_emoji_list = []
                    for game in games_list:
                        games_emoji_list.append(game_emojis.get(game, '🎮'))
                    games_emoji_text = ' '.join(games_emoji_list)

                    # СПИСОК ИГРОКОВ
                    players_lines = []
                    player_count = len(lobby['players'])
                    for i, player in enumerate(lobby['players']):
                        player_name = player.get('username', 'Player')
                        if player_name.startswith('@'):
                            player_name = player_name[1:]
                        prefix = '└' if i == player_count - 1 else '├'
                        players_lines.append(f"{prefix} @{player_name}")
                    players_text = '\n'.join(players_lines)

                    # БАНК
                    bank_amount = lobby['bet_amount'] * lobby['current_players']

                    # ФОРМИРУЕМ СООБЩЕНИЕ
                    message_text = (
                        f"<tg-emoji emoji-id='5411267268036302635'>✔️</tg-emoji> "
                        f"<b>Batl начался!</b> #{lobby_hash.upper()}\n\n"
                        f"<tg-emoji emoji-id='5411566356673896077'>🏦</tg-emoji><b>Банк:</b> {bank_amount:.2f} "
                        f"<tg-emoji emoji-id='5411228939748155514'>💎</tg-emoji>\n\n"
                        f"<tg-emoji emoji-id='5413523620515326864'>👉</tg-emoji> {games_emoji_text} <tg-emoji emoji-id='5413344971350650770'>👈</tg-emoji>\n\n"
                        f"<blockquote><b><tg-emoji emoji-id='5413739511341425163'>🎁</tg-emoji> Игроки:</b>\n{players_text}</blockquote>"
                    )

                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            text="Войти в игру",
                            url=external_url,
                            icon_custom_emoji_id="5411583656802162641"  # ← ID премиум-эмодзи 🎮
                        )]
                    ])

                    # ===== ОТПРАВЛЯЕМ ИГРОКАМ =====
                    for player in lobby['players']:
                        player_id = player['user_id']
                        user_data = get_user_data(player_id)
                        notifications_enabled = user_data.get('notifications', True) if user_data else True

                        if notifications_enabled:
                            try:
                                send_message_sync(
                                    chat_id=player_id,
                                    text=message_text,
                                    parse_mode='HTML',
                                    reply_markup=keyboard
                                )
                                print(f"✅ Уведомление отправлено игроку {player_id}")
                            except Exception as e:
                                print(f"❌ Ошибка отправки уведомления игроку {player_id}: {e}")

                    # ===== ГЕНЕРИРУЕМ ИЗОБРАЖЕНИЕ С ИМЕНАМИ =====
                    try:
                        from PIL import Image, ImageDraw, ImageFont

                        template_path = os.path.join(BASE_DIR, 'web', 'sticer', 'game_batl_start.png')

                        if os.path.exists(template_path):
                            img = Image.open(template_path)

                            # СОЗДАЕМ СЛОЙ ДЛЯ РИСОВАНИЯ С ПРОЗРАЧНОСТЬЮ
                            overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                            draw = ImageDraw.Draw(overlay)

                            img_width, img_height = img.size

                            # ПОЛУЧАЕМ СПИСОК ИГРОКОВ
                            players_list = lobby['players']
                            player_count = len(players_list)

                            # ОПРЕДЕЛЯЕМ РАЗМЕР ШРИФТА В 2 РАЗА МЕНЬШЕ
                            if player_count == 3:
                                font_size = 60
                            elif player_count >= 4:
                                font_size = 50
                            else:
                                font_size = 80

                            try:
                                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                                          font_size)
                            except:
                                try:
                                    font = ImageFont.truetype("arial.ttf", font_size)
                                except:
                                    font = ImageFont.load_default()

                            # ИЗМЕРЯЕМ ТЕКСТ ДЛЯ КАЖДОГО ИГРОКА
                            player_names = []
                            text_widths = []
                            text_heights = []

                            for player in players_list:
                                player_name = player.get('username', 'Player')
                                if player_name.startswith('@'):
                                    player_name = player_name[1:]
                                player_names.append(player_name)

                                bbox = draw.textbbox((0, 0), player_name, font=font)
                                text_widths.append(bbox[2] - bbox[0])
                                text_heights.append(bbox[3] - bbox[1])

                            # ОДИНАКОВАЯ ВЫСОТА ДЛЯ ВСЕХ ПРЯМОУГОЛЬНИКОВ
                            max_text_height = max(text_heights)
                            padding_y = 30
                            rect_height = max_text_height + padding_y * 2

                            # ОТСТУП ОТ НИЗА
                            bottom_offset = 60

                            # ===== РАЗМЕЩЕНИЕ В ЗАВИСИМОСТИ ОТ КОЛИЧЕСТВА ИГРОКОВ =====
                            if player_count == 2:
                                half_width = img_width // 2
                                spacing = 30

                                for i in range(2):
                                    padding_x = 40
                                    rect_width = text_widths[i] + padding_x * 2
                                    max_width = half_width - spacing - 20
                                    rect_width = min(rect_width, max_width)

                                    if i == 0:
                                        x = (half_width - rect_width) // 2
                                    else:
                                        x = half_width + (half_width - rect_width) // 2

                                    y = img_height - rect_height - bottom_offset

                                    draw.rounded_rectangle(
                                        [x, y, x + rect_width, y + rect_height],
                                        radius=20,
                                        fill=(0, 0, 0, 180),
                                        outline=None,
                                        width=0
                                    )

                                    text_x = x + (rect_width - text_widths[i]) // 2
                                    text_y = y + (rect_height - text_heights[i]) // 2 - 5
                                    draw.text((text_x, text_y), player_names[i], fill=(255, 255, 255, 255), font=font)

                            elif player_count == 3:
                                spacing = 20
                                padding_x = 30

                                rect_widths = []
                                for i in range(3):
                                    rect_width = text_widths[i] + padding_x * 2
                                    rect_widths.append(rect_width)

                                total_width = sum(rect_widths) + spacing * 2

                                if total_width > img_width - 40:
                                    scale = (img_width - 40) / total_width
                                    rect_widths = [w * scale for w in rect_widths]
                                    spacing = spacing * scale
                                    total_width = sum(rect_widths) + spacing * 2

                                start_x = (img_width - total_width) // 2
                                y = img_height - rect_height - bottom_offset

                                for i in range(3):
                                    x = start_x + sum(rect_widths[:i]) + spacing * i

                                    draw.rounded_rectangle(
                                        [x, y, x + rect_widths[i], y + rect_height],
                                        radius=18,
                                        fill=(0, 0, 0, 180),
                                        outline=None,
                                        width=0
                                    )

                                    text_x = x + (rect_widths[i] - text_widths[i]) // 2
                                    text_y = y + (rect_height - text_heights[i]) // 2 - 5
                                    draw.text((text_x, text_y), player_names[i], fill=(255, 255, 255, 255), font=font)

                            elif player_count == 4:
                                half_width = img_width // 2
                                spacing = 20
                                padding_x = 30
                                font_size = 50

                                try:
                                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                                              50)
                                except:
                                    try:
                                        font = ImageFont.truetype("arial.ttf", 50)
                                    except:
                                        font = ImageFont.load_default()

                                text_widths = []
                                text_heights = []
                                for name in player_names:
                                    bbox = draw.textbbox((0, 0), name, font=font)
                                    text_widths.append(bbox[2] - bbox[0])
                                    text_heights.append(bbox[3] - bbox[1])

                                max_text_height = max(text_heights)
                                rect_height = max_text_height + padding_y * 2

                                for row in range(2):
                                    y = img_height - bottom_offset - (2 - row) * (rect_height + 20)

                                    for col in range(2):
                                        idx = row * 2 + col
                                        rect_width = text_widths[idx] + padding_x * 2
                                        max_width = half_width - spacing - 15
                                        rect_width = min(rect_width, max_width)

                                        if col == 0:
                                            x = (half_width - rect_width) // 2
                                        else:
                                            x = half_width + (half_width - rect_width) // 2

                                        draw.rounded_rectangle(
                                            [x, y, x + rect_width, y + rect_height],
                                            radius=18,
                                            fill=(0, 0, 0, 180),
                                            outline=None,
                                            width=0
                                        )

                                        text_x = x + (rect_width - text_widths[idx]) // 2
                                        text_y = y + (rect_height - text_heights[idx]) // 2 - 5
                                        draw.text((text_x, text_y), player_names[idx], fill=(255, 255, 255, 255),
                                                  font=font)

                            else:
                                padding_x = 50
                                rect_width = text_widths[0] + padding_x * 2
                                max_width = img_width - 80
                                rect_width = min(rect_width, max_width)

                                x = (img_width - rect_width) // 2
                                y = img_height - rect_height - bottom_offset

                                draw.rounded_rectangle(
                                    [x, y, x + rect_width, y + rect_height],
                                    radius=20,
                                    fill=(0, 0, 0, 180),
                                    outline=None,
                                    width=0
                                )

                                text_x = x + (rect_width - text_widths[0]) // 2
                                text_y = y + (rect_height - text_heights[0]) // 2 - 5
                                draw.text((text_x, text_y), player_names[0], fill=(255, 255, 255, 255), font=font)

                            # ===== НАКЛАДЫВАЕМ ПРОЗРАЧНЫЙ СЛОЙ =====
                            img = img.convert('RGBA')
                            img = Image.alpha_composite(img, overlay)
                            img = img.convert('RGB')

                            output_path = os.path.join(BASE_DIR, 'web', 'sticer', 'game_batl_start_with_players.png')
                            img.save(output_path, 'PNG')
                            image_path = output_path
                            print(f"✅ Изображение сгенерировано: {image_path}")
                        else:
                            image_path = os.path.join(BASE_DIR, 'web', 'sticer', 'game_batl_start.png')
                            print(f"⚠️ Шаблон не найден, используем {image_path}")

                    except Exception as e:
                        print(f"❌ Ошибка генерации изображения: {e}")
                        import traceback
                        traceback.print_exc()
                        image_path = os.path.join(BASE_DIR, 'web', 'sticer', 'game_batl_start.png')

                    # ===== ОТПРАВЛЯЕМ В ЧАТ =====
                    try:
                        admin_chat_id = "-1004360731939"
                        admin_keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                text="Посмотреть",
                                url=external_url,
                                icon_custom_emoji_id="5411617475374652379"  # ← ID премиум-эмодзи 🎮
                            )]
                        ])

                        if os.path.exists(image_path):
                            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                            with open(image_path, 'rb') as photo:
                                files = {'photo': photo}
                                data = {
                                    'chat_id': admin_chat_id,
                                    'caption': message_text,
                                    'parse_mode': 'HTML',
                                    'reply_markup': json.dumps(admin_keyboard)
                                }
                                response = requests.post(url, files=files, data=data, timeout=10)
                                if response.status_code == 200:
                                    print(f"✅ Уведомление с фото отправлено в чат {admin_chat_id}")
                                else:
                                    print(f"❌ Ошибка отправки фото: {response.status_code}")
                        else:
                            send_message_sync(
                                chat_id=admin_chat_id,
                                text=message_text,
                                parse_mode='HTML',
                                reply_markup=admin_keyboard
                            )
                            print(f"✅ Уведомление (без фото) отправлено в чат {admin_chat_id}")

                    except Exception as e:
                        print(f"❌ Ошибка отправки уведомления в чат: {e}")

                    return jsonify({
                        'success': True,
                        'lobby': lobby,
                        'external_url': external_url,
                        'redirect_url': internal_url,
                        'auto_started': True,
                        'redirect': True
                    })

                save_pve_lobbies(data)
                return jsonify({'success': True, 'lobby': lobby})

        return jsonify({'success': False, 'error': 'Лобби не найдено'}), 404
    except Exception as e:
        print(f"❌ Ошибка join_pve_lobby: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400

def load_promos():
    """Загружает промокоды из файла"""
    if not os.path.exists(PROMO_FILE):
        return {}
    try:
        with open(PROMO_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        print(f"⚠️ Ошибка JSON в {PROMO_FILE}, создаем новый")
        return {}
    except Exception as e:
        print(f"❌ Ошибка загрузки промокодов: {e}")
        return {}

def save_promos(data):
    """Сохраняет промокоды в файл"""
    os.makedirs(os.path.dirname(PROMO_FILE), exist_ok=True)
    with open(PROMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

@app.route('/api/promo/activate', methods=['POST'])
def activate_promo():
    """Активация промокода"""
    try:
        data = request.json
        user_id = data.get('user_id')
        promo_code = data.get('promo_code', '').strip().upper()

        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Пользователь не найден'
            }), 400

        if not promo_code or len(promo_code) < 3:
            return jsonify({
                'success': False,
                'error': 'Неверный формат промокода'
            }), 400

        # ===== 1. ЗАГРУЖАЕМ ПРОМОКОДЫ =====
        promos = load_promos()

        if promo_code not in promos:
            return jsonify({
                'success': False,
                'error': 'Промокод не найден'
            })

        promo = promos[promo_code]

        # ===== 2. ПРОВЕРЯЕМ СРОК ДЕЙСТВИЯ =====
        if 'expires_at' in promo and promo['expires_at']:
            try:
                expires_at = datetime.fromisoformat(promo['expires_at'])
                if datetime.now() > expires_at:
                    return jsonify({
                        'success': False,
                        'error': 'Промокод истек'
                    })
            except:
                pass

        # ===== 3. ПРОВЕРЯЕМ ЛИМИТ ИСПОЛЬЗОВАНИЙ =====
        max_uses = promo.get('max_uses', 1)
        used_count = promo.get('used_count', 0)

        if max_uses is not None and used_count >= max_uses:
            return jsonify({
                'success': False,
                'error': 'Промокод уже использован максимальное количество раз'
            })

        # ===== 4. ПРОВЕРЯЕМ НЕ ИСПОЛЬЗОВАЛ ЛИ УЖЕ ПОЛЬЗОВАТЕЛЬ =====
        used_by = promo.get('used_by', [])
        if user_id in used_by:
            return jsonify({
                'success': False,
                'error': 'Вы уже использовали этот промокод'
            })

        # ===== 5. НАЧИСЛЯЕМ НАГРАДУ =====
        reward = float(promo.get('reward', 0))

        if reward <= 0:
            return jsonify({
                'success': False,
                'error': 'Неверная сумма награды'
            })

        # Обновляем баланс пользователя
        balance_result = update_user_balance(
            user_id,
            reward,
            f'Промокод {promo_code}',
            'Начисление'
        )

        if not balance_result['success']:
            return jsonify({
                'success': False,
                'error': 'Ошибка начисления средств'
            }), 500

        # ===== 6. ДОБАВЛЯЕМ ВЕДЖЕР В 5 РАЗ БОЛЬШЕ =====
        vager_amount = reward * 5  # ← В 5 РАЗ БОЛЬШЕ!
        update_vager(user_id, vager_amount)
        print(f"💰 Веджер +{vager_amount:.2f} (промокод: {reward:.2f} × 5)")

        # ===== 7. ОБНОВЛЯЕМ ДАННЫЕ ПРОМОКОДА =====
        promo['used_count'] = used_count + 1
        promo['used_by'] = used_by + [user_id]
        promo['last_used_at'] = datetime.now().isoformat()

        promos[promo_code] = promo
        save_promos(promos)

        # ===== 8. ЛОГГИРУЕМ =====
        write_log('info', f'Активирован промокод {promo_code}',
                  data={
                      'user_id': user_id,
                      'reward': reward,
                      'vager_added': vager_amount,
                      'new_balance': balance_result['new_balance']
                  })

        # ===== 9. ВОЗВРАЩАЕМ ОТВЕТ =====
        return jsonify({
            'success': True,
            'reward': reward,
            'vager_added': vager_amount,  # ← ДОБАВЛЯЕМ В ОТВЕТ
            'new_balance': balance_result['new_balance'],
            'message': f'Промокод активирован! +{reward:.2f} GRAM, +{vager_amount:.2f} веджера'
        })

    except Exception as e:
        print(f"❌ Ошибка активации промокода: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Внутренняя ошибка сервера'
        }), 500

@app.route('/games/Batl/lobby/<lobby_hash>')
def game_batl_lobby(lobby_hash):
    """Страница игры для лобби (после сбора всех игроков)"""
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    user_id = request.args.get('user_id')

    # Проверяем, существует ли лобби
    data = load_pve_lobbies()
    lobby = None
    for l in data['lobbies']:
        if l['hash'] == lobby_hash:
            lobby = l
            break

    if not lobby:
        return "Лобби не найдено", 404

    return render_template('lobby.html',  # ← ИСПРАВЬ: game_batl.html вместо lobby.html
                           device_type=device_type,
                           user_id=user_id,
                           lobby_hash=lobby_hash)

# ========== LONG POLLING ДЛЯ PVE ЛОББИ (ОПТИМИЗИРОВАННЫЙ) ==========
@app.route('/api/pve/lobby/poll', methods=['GET'])
def poll_pve_lobby():
    """
    Long polling с версионированием.
    Клиент отправляет текущую версию, сервер ждёт изменения.
    """
    try:
        lobby_hash = request.args.get('hash')
        client_version = request.args.get('version', 0, type=int)

        if not lobby_hash:
            return jsonify({'error': 'No hash'}), 400

        timeout = 25  # Максимальное время ожидания
        start_time = time.time()
        last_lobby = None  # ← СОХРАНЯЕМ ПОСЛЕДНЕЕ СОСТОЯНИЕ

        while time.time() - start_time < timeout:
            # Загружаем лобби
            data = load_pve_lobbies()
            lobby = None
            for l in data['lobbies']:
                if l['hash'] == lobby_hash:
                    lobby = l
                    break

            if not lobby:
                return jsonify({'error': 'Lobby not found'}), 404

            last_lobby = lobby  # ← ЗАПОМИНАЕМ

            # Если версия изменилась — возвращаем обновлённые данные
            current_version = lobby.get('version', 0)
            if current_version > client_version:
                return jsonify(lobby)

            # Если лобби завершено — возвращаем
            if lobby.get('status') == 'finished':
                return jsonify(lobby)

            # Ждём 500 мс перед следующей проверкой
            time.sleep(0.5)

        # Таймаут — возвращаем последнее известное состояние
        if last_lobby:
            return jsonify(last_lobby)
        else:
            return jsonify({'error': 'Lobby not found'}), 404

    except Exception as e:
        print(f"❌ Ошибка в poll_pve_lobby: {e}")
        return jsonify({'error': str(e)}), 500

# ========== СОХРАНЕНИЕ РЕЗУЛЬТАТОВ ХОДОВ В BATL ==========
@app.route('/api/pve/game/save_move', methods=['POST'])
def save_batl_move():
    try:
        data = request.json
        lobby_hash = data.get('lobby_hash')
        user_id = str(data.get('user_id'))
        game_name = data.get('game_name')
        result = data.get('result')
        score = data.get('score')
        timestamp = data.get('timestamp', time.time())

        if not lobby_hash or not user_id:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        # ===== 1. ЗАГРУЖАЕМ ДАННЫЕ =====
        lobbies_data = load_pve_lobbies()

        # ===== 2. ИЩЕМ ЛОББИ =====
        lobby = None
        lobby_index = -1
        for i, l in enumerate(lobbies_data['lobbies']):
            if l['hash'] == lobby_hash:
                lobby = l
                lobby_index = i
                break

        if not lobby:
            print("❌ ЛОББИ НЕ НАЙДЕНО!")
            return jsonify({'success': False, 'error': 'Лобби не найдено'}), 404

        games_queue = lobby.get('games_queue', [])

        # ===== 3. ПРОВЕРЯЕМ, ЧТО ИГРЫ ЕСТЬ =====
        if not games_queue:
            return jsonify({'success': False, 'error': 'Нет игр в очереди'}), 400

        # ===== 4. РАБОТАЕМ С results =====
        if 'results' not in lobby:
            lobby['results'] = {}

        # Инициализируем массив для пользователя
        if user_id not in lobby['results']:
            lobby['results'][user_id] = []
        elif isinstance(lobby['results'][user_id], dict):
            if 'moves' in lobby['results'][user_id]:
                lobby['results'][user_id] = lobby['results'][user_id]['moves']
            else:
                lobby['results'][user_id] = []
        elif not isinstance(lobby['results'][user_id], list):
            lobby['results'][user_id] = []

        user_moves = lobby['results'][user_id]
        games_played = len(user_moves)

        # ===== 5. ПРОВЕРЯЕМ, НЕ ВСЕ ЛИ ИГРЫ СЫГРАНЫ =====
        if games_played >= len(games_queue):
            return jsonify({
                'success': False,
                'error': 'Все игры уже сыграны',
                'completed': True
            }), 400

        # ===== 6. ПРОВЕРЯЕМ ОЧЕРЕДНОСТЬ ИГР =====
        expected_game = games_queue[games_played]

        if game_name != expected_game:
            return jsonify({
                'success': False,
                'error': f'Сейчас должна быть игра {expected_game}, а ты кинул {game_name}',
                'expected_game': expected_game,
                'your_game': game_name
            }), 400

        # ===== 7. ПРОВЕРКА НА ДУБЛИКАТ =====
        if user_moves:
            last_move = user_moves[-1]
            if abs(last_move.get('timestamp', 0) - timestamp) < 2:
                # Вычисляем общий счет
                total_score = sum(m.get('score', 0) for m in user_moves)
                return jsonify({
                    'success': True,
                    'total_score': total_score,
                    'games_played': len(user_moves),
                    'completed': len(user_moves) >= len(games_queue),
                    'duplicate': True
                })

        # ===== 8. ДОБАВЛЯЕМ ХОД =====
        user_moves.append({
            'game': game_name,
            'result': result,
            'score': score,
            'timestamp': timestamp
        })

        # ===== 9. ВЫЧИСЛЯЕМ ОБЩИЙ СЧЕТ ИГРОКА =====
        last_score = user_moves[-1].get('score', 0) if user_moves else 0
        games_played = len(user_moves)
        completed = games_played >= len(games_queue)

        # ===== 10. СОБИРАЕМ СЧЕТА ВСЕХ ИГРОКОВ =====
        all_scores = {}
        for player_id, moves in lobby['results'].items():
            if isinstance(moves, list) and moves:
                last_score_player = moves[-1].get('score', 0)
                all_scores[player_id] = {
                    'total_score': last_score_player,
                    'moves_count': len(moves),
                    'completed': len(moves) >= len(games_queue) if games_queue else False
                }
            else:
                all_scores[player_id] = {
                    'total_score': 0,
                    'moves_count': 0,
                    'completed': False
                }

        # ===== 11. УВЕЛИЧИВАЕМ ВЕРСИЮ И СОХРАНЯЕМ =====
        lobby['version'] = lobby.get('version', 0) + 1
        lobbies_data['lobbies'][lobby_index] = lobby
        save_pve_lobbies(lobbies_data)

        # ===== 12. ОТПРАВЛЯЕМ ОБНОВЛЕНИЕ ЧЕРЕЗ WEBSOCKET =====
        username = 'Игрок'
        for player in lobby.get('players', []):
            if str(player.get('user_id')) == user_id:
                username = player.get('username', 'Игрок')
                if username.startswith('@'):
                    username = username[1:]
                break

        result_str = str(result) if result is not None else ''

        # Определяем GIF для результата
        gif_url = ''
        if game_name == 'Кегли' or game_name == 'Batl':
            if result_str.isdigit():
                gif_url = f'/sticer/game/gegli_{result_str}.webp'
            else:
                gif_url = '/sticer/game/gegli_og.gif'
        elif game_name == 'Дартс':
            if result_str.isdigit():
                gif_url = f'/sticer/game/dar_{result_str}.webp'
            else:
                gif_url = '/sticer/game/dar_og.gif'
        elif game_name == 'Кости':
            if result_str.isdigit():
                gif_url = f'/sticer/game/kub_{result_str}.webp'
            else:
                gif_url = '/sticer/game/kub_og.gif'

        # Отправляем через Socket.IO
        socketio.emit('move_made', {
            'user_id': user_id,
            'username': username,
            'game_name': game_name,
            'result': result,
            'score': score,
            'total_score': last_score,
            'gif_url': gif_url,
            'is_completed': completed,
            'lobby_data': lobby,
            'timestamp': timestamp,
            'all_scores': all_scores
        }, room=lobby_hash)

        print(f'🎮 {username} сделал ход: {game_name} -> {result} (счет: {score}, всего: {last_score})')

        # ===== 13. ПРОВЕРЯЕМ, НЕ ЗАКОНЧИЛАСЬ ЛИ ИГРА =====
        all_players_completed = True
        for player in lobby.get('players', []):
            player_id = str(player.get('user_id'))
            if player_id in lobby['results']:
                moves = lobby['results'][player_id]
                if isinstance(moves, list):
                    if len(moves) < len(games_queue):
                        all_players_completed = False
                        break
                else:
                    all_players_completed = False
                    break
            else:
                all_players_completed = False
                break

        if all_players_completed and len(lobby.get('players', [])) > 0:
            # ===== ОПРЕДЕЛЯЕМ ВСЕХ ПОБЕДИТЕЛЕЙ =====
            max_score = -1
            winners = []

            for player_id, score_data in all_scores.items():
                if score_data['total_score'] > max_score:
                    max_score = score_data['total_score']
                    winners = [player_id]
                elif score_data['total_score'] == max_score:
                    winners.append(player_id)

            # Находим имена победителей
            winner_names = []
            for player in lobby.get('players', []):
                if str(player.get('user_id')) in winners:
                    name = player.get('username', 'Игрок')
                    if name.startswith('@'):
                        name = name[1:]
                    winner_names.append(name)

            # Определяем, ничья или нет
            is_draw = len(winners) > 1

            # ===== ВЫЧИСЛЯЕМ БАНК И КОМИССИЮ =====
            bet_amount = float(lobby.get('bet_amount', 1.0))
            player_count = len(lobby.get('players', []))
            total_bank = bet_amount * player_count

            from config import COMA
            commission_percent = lobby.get('commission', COMA)

            # ✅ ПРАВИЛЬНЫЙ РАСЧЕТ ДЛЯ РАЗДЕЛЬНОЙ ПОБЕДЫ
            winners_count = len(winners)
            losers_count = player_count - winners_count
            profit = losers_count * bet_amount  # ← ПРИБЫЛЬ = СТАВКИ ПРОИГРАВШИХ
            commission = profit * (commission_percent / 100)  # ← КОМИССИЯ С ПРИБЫЛИ
            bank_after_commission = total_bank - commission

            if not is_draw:
                for player in lobby.get('players', []):
                    player_id = player.get('user_id')
                    is_winner = str(player_id) in winners if winners else False

                    if is_winner:
                        if len(winners) > 1:
                            split_amount = bank_after_commission / len(winners)
                            win_amount = split_amount - bet_amount
                            # ✅ ЗАПИСЬ В ИСТОРИЮ
                            add_history_record(
                                player_id,
                                win_amount,
                                'GRAM',
                                'Batl',
                                '',
                                f'Выигрыш|{lobby_hash[:6]}'
                            )
                            # ✅ СРАЗУ ОБНОВЛЯЕМ VAGER
                            update_vager(player_id, -bet_amount)
                        else:
                            win_amount = bank_after_commission - bet_amount
                            # ✅ ЗАПИСЬ В ИСТОРИЮ
                            add_history_record(
                                player_id,
                                win_amount,
                                'GRAM',
                                'Batl',
                                '',
                                f'Выигрыш|{lobby_hash[:6]}'
                            )
                            # ✅ СРАЗУ ОБНОВЛЯЕМ VAGER
                            update_vager(player_id, -bet_amount)
                    else:
                        # ✅ ЗАПИСЬ В ИСТОРИЮ (проигрыш)
                        add_history_record(
                            player_id,
                            -bet_amount,
                            'GRAM',
                            'Batl',
                            '',
                            f'Проигрыш|{lobby_hash[:6]}'
                        )
                        # ✅ СРАЗУ ОБНОВЛЯЕМ VAGER (отрицательное значение)
                        update_vager(player_id, -bet_amount)

            # ===== НАЧИСЛЯЕМ ВЫИГРЫШ =====
            if is_draw:
                # ✅ НИЧЬЯ - ВОЗВРАЩАЕМ СТАВКУ (НЕ БАНК!)
                for winner_id in winners:
                    update_user_balance(
                        winner_id,
                        bet_amount,  # ← ВОЗВРАЩАЕМ ТОЛЬКО СТАВКУ!
                        f'Ничья в Batl (лобби {lobby_hash[:6]})',
                        skip_history=True
                    )
            else:
                # ✅ ЕСТЬ ПОБЕДИТЕЛЬ - С КОМИССИЕЙ
                save_commission_safe('pvp_kub', commission)

                if len(winners) > 1:
                    # Разделенная победа
                    split_amount = bank_after_commission / len(winners)
                    for winner_id in winners:
                        update_user_balance(
                            winner_id,
                            split_amount,  # ← ПОЛНАЯ СУММА (банк / победители)
                            f'Победа в Batl  {lobby_hash[:6]}',
                            skip_history=True
                        )
                else:
                    # Единственный победитель
                    winner_id = winners[0]
                    update_user_balance(
                        winner_id,
                        bank_after_commission,  # ← ПОЛНАЯ СУММА (весь банк минус комиссия)
                        f'Победа в Batl (лобби {lobby_hash[:6]})',
                        skip_history=True
                    )

            # Сохраняем статус лобби
            lobby['status'] = 'finished'
            lobby['winner_id'] = None if is_draw else winners[0]
            lobby['winner_name'] = ', '.join(winner_names) if is_draw else winner_names[0]
            lobby['is_draw'] = is_draw
            lobby['finished_at'] = time.time()

            # ===== СОБИРАЕМ РЕЗУЛЬТАТЫ ИГРОКОВ =====
            players_results = {}
            for player in lobby.get('players', []):
                player_id = str(player.get('user_id'))
                username_player = player.get('username', 'Игрок')
                if username_player.startswith('@'):
                    username_player = username_player[1:]

                score_data = all_scores.get(player_id, {})
                score_total = score_data.get('total_score', 0)
                is_winner = (player_id in winners) if winners else False

                players_results[player_id] = {
                    'username': username_player,
                    'score': score_total,
                    'is_winner': is_winner
                }

            # Сохраняем
            lobbies_data['lobbies'][lobby_index] = lobby
            save_pve_lobbies(lobbies_data)

            # ===== ОТПРАВЛЯЕМ СОБЫТИЕ О ЗАВЕРШЕНИИ =====
            socketio.emit('game_finished', {
                'lobby_hash': lobby_hash,
                'winner_id': None if is_draw else winners[0],
                'winner_name': ', '.join(winner_names) if is_draw else winner_names[0],
                'winner_names': winner_names,
                'is_draw': is_draw,
                'winners_count': len(winners),
                'all_scores': all_scores,
                'games_queue': games_queue,
                'players_results': players_results,
                'lobby_data': lobby,
                'commission': commission_percent,
                'bank_after_commission': bank_after_commission if not is_draw else total_bank
            }, room=lobby_hash)

        # ===== 14. ВОЗВРАЩАЕМ ОТВЕТ =====
        return jsonify({
            'success': True,
            'total_score': last_score,
            'games_played': games_played,
            'completed': completed,
            'all_scores': all_scores,
            'version': lobby['version']
        })

    except Exception as e:
        print(f"❌ Ошибка сохранения хода: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/staking/data', methods=['GET'])
def get_staking_data():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id'}), 400

    # ===== 1. ПОЛУЧАЕМ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ =====
    user_data = get_staking_user(user_id)
    user_points = user_data.get('points', 0)
    staked_balance = user_data.get('gram', 0)
    created_at = user_data.get('created_at')

    # ===== 2. ЗАГРУЖАЕМ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ СО СТЕЙКИНГОМ =====
    staking_file = os.path.join('data', 'staking.json')
    total_points = 0

    if os.path.exists(staking_file):
        with open(staking_file, 'r', encoding='utf-8') as f:
            all_staking = json.load(f)

        # Суммируем очки всех пользователей
        for user_id_str, data in all_staking.items():
            total_points += data.get('points', 0)

    # ===== 3. ЗАГРУЖАЕМ STATISTIK ДЛЯ staging =====
    stat_file = os.path.join('data', 'statistik.json')
    staging = 0

    if os.path.exists(stat_file):
        with open(stat_file, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        staging = stats.get('staging', 0)

    # ===== 4. РАССЧИТЫВАЕМ НАГРАДУ =====
    reward = 0
    if total_points > 0 and staging > 0:
        reward = (user_points / total_points) * staging
        reward = round(reward, 2)

    return jsonify({
        'staked_balance': staked_balance,
        'points': user_points,
        'reward': reward,
        'created_at': created_at
        # ← УБРАЛИ total_points и staging
    })


@app.route('/api/staking/unstake', methods=['POST'])
def unstake():
    try:
        data = request.json
        user_id = data.get('user_id')

        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Пользователь не найден'
            }), 400

        # ===== 1. ПОЛУЧАЕМ ДАННЫЕ СТЕЙКИНГА =====
        staking_data = get_staking_user(user_id)
        amount = staking_data.get('gram', 0)
        created_at = staking_data.get('created_at')

        print(f"📊 Стейкинг пользователя {user_id}:")
        print(f"   💰 Сумма: {amount}")
        print(f"   🕐 Дата создания: {created_at}")

        # ===== 2. ПРОВЕРЯЕМ, ЕСТЬ ЛИ СТЕЙКИНГ =====
        if amount <= 0:
            return jsonify({
                'success': False,
                'error': 'У вас нет застейканных средств',
                'code': 'NO_STAKE'
            }), 400

        # ===== 3. ПРОВЕРЯЕМ ВРЕМЯ =====
        if not created_at:
            return jsonify({
                'success': False,
                'error': 'Ошибка: не удалось определить дату стейкинга. Обратитесь в поддержку.',
                'code': 'NO_DATE'
            }), 400

        try:
            # Парсим дату из staking.json
            if 'Z' in created_at:
                created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                created_date = datetime.fromisoformat(created_at)

            now = datetime.now(timezone.utc)
            diff_seconds = (now - created_date).total_seconds()
            diff_days = diff_seconds / (60 * 60 * 24)

            print(f"   📅 Создан: {created_date}")
            print(f"   📅 Сейчас: {now}")
            print(f"   📊 Прошло дней: {diff_days:.2f}")

            # Проверка, что дата не в будущем (защита от подделки)
            if diff_seconds < 0:
                return jsonify({
                    'success': False,
                    'error': 'Некорректная дата стейкинга. Обратитесь в поддержку.',
                    'code': 'INVALID_DATE'
                }), 400

            # Проверка 7 дней
            if diff_days < 7:
                remaining_days = int(7 - diff_days)
                remaining_hours = int((7 - diff_days) * 24) % 24

                # Формируем сообщение
                if remaining_days > 0:
                    time_msg = f'{remaining_days} дн.'
                    if remaining_hours > 0:
                        time_msg += f' {remaining_hours} ч.'
                else:
                    time_msg = f'{remaining_hours} ч.'

                # Дата, когда станет доступно
                unlock_date = created_date + timedelta(days=7)
                unlock_date_str = unlock_date.strftime('%d.%m.%Y')

                return jsonify({
                    'success': False,
                    'error': f'Вывод доступен через {time_msg}',
                    'code': 'TOO_EARLY',
                    'remaining_days': remaining_days,
                    'remaining_hours': remaining_hours,
                    'unlock_date': unlock_date_str
                }), 400

        except Exception as e:
            print(f"❌ Ошибка парсинга даты: {e}")
            return jsonify({
                'success': False,
                'error': 'Ошибка проверки даты стейкинга. Обратитесь в поддержку.',
                'code': 'PARSE_ERROR'
            }), 400

        # ===== 4. ВСЁ ХОРОШО — ВЫПОЛНЯЕМ ВЫВОД =====
        print(f"✅ Вывод разрешён для пользователя {user_id}")

        # Начисляем на баланс
        result = update_user_balance(
            user_id,
            amount,
            'Возврат из стейкинга',
            'Успешно'
        )

        if not result['success']:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Ошибка начисления средств')
            }), 500

        # Обнуляем стейк
        update_staking_gram(user_id, -amount)

        print(f"✅ Вывод выполнен: +{amount} GRAM для пользователя {user_id}")

        return jsonify({
            'success': True,
            'amount': amount,
            'message': f'✅ Выведено {amount:.2f} GRAM'
        })

    except Exception as e:
        print(f"❌ Ошибка unstake: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Внутренняя ошибка сервера. Попробуйте позже.'
        }), 500

@app.route('/data/ban.json')
def serve_ban_json():
    """Возвращает файл ban.json для проверки бана"""
    try:
        ban_file = os.path.join(BASE_DIR, 'data', 'ban.json')
        if os.path.exists(ban_file):
            return send_from_directory(os.path.dirname(ban_file), 'ban.json')
        else:
            # Если файл не существует, возвращаем пустой список
            return jsonify({"banned_users": []})
    except Exception as e:
        print(f"❌ Ошибка загрузки ban.json: {e}")
        return jsonify({"banned_users": []})
# ========== Обычные страницы ==========
@app.route('/home')
def home_full():
    user_agent = request.headers.get('User-Agent', '')
    device_type = detect_device(user_agent)
    return render_template('home.html', device_type=device_type)
# ========== SOCKET.IO ОБРАБОТЧИКИ ==========
@socketio.on('connect')
def handle_connect():
    print(f'✅ Клиент подключился: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'❌ Клиент отключился: {request.sid}')
    # Удаляем из всех комнат
    for lobby_hash, room_data in lobby_rooms.items():
        if request.sid in room_data.get('players', set()):
            room_data['players'].remove(request.sid)

@socketio.on('join_lobby')
def handle_join_lobby(data):
    """Игрок подключается к лобби"""
    lobby_hash = data.get('lobby_hash')
    user_id = data.get('user_id')
    username = data.get('username', 'Player')

    if not lobby_hash:
        return

    # Создаем комнату если не существует
    if lobby_hash not in lobby_rooms:
        lobby_rooms[lobby_hash] = {'players': set(), 'last_data': {}}

    # Добавляем в комнату
    join_room(lobby_hash)
    lobby_rooms[lobby_hash]['players'].add(request.sid)

    print(f'👤 {username} присоединился к лобби {lobby_hash}')

    # Если есть последние данные — отправляем новому игроку
    if lobby_rooms[lobby_hash].get('last_data'):
        emit('move_made', lobby_rooms[lobby_hash]['last_data'], room=request.sid)

    # Отправляем подтверждение
    emit('joined', {'lobby_hash': lobby_hash, 'user_id': user_id}, room=request.sid)

@socketio.on('move_made')
def handle_move_made(data):
    """Игрок сделал ход — отправляем всем в лобби"""
    lobby_hash = data.get('lobby_hash')
    user_id = data.get('user_id')
    username = data.get('username', 'Player')
    game_name = data.get('game_name')
    result = data.get('result')
    score = data.get('score')
    total_score = data.get('total_score', 0)
    gif_url = data.get('gif_url', '')
    is_completed = data.get('is_completed', False)
    lobby_data = data.get('lobby_data')  # ← ВАЖНО: передаем полные данные лобби

    print(f'🎮 {username} сделал ход: {game_name} -> {result} (счет: {score}, всего: {total_score})')

    # Сохраняем последние данные
    if lobby_hash in lobby_rooms:
        lobby_rooms[lobby_hash]['last_data'] = {
            'user_id': user_id,
            'username': username,
            'game_name': game_name,
            'result': result,
            'score': score,
            'total_score': total_score,
            'gif_url': gif_url,
            'is_completed': is_completed,
            'lobby_data': lobby_data,  # ← ПЕРЕДАЕМ ВСЕ ДАННЫЕ ЛОББИ
            'timestamp': data.get('timestamp', time.time())
        }

    # Отправляем ВСЕМ в лобби (включая отправителя)
    emit('move_made', {
        'user_id': user_id,
        'username': username,
        'game_name': game_name,
        'result': result,
        'score': score,
        'total_score': total_score,
        'gif_url': gif_url,
        'is_completed': is_completed,
        'lobby_data': lobby_data,  # ← ПЕРЕДАЕМ ВСЕ ДАННЫЕ ЛОББИ
        'timestamp': data.get('timestamp', time.time())
    }, room=lobby_hash)

@socketio.on('leave_lobby')
def handle_leave_lobby(data):
    lobby_hash = data.get('lobby_hash')
    if lobby_hash and lobby_hash in lobby_rooms:
        if request.sid in lobby_rooms[lobby_hash]['players']:
            lobby_rooms[lobby_hash]['players'].remove(request.sid)
        leave_room(lobby_hash)
        print(f'👋 Игрок покинул лобби {lobby_hash}')

def get_commission(game_type):
    """БЫСТРО получает сумму комиссии из statistik.json"""
    if not os.path.exists(STAT_FILE):
        recalculate_statistik()

    try:
        with open(STAT_FILE, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        return stats.get(game_type, 0.0)
    except:
        stats = recalculate_statistik()
        return stats.get(game_type, 0.0)

# ===== ДОБАВЛЯЕМ ОБРАБОТЧИК ДЛЯ game_finished =====
@socketio.on('game_finished')
def handle_game_finished(data):
    """Обработчик события завершения игры"""
    lobby_hash = data.get('lobby_hash')
    winner_name = data.get('winner_name', 'Игрок')
    players_results = data.get('players_results', {})

    print(f'🏁 Игра в лобби {lobby_hash} завершена! Победитель: {winner_name}')

    # Отправляем событие всем в комнате
    emit('game_finished', {
        'lobby_hash': lobby_hash,
        'winner_id': data.get('winner_id'),
        'winner_name': winner_name,
        'all_scores': data.get('all_scores', {}),
        'games_queue': data.get('games_queue', []),
        'players_results': players_results
    }, room=lobby_hash)

# ========== ХРАНИЛИЩЕ ДЛЯ ИГР В МИНЫ ==========
MINES_GAMES_FILE = os.path.join(BASE_DIR, 'data', 'mines_games.json')

def load_mines_games():
    if not os.path.exists(MINES_GAMES_FILE):
        return {}
    try:
        with open(MINES_GAMES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_mines_games(data):
    os.makedirs(os.path.dirname(MINES_GAMES_FILE), exist_ok=True)
    with open(MINES_GAMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def generate_game_hash():
    import uuid
    return uuid.uuid4().hex[:16]

# ========== 1. СОЗДАНИЕ ПОЛЯ ==========
@app.route('/api/mines/create_board', methods=['POST'])
def mines_create_board():
    try:
        data = request.json
        user_id = data.get('user_id')
        mines_count = data.get('mines_count', 3)
        bet_amount = data.get('bet_amount', 0)

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        if bet_amount <= 0:
            return jsonify({'success': False, 'error': 'Invalid bet_amount'}), 400

        # ===== 1. СПИСЫВАЕМ СТАВКУ =====
        balance_result = update_user_balance(
            user_id,
            -bet_amount,
            f'Ставка в Майнсвипер',
            'Игра',
            skip_history=True
        )

        if not balance_result['success']:
            return jsonify({
                'success': False,
                'error': 'Недостаточно средств или ошибка списания'
            }), 400


        mines_count = max(1, min(24, mines_count))
        TOTAL_CELLS = 25

        # Генерируем уникальный хеш игры
        game_hash = generate_game_hash()

        # Генерируем сид
        seed = str(int(time.time() * 1000)) + str(random.randint(1000, 9999))

        # 1D массив: 0 = безопасно, 1 = мина
        board = [0] * TOTAL_CELLS

        # Расставляем мины
        seed_num = 0
        for ch in seed:
            seed_num += ord(ch)

        mines_placed = 0
        index = 0
        while mines_placed < mines_count:
            pseudo_random = (seed_num + index * 7919) % TOTAL_CELLS
            if board[pseudo_random] != 1:
                board[pseudo_random] = 1
                mines_placed += 1
            index += 1
            seed_num = (seed_num * 16807) % 2147483647

        # Сохраняем игру в файл
        games = load_mines_games()
        games[game_hash] = {
            'user_id': user_id,
            'seed': seed,
            'board': board,
            'mines_count': mines_count,
            'bet_amount': bet_amount,
            'multiplier': 1.0,
            'win_amount': 0,
            'is_win': False,
            'revealed': [0] * TOTAL_CELLS,
            'game_active': True,
            'created_at': time.time()
        }
        save_mines_games(games)

        # ================================================================
        # ✅ ВОЗВРАЩАЕМ ТОЛЬКО НЕОБХОДИМОЕ (БЕЗ board И seed!)
        # ================================================================
        return jsonify({
            'success': True,
            'game_hash': game_hash,
            'mines_count': mines_count,
            'total_cells': TOTAL_CELLS,
            'bet_amount': bet_amount,
            'new_balance': balance_result.get('new_balance', 0)
        })

    except Exception as e:
        print(f"❌ Ошибка mines_create_board: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== 2. ПРОВЕРКА КЛЕТКИ ==========
@app.route('/api/mines/reveal_cell', methods=['POST'])
def mines_reveal_cell():
    try:
        data = request.json
        game_hash = data.get('game_hash')
        user_id = data.get('user_id')
        cell_index = data.get('cell_index')

        if not game_hash:
            return jsonify({'success': False, 'error': 'Missing game_hash'}), 400

        if not user_id:
            return jsonify({'success': False, 'error': 'Missing user_id'}), 400

        if cell_index is None:
            return jsonify({'success': False, 'error': 'Missing cell_index'}), 400

        if cell_index < 0 or cell_index > 24:
            return jsonify({'success': False, 'error': 'Invalid cell index'}), 400

        games = load_mines_games()

        if game_hash not in games:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        game = games[game_hash]

        if str(game.get('user_id')) != str(user_id):
            return jsonify({
                'success': False,
                'error': 'Access denied: this game belongs to another user',
                'code': 'ACCESS_DENIED'
            }), 403

        if not game.get('game_active', False):
            return jsonify({'success': False, 'error': 'Game is not active'}), 400

        if game['revealed'][cell_index] == 1:
            return jsonify({
                'success': True,
                'already_revealed': True,
                'has_mine': game['board'][cell_index] == 1,
                'cell_index': cell_index
            })

        # Открываем клетку
        game['revealed'][cell_index] = 1

        has_mine = game['board'][cell_index] == 1

        # ===== РАССЧИТЫВАЕМ ТЕКУЩИЙ МНОЖИТЕЛЬ =====
        revealed_count = sum(game['revealed'])
        mines_count = game['mines_count']

        if revealed_count == 0:
            multiplier = 1.0
        else:
            multiplier = 1.0
            for i in range(revealed_count):
                multiplier *= (25 - i) / (25 - i - mines_count)
            multiplier *= 0.948
            multiplier = max(1.0, round(multiplier, 2))

        game['multiplier'] = multiplier
        bet_amount = game['bet_amount']
        # ================================================================
        # 1️⃣ ПОПАЛИ В МИНУ — ПРОИГРЫШ
        # ================================================================
        if has_mine:
            game['game_active'] = False
            game['is_win'] = False
            game['win_amount'] = 0
            save_mines_games(games)
            save_commission_safe('mine', bet_amount)
            update_vager(user_id, -bet_amount)
            try:
                from functions import save_minesweeper_game as save_game

                board_2d = []
                for row in range(5):
                    row_data = []
                    for col in range(5):
                        idx = row * 5 + col
                        row_data.append(game['board'][idx])
                    board_2d.append(row_data)

                save_game(
                    user_id,
                    board_2d,
                    game.get('seed', ''),
                    bet_amount,
                    -bet_amount,
                    False,
                    multiplier
                )
            except Exception as e:
                print(f"⚠️ Ошибка сохранения проигрыша: {e}")

            del games[game_hash]
            save_mines_games(games)

            # ✅ ВОЗВРАЩАЕМ ТОЛЬКО НЕОБХОДИМОЕ
            mine_positions = [i for i, val in enumerate(game['board']) if val == 1]

            return jsonify({
                'success': True,
                'has_mine': True,
                'cell_index': cell_index,
                'mine_positions': mine_positions  # ← ТОЛЬКО ИНДЕКСЫ МИН!
            })

        # ================================================================
        # 2️⃣ ПРОВЕРЯЕМ ПОБЕДУ
        # ================================================================
        total_cells = 25
        safe_cells = total_cells - mines_count
        all_revealed = revealed_count >= safe_cells

        if all_revealed:
            # 🏆 ПОБЕДА
            win_amount = bet_amount * multiplier
            profit = win_amount - bet_amount

            # ================================================================
            # ✅ НАЧИСЛЯЕМ ВЫИГРЫШ НА БАЛАНС (ДОБАВЛЕНО!)
            # ================================================================
            try:
                balance_result = update_user_balance(
                    user_id,
                    win_amount,
                    f'Победа в Майнсвипер (x{multiplier:.2f})',
                    'Выигрыш',
                    skip_history=True
                )
                print(f"💰 Начислен выигрыш {win_amount:.2f} для пользователя {user_id}")
                print(f"💰 Новый баланс: {balance_result.get('new_balance', 0):.2f}")
            except Exception as e:
                print(f"❌ Ошибка начисления выигрыша: {e}")

            game['game_active'] = False
            game['is_win'] = True
            game['win_amount'] = win_amount
            save_mines_games(games)

            # ✅ СОХРАНЯЕМ В ИСТОРИЮ
            try:
                from functions import save_minesweeper_game as save_game

                board_2d = []
                for row in range(5):
                    row_data = []
                    for col in range(5):
                        idx = row * 5 + col
                        row_data.append(game['board'][idx])
                    board_2d.append(row_data)

                save_game(
                    user_id,
                    board_2d,
                    game.get('seed', ''),
                    bet_amount,
                    profit,
                    True,
                    multiplier
                )
            except Exception as e:
                print(f"⚠️ Ошибка сохранения истории: {e}")

            del games[game_hash]
            save_mines_games(games)

            return jsonify({
                'success': True,
                'has_mine': False,
                'all_revealed': True,
                'cell_index': cell_index,
                'multiplier': multiplier,
                'win_amount': win_amount,
                'profit': profit,
                'message': '🎉 ПОБЕДА! Все клетки открыты!'
            })

        # ================================================================
        # 3️⃣ ИГРА ПРОДОЛЖАЕТСЯ
        # ================================================================
        save_mines_games(games)

        return jsonify({
            'success': True,
            'has_mine': False,
            'all_revealed': False,
            'cell_index': cell_index,
            'multiplier': multiplier,
            'safe_cells_left': safe_cells - revealed_count
        })

    except Exception as e:
        print(f"❌ Ошибка mines_reveal_cell: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== 3. ЗАВЕРШИТЬ ИГРУ ==========
@app.route('/api/mines/end_game', methods=['POST'])
def mines_end_game():
    try:
        data = request.json
        game_hash = data.get('game_hash')
        user_id = data.get('user_id')

        if not game_hash:
            return jsonify({'success': False, 'error': 'No game_hash'}), 400

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        games = load_mines_games()

        if game_hash not in games:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        game = games[game_hash]

        if str(game.get('user_id')) != str(user_id):
            return jsonify({
                'success': False,
                'error': 'Access denied'
            }), 403

        if not game.get('game_active', False):
            return jsonify({'success': False, 'error': 'Game is not active'}), 400

        bet_amount = game.get('bet_amount', 0)
        multiplier = game.get('multiplier', 1.0)

        if bet_amount <= 0:
            return jsonify({'success': False, 'error': 'Invalid bet amount'}), 400

        # ================================================================
        # ✅ ПРИ ЗАВЕРШЕНИИ ИГРЫ ВСЕГДА ПОБЕДА
        # ================================================================
        win_amount = bet_amount * multiplier
        profit = win_amount - bet_amount

        # ================================================================
        # ✅ РАСЧЁТ VAGER: списываем с чистого выигрыша, но не больше ставки
        # ================================================================
        if profit > 0:
            vager_delta = -min(profit, bet_amount)
            update_vager(user_id, vager_delta)
            print(f"💰 Vager: списано {abs(vager_delta)} (profit: {profit}, bet: {bet_amount})")
        else:
            # При проигрыше Vager уже был списан при создании игры
            print(f"💰 Vager: не списывается (profit: {profit})")

        # Обновляем данные игры
        game['is_win'] = True
        game['win_amount'] = win_amount
        game['game_active'] = False
        save_mines_games(games)

        # Сохраняем комиссию
        save_commission_safe('mine', -profit)

        # ================================================================
        # ✅ НАЧИСЛЯЕМ ВЫИГРЫШ НА БАЛАНС
        # ================================================================
        balance_result = None
        if win_amount > 0:
            balance_result = update_user_balance(
                user_id,
                win_amount,
                f'Выигрыш в Майнсвипер (x{multiplier:.2f})',
                'Выигрыш',
                skip_history=False
            )
            print(f"💰 Начислен выигрыш {win_amount:.2f} для пользователя {user_id}")

        # ================================================================
        # ✅ СОХРАНЯЕМ В ИСТОРИЮ
        # ================================================================
        try:
            from functions import save_minesweeper_game as save_game

            board_2d = []
            for row in range(5):
                row_data = []
                for col in range(5):
                    idx = row * 5 + col
                    row_data.append(game['board'][idx])
                board_2d.append(row_data)

            save_game(
                user_id,
                board_2d,
                game.get('seed', ''),
                bet_amount,
                profit,
                True,
                multiplier
            )
        except Exception as e:
            print(f"⚠️ Ошибка сохранения истории: {e}")

        # ================================================================
        # ✅ УДАЛЯЕМ ИГРУ
        # ================================================================
        del games[game_hash]
        save_mines_games(games)

        return jsonify({
            'success': True,
            'multiplier': multiplier,
            'win_amount': win_amount,
            'new_balance': balance_result.get('new_balance', 0) if balance_result else 0
        })

    except Exception as e:
        print(f"❌ Ошибка mines_end_game: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== 4. ВОССТАНОВЛЕНИЕ ИГРЫ (POST) ==========
@app.route('/api/mines/get_board', methods=['POST'])
def mines_get_board():
    """
    Восстанавливает состояние игры после обновления страницы.
    Возвращает ТОЛЬКО уже открытые ячейки.
    """
    try:
        data = request.json
        game_hash = data.get('game_hash')
        user_id = data.get('user_id')

        if not game_hash:
            return jsonify({'success': False, 'error': 'No game_hash'}), 400

        if not user_id:
            return jsonify({'success': False, 'error': 'No user_id'}), 400

        games = load_mines_games()

        if game_hash not in games:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        game = games[game_hash]

        # Проверяем владельца
        if str(game.get('user_id')) != str(user_id):
            return jsonify({
                'success': False,
                'error': 'Access denied'
            }), 403

        # Проверяем, активна ли игра
        if not game.get('game_active', False):
            return jsonify({
                'success': False,
                'error': 'Game is not active',
                'game_active': False
            }), 400

        # ================================================================
        # ✅ ВОЗВРАЩАЕМ ТОЛЬКО ОТКРЫТЫЕ ЯЧЕЙКИ (revealed)
        # ================================================================
        # revealed: массив из 25 элементов (0 = скрыто, 1 = открыто)
        # board: массив из 25 элементов (0 = безопасно, 1 = мина) - НЕ ВОЗВРАЩАЕМ!

        return jsonify({
            'success': True,
            'revealed': game['revealed'],  # ← ТОЛЬКО ОТКРЫТЫЕ/СКРЫТЫЕ
            'game_active': game.get('game_active', False),
            'multiplier': game.get('multiplier', 1.0),
            'mines_count': game.get('mines_count', 0),
            'bet_amount': game.get('bet_amount', 0)
        })

    except Exception as e:
        print(f"❌ Ошибка mines_get_board: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
check_chat_subscription
# ========== ЗАПУСК СЕРВЕРА ==========
if __name__ == '__main__':
    print("=" * 50)
    print("🌐 Flask сервер запущен")
    print("📍 Адрес: http://0.0.0.0:5000")
    print("📝 Логи пишутся в файл: logs.txt")
    print(f"⚡ Режим SocketIO: {ASYNC_MODE}")
    print("=" * 50)
    try:
        # ✅ ВСЕГДА используем socketio.run() для WebSocket поддержки
        socketio.run(
            app,
            host='0.0.0.0',
            port=5000,
            debug=False,
            allow_unsafe_werkzeug=True
        )
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        print("🔄 Запуск в обычном режиме Flask...")
        try:
            app.run(host='0.0.0.0', port=5000, debug=False)
        except OSError:
            print("❌ Порт 5000 занят! Использую порт 5001...")
            app.run(host='0.0.0.0', port=5001, debug=False)