import telebot
import json
from telebot import types
from collections import defaultdict

# Ваш токен бота и ID канала
TOKEN = '8155202361:AAG1oFGPtAfwMRuGhh5ZUg4bzv3VOmu9SMY'
CHANNEL_ID = '-1002495576009'
bot = telebot.TeleBot(TOKEN)

# Файлы с данными
ALLOWED_USERS_FILE = 'allowed_users.json'
ADMINS_FILE = 'admins.txt'

# Словарь для хранения альбомов
media_groups = defaultdict(list)

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
    bot.send_message(
        message.chat.id,
        "Привет! Ты можешь отправить фотоотчёт, если ты авторизован!",
        reply_markup=markup
    )

# Обработчик нажатия на кнопку "Добавить"
@bot.message_handler(func=lambda message: message.text == "Добавить" and is_admin(message.from_user.id))
def request_user_data(message):
    bot.send_message(message.chat.id, "Введите ID и имя пользователя в формате: chat_id имя")
    bot.register_next_step_handler(message, add_user_by_text)

# Обработчик добавления пользователя
def add_user_by_text(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У вас нет прав на добавление пользователей!")
        return

    try:
        chat_id, name = message.text.split(maxsplit=1)
        users = get_allowed_users()
        users[chat_id] = name
        save_allowed_users(users)
        bot.reply_to(message, f"Пользователь {name} (ID: {chat_id}) добавлен в список разрешенных!")
    except ValueError:
        bot.reply_to(message, "Ошибка! Используйте формат: chat_id имя")

@bot.message_handler(func=lambda message: message.text == 'Сделать фотоотчёт')
def start_album(message):
    bot.send_message(message.chat.id, 'Введите комментарий к фотоотчёту:')
    bot.register_next_step_handler(message, handle_comment)

# Обработчик комментария
def handle_comment(message):
    user_id = str(message.from_user.id)

    # Проверка, разрешён ли пользователь
    if not is_user_allowed(user_id):
        bot.reply_to(message, "Извините, у вас нет прав на отправку фотографий.")
        return

    # Сохраняем комментарий
    comment = message.text
    bot.send_message(message.chat.id, 'Отправьте ваш фотоотчёт (можно в виде альбома)')
    bot.register_next_step_handler(message, lambda msg: handle_photo_album(msg, comment))

def send_media_group_with_caption(photo_list, user_name, comment):
    """
    Отправляет медиа группу с подписью в канал.
    """
    media_files = []
    
    for i, msg in enumerate(photo_list):
        if i == 0:  # Подпись только для первого фото
            media_files.append(types.InputMediaPhoto(
                media=msg.photo[-1].file_id, 
                caption=f"Фотоотчёт от {user_name}\nКомментарий: {comment}"
            ))
        else:
            media_files.append(types.InputMediaPhoto(media=msg.photo[-1].file_id))
    
    # Отправка медиа группы
    bot.send_media_group(CHANNEL_ID, media_files)

# Обработчик фотографий (одиночных и альбомов)
def handle_photo_album(message, comment):
    user_id = str(message.from_user.id)

    # Проверка, разрешён ли пользователь
    if not is_user_allowed(user_id):
        bot.reply_to(message, "Извините, у вас нет прав на отправку фотографий.")
        return

    user_name = get_user_name(user_id)  # Получаем имя пользователя

    # Если это часть альбома
    if message.media_group_id:
        media_groups[message.media_group_id].append(message)

        # Если получено минимум 2 фото
        if len(media_groups[message.media_group_id]) >= 2:
            # Отправляем альбом
            send_media_group_with_caption(media_groups[message.media_group_id], user_name, comment)

            bot.send_message(message.chat.id, 'Фотоотчёт отправлен в канал')

            # Удаляем фото из списка
            del media_groups[message.media_group_id]
    else:
        # Если это одиночное фото
        caption = f"Фото от {user_name}\nКомментарий: {comment}"
        bot.send_photo(CHANNEL_ID, message.photo[-1].file_id, caption=caption)
        bot.send_message(message.chat.id, "Ваше фото отправлено в канал!")

# Обработчик медиагрупп
@bot.message_handler(content_types=['photo'])
def handle_media_group(message):
    if message.media_group_id:
        # Если это часть альбома, сохраняем в словарь
        media_groups[message.media_group_id].append(message)
    else:
        # Если это одиночное фото, обрабатываем его
        handle_photo_album(message, "")

# Запуск бота
bot.polling(none_stop=True)
