import base64
import os
import json
from datetime import datetime,timezone
from tonsdk.utils import Address
from tonsdk.contract.token.ft import JettonWallet
import requests

BAC_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(BAC_DIR)
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# ========== РЕФЕРАЛЬНАЯ СИСТЕМА ==========

REF_FILE = os.path.join(DATA_DIR, 'ref.txt')           # Готовое дерево (перезаписывается)
REF_LINKS_FILE = os.path.join(DATA_DIR, 'ref_links.txt') # Сырые связи (только дописывается)
JETTON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"

STAT_LOG_FILE = os.path.join(BASE_DIR, 'data', 'statistik_log.txt')
STAT_FILE = os.path.join(BASE_DIR, 'data', 'statistik.json')

USDT_MASTER_RAW = "0:b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe"
DESTINATION_ADDRESS = "UQCiPnG0mf7npCpHchKp_UvE2f2cWRwZZ2OLFQy2YSPqFdLI"

def build_jetton_transfer_payload(jetton_amount, user_address, query_id=0):
    try:
        # 1. ПОЛУЧАЕМ JETTON WALLET ОТПРАВИТЕЛЯ ЧЕРЕЗ TONAPI
        response = requests.get(f'https://tonapi.io/v2/accounts/{user_address}/jettons')
        data = response.json()

        usdt = None
        for jetton in data.get('balances', []):
            if jetton['jetton']['address'] == USDT_MASTER_RAW:
                usdt = jetton
                break

        if not usdt:
            raise Exception("USDT не найден на кошельке пользователя")

        jetton_wallet_sender_raw = usdt['wallet_address']['address']
        jetton_wallet_sender = Address(jetton_wallet_sender_raw)

        # 2. ПОЛУЧАЕМ JETTON WALLET ПОЛУЧАТЕЛЯ
        response_dest = requests.get(f'https://tonapi.io/v2/accounts/{DESTINATION_ADDRESS}/jettons')
        data_dest = response_dest.json()

        usdt_dest = None
        for jetton in data_dest.get('balances', []):
            if jetton['jetton']['address'] == USDT_MASTER_RAW:
                usdt_dest = jetton
                break

        if usdt_dest:
            destination_jetton_raw = usdt_dest['wallet_address']['address']
        else:
            destination_jetton_raw = DESTINATION_ADDRESS

        destination_jetton = Address(destination_jetton_raw)

        # 3. ✅ ИСПОЛЬЗУЕМ JettonWallet ДЛЯ СОЗДАНИЯ BODY
        jw = JettonWallet()

        # Создаем body для перевода
        body = jw.create_transfer_body(
            Address(DESTINATION_ADDRESS),  # куда отправляем
            int(jetton_amount)  # сумма в минимальных единицах
        )

        # 4. КОНВЕРТИРУЕМ BODY В BASE64
        cell = body.to_boc(False)
        payload_base64 = base64.b64encode(cell).decode('utf-8')

        # 5. ВОЗВРАЩАЕМ BOUNCEABLE АДРЕСА (EQ...)
        jetton_wallet_sender_bounceable = jetton_wallet_sender.to_string(True, True, False)
        destination_jetton_bounceable = destination_jetton.to_string(True, True, False)

        print(f"📌 Jetton Wallet отправителя: {jetton_wallet_sender_bounceable}")
        print(f"📌 Jetton Wallet получателя: {destination_jetton_bounceable}")

        return {
            'jetton_wallet': jetton_wallet_sender_bounceable,  # EQ...
            'payload': payload_base64,
            'jetton_amount': jetton_amount,
            'destination': destination_jetton_bounceable  # EQ...
        }

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return None

