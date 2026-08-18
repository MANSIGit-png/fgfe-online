import base64
import os
import json
from datetime import datetime,timezone
from tonsdk.utils import Address
from tonsdk.contract.token.ft import JettonWallet
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
WEB_DIR = os.path.join(PROJECT_ROOT, 'web')

def data_path(*parts):
    return os.path.join(DATA_DIR, *parts)

REF_FILE = data_path('ref.txt')
REF_LINKS_FILE = data_path('ref_links.txt')
JETTON_MASTER = 'EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAT_LOG_FILE = os.path.join(BASE_DIR, 'data', 'statistik_log.txt')
STAT_FILE = os.path.join(BASE_DIR, 'data', 'statistik.json')
USDT_MASTER_RAW = '0:b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe'
DESTINATION_ADDRESS = 'UQCiPnG0mf7npCpHchKp_UvE2f2cWRwZZ2OLFQy2YSPqFdLI'

def build_jetton_transfer_payload(jetton_amount, user_address, query_id=0):
    try:
        response = requests.get(f'https://tonapi.io/v2/accounts/{user_address}/jettons')
        data = response.json()
        usdt = None
        for jetton in data.get('balances', []):
            if jetton['jetton']['address'] == USDT_MASTER_RAW:
                usdt = jetton
                break
        if not usdt:
            raise Exception('USDT не найден на кошельке пользователя')
        jetton_wallet_sender_raw = usdt['wallet_address']['address']
        jetton_wallet_sender = Address(jetton_wallet_sender_raw)
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
        jw = JettonWallet()
        body = jw.create_transfer_body(Address(DESTINATION_ADDRESS), int(jetton_amount))
        cell = body.to_boc(False)
        payload_base64 = base64.b64encode(cell).decode('utf-8')
        jetton_wallet_sender_bounceable = jetton_wallet_sender.to_string(True, True, False)
        destination_jetton_bounceable = destination_jetton.to_string(True, True, False)
        print(f'📌 Jetton Wallet отправителя: {jetton_wallet_sender_bounceable}')
        print(f'📌 Jetton Wallet получателя: {destination_jetton_bounceable}')
        return {'jetton_wallet': jetton_wallet_sender_bounceable, 'payload': payload_base64, 'jetton_amount': jetton_amount, 'destination': destination_jetton_bounceable}
    except Exception as e:
        print(f'❌ Ошибка: {e}')
        import traceback
        traceback.print_exc()
        return None

def init_ref_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(REF_LINKS_FILE):
        with open(REF_LINKS_FILE, 'w', encoding='utf-8'):
            pass
    if not os.path.exists(REF_FILE):
        with open(REF_FILE, 'w', encoding='utf-8') as f:
            f.write('')

def get_gram_balance(user_id):
    user_id = str(user_id)
    users = load_users()
    if user_id in users:
        balance = users[user_id].get('ton_balance', 0)
        if isinstance(balance, str):
            try:
                balance = float(balance.replace(',', '.'))
            except Exception:
                balance = 0.0
        return float(balance)
    return 0.0

def add_referral(user_id, referrer_id):
    init_ref_file()
    user_id = str(user_id)
    referrer_id = str(referrer_id)
    if user_id == referrer_id:
        return False
    user_data = get_user(user_id)
    if user_data and user_data.get('invited_by', '-') != '-':
        return False
    update_user_field(user_id, 'invited_by', referrer_id)
    with open(REF_LINKS_FILE, 'a', encoding='utf-8') as f:
        f.write(f'{user_id}|{referrer_id}\n')
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
    children = {}
    for child, parent in connections.items():
        children.setdefault(parent, []).append(child)
    roots = all_users - set(connections.keys())
    if not roots:
        roots = all_users
    def build_tree_lines(node, prefix='', is_last=True):
        lines = [f"{prefix}{('└─ ' if is_last else '├─ ')}{node}"]
        if node in children:
            child_list = sorted(children[node])
            for i, child in enumerate(child_list):
                is_last_child = i == len(child_list) - 1
                new_prefix = prefix + ('    ' if is_last else '│   ')
                lines.extend(build_tree_lines(child, new_prefix, is_last_child))
        return lines
    tree_lines = []
    roots_list = sorted(roots)
    for i, root in enumerate(roots_list):
        tree_lines.extend(build_tree_lines(root, '', i == len(roots_list) - 1))
    with open(REF_FILE, 'w', encoding='utf-8') as f:
        for line in tree_lines:
            f.write(line + '\n')
    return True

def get_referral_tree():
    init_ref_file()
    if not os.path.exists(REF_FILE):
        return 'Нет рефералов'
    with open(REF_FILE, 'r', encoding='utf-8') as f:
        return f.read()

DATA_FILE = data_path('users.json')

