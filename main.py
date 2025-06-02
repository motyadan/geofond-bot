import telebot
import json
import os
import re
import io
import threading
import time
from datetime import datetime
from telebot import types
from collections import defaultdict

# ================== НАСТРОЙКИ ==================

TOKEN = '815520.......'
CHANNEL_ID = '-1002599464119'  # ID канала для пересылки медиагрупп

# Файлы с данными
ALLOWED_USERS_FILE = 'allowed_users.json'
ADMINS_FILE = 'admins.txt'

# Базовая папка для локального хранения отчётов
LOCAL_REPORTS_BASE = 'reports'

# Временное хранилище данных отчётов
# Структура: user_data[chat_id_str] = {"photos": [file_id, ...], "comment": "текст"}
user_data = defaultdict(lambda: {"photos": [], "comment": ""})


# ================================================
# ======== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ================
# ================================================

def sanitize_for_path(name: str) -> str:
    """
    Заменяет в имени всё, что не подходит для пути:
    запрещённые символы \ / : * ? " < > | # на подчёркивание.
    """
    return re.sub(r'[\\/:*?"<>|#]', '_', name).strip()

def get_admins():
    try:
        with open(ADMINS_FILE, 'r', encoding='utf-8') as f:
            return set(f.read().split())
    except FileNotFoundError:
        return set()