def init_ref_file():
    """Создает файлы если их нет"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(REF_LINKS_FILE):
        with open(REF_LINKS_FILE, 'w', encoding='utf-8') as f:
            pass
    if not os.path.exists(REF_FILE):
        with open(REF_FILE, 'w', encoding='utf-8') as f:
            f.write("")


def get_gram_balance(user_id):
    """Получает баланс в GRAM (ton_balance)"""
    user_id = str(user_id)

    print(f"🔍 get_gram_balance: ищем пользователя {user_id}")

    users = load_users()
    print(f"🔍 Всего пользователей в файле: {len(users)}")
    print(f"🔍 Список ID пользователей: {list(users.keys())}")

    if user_id in users:
        balance = users[user_id].get('ton_balance', 0)
        print(f"✅ Пользователь {user_id} НАЙДЕН!")
        print(f"   📊 ton_balance: {balance}")
        print(f"   📊 Полные данные: {users[user_id]}")

        if isinstance(balance, str):
            try:
                balance = float(balance.replace(',', '.'))
            except:
                balance = 0.0
        return float(balance)

    print(f"❌ Пользователь {user_id} НЕ НАЙДЕН в файле!")
    return 0.0

def add_referral(user_id, referrer_id):
    """Добавляет реферала"""
    init_ref_file()

    user_id = str(user_id)
    referrer_id = str(referrer_id)

    if user_id == referrer_id:
        return False

    # Проверяем, есть ли уже пригласитель
    user_data = get_user(user_id)
    if user_data and user_data.get('invited_by', '-') != '-':
        return False

    # Записываем кто пригласил в users.json
    update_user_field(user_id, 'invited_by', referrer_id)

    # ========== 1. ДОПИСЫВАЕМ СВЯЗЬ В ФАЙЛ СВЯЗЕЙ ==========
    with open(REF_LINKS_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{user_id}|{referrer_id}\n")

    # ========== 2. ПЕРЕСТРАИВАЕМ ДЕРЕВО ИЗ ФАЙЛА СВЯЗЕЙ ==========
    # Читаем ВСЕ связи из REF_LINKS_FILE
    connections = {}
    all_users = set()

    with open(REF_LINKS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and '|' in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    child = parts[0]
                    parent = parts[1]
                    connections[child] = parent
                    all_users.add(child)
                    all_users.add(parent)

    # Строим дерево детей
    children = {}
    for child, parent in connections.items():
        if parent not in children:
            children[parent] = []
        children[parent].append(child)

    # Находим корни (у кого нет родителя)
    all_children = set(connections.keys())
    roots = all_users - all_children
    if not roots:
        roots = all_users

    # Функция построения дерева
    def build_tree_lines(node, prefix="", is_last=True):
        lines = []
        lines.append(f"{prefix}{'└─ ' if is_last else '├─ '}{node}")
        if node in children:
            child_list = sorted(children[node])
            for i, child in enumerate(child_list):
                is_last_child = (i == len(child_list) - 1)
                new_prefix = prefix + ("    " if is_last else "│   ")
                lines.extend(build_tree_lines(child, new_prefix, is_last_child))
        return lines

    # Строим всё дерево
    tree_lines = []
    roots_list = sorted(roots)
    for i, root in enumerate(roots_list):
        is_last_root = (i == len(roots_list) - 1)
        tree_lines.extend(build_tree_lines(root, "", is_last_root))

    # Записываем готовое дерево в ref.txt
    with open(REF_FILE, 'w', encoding='utf-8') as f:
        for line in tree_lines:
            f.write(line + '\n')

    return True

def get_referral_tree():
    """Возвращает содержимое файла ref.txt"""
    init_ref_file()
    if not os.path.exists(REF_FILE):
        return "Нет рефералов"
    with open(REF_FILE, 'r', encoding='utf-8') as f:
        return f.read()

# ========== РАБОТА С ФАЙЛОМ users.json (построчно) ==========

DATA_FILE = os.path.join(DATA_DIR, 'users.json')

def update_referral_earnings(user_id, amount_change):
    user_id = str(user_id)
    # Кто пригласил?
    user = get_user(user_id)
    if not user:
        return False

    invited_by = user.get('invited_by', '-')
    if invited_by == '-' or not invited_by:
        return False

    referral_amount = abs(amount_change) * 0.1
    # Получаем текущие referral_earnings пригласившего
    referrer = get_user(invited_by)
    if not referrer:
        return False
    current = referrer.get('referral_earnings', 0.0)
    if amount_change > 0:
        new_amount = current + referral_amount
    else:
        new_amount = current - referral_amount
    # Сохраняем
    users = load_users()
    users[invited_by]['referral_earnings'] = new_amount
    save_users(users)

    return True

def init_db():
    """Создает папку и файл если не существует"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, 'mine'), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            pass  # Создаем пустой файл

