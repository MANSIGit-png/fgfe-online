import base64
import os
import json
from datetime import datetime, timezone
from tonsdk.utils import Address
from tonsdk.contract.token.ft import JettonWallet
import requests
REF_FILE = 'data/ref.txt'
REF_LINKS_FILE = 'data/ref_links.txt'
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
    os.makedirs('data', exist_ok=True)
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

DATA_FILE = 'data/users.json'

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
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/mine', exist_ok=True)
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
    daily_file = os.path.join('data', 'mine', f'{date_str}.txt')
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
    history_file = os.path.join('data', 'history', f'{user_id}.txt')
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
        result_stats[key] = round(existing_stats.get(key, 0.0) + value, 2)
    half_new_income = total_new_income / 2
    result_stats['staging'] = round(existing_stats.get('staging', 0.0) + half_new_income, 2)
    result_stats['dohod'] = round(existing_stats.get('dohod', 0.0) + half_new_income, 2)
    os.makedirs(os.path.dirname(stat_file), exist_ok=True)
    with open(stat_file, 'w', encoding='utf-8') as f:
        json.dump(result_stats, f, indent=2, ensure_ascii=False)
    if os.path.exists(stat_log_file):
        open(stat_log_file, 'w', encoding='utf-8').close()
    return result_stats

def get_language(user_id):
    user = get_user(user_id)
    return user.get('language', 'ru') if user else 'ru'

def update_user_balance(user_id, amount_change, description='Игра Mines', status='', skip_history=False):
    users = load_users(); user_id_str = str(user_id)
    if user_id_str not in users:
        return {'success': False, 'error': f'Пользователь с ID {user_id} не найден'}
    amount_change = float(amount_change.replace(',', '.')) if isinstance(amount_change, str) else float(amount_change)
    current_balance = users[user_id_str].get('ton_balance', 0)
    if isinstance(current_balance, str): current_balance = float(current_balance.replace(',', '.'))
    new_balance = round(current_balance + amount_change, 2)
    users[user_id_str]['ton_balance'] = new_balance
    save_users(users); update_user_stats(user_id, amount_change)
    if not skip_history:
        now = datetime.now(); history_file = os.path.join('data', 'history', f'{user_id_str}.txt'); os.makedirs(os.path.dirname(history_file), exist_ok=True)
        result_status = status or ('Проигрыш' if amount_change < 0 else 'Выигрыш')
        with open(history_file, 'a', encoding='utf-8') as f:
            f.write(f"{now.strftime('%Y-%m-%d')}|{now.strftime('%H:%M:%S')}|{amount_change:+g}|GRAM|{description}|{result_status}\n")
    return {'success': True, 'new_balance': new_balance, 'old_balance': current_balance, 'change': amount_change}

def add_history_record(user_id, amount, token, description, balance_after='', status=''):
    history_file = os.path.join('data', 'history', f'{user_id}.txt'); os.makedirs(os.path.dirname(history_file), exist_ok=True)
    now = datetime.now(); amount_str = f'+{amount}' if amount > 0 else f'{amount}'
    fields = [now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), amount_str, token, description]
    if status: fields.append(status)
    elif balance_after != '': fields.append(str(balance_after))
    with open(history_file, 'a', encoding='utf-8') as f: f.write('|'.join(fields) + '\n')

def add_balance(user_id, amount, token='FTFE', description=''):
    user = get_user(user_id)
    if not user: return None
    if token == 'TON':
        new_balance = float(user.get('ton_balance', 0)) + amount; update_ton_balance(user_id, new_balance)
    else:
        new_balance = int(user.get('balans', 0)) + amount; update_balans(user_id, new_balance)
    add_history_record(user_id, amount, token, description or f'Начисление {token}', new_balance)
    return new_balance

def subtract_balance(user_id, amount, token='FTFE', description=''):
    user = get_user(user_id)
    if not user: return None
    current = float(user.get('ton_balance', 0)) if token == 'TON' else int(user.get('balans', 0))
    new_balance = current - amount
    if new_balance >= 0:
        (update_ton_balance if token == 'TON' else update_balans)(user_id, new_balance)
        add_history_record(user_id, -amount, token, description or f'Списание {token}', new_balance)
        return new_balance
    return current

def get_user_history(user_id, token=None, limit=50):
    history_file = os.path.join('data', 'history', f'{user_id}.txt'); history = []
    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 5:
                    try: amount = float(parts[2])
                    except Exception: continue
                    transaction = {'date': f'{parts[0]} {parts[1]}', 'amount': amount, 'token': parts[3], 'description': parts[4], 'balance_after': 0}
                    if len(parts) > 5:
                        try: transaction['balance_after'] = float(parts[5])
                        except Exception: transaction['status'] = parts[5]
                    if token is None or transaction['token'] == token: history.append(transaction)
    history.reverse(); return history[:limit]

