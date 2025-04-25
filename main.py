import telebot
import json
from telebot import types
from collections import defaultdict
import time
import os
from datetime import datetime

# Конфигурационные переменные
TOKEN = '8155202...........'
CHANNEL_ID = '-1002495576009'
PHOTOS_BASE_PATH = 'reports'  # Базовый путь для сохранения фотоотчётов

bot = telebot.TeleBot(TOKEN)

# Файлы с данными
ALLOWED_USERS_FILE = 'allowed_users.json'
ADMINS_FILE = 'admins.txt'

# Словарь для хранения данных пользователей
user_data = defaultdict(lambda: {"photos": [], "comment": "", "folder": ""})

# Создаём базовую директорию, если её нет
os.makedirs(PHOTOS_BASE_PATH, exist_ok=True)

# --- Утилиты ---

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
    return users.get(str(user_id), "Неизвестный пользователь")

# --- Меню ---

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

# --- Добавление пользователя ---

@bot.callback_query_handler(func=lambda call: call.data == 'add')
def add_callback(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "Нет прав!")
        return send_main_menu(call.message.chat.id, user_id)
    msg = bot.send_message(call.message.chat.id,
                           "Введите ID и имя пользователя в формате: chat_id имя",
                           reply_markup=types.ForceReply(selective=True))
    bot.register_next_step_handler(msg, add_user_by_text)


def add_user_by_text(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "Нет прав на добавление!")
    else:
        try:
            chat_id, name = message.text.split(maxsplit=1)
            users = get_allowed_users()
            users[chat_id] = name
            save_allowed_users(users)
            bot.reply_to(message, f"Пользователь {name} добавлен.")
        except ValueError:
            bot.reply_to(message, "Ошибка формата. Используйте: chat_id имя")
    time.sleep(1)
    send_main_menu(message.chat.id, user_id)

# --- Начало отчёта ---

@bot.callback_query_handler(func=lambda call: call.data == 'report')
def report_callback(call):
    user_id = call.from_user.id
    if not is_user_allowed(user_id):
        bot.answer_callback_query(call.id, "Нет прав!")
        return send_main_menu(call.message.chat.id, user_id)
    uid = str(user_id)
    user_data[uid] = {"photos": [], "comment": "", "folder": ""}
    msg = bot.send_message(call.message.chat.id,
                           "Какой объект (комментарий)?",
                           reply_markup=types.ForceReply(selective=True))
    bot.register_next_step_handler(msg, handle_comment)


def handle_comment(message):
    user_id = str(message.from_user.id)
    comment = message.text
    user_data[user_id]["comment"] = comment
    folder_name = f"{comment}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    folder_path = os.path.join(PHOTOS_BASE_PATH, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    user_data[user_id]["folder"] = folder_path
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Завершить отчет", callback_data="finish"))
    kb.add(types.InlineKeyboardButton("Отменить отчет", callback_data="cancel"))
    bot.send_message(message.chat.id,
                     'Теперь отправьте фото. Когда закончите, нажмите "Завершить отчет".',
                     reply_markup=kb)

# --- Приём фото (только сохранение ID) ---

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    uid = str(message.from_user.id)
    if not is_user_allowed(message.from_user.id):
        return bot.reply_to(message, "Нет прав на отправку фото.")
    user_data[uid]["photos"].append(message.photo[-1].file_id)


# --- Завершение отчёта ---

@bot.callback_query_handler(func=lambda call: call.data == 'finish')
def finish_report(call):
    # Подтверждаем callback сразу
    bot.answer_callback_query(call.id)
    uid = str(call.from_user.id)
    if not is_user_allowed(call.from_user.id):
        return send_main_menu(call.message.chat.id, call.from_user.id)
    photos = user_data[uid]["photos"]
    comment = user_data[uid]["comment"]
    folder_path = user_data[uid]["folder"]
    name = get_user_name(uid)
    if not photos:
        bot.send_message(call.message.chat.id, "Никаких фото не было отправлено.")
        return
    # Скачиваем фото
    for fid in photos:
        file_info = bot.get_file(fid)
        data = bot.download_file(file_info.file_path)
        with open(f"{folder_path}/{fid}.jpg", 'wb') as f:
            f.write(data)
    # Отправка фото в канале: открываем файлы без закрытия до после отправки
    for i in range(0, len(photos), 10):
        group = photos[i:i+10]
        media = []
        open_files = []
        for idx, fid in enumerate(group):
            path = f"{folder_path}/{fid}.jpg"
            f = open(path, 'rb')
            open_files.append(f)
            if idx == 0:
                media.append(types.InputMediaPhoto(f, caption=f"Фотоотчёт от {name}\nКомментарий: {comment}"))
            else:
                media.append(types.InputMediaPhoto(f))
        bot.send_media_group(CHANNEL_ID, media)
        # Закрываем файлы после отправки
        for f in open_files:
            f.close()
    # Очистка данных и уведомление
    user_data[uid] = {"photos": [], "comment": "", "folder": ""}
    bot.send_message(call.message.chat.id, "Фотоотчёт успешно отправлен в канал!")
    send_main_menu(call.message.chat.id, call.from_user.id)

# --- Отмена отчёта ---

@bot.callback_query_handler(func=lambda call: call.data == 'cancel')
def cancel_report(call):
    bot.answer_callback_query(call.id, "Отчет отменён.")
    uid = str(call.from_user.id)
    user_data[uid] = {"photos": [], "comment": "", "folder": ""}
    send_main_menu(call.message.chat.id, call.from_user.id)

# --- Запуск бота ---

if __name__ == '__main__':
    bot.polling(none_stop=True)
