import telebot
import json
import os
import re
import threading
import time
from datetime import datetime
from telebot import types
from collections import defaultdict

# ============ НАСТРОЙКИ ============

TOKEN = os.getenv('TOKEN')
CHANNEL_ID = '-1002495576009'

ALLOWED_USERS_FILE = 'allowed_users.json'
ADMINS_FILE = 'admins.txt'
LOCAL_REPORTS_BASE = 'reports'

user_data = defaultdict(lambda: {"photos": [], "comment": ""})

# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============

def sanitize_for_path(name: str) -> str:
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
            print(f"Ошибка при сохранении {file_id}: {e}")

# ============ ОСНОВНОЙ КОД БОТА ============

bot = telebot.TeleBot(TOKEN)

def send_main_menu(chat_id, user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = []
    if is_admin(user_id):
        buttons.append(types.KeyboardButton("Админ панель"))
    if is_user_allowed(user_id):
        buttons.append(types.KeyboardButton("Сделать фотоотчёт"))
    markup.add(*buttons)
    bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(message):
    send_main_menu(message.chat.id, message.from_user.id)

# ============ АДМИН-ПАНЕЛЬ ============

@bot.message_handler(func=lambda msg: msg.text == "Админ панель")
def admin_panel(message):
    if not is_admin(message.from_user.id):
        return bot.reply_to(message, "У вас нет прав доступа.")
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Добавить пользователя", "Список пользователей")
    markup.add("Удалить пользователя", "Назад")
    bot.send_message(message.chat.id, "🔧 Админ панель:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text == "Назад")
def back_to_main(message):
    send_main_menu(message.chat.id, message.from_user.id)

@bot.message_handler(func=lambda msg: msg.text == "Добавить пользователя")
def add_user_request(message):
    if not is_admin(message.from_user.id):
        return bot.reply_to(message, "У вас нет прав на добавление пользователей.")
    msg = bot.send_message(
        message.chat.id,
        "Введите ID и имя пользователя в формате: chat_id имя"
    )
    bot.register_next_step_handler(msg, add_user_by_text)

def add_user_by_text(message):
    if not is_admin(message.from_user.id):
        return bot.reply_to(message, "Нет прав на добавление!")
    try:
        chat_id, name = message.text.split(maxsplit=1)
        users = get_allowed_users()
        users[chat_id] = name
        save_allowed_users(users)
        bot.reply_to(message, f"Пользователь '{name}' добавлен.")
    except ValueError:
        bot.reply_to(message, "Ошибка формата. Используйте: chat_id имя")
    time.sleep(1)
    admin_panel(message)

@bot.message_handler(func=lambda msg: msg.text == "Список пользователей")
def show_user_list(message):
    if not is_admin(message.from_user.id):
        return bot.reply_to(message, "Нет доступа.")
    users = get_allowed_users()
    if not users:
        text = "Список пользователей пуст."
    else:
        text = "📋 <b>Список пользователей:</b>\n"
        for uid, name in users.items():
            text += f"🆔 <code>{uid}</code> — {name}\n"
    bot.send_message(message.chat.id, text, parse_mode='HTML')

# --- Новый код для удаления пользователя с инлайн-кнопками ---

@bot.message_handler(func=lambda msg: msg.text == "Удалить пользователя")
def delete_user_request(message):
    if not is_admin(message.from_user.id):
        return bot.reply_to(message, "Нет доступа.")
    
    users = get_allowed_users()
    if not users:
        return bot.send_message(message.chat.id, "Список пользователей пуст.")
    
    markup = types.InlineKeyboardMarkup()
    for uid, name in users.items():
        button = types.InlineKeyboardButton(text=name, callback_data=f"del_select_{uid}")
        markup.add(button)
    
    bot.send_message(message.chat.id, "Выбери пользователя для удаления:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_select_"))
def confirm_delete_user(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.")
        return
    
    user_id_to_delete = call.data[len("del_select_"):]
    users = get_allowed_users()
    user_name = users.get(user_id_to_delete, "Неизвестный пользователь")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(text="Да", callback_data=f"del_confirm_yes_{user_id_to_delete}"),
        types.InlineKeyboardButton(text="Нет", callback_data="del_confirm_no")
    )
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"Уверены, что хотите удалить пользователя '{user_name}'?",
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_confirm_"))
def process_delete_confirmation(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.")
        return
    
    if call.data == "del_confirm_no":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Удаление отменено."
        )
        bot.answer_callback_query(call.id)
        return
    
    if call.data.startswith("del_confirm_yes_"):
        user_id_to_delete = call.data[len("del_confirm_yes_"):]
        users = get_allowed_users()
        if user_id_to_delete in users:
            user_name = users.pop(user_id_to_delete)
            save_allowed_users(users)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Пользователь '{user_name}' удалён."
            )
        else:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Пользователь не найден."
            )
        bot.answer_callback_query(call.id)