def get_minesweeper_history(user_id, limit=50):
    mine_dir = os.path.join('data', 'mine')
    if not os.path.exists(mine_dir): return []
    games = []
    for filename in os.listdir(mine_dir):
        if filename.startswith(f'{user_id}_') and filename.endswith('.txt'):
            filepath = os.path.join(mine_dir, filename)
            try:
                content = open(filepath, 'r', encoding='utf-8').read(); game_data = {'filename': filename, 'full_content': content}
                for line in content.split('\n'):
                    if line.startswith('Ставка:'): game_data['bet'] = float(line.split(':')[1].strip().replace('TON', '').strip())
                    elif line.startswith('Выигрыш:'): game_data['win'] = float(line.split(':')[1].strip().replace('TON', '').strip())
                    elif line.startswith('Проигрыш:'): game_data['win'] = -float(line.split(':')[1].strip().replace('TON', '').strip())
                    elif line.startswith('Множитель:'): game_data['multiplier'] = float(line.split(':')[1].strip().replace('x', '').strip())
                    elif line.startswith('Результат:'): game_data['result'] = line.split(':')[1].strip()
                    elif line.startswith('Дата:'): game_data['date'] = line.split(':')[1].strip()
                    elif line.startswith('Хеш:'): game_data['hash'] = line.split(':')[1].strip()
                games.append(game_data)
            except Exception as e: print(f'Ошибка чтения {filename}: {e}')
    games.sort(key=lambda x: x.get('filename', ''), reverse=True); return games[:limit]

def get_user_game_stats(user_id):
    games = get_minesweeper_history(user_id, 1000); stats = {'total_games': len(games), 'wins': 0, 'losses': 0, 'total_net': 0.0, 'total_bet': 0.0, 'total_win': 0.0}
    for game in games:
        if game.get('result') == 'WIN':
            stats['wins'] += 1; win_amount = game.get('win', 0); stats['total_win'] += win_amount; stats['total_net'] += win_amount
        else:
            stats['losses'] += 1; stats['total_net'] -= game.get('bet', 0)
        stats['total_bet'] += game.get('bet', 0)
    stats['win_rate'] = round(stats['wins'] / stats['total_games'] * 100, 1) if stats['total_games'] else 0
    return stats

def connect_wallet(user_id, wallet_address): return update_kosh(user_id, wallet_address)
def get_all_history(user_id, limit=50): return get_user_history(user_id, None, limit)
def get_ftfe_history(user_id, limit=50): return get_user_history(user_id, 'FTFE', limit)
def get_ton_history(user_id, limit=50): return get_user_history(user_id, 'TON', limit)
def get_balance(user_id):
    user = get_user(user_id); return int(user['balans']) if user else 0

def get_history_stats(user_id):
    history = get_all_history(user_id, 1000); stats = {'FTFE': {'total_in': 0, 'total_out': 0, 'total_turnover': 0, 'record_balance': 0}, 'TON': {'total_in': 0, 'total_out': 0, 'total_turnover': 0, 'record_balance': 0}}
    for trans in history:
        token = trans['token']; amount = trans['amount']; balance_after = trans.get('balance_after', 0)
        if token not in stats: stats[token] = {'total_in': 0, 'total_out': 0, 'total_turnover': 0, 'record_balance': 0}
        if amount > 0: stats[token]['total_in'] += amount
        else: stats[token]['total_out'] += abs(amount)
        stats[token]['total_turnover'] += abs(amount); stats[token]['record_balance'] = max(stats[token]['record_balance'], balance_after)
    return stats

def get_referral_count(user_id):
    try: return sum(1 for u in load_users().values() if u.get('invited_by', '-') == str(user_id))
    except Exception: return 0

def get_referral_earnings(user_id):
    user = get_user(user_id); return user.get('referral_earnings', 0.0) if user else 0.0

STAKING_FILE = os.path.join('data', 'staking.json')
def load_staking_data():
    if not os.path.exists(STAKING_FILE):
        os.makedirs(os.path.dirname(STAKING_FILE), exist_ok=True); json.dump({}, open(STAKING_FILE, 'w', encoding='utf-8')); return {}
    with open(STAKING_FILE, 'r', encoding='utf-8') as f: return json.load(f)
def save_staking_data(data):
    with open(STAKING_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2, ensure_ascii=False)
def get_staking_user(user_id):
    try:
        data = load_staking_data().get(str(user_id), {}); return {'gram': data.get('gram', 0), 'points': data.get('points', 0), 'created_at': data.get('created_at')}
    except Exception: return {'gram': 0, 'points': 0, 'created_at': None}
def update_staking_gram(user_id, amount):
    data = load_staking_data(); uid = str(user_id); entry = data.get(uid, {}); new_gram = max(0, entry.get('gram', 0) + amount)
    if new_gram == 0: data.pop(uid, None)
    else:
        entry['gram'] = round(new_gram, 2)
        if amount > 0 or not entry.get('created_at'): entry['created_at'] = datetime.now(timezone.utc).isoformat()
        data[uid] = entry
    save_staking_data(data); return True
def update_staking_points(user_id, points):
    data = load_staking_data(); uid = str(user_id); data.setdefault(uid, {'gram': 0, 'points': 0}); data[uid]['points'] = data[uid].get('points', 0) + points; save_staking_data(data); return data[uid]
def get_level(user_id):
    user = get_user(user_id); return int(user['lvl']) if user else 1
def upgrade_level(user_id):
    user = get_user(user_id)
    if not user: return 1
    new_lvl = int(user['lvl']) + 1; update_lvl(user_id, new_lvl); return new_lvl
def register_user(user_id, username, first_name): return add_user(user_id, username, first_name)
