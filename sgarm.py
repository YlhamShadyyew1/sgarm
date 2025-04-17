from pywebio.input import *
from pywebio.output import *
from pywebio.session import *
from pywebio.platform.flask import webio_view
from flask import Flask
import time
import json
import os

app = Flask(__name__)

# Файлы данных
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def load_json(filename, default):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users = load_json("users.json", {})
banned_users = set(load_json("banned.json", []))
channels = load_json("channels.json", {"general": []})
verifications = load_json("verifications.json", {})

def save_all():
    save_json("users.json", users)
    save_json("banned.json", list(banned_users))
    save_json("channels.json", channels)
    save_json("verifications.json", verifications)

def get_verification_mark(user):
    mark = verifications.get(user, '')
    if mark == 'blue':
        return ' <span style="color:#1da1f2;">✔</span>'
    elif mark == 'gold':
        return ' <span style="color:gold;">★</span>'
    elif mark == 'youtube':
        return ' <span style="color:red;">▶</span>'
    return ''

def render_messages(channel):
    clear()
    html = '<div class="chat">'
    for m in channels[channel][-100:]:
        mark = get_verification_mark(m["user"])
        html += f'<div class="msg"><b>{m["user"]}</b>{mark}: {m["text"]}</div>'
    html += '</div>'
    put_html(f"""
        <style>
        .chat {{ max-height: 70vh; overflow-y: auto; }}
        .msg {{ padding: 5px; margin: 2px 0; border-bottom: 1px solid #eee; }}
        @media (max-width: 768px) {{
            .msg {{ font-size: 14px; }}
        }}
        @media (max-width: 480px) {{
            .msg {{ font-size: 12px; }}
        }}
        </style>
    """)
    put_scrollable(html, height=400)

async def login():
    data = await input_group("Вход или регистрация", [
        input("Юзернейм", name="username", required=True),
        input("Пароль", name="password", type=PASSWORD, required=True),
    ])
    if data['username'] in banned_users:
        put_error("Вы забанены.")
        return None

    if data['username'] in users:
        if users[data['username']]['password'] == data['password']:
            return data['username']
        else:
            put_error("Неверный пароль.")
            return None
    else:
        users[data['username']] = {
            'password': data['password'],
            'nick': data['username'],
            'about': '',
            'avatar': ''
        }
        save_all()
        return data['username']

async def admin_panel(user):
    while True:
        action = await select("Админ-панель", [
            'Забанить пользователя', 'Выдать галочку', 'Создать канал', 'Назад'
        ])
        if action == 'Забанить пользователя':
            target = await input("Кого забанить?")
            banned_users.add(target)
            save_all()
            put_success(f"{target} забанен.")
        elif action == 'Выдать галочку':
            target = await input("Кому выдать?")
            badge = await select("Тип галочки", ['blue', 'gold', 'youtube'])
            verifications[target] = badge
            save_all()
        elif action == 'Создать канал':
            cname = await input("Имя канала:")
            channels[cname] = []
            save_all()
        else:
            break

async def edit_profile(username):
    data = await input_group("Профиль", [
        input("Ник", name="nick", value=users[username]['nick']),
        textarea("Описание", name="about", value=users[username]['about']),
        input("Ссылка на аватар", name="avatar", value=users[username]['avatar']),
    ])
    users[username].update(data)
    save_all()

async def main():
    username = await login()
    if not username:
        return
    if username == "@snike":
        verifications[username] = "blue"
        save_all()

    # Устанавливаем title на странице
    run_js(f"document.title = 'SGarm - Добро пожаловать, {username}';")

    while True:
        action = await select(f"Добро пожаловать, {username}", [
            "В чат", "Профиль", "Каналы", "Админ-панель" if username == "@snike" else None, "Выход"
        ])
        if action == "В чат":
            current_channel = await select("Выберите канал", list(channels.keys()))
            while True:
                render_messages(current_channel)
                data = await input_group("SGarm", [
                    input("Сообщение", name='text', required=True)
                ])
                channels[current_channel].append({"user": username, "text": data['text']})
                save_all()
                time.sleep(0.5)
        elif action == "Профиль":
            await edit_profile(username)
        elif action == "Каналы":
            put_table([[k, len(v)] for k, v in channels.items()])
        elif action == "Админ-панель" and username == "@snike":
            await admin_panel(username)
        elif action == "Выход":
            break

app.add_url_rule('/', 'webio_view', webio_view(main), methods=['GET', 'POST'])

if __name__ == '__main__':
    app.run()


# ============== ЗАЩИТА ОТ DDoS ==============
rate_limit_msgs = {}
rate_limit_login = {}
blocked_ips = {}

MAX_MSGS_PER_MIN = 10
MAX_LOGINS_PER_10MIN = 5
BLOCK_TIME = 300  # секунд

def check_msg_limit(username):
    now = time.time()
    history = rate_limit_msgs.get(username, [])
    history = [t for t in history if now - t < 60]
    if len(history) >= MAX_MSGS_PER_MIN:
        return False
    history.append(now)
    rate_limit_msgs[username] = history
    return True

def check_login_limit(ip):
    now = time.time()
    if ip in blocked_ips and blocked_ips[ip] > now:
        return False
    attempts = rate_limit_login.get(ip, [])
    attempts = [t for t in attempts if now - t < 600]
    if len(attempts) >= MAX_LOGINS_PER_10MIN:
        blocked_ips[ip] = now + BLOCK_TIME
        return False
    attempts.append(now)
    rate_limit_login[ip] = attempts
    return True

# Вставим в login и main
orig_login = login
async def login():
    ip = info.user_ip
    if not check_login_limit(ip):
        put_error("Слишком много попыток входа. Попробуйте позже.")
        return None
    return await orig_login()

orig_main = main
async def main():
    username = await login()
    if not username:
        return
    if username == "@snike":
        verifications[username] = "blue"
        save_all()
    while True:
        action = await select(f"Добро пожаловать, {username}", [
            "В чат", "Профиль", "Каналы", "Админ-панель" if username == "@snike" else None, "Выход"
        ])
        if action == "В чат":
            current_channel = await select("Выберите канал", list(channels.keys()))
            while True:
                render_messages(current_channel)
                data = await input_group("SGarm", [
                    input("Сообщение", name='text', required=True)
                ])
                if not check_msg_limit(username):
                    put_error("Слишком много сообщений. Подождите немного.")
                    continue
                channels[current_channel].append({"user": username, "text": data['text']})
                save_all()
                time.sleep(0.5)
        elif action == "Профиль":
            await edit_profile(username)
        elif action == "Каналы":
            put_table([[k, len(v)] for k, v in channels.items()])
        elif action == "Админ-панель" and username == "@snike":
            await admin_panel(username)
        elif action == "Выход":
            break