def load_users():
    """Загружает всех пользователей из JSON (построчно)"""
    init_db()
    users = {}

    if not os.path.exists(DATA_FILE):
        return users

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    user_data = json.loads(line)
                    user_id = list(user_data.keys())[0]
                    users[user_id] = user_data[user_id]
                except:
                    pass
    return users

def save_users(users):
    """Сохраняет пользователей в JSON (каждый пользователь на новой строке)"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        for user_id, user_data in users.items():
            line = json.dumps({user_id: user_data}, separators=(',', ':'), ensure_ascii=False)
            f.write(line + '\n')

def add_user(user_id, username, first_name):
    users = load_users()
    user_id_str = str(user_id)

    if user_id_str in users:
        return False

    users[user_id_str] = {
        "id": user_id_str,
        "name": first_name,
        "username": username,
        "balans": 0,
        "kosh": "Не подключен",
        "lvl": 1,
        "language": "ru",
        "ton_balance": 0,
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "notifications": True,
        "total_turnover": 0,
        "record_balance": 0,
        "total_withdrawn": 0,
        "invited_by": "-",           # Кто пригласил
        "referral_earnings": 0.0,# Сумма заработка от реферало
        "vager": 0.00,
        "tame": 1.0
    }
    save_users(users)
    return True

def get_user(user_id):
    """Получает данные пользователя"""
    users = load_users()
    user_id_str = str(user_id)

    if user_id_str not in users:
        return None

    return users[user_id_str]

def update_user_stats(user_id, amount_change):
    """Обновляет статистику пользователя

    Args:
        user_id: ID пользователя
        amount_change: сумма изменения (положительная - начисление, отрицательная - списание)
    """
    users = load_users()
    user_id_str = str(user_id)

    if user_id_str not in users:
        return

    current_balance = users[user_id_str].get('ton_balance', 0)
    if isinstance(current_balance, str):
        current_balance = float(current_balance.replace(',', '.'))

    record_balance = users[user_id_str].get('record_balance', 0)
    total_withdrawn = users[user_id_str].get('total_withdrawn', 0)
    total_turnover = users[user_id_str].get('total_turnover', 0)

    # ✅ ОБНОВЛЯЕМ ОБОРОТ ТОЛЬКО ДЛЯ СТАВОК (ОТРИЦАТЕЛЬНЫЕ ИЗМЕНЕНИЯ)
    if amount_change < 0:
        total_turnover += abs(amount_change)  # Только ставки идут в оборот

    # Обновляем рекордный баланс
    if current_balance > record_balance:
        record_balance = current_balance

    # ❌ УБИРАЕМ увеличение total_withdrawn здесь
    # total_withdrawn будет увеличиваться ТОЛЬКО при подтверждении вывода

    users[user_id_str]['record_balance'] = record_balance
    users[user_id_str]['total_turnover'] = total_turnover
    # total_withdrawn НЕ меняем здесь

    save_users(users)

def update_withdrawn_stats(user_id, amount):
    """Увеличивает total_withdrawn при подтвержденном выводе"""
    users = load_users()
    user_id_str = str(user_id)

    if user_id_str not in users:
        return False

    total_withdrawn = users[user_id_str].get('total_withdrawn', 0)
    total_withdrawn += abs(amount)
    users[user_id_str]['total_withdrawn'] = total_withdrawn
    save_users(users)
    return True

def get_user_data(user_id):
    """Возвращает данные пользователя (для API)"""
    user = get_user(user_id)
    if user:
        return user
    return {
        'id': str(user_id),
        'name': 'User',
        'username': 'unknown',
        'balans': '0',
        'kosh': 'Не подключен',
        'lvl': '1',
        'language': 'ru',
        'ton_balance': '0',
        'total_turnover': 0,
        'record_balance': 0,
        'total_withdrawn': 0,
        'invited_by': '-',
        'referral_earnings': 0.0,
        'vager': 0.0,      # ✅ ДОБАВЛЕНО
        'tame': 0.0        # ✅ ДОБАВЛЕНО
    }

#================ РАбота с данными пользоватлея=============
def update_vager(user_id, amount_change):
    user = get_user(user_id)
    if not user:
        return False

    current = user.get('vager', 0.0)
    if isinstance(current, str):
        current = float(current.replace(',', '.'))

    new_vager = current + amount_change

    # ✅ НЕ ДАЕМ УЙТИ В МИНУС
    if new_vager < 0:
        new_vager = 0

    return update_user_field(user_id, 'vager', new_vager)

def get_vager(user_id):
    """Получает vager пользователя"""
    user = get_user(user_id)
    if user:
        return user.get('vager', 0.0)
    return 0.0

def update_tame(user_id, amount_change):
    user = get_user(user_id)
    if not user:
        return False

    current = user.get('tame', 0.0)
    if isinstance(current, str):
        current = float(current.replace(',', '.'))

    new_tame = current + amount_change

    # ✅ НЕ ДАЕМ УЙТИ В МИНУС
    if new_tame < 0:
        new_tame = 0

    return update_user_field(user_id, 'tame', new_tame)

def get_tame(user_id):
    """Получает tame пользователя"""
    user = get_user(user_id)
    if user:
        return user.get('tame', 0.0)
    return 0.0

def update_user_field(user_id, field, value):
    """Обновляет конкретное поле пользователя"""
    users = load_users()
    print(users)
    print(field)
    print(value)
    user_id_str = str(user_id)

    if user_id_str not in users:
        return False

    users[user_id_str][field] = value
    save_users(users)
    return True

def update_balans(user_id, new_balans):
    """Обновляет баланс пользователя"""
    return update_user_field(user_id, 'balans', new_balans)

def update_kosh(user_id, wallet):
    """Обновляет кошелек пользователя"""
    return update_user_field(user_id, 'kosh', wallet)

def update_lvl(user_id, new_lvl):
    """Обновляет уровень пользователя"""
    return update_user_field(user_id, 'lvl', new_lvl)

def update_language(user_id, language):
    """Обновляет язык пользователя"""
    return update_user_field(user_id, 'language', language)

def save_minesweeper_game(user_id, board, mines_hash, bet_amount, win_amount, is_win, multiplier):
    """Сохраняет игру в общий файл по дням и добавляет хеш в историю пользователя"""
    init_db()

    now = datetime.now()
    date_str = now.strftime('%d_%m_%Y')  # Формат: 10_06_2026
    time_str = now.strftime('%H:%M:%S')

    # ========== 1. СОХРАНЯЕМ В ОБЩИЙ ФАЙЛ ПО ДНЯМ ==========
    daily_file = os.path.join(DATA_DIR, 'mine', f'{date_str}.txt')

    # Преобразуем board в читаемый формат
    board_lines = []
    for row in board:
        row_str = ''
        for cell in row:
            if cell == 1 or cell == 'mine':
                row_str += '[💣]'
            else:
                row_str += '[🔷]'
        board_lines.append(row_str)

    # Записываем в общий файл (компактно, без лишнего)
    with open(daily_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'=' * 50}\n")
        f.write(f"[{time_str}] Пользователь: {user_id}\n")
        f.write(f"Хеш: {mines_hash}\n")
        f.write(
            f"Ставка: {bet_amount:.2f} GRAM | Результат: {'WIN' if is_win else 'LOSS'} | Множитель: x{multiplier:.2f}\n")
        if is_win:
            f.write(f"Выигрыш: {win_amount:.2f} TON\n")
        else:
            f.write(f"Проигрыш: {bet_amount:.2f} TON\n")
        f.write(f"Поле:\n")
        for line in board_lines:
            f.write(f"  {line}\n")
        f.write(f"{'=' * 50}\n")

    # ========== 2. ДОБАВЛЯЕМ ХЕШ В ИСТОРИЮ ПОЛЬЗОВАТЕЛЯ ==========
    history_file = os.path.join(DATA_DIR, 'history', f'{user_id}.txt')
    os.makedirs(os.path.dirname(history_file), exist_ok=True)

    with open(history_file, 'a', encoding='utf-8') as f:
        if is_win:
            f.write(f"{now.strftime('%Y-%m-%d')}|{time_str}|+{win_amount:.2f}|GRAM|Minesweeper|Выигрыш|{mines_hash}\n")
        else:
            f.write(f"{now.strftime('%Y-%m-%d')}|{time_str}|-{bet_amount:.2f}|GRAM|Minesweeper|Проигрыш|{mines_hash}\n")

    return daily_file
def save_commission_safe(game_type, amount):
    """
    БЕЗОПАСНО сохраняет комиссию — просто дописывает строку в лог-файл.
    НЕ перезаписывает statistik.json!
    """
    os.makedirs(os.path.dirname(STAT_LOG_FILE), exist_ok=True)

    with open(STAT_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{game_type}|{amount}|{datetime.now().isoformat()}\n")

    return True


def recalculate_statistik():
    """
    Пересчитывает статистику из логов (суммирует все записи за все время)
    """
    STAT_LOG_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'statistik_log.txt')
    STAT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'statistik.json')

    # Загружаем существующую статистику
    existing_stats = {}
    if os.path.exists(STAT_FILE):
        try:
            with open(STAT_FILE, 'r', encoding='utf-8') as f:
                existing_stats = json.load(f)
        except:
            existing_stats = {}

    # Суммируем новые данные из лога
    new_stats = {
        'pvp_kub': 0.0,
        'pvp_ship': 0.0,
        'mine': 0.0,
        'vivod': 0.0
    }

    # Отдельно считаем staging и dohod из новых данных
    total_new_income = 0.0

    if os.path.exists(STAT_LOG_FILE):
        with open(STAT_LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    game_type = parts[0]
                    try:
                        amount = float(parts[1])

                        # Если это staging или dohod - просто суммируем для total
                        if game_type == 'staging' or game_type == 'dohod':
                            total_new_income += amount
                        else:
                            # Для остальных типов - суммируем в new_stats
                            if game_type in new_stats:
                                new_stats[game_type] += amount
                            else:
                                new_stats[game_type] = amount
                            # И добавляем в общий доход
                            total_new_income += amount
                    except:
                        pass

    # ===== ФОРМИРУЕМ РЕЗУЛЬТАТ =====
    result_stats = {}

    # 1. Копируем все старые значения
    for key, value in existing_stats.items():
        result_stats[key] = value

    # 2. Обновляем типы (кроме staging и dohod) - СКЛАДЫВАЕМ со старыми
    for key, value in new_stats.items():
        old_value = existing_stats.get(key, 0.0)
        result_stats[key] = round(old_value + value, 2)

    # 3. ВЫЧИСЛЯЕМ staging и dohod из ОБЩЕГО дохода
    # Берем старые staging и dohod (если есть) и добавляем новый доход / 2
    old_staging = existing_stats.get('staging', 0.0)
    old_dohod = existing_stats.get('dohod', 0.0)

    # Добавляем половину нового дохода к каждому
    half_new_income = total_new_income / 2
    result_stats['staging'] = round(old_staging + half_new_income, 2)
    result_stats['dohod'] = round(old_dohod + half_new_income, 2)

    # Сохраняем
    os.makedirs(os.path.dirname(STAT_FILE), exist_ok=True)
    with open(STAT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result_stats, f, indent=2, ensure_ascii=False)

    # ОЧИЩАЕМ ЛОГ (чтобы не дублировать записи)
    if os.path.exists(STAT_LOG_FILE):
        with open(STAT_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("")

    return result_stats

def get_language(user_id):
    """Получает язык пользователя"""
    user = get_user(user_id)
    if user:
        return user.get('language', 'ru')
    return 'ru'

def update_user_balance(user_id, amount_change, description='Игра Mines', status='', skip_history=False):

    users = load_users()
    user_id_str = str(user_id)

    if user_id_str not in users:
        return {'success': False, 'error': f'Пользователь с ID {user_id} не найден'}

    if isinstance(amount_change, str):
        amount_change = float(amount_change.replace(',', '.'))
    else:
        amount_change = float(amount_change)

    current_balance = users[user_id_str].get('ton_balance', 0)
    if isinstance(current_balance, str):
        current_balance = float(current_balance.replace(',', '.'))

    new_balance = round(current_balance + amount_change, 2)
    users[user_id_str]['ton_balance'] = new_balance
    save_users(users)

    # Обновляем статистику
    update_user_stats(user_id, amount_change)

    # Записываем в историю ТОЛЬКО если skip_history = False
    if not skip_history:
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')
        history_file = os.path.join(DATA_DIR, 'history', f'{user_id_str}.txt')
        os.makedirs(os.path.dirname(history_file), exist_ok=True)

        with open(history_file, 'a', encoding='utf-8') as f:
            if amount_change < 0:
                if status:
                    f.write(f"{date_str}|{time_str}|{amount_change}|GRAM|{description}|{status}\n")
                else:
                    f.write(f"{date_str}|{time_str}|{amount_change}|GRAM|{description}|Проигрыш\n")
            else:
                if status:
                    f.write(f"{date_str}|{time_str}|+{amount_change}|GRAM|{description}|{status}\n")
                else:
                    f.write(f"{date_str}|{time_str}|+{amount_change}|GRAM|{description}|Выигрыш\n")

    return {
        'success': True,
        'new_balance': new_balance,
        'old_balance': current_balance,
        'change': amount_change
    }

def add_balance(user_id, amount, token='FTFE', description=''):
    """Добавляет баланс пользователю (FTFE или TON)"""
    user = get_user(user_id)
    if not user:
        return None

    if token == 'TON':
        current = float(user.get('ton_balance', 0))
        new_balance = current + amount
        update_ton_balance(user_id, new_balance)
    else:
        current = int(user.get('balans', 0))
        new_balance = current + amount
        update_balans(user_id, new_balance)

    add_history_record(user_id, amount, token, description or f'Начисление {token}', new_balance)
    return new_balance

def subtract_balance(user_id, amount, token='FTFE', description=''):
    """Вычитает баланс у пользователя (FTFE или TON)"""
    user = get_user(user_id)
    if not user:
        return None

    if token == 'TON':
        current = float(user.get('ton_balance', 0))
        new_balance = current - amount
        if new_balance >= 0:
            update_ton_balance(user_id, new_balance)
            add_history_record(user_id, -amount, token, description or f'Списание {token}', new_balance)
            return new_balance
    else:
        current = int(user.get('balans', 0))
        new_balance = current - amount
        if new_balance >= 0:
            update_balans(user_id, new_balance)
            add_history_record(user_id, -amount, token, description or f'Списание {token}', new_balance)
            return new_balance

    return current

def update_ton_balance(user_id, new_balance):
    """Обновляет TON баланс пользователя"""
    return update_user_field(user_id, 'ton_balance', new_balance)

def update_notifications(user_id, enabled):
    """Обновляет настройки уведомлений"""
    return update_user_field(user_id, 'notifications', enabled)

def get_notifications(user_id):
    """Получает настройки уведомлений"""
    user = get_user(user_id)
    if user:
        return user.get('notifications', True)
    return True

def get_user_history(user_id, token=None, limit=50):
    history_file = os.path.join(DATA_DIR, 'history', f'{user_id}.txt')
    history = []

    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split('|')
                    if len(parts) >= 6:
                        transaction = {
                            'date': f"{parts[0]} {parts[1]}",
                            'amount': float(parts[2]),
                            'token': parts[3],
                            'description': parts[4],
                            'balance_after': float(parts[5]) if len(parts) > 5 else 0
                        }
                        if token is None or transaction['token'] == token:
                            history.append(transaction)
                    elif len(parts) >= 5:
                        transaction = {
                            'date': f"{parts[0]} {parts[1]}",
                            'amount': float(parts[2]),
                            'token': parts[3],
                            'description': parts[4],
                            'balance_after': 0
                        }
                        if token is None or transaction['token'] == token:
                            history.append(transaction)

    history.reverse()
    return history[:limit]

def get_minesweeper_history(user_id, limit=50):

    mine_dir = os.path.join('data', 'mine')
    if not os.path.exists(mine_dir):
        return []

    games = []

    for filename in os.listdir(mine_dir):
        if filename.startswith(f"{user_id}_") and filename.endswith('.txt'):
            filepath = os.path.join(mine_dir, filename)

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Парсим файл
                game_data = {
                    'filename': filename,
                    'full_content': content
                }

                # Извлекаем основные данные
                for line in content.split('\n'):
                    if line.startswith('Ставка:'):
                        game_data['bet'] = float(line.split(':')[1].strip().replace('TON', '').strip())
                    elif line.startswith('Выигрыш:'):
                        game_data['win'] = float(line.split(':')[1].strip().replace('TON', '').strip())
                    elif line.startswith('Проигрыш:'):
                        game_data['win'] = -float(line.split(':')[1].strip().replace('TON', '').strip())
                    elif line.startswith('Множитель:'):
                        game_data['multiplier'] = float(line.split(':')[1].strip().replace('x', '').strip())
                    elif line.startswith('Результат:'):
                        game_data['result'] = line.split(':')[1].strip()
                    elif line.startswith('Дата:'):
                        game_data['date'] = line.split(':')[1].strip()
                    elif line.startswith('Хеш:'):
                        game_data['hash'] = line.split(':')[1].strip()

                games.append(game_data)
            except Exception as e:
                print(f"Ошибка чтения {filename}: {e}")
                continue

    # Сортируем по дате (из имени файла)
    games.sort(key=lambda x: x.get('filename', ''), reverse=True)

    return games[:limit]

def get_user_game_stats(user_id):
    games = get_minesweeper_history(user_id, limit=1000)

    stats = {
        'total_games': len(games),
        'wins': 0,
        'losses': 0,
        'total_net': 0.0,
        'total_bet': 0.0,
        'total_win': 0.0
    }

    for game in games:
        if game.get('result') == 'WIN':
            stats['wins'] += 1
            win_amount = game.get('win', 0)
            stats['total_win'] += win_amount
            stats['total_net'] += win_amount
        else:
            stats['losses'] += 1
            bet_amount = game.get('bet', 0)
            stats['total_net'] -= bet_amount

        stats['total_bet'] += game.get('bet', 0)

    if stats['total_games'] > 0:
        stats['win_rate'] = round((stats['wins'] / stats['total_games']) * 100, 1)
    else:
        stats['win_rate'] = 0

    return stats

def connect_wallet(user_id, wallet_address):
    return update_kosh(user_id, wallet_address)

def get_all_history(user_id, limit=50):
    return get_user_history(user_id, token=None, limit=limit)

def get_history_stats(user_id):
    history = get_all_history(user_id, limit=1000)

    stats = {
        'FTFE': {
            'total_in': 0,
            'total_out': 0,
            'total_turnover': 0,
            'record_balance': 0
        },
        'TON': {
            'total_in': 0,
            'total_out': 0,
            'total_turnover': 0,
            'record_balance': 0
        }
    }

    for trans in history:
        token = trans['token']
        amount = trans['amount']
        balance_after = trans.get('balance_after', 0)

        if amount > 0:
            stats[token]['total_in'] += amount
        else:
            stats[token]['total_out'] += abs(amount)

        stats[token]['total_turnover'] += abs(amount)

        if balance_after > stats[token]['record_balance']:
            stats[token]['record_balance'] = balance_after

    return stats

def get_ftfe_history(user_id, limit=50):
    return get_user_history(user_id, token='FTFE', limit=limit)

def get_ton_history(user_id, limit=50):
    return get_user_history(user_id, token='TON', limit=limit)

def get_balance(user_id):
    user = get_user(user_id)
    return int(user['balans']) if user else 0

def get_referral_count(user_id):
    try:
        users = load_users()
        user_id_str = str(user_id)
        count = 0
        for uid, user_data in users.items():
            if user_data.get('invited_by', '-') == user_id_str:
                count += 1
        return count
    except Exception as e:
        print(f"Ошибка get_referral_count: {e}")
        return 0

def get_referral_earnings(user_id):
    """Возвращает сумму заработка от рефералов"""
    try:
        user = get_user(user_id)
        if user:
            return user.get('referral_earnings', 0.0)
        return 0.0
    except Exception as e:
        print(f"Ошибка get_referral_earnings: {e}")
        return 0.0


def update_staking_gram(user_id, amount):
    """
    Обновляет стейкинг пользователя (добавляет или убавляет GRAM)
    При добавлении обновляет created_at
    """
    try:
        staking_file = os.path.join(DATA_DIR, 'staking.json')
        os.makedirs(os.path.dirname(staking_file), exist_ok=True)

        # Загружаем данные
        if os.path.exists(staking_file):
            with open(staking_file, 'r', encoding='utf-8') as f:
                staking_data = json.load(f)
        else:
            staking_data = {}

        user_id_str = str(user_id)

        # Получаем текущее значение
        current_gram = 0
        created_at = None

        if user_id_str in staking_data:
            current_gram = staking_data[user_id_str].get('gram', 0)
            created_at = staking_data[user_id_str].get('created_at')

        new_gram = max(0, current_gram + amount)

        # ✅ ЕСЛИ ДОБАВЛЯЕМ — ОБНОВЛЯЕМ created_at
        if amount > 0:
            now = datetime.now(timezone.utc).isoformat()

            if user_id_str not in staking_data:
                staking_data[user_id_str] = {}

            # ✅ ВСЕГДА ОБНОВЛЯЕМ created_at ПРИ ПОПОЛНЕНИИ!
            staking_data[user_id_str]['created_at'] = now
            print(f"🕐 ОБНОВЛЕНО created_at для {user_id}: {now}")

        # ✅ ЕСЛИ СТЕЙК СТАЛ 0 — УДАЛЯЕМ ЗАПИСЬ
        if new_gram == 0 and user_id_str in staking_data:
            del staking_data[user_id_str]
            print(f"🗑️ Стейкинг пользователя {user_id} обнулен и удален")
        else:
            if user_id_str not in staking_data:
                staking_data[user_id_str] = {}
            staking_data[user_id_str]['gram'] = round(new_gram, 2)
            # Сохраняем created_at если он был установлен
            if 'created_at' not in staking_data[user_id_str]:
                staking_data[user_id_str]['created_at'] = datetime.now(timezone.utc).isoformat()

        # Сохраняем
        with open(staking_file, 'w', encoding='utf-8') as f:
            json.dump(staking_data, f, indent=2, ensure_ascii=False)

        print(f"💾 Сохранено в staking.json: {staking_data}")
        return True

    except Exception as e:
        print(f"❌ Ошибка update_staking_gram: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_level(user_id):
    """Получает уровень пользователя"""
    user = get_user(user_id)
    return int(user['lvl']) if user else 1

def upgrade_level(user_id):
    """Повышает уровень пользователя"""
    user = get_user(user_id)
    if user:
        current_lvl = int(user['lvl'])
        new_lvl = current_lvl + 1
        update_lvl(user_id, new_lvl)
        return new_lvl
    return 1


import json
import os

STAKING_FILE = os.path.join(DATA_DIR, 'staking.json')


def load_staking_data():
    """Загружает данные стейкинга"""
    if not os.path.exists(STAKING_FILE):
        with open(STAKING_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=2, ensure_ascii=False)
        return {}

    with open(STAKING_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_staking_data(data):
    """Сохраняет данные стейкинга"""
    with open(STAKING_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_staking_user(user_id):
    """
    Возвращает данные стейкинга пользователя
    """
    try:
        staking_file = os.path.join(DATA_DIR, 'staking.json')
        if not os.path.exists(staking_file):
            return {"gram": 0, "points": 0, "created_at": None}

        with open(staking_file, 'r', encoding='utf-8') as f:
            staking_data = json.load(f)

        user_id_str = str(user_id)
        if user_id_str in staking_data:
            data = staking_data[user_id_str]
            return {
                "gram": data.get('gram', 0),
                "points": data.get('points', 0),
                "created_at": data.get('created_at')  # ← ВРЕМЯ ПОСЛЕДНЕГО ПОПОЛНЕНИЯ
            }

        return {"gram": 0, "points": 0, "created_at": None}

    except Exception as e:
        print(f"❌ Ошибка get_staking_user: {e}")
        return {"gram": 0, "points": 0, "created_at": None}



def update_staking_points(user_id, points):
    """Обновляет количество очков"""
    data = load_staking_data()
    user_id_str = str(user_id)

    if user_id_str not in data:
        data[user_id_str] = {"gram": 0, "points": 0}

    data[user_id_str]["points"] += points
    save_staking_data(data)
    return data[user_id_str]
def add_history_record(user_id, amount, token, description, balance_after='', status=''):
    """Добавляет запись в историю операций"""
    history_file = os.path.join(DATA_DIR, 'history', f'{user_id}.txt')
    os.makedirs(os.path.dirname(history_file), exist_ok=True)

    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S')

    if amount > 0:
        amount_str = f"+{amount}"
    else:
        amount_str = f"{amount}"

    with open(history_file, 'a', encoding='utf-8') as f:
        if status:
            f.write(f"{date_str}|{time_str}|{amount_str}|{token}|{description}|{status}\n")
        elif balance_after:
            f.write(f"{date_str}|{time_str}|{amount_str}|{token}|{description}|{balance_after}\n")
        else:
            f.write(f"{date_str}|{time_str}|{amount_str}|{token}|{description}\n")

def register_user(user_id, username, first_name):
    """Регистрирует пользователя при первом запуске"""
    return add_user(user_id, username, first_name)
recalculate_statistik