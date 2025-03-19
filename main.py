import telebot
import json
from telebot import types
from collections import defaultdict
import time
import os
from datetime import datetime

# Ваш токен бота и ID канала
TOKEN = '8155202361:AAG1oFGPtAfwMRuGhh5ZUg4bzv3VOmu9SMY'
CHANNEL_ID = '-1002495576009'
bot = telebot.TeleBot(TOKEN)

# Файлы с данными
ALLOWED_USERS_FILE = 'allowed_users.json'
ADMINS_FILE = 'admins.txt'

# Словарь для хранения альбомов и комментариев
user_data = defaultdict(lambda: {"photos": [], "comment": ""})

# Функция для чтения ID администраторов
def get_admins():
    try:
        with open(ADMINS_FILE, 'r', encoding='utf-8') as file:
            return set(file.read().strip().split())
    except FileNotFoundError:
        return set()

# Функция для чтения разрешенных пользователей
def get_allowed_users():
    try:
        with open(ALLOWED_USERS_FILE, 'r', encoding='utf-8') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Функция для записи разрешенных пользователей
def save_allowed_users(users):
    with open(ALLOWED_USERS_FILE, 'w', encoding='utf-8') as file:
        json.dump(users, file, ensure_ascii=False, indent=4)

# Функция для проверки, является ли пользователь администратором
def is_admin(user_id):
    return str(user_id) in get_admins()

# Функция для проверки, разрешен ли пользователь
def is_user_allowed(user_id):
    return str(user_id) in get_allowed_users()

# Получение имени пользователя по chat_id
def get_user_name(user_id):
    users = get_allowed_users()
    return users.get(str(user_id), "Неизвестный пользователь")

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if is_admin(message.from_user.id):
        markup.add(types.KeyboardButton("Добавить"))
    if is_user_allowed(message.from_user.id):
        markup.add(types.KeyboardButton("Сделать фотоотчёт"))
    if is_user_allowed(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "Бот для отправки фото объектов",
            reply_markup=markup
        )
    else:
        bot.send_message(message.chat.id, 'Доступ запрещен!')

@bot.message_handler(func=lambda message: message.text == "Добавить" and is_admin(message.from_user.id))
def request_user_data(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('Отмена'))
    bot.send_message(message.chat.id, "Введите ID и имя пользователя в формате: chat_id имя", reply_markup=markup)
    bot.register_next_step_handler(message, add_user_by_text)

# Обработчик добавления пользователя
def add_user_by_text(message):
    if message.text == 'Отмена':
        start(message)
        return
    
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У вас нет прав на добавление пользователей!")
        return

    try:
        chat_id, name = message.text.split(maxsplit=1)
        users = get_allowed_users()
        users[chat_id] = name
        save_allowed_users(users)
        bot.send_message(message.chat.id, f"Пользователь {name} (ID: {chat_id}) добавлен в список разрешенных!")
    except ValueError:
        bot.send_message(message.chat.id, "Ошибка! Используйте формат: chat_id имя")
    
    time.sleep(1)
    start(message)

# Обработчик нажатия на кнопку "Сделать фотоотчёт"
@bot.message_handler(func=lambda message: message.text == 'Сделать фотоотчёт')
def start_album(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('Отмена'))
    user_id = str(message.from_user.id)
    if not is_user_allowed(user_id):
        bot.reply_to(message, "Извините, у вас нет прав на отправку фотографий.")
        return

    # Очищаем предыдущие данные пользователя
    user_data[user_id] = {"photos": [], "comment": ""}

    bot.send_message(message.chat.id, 'Какой объект:', reply_markup=markup)

    bot.register_next_step_handler(message, handle_comment)

# Обработчик комментария
def handle_comment(message):
    if message.text == 'Отмена':
        start(message)
    else:
        user_id = str(message.from_user.id)
        user_data[user_id]["comment"] = message.text

        # Создаем папку для отчета
        folder_name = f"{message.text}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        os.makedirs(folder_name, exist_ok=True)
        user_data[user_id]["folder"] = folder_name

        # Добавляем кнопку "Завершить отчет"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("Завершить отчет"))
        markup.add(types.KeyboardButton('Отменить отчёт'))

        bot.send_message(
            message.chat.id,
            'Отправьте фото.',
            reply_markup=markup
        )

# Обработчик фотографий
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = str(message.from_user.id)
    if not is_user_allowed(user_id):
        bot.reply_to(message, "Извините, у вас нет прав на отправку фотографий.")
        return

    # Сохраняем фото
    photo_id = message.photo[-1].file_id
    user_data[user_id]["photos"].append(photo_id)

    # Скачиваем фото и сохраняем в папку
    file_info = bot.get_file(photo_id)
    downloaded_file = bot.download_file(file_info.file_path)
    folder_name = user_data[user_id]["folder"]
    with open(f"{folder_name}/{photo_id}.jpg", 'wb') as new_file:
        new_file.write(downloaded_file)

# Обработчик кнопки "Завершить отчет"
@bot.message_handler(func=lambda message: message.text == 'Завершить отчет')
def finish_report(message):
    user_id = str(message.from_user.id)
    if not is_user_allowed(user_id):
        bot.reply_to(message, "Извините, у вас нет прав на отправку фотографий.")
        return

    # Получаем данные пользователя
    photos = user_data[user_id]["photos"]
    comment = user_data[user_id]["comment"]
    user_name = get_user_name(user_id)

    if not photos:
        bot.reply_to(message, "Вы не отправили ни одного фото.")
        return

    # Отправляем фото в канал
    send_photos_to_channel(message, user_id, photos, user_name, comment)

    # Очищаем данные пользователя
    user_data[user_id] = {"photos": [], "comment": ""}

    # Убираем кнопку "Завершить отчет"
    markup = types.ReplyKeyboardRemove()
    bot.send_message(message.chat.id, "Фотоотчёт успешно отправлен в канал!", reply_markup=markup)
    time.sleep(2)
    start(message)

# Функция для отправки фото в канал
def send_photos_to_channel(message, user_id, photos, user_name, comment):
    # Разделяем фото на группы по 10 штук
    for i in range(0, len(photos), 10):
        group = photos[i:i + 10]
        media = []

        for j, photo in enumerate(group):
            if j == 0:  # Подпись только для первого фото
                media.append(types.InputMediaPhoto(photo, caption=f"Фотоотчёт от {user_name}\nКомментарий: {comment}"))
            else:
                media.append(types.InputMediaPhoto(photo))

        # Отправляем группу фото
        bot.send_media_group(CHANNEL_ID, media)


@bot.message_handler(func=lambda message: message.text == 'Отменить отчёт')
def back(message):
    bot.send_message(message.chat.id, "Вы снова в меню")
    start(message)

# Запуск бота
bot.polling(none_stop=True)