def update_referral_earnings(user_id, amount_change):
    user_id = str(user_id)
    user = get_user(user_id)
    if not user:
        return False
    invited_by = user.get('invited_by', '-')
    if invited_by == '-' or not invited_by:
        return False
    referral_amount = abs(amount_change) * 0.1
    referrer = get_user(invited_by)
    if not referrer:
        return False
    current = referrer.get('referral_earnings', 0.0)
    new_amount = current + referral_amount if amount_change > 0 else current - referral_amount
    users = load_users()
    users[invited_by]['referral_earnings'] = new_amount
    save_users(users)
    return True

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(data_path('mine'), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8'):
            pass

def load_users():
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
                except Exception:
                    pass
    return users

def save_users(users):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        for user_id, user_data in users.items():
            f.write(json.dumps({user_id: user_data}, separators=(',', ':'), ensure_ascii=False) + '\n')

def add_user(user_id, username, first_name):
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str in users:
        return False
    users[user_id_str] = {'id': user_id_str, 'name': first_name, 'username': username, 'balans': 0, 'kosh': 'Не подключен', 'lvl': 1, 'language': 'ru', 'ton_balance': 0, 'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'notifications': True, 'total_turnover': 0, 'record_balance': 0, 'total_withdrawn': 0, 'invited_by': '-', 'referral_earnings': 0.0, 'vager': 0.0, 'tame': 1.0}
    save_users(users)
    return True

def get_user(user_id):
    users = load_users()
    return users.get(str(user_id))

def update_user_stats(user_id, amount_change):
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str not in users:
        return
    current_balance = users[user_id_str].get('ton_balance', 0)
    if isinstance(current_balance, str):
        current_balance = float(current_balance.replace(',', '.'))
    record_balance = users[user_id_str].get('record_balance', 0)
    total_turnover = users[user_id_str].get('total_turnover', 0)
    if amount_change < 0:
        total_turnover += abs(amount_change)
    if current_balance > record_balance:
        record_balance = current_balance
    users[user_id_str]['record_balance'] = record_balance
    users[user_id_str]['total_turnover'] = total_turnover
    save_users(users)

def update_withdrawn_stats(user_id, amount):
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str not in users:
        return False
    users[user_id_str]['total_withdrawn'] = users[user_id_str].get('total_withdrawn', 0) + abs(amount)
    save_users(users)
    return True

def get_user_data(user_id):
    user = get_user(user_id)
    if user:
        return user
    return {'id': str(user_id), 'name': 'User', 'username': 'unknown', 'balans': '0', 'kosh': 'Не подключен', 'lvl': '1', 'language': 'ru', 'ton_balance': '0', 'total_turnover': 0, 'record_balance': 0, 'total_withdrawn': 0, 'invited_by': '-', 'referral_earnings': 0.0, 'vager': 0.0, 'tame': 0.0}

def update_vager(user_id, amount_change):
    user = get_user(user_id)
    if not user:
        return False
    current = user.get('vager', 0.0)
    if isinstance(current, str):
        current = float(current.replace(',', '.'))
    return update_user_field(user_id, 'vager', max(0, current + amount_change))

def get_vager(user_id):
    user = get_user(user_id)
    return user.get('vager', 0.0) if user else 0.0

def update_tame(user_id, amount_change):
    user = get_user(user_id)
    if not user:
        return False
    current = user.get('tame', 0.0)
    if isinstance(current, str):
        current = float(current.replace(',', '.'))
    return update_user_field(user_id, 'tame', max(0, current + amount_change))

def get_tame(user_id):
    user = get_user(user_id)
    return user.get('tame', 0.0) if user else 0.0

def update_user_field(user_id, field, value):
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str not in users:
        return False
    users[user_id_str][field] = value
    save_users(users)
    return True

def update_balans(user_id, new_balans): return update_user_field(user_id, 'balans', new_balans)
def update_kosh(user_id, wallet): return update_user_field(user_id, 'kosh', wallet)
def update_lvl(user_id, new_lvl): return update_user_field(user_id, 'lvl', new_lvl)
def update_language(user_id, language): return update_user_field(user_id, 'language', language)
def update_ton_balance(user_id, new_balance): return update_user_field(user_id, 'ton_balance', new_balance)
def update_notifications(user_id, enabled): return update_user_field(user_id, 'notifications', enabled)

def get_notifications(user_id):
    user = get_user(user_id)
    return user.get('notifications', True) if user else True

def save_minesweeper_game(user_id, board, mines_hash, bet_amount, win_amount, is_win, multiplier):
    init_db()
    now = datetime.now()
    date_str = now.strftime('%d_%m_%Y')
    time_str = now.strftime('%H:%M:%S')
    daily_file = os.path.join(DATA_DIR, 'mine', f'{date_str}.txt')
    board_lines = []
    for row in board:
        row_str = ''.join('[💣]' if cell == 1 or cell == 'mine' else '[🔷]' for cell in row)
        board_lines.append(row_str)
    with open(daily_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'=' * 50}\n[{time_str}] Пользователь: {user_id}\nХеш: {mines_hash}\n")
        f.write(f"Ставка: {bet_amount:.2f} GRAM | Результат: {('WIN' if is_win else 'LOSS')} | Множитель: x{multiplier:.2f}\n")
        f.write(f"{'Выигрыш' if is_win else 'Проигрыш'}: {(win_amount if is_win else bet_amount):.2f} TON\nПоле:\n")
        for line in board_lines:
            f.write(f'  {line}\n')
        f.write(f"{'=' * 50}\n")
    history_file = os.path.join(DATA_DIR, 'history', f'{user_id}.txt')
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    with open(history_file, 'a', encoding='utf-8') as f:
        amount = win_amount if is_win else -bet_amount
        result = 'Выигрыш' if is_win else 'Проигрыш'
        f.write(f"{now.strftime('%Y-%m-%d')}|{time_str}|{amount:+.2f}|GRAM|Minesweeper|{result}|{mines_hash}\n")
    return daily_file

def save_commission_safe(game_type, amount):
    os.makedirs(os.path.dirname(STAT_LOG_FILE), exist_ok=True)
    with open(STAT_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f'{game_type}|{amount}|{datetime.now().isoformat()}\n')
    return True

def recalculate_statistik():
    stat_log_file = os.path.join(BASE_DIR, 'data', 'statistik_log.txt')
    stat_file = os.path.join(BASE_DIR, 'data', 'statistik.json')
    existing_stats = {}
    if os.path.exists(stat_file):
        try:
            with open(stat_file, 'r', encoding='utf-8') as f:
                existing_stats = json.load(f)
        except Exception:
            existing_stats = {}
    new_stats = {'pvp_kub': 0.0, 'pvp_ship': 0.0, 'mine': 0.0, 'vivod': 0.0}
    total_new_income = 0.0
    if os.path.exists(stat_log_file):
        with open(stat_log_file, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 2:
                    try:
                        amount = float(parts[1]); game_type = parts[0]
                        if game_type not in ('staging', 'dohod'):
                            new_stats[game_type] = new_stats.get(game_type, 0.0) + amount
                        total_new_income += amount
                    except Exception:
                        pass
    result_stats = dict(existing_stats)
    for key, value in new_stats.items():
        result_stats[key] = value
    result_stats['dohod'] = total_new_income
    with open(stat_file, 'w', encoding='utf-8') as f:
        json.dump(result_stats, f, ensure_ascii=False, indent=2)
    return result_stats

def register_user(user_id, username, first_name):
    return add_user(user_id, username, first_name)

def get_balance(user_id):
    return get_gram_balance(user_id)

def update_user_balance(user_id, amount):
    user = get_user(user_id)
    if not user:
        return False
    current = user.get('ton_balance', 0)
    if isinstance(current, str):
        try:
            current = float(current.replace(',', '.'))
        except Exception:
            current = 0.0
    new_balance = current + float(amount)
    update_ton_balance(user_id, new_balance)
    update_user_stats(user_id, float(amount))
    return True

def add_balance(user_id, amount):
    return update_user_balance(user_id, amount)

def connect_wallet(user_id, wallet):
    return update_kosh(user_id, wallet)

def get_language(user_id):
    user = get_user(user_id)
    return user.get('language', 'ru') if user else 'ru'

def get_referral_earnings(user_id):
    user = get_user(user_id)
    return user.get('referral_earnings', 0.0) if user else 0.0

def get_referral_count(user_id):
    init_ref_file()
    user_id = str(user_id)
    count = 0
    if os.path.exists(REF_LINKS_FILE):
        with open(REF_LINKS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 2 and parts[1] == user_id:
                    count += 1
    return count

def add_history_record(user_id, amount, currency='GRAM', operation='operation', status='ok', extra=''):
    os.makedirs(data_path('history'), exist_ok=True)
    path = data_path('history', f'{user_id}.txt')
    now = datetime.now()
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f"{now.strftime('%Y-%m-%d')}|{now.strftime('%H:%M:%S')}|{float(amount):+.8f}|{currency}|{operation}|{status}|{extra}\n")
    return True

def get_history_stats(user_id):
    path = data_path('history', f'{user_id}.txt')
    result = {'count': 0, 'income': 0.0, 'expense': 0.0}
    if not os.path.exists(path):
        return result
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\n').split('|')
            if len(parts) >= 3:
                try:
                    amount = float(parts[2])
                except Exception:
                    continue
                result['count'] += 1
                if amount >= 0:
                    result['income'] += amount
                else:
                    result['expense'] += abs(amount)
    return result

STAKING_FILE = data_path('staking.json')

def load_staking_data():
    if not os.path.exists(STAKING_FILE):
        return {}
    try:
        with open(STAKING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_staking_data(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STAKING_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True

def get_staking_user(user_id):
    return load_staking_data().get(str(user_id), {})

def update_staking_gram(user_id, amount):
    data = load_staking_data()
    uid = str(user_id)
    user = data.setdefault(uid, {})
    current = user.get('gram', 0)
    try:
        current = float(current)
    except Exception:
        current = 0.0
    user['gram'] = current + float(amount)
    save_staking_data(data)
    return user['gram']