def get_allowed_users():
    try:
        with open(ALLOWED_USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_allowed_users(users):
    with open(ALLOWED_USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def is_admin(user_id):
    return str(user_id) in get_admins()

def is_user_allowed(user_id):
    return str(user_id) in get_allowed_users()

def get_user_name(user_id):
    users = get_allowed_users()
    return users.get(str(user_id), "Неизвестный_пользователь")

def save_photos_thread(photos, safe_user_name, safe_comment, chat_id_str, timestamp):
    """
    Функция, исполняемая в отдельном потоке:
    скачивает фото из Telegram и сохраняет их в локальный каталог.
    """
    report_folder = os.path.join(LOCAL_REPORTS_BASE, safe_user_name, safe_comment)
    os.makedirs(report_folder, exist_ok=True)

    for idx, file_id in enumerate(photos, start=1):
        try:
            file_info = bot.get_file(file_id)
            file_path = file_info.file_path
            photo_data = bot.download_file(file_path)
            filename = f"{chat_id_str}-{timestamp}-{idx}.jpg"
            filepath = os.path.join(report_folder, filename)
            with open(filepath, 'wb') as f:
                f.write(photo_data)
        except Exception as e:
            # В случае ошибки сохраняем лог, но продолжаем
            print(f"Ошибка при сохранении {file_id}: {e}")



# ================================================
# =============== ОСНОВНОЙ КОД БОТА ==============
# ================================================

bot = telebot.TeleBot(TOKEN)

# --- МЕНЮ ---

def send_main_menu(chat_id, user_id):
    markup = types.InlineKeyboardMarkup()
    if is_admin(user_id):
        markup.add(types.InlineKeyboardButton("Добавить", callback_data="add"))
    if is_user_allowed(user_id):
        markup.add(types.InlineKeyboardButton("Сделать фотоотчёт", callback_data="report"))
    bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(message):
    send_main_menu(message.chat.id, message.from_user.id)


# --- ДОБАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ---

@bot.callback_query_handler(func=lambda call: call.data == 'add')
def add_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет прав!")
        return send_main_menu(call.message.chat.id, call.from_user.id)
    msg = bot.send_message(
        call.message.chat.id,
        "Введите ID и имя пользователя в формате: chat_id имя",
        reply_markup=types.ForceReply(selective=True)
    )
    bot.register_next_step_handler(msg, add_user_by_text)

def add_user_by_text(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Нет прав на добавление!")
        return
    try:
        chat_id, name = message.text.split(maxsplit=1)
        users = get_allowed_users()
        users[chat_id] = name
        save_allowed_users(users)
        bot.reply_to(message, f"Пользователь '{name}' добавлен.")
    except ValueError:
        bot.reply_to(message, "Ошибка формата. Используйте: chat_id имя")
    time.sleep(1)
    send_main_menu(message.chat.id, message.from_user.id)


# --- НАЧАЛО ФОРМИРОВАНИЯ ОТЧЁТА ---

@bot.callback_query_handler(func=lambda call: call.data == 'report')
def report_callback(call):
    if not is_user_allowed(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа!")
        return send_main_menu(call.message.chat.id, call.from_user.id)

    uid = str(call.from_user.id)
    user_data[uid] = {"photos": [], "comment": ""}
    msg = bot.send_message(
        call.message.chat.id,
        "Какой объект (комментарий)?",
        reply_markup=types.ForceReply(selective=True)
    )
    bot.register_next_step_handler(msg, handle_comment)

def handle_comment(message):
    uid = str(message.from_user.id)
    user_data[uid]["comment"] = message.text
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Завершить отчет", callback_data="finish"))
    kb.add(types.InlineKeyboardButton("Отменить отчет", callback_data="cancel"))
    bot.send_message(
        message.chat.id,
        'Теперь отправьте фото. Когда закончите, нажмите "Завершить отчет".',
        reply_markup=kb
    )

# --- ПРИЁМ ФОТО ОТ ПОЛЬЗОВАТЕЛЯ ---

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    uid = str(message.from_user.id)
    if not is_user_allowed(message.from_user.id):
        return bot.reply_to(message, "Нет доступа для отправки фото.")
    file_id = message.photo[-1].file_id
    user_data[uid]["photos"].append(file_id)

# --- ЗАВЕРШЕНИЕ ОТЧЁТА: ПЕРЕСЫЛКА + ОТДЕЛЬНЫЙ ПОТОК ДЛЯ СОХРАНЕНИЯ ---

@bot.callback_query_handler(func=lambda call: call.data == 'finish')
def finish_report(call):
    bot.answer_callback_query(call.id)
    uid = str(call.from_user.id)
    if not is_user_allowed(call.from_user.id):
        return send_main_menu(call.message.chat.id, call.from_user.id)

    photos = user_data[uid]["photos"]
    comment_raw = user_data[uid]["comment"]
    name_raw = get_user_name(uid)
    chat_id_str = uid  # для формирования имён файлов

    if not photos:
        bot.send_message(call.message.chat.id, "Вы не отправили ни одной фотографии.")
        return

    # --------------------------------------------------------
    # 1) Пересылаем медиагруппами в канал (по 10 фото в группе)
    # --------------------------------------------------------

    caption = f"<b>Фотоотчёт от {name_raw}</b>\nКомментарий: {comment_raw}"
    chunk_size = 10

    for i in range(0, len(photos), chunk_size):
        group = photos[i:i + chunk_size]
        media_group = []
        for j, file_id in enumerate(group):
            if j == 0:
                media_group.append(
                    types.InputMediaPhoto(media=file_id, caption=caption, parse_mode='HTML')
                )
            else:
                media_group.append(types.InputMediaPhoto(media=file_id))
        bot.send_media_group(CHANNEL_ID, media_group)

    # --------------------------------------------------------
    # 2) Запускаем поток для скачивания и сохранения фото
    # --------------------------------------------------------

    safe_user_name = sanitize_for_path(name_raw)
    safe_comment = sanitize_for_path(comment_raw)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    # Копируем список, чтобы очистить пользовательские данные и не блокировать основной поток
    photos_copy = list(photos)

    # Очищаем данные пользователя, чтобы он мог начать новый отчёт сразу
    user_data[uid] = {"photos": [], "comment": ""}

    # Запускаем поток
    t = threading.Thread(
        target=save_photos_thread,
        args=(photos_copy, safe_user_name, safe_comment, chat_id_str, timestamp),
        daemon=True
    )
    t.start()

    bot.send_message(call.message.chat.id, "Отчёт отправлен в канал, сохранение началось в фоне.")
    send_main_menu(call.message.chat.id, call.from_user.id)

# --- ОТМЕНА ОТЧЁТА ---

@bot.callback_query_handler(func=lambda call: call.data == 'cancel')
def cancel_report(call):
    bot.answer_callback_query(call.id, "Отчёт отменён.")
    user_data[str(call.from_user.id)] = {"photos": [], "comment": ""}
    send_main_menu(call.message.chat.id, call.from_user.id)

# --- ЗАПУСК БОТА ---

if __name__ == '__main__':
    os.makedirs(LOCAL_REPORTS_BASE, exist_ok=True)
    bot.polling(none_stop=True)