# ============ ОТЧЁТЫ ============

@bot.message_handler(func=lambda msg: msg.text == "Сделать фотоотчёт")
def report_start(message):
    if not is_user_allowed(message.from_user.id):
        return bot.reply_to(message, "Нет доступа.")
    uid = str(message.from_user.id)
    user_data[uid] = {"photos": [], "comment": ""}
    msg = bot.send_message(message.chat.id, "Какой объект (комментарий)?")
    bot.register_next_step_handler(msg, handle_comment)

def handle_comment(message):
    uid = str(message.from_user.id)
    user_data[uid]["comment"] = message.text
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Завершить отчёт"))
    markup.add(types.KeyboardButton("Отменить отчёт"))
    bot.send_message(message.chat.id, "Теперь отправь фото. Когда закончишь, нажми 'Завершить отчёт'.", reply_markup=markup)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    uid = str(message.from_user.id)
    if not is_user_allowed(message.from_user.id):
        return bot.reply_to(message, "Нет доступа для отправки фото.")
    file_id = message.photo[-1].file_id
    user_data[uid]["photos"].append(file_id)

@bot.message_handler(func=lambda msg: msg.text == "Завершить отчёт")
def finish_report(message):
    uid = str(message.from_user.id)
    if not is_user_allowed(message.from_user.id):
        return bot.reply_to(message, "Нет доступа.")
    photos = user_data[uid]["photos"]
    comment_raw = user_data[uid]["comment"]
    name_raw = get_user_name(uid)
    chat_id_str = uid

    if not photos:
        return bot.send_message(message.chat.id, "Вы не отправили ни одной фотографии.")
    
    sending_msg = bot.send_message(message.chat.id, "Отправка...")

    caption = f"<b>Фотоотчёт от {name_raw}</b>\nКомментарий: {comment_raw}"
    chunk_size = 10
    for i in range(0, len(photos), chunk_size):
        group = photos[i:i + chunk_size]
        media_group = []
        for j, file_id in enumerate(group):
            if j == 0:
                media_group.append(types.InputMediaPhoto(media=file_id, caption=caption, parse_mode='HTML'))
            else:
                media_group.append(types.InputMediaPhoto(media=file_id))
        bot.send_media_group(CHANNEL_ID, media_group)

    safe_user_name = sanitize_for_path(name_raw)
    safe_comment = sanitize_for_path(comment_raw)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    photos_copy = list(photos)
    user_data[uid] = {"photos": [], "comment": ""}

    t = threading.Thread(
        target=save_photos_thread,
        args=(photos_copy, safe_user_name, safe_comment, chat_id_str, timestamp),
        daemon=True
    )
    t.start()

    bot.edit_message_text("Отчёт отправлен в канал.", chat_id=message.chat.id, message_id=sending_msg.message_id)
    send_main_menu(message.chat.id, message.from_user.id)

@bot.message_handler(func=lambda msg: msg.text == "Отменить отчёт")
def cancel_report(message):
    uid = str(message.from_user.id)
    user_data[uid] = {"photos": [], "comment": ""}
    bot.send_message(message.chat.id, "Отчёт отменён.")
    send_main_menu(message.chat.id, message.from_user.id)

# ============ ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ============

@bot.message_handler(func=lambda msg: True)
def fallback(message):
    send_main_menu(message.chat.id, message.from_user.id)

# ============ ЗАПУСК БОТА ============

if __name__ == '__main__':
    if not os.path.exists(LOCAL_REPORTS_BASE):
        os.makedirs(LOCAL_REPORTS_BASE)
    print("Бот запущен.")
    bot.infinity_polling()
