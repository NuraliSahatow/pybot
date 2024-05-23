import telebot
import sqlite3
from telebot import types
import requests
import time
import schedule
from PIL import Image, ImageDraw, ImageFont
import random
import io
import re
from crypto_pay_api_sdk import cryptopay
import uuid  
TOKEN = '7029336671:AAGUlJ3fBv-jNo4FWMd_-i_kHvRyGoLxj8E'
bot = telebot.TeleBot(TOKEN)
user_state = {}
user_checking_subscription = {}
referrals_earn = 0.5
min_withdraw = 10
tasks_per_page = 1  # Количество заданий на одной странице
Crypto = cryptopay.Crypto("190404:AA7vbdJlBtZnCldrWCsiftHV4GJIOKRfk8w") #default testnet = False
checked = False
withd = True
bonus_r = 1
channels_per_page = 1
# Подключение к базе данных
conn = sqlite3.connect('bot.db', check_same_thread=False)
cursor = conn.cursor()
user_checking_subscription = {}
captcha_answers = {}

# Генерация капчи
def generate_captcha():
    image = Image.new('RGB', (100, 40), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)

    # Генерация случайного текста
    text = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=5))
    draw.text((10, 5), text, font=font, fill=(0, 0, 0))

    # Сохранение изображения в байтовый поток
    byte_io = io.BytesIO()
    image.save(byte_io, 'PNG')
    byte_io.seek(0)

    return text, byte_io
# Инициализация базы данных
def init_db():
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance REAL DEFAULT 0,
        ref_link TEXT,
        referrals INTEGER DEFAULT 0,
        earnings REAL DEFAULT 0,
        first_reward_received BOOLEAN DEFAULT FALSE,
        referred_by INTEGER DEFAULT NULL,
        earneds	DEFAULT 0
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_type TEXT,
        description TEXT,
        link TEXT,
        reward REAL,
        verification_needed BOOLEAN,
        interval_limit INTEGER DEFAULT 0,
        max_executions_per_hour INTEGER DEFAULT 0
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_tasks (
        user_id INTEGER,
        task_id INTEGER,
        completion_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending',
        report TEXT DEFAULT NULL,
        channel_link TEXT,
        reward INTEGER,
        checked TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (task_id) REFERENCES tasks(task_id),
        UNIQUE(user_id, task_id)
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS start_channels (
        channel_id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_link TEXT
    )
    ''')
    conn.commit()
referred_by = None

def check_all_tasks():
    cursor.execute("SELECT user_id, task_id, channel_link, reward FROM user_tasks WHERE status = 'completed'")
    tasks = cursor.fetchall()
    for task in tasks:
        user_id, task_id, channel_link = task
        if not check_channel_membership(user_id, channel_link):
            bot.send_message(user_id,f"Кто это хотел меня обмануть? Ты отписался из канала {channel_link}! Было изято с вашего баланса {reward*2}")
            mreward = reward*2
            cursor.execute("UPDATE balance FROM users WHERE user_id= ?",(-mreward))
            cursor.execute("DELETE * FROM user_tasks WHERE status = 'completed', user_id = ?, channel_link= ?", (user_id,channel_link))

# Подсчет всех заданий
def count_all_tasks():
    cursor.execute('SELECT COUNT(*) FROM tasks')
    return cursor.fetchone()[0]

# Получение всех заданий с пагинацией
def get_all_tasks_with_pagination(offset=0, limit=tasks_per_page):
    cursor.execute('SELECT task_id, task_type, description, link, reward, verification_needed FROM tasks LIMIT ? OFFSET ?', (limit, offset))
    return cursor.fetchall()

# Удаление задания по ID
def delete_task(task_id):
    cursor.execute('DELETE FROM tasks WHERE task_id = ?', (task_id,))
    conn.commit()
# Регистрация пользователя
def register_user(user_id, referred_by=None):
    ref_link = f'https://t.me/TurkeyMatching_Bot?start={user_id}'
    cursor.execute('INSERT OR IGNORE INTO users (user_id, ref_link, referred_by) VALUES (?, ?, ?)', (user_id, ref_link, referred_by))
    if referred_by:
        cursor.execute('UPDATE users SET referrals = referrals + 1 WHERE user_id = ?', (referred_by,))
    conn.commit()

# Обновление баланса
def update_balance(user_id, amount):
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
def update_balance2(user_id, amount):
    cursor.execute('UPDATE users SET earneds = earneds + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
# Получение информации о пользователе
def get_user_info(user_id):
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

# Проверка, зарегистрирован ли пользователь
def is_registered(user_id):
    cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone() is not None

# Получение всех заданий
def get_all_tasks():
    cursor.execute('SELECT * FROM tasks')
    return cursor.fetchall()

# Получение задания по ID
def get_task_by_id(task_id):
    cursor.execute('SELECT * FROM tasks WHERE task_id = ?', (task_id,))
    return cursor.fetchone()


# Получение невыполненных заданий пользователем
def get_user_tasks(user_id, task_type, offset=0, limit=tasks_per_page):
    cursor.execute('''
        SELECT t.task_id, t.task_type, t.description, t.link, t.reward, t.verification_needed
        FROM tasks t
        LEFT JOIN user_tasks ut ON t.task_id = ut.task_id AND ut.user_id = ?
        WHERE (ut.status IS NULL OR ut.status != 'completed') AND t.task_type = ?
        LIMIT ? OFFSET ?
    ''', (user_id, task_type, limit, offset))
    return cursor.fetchall()

# Подсчет количества невыполненных заданий пользователем
def count_user_tasks(user_id, task_type):
    cursor.execute('''
        SELECT COUNT(*)
        FROM tasks t
        LEFT JOIN user_tasks ut ON t.task_id = ut.task_id AND ut.user_id = ?
        WHERE (ut.status IS NULL OR ut.status != 'completed') AND t.task_type = ?
    ''', (user_id, task_type))
    return cursor.fetchone()[0]

# Добавление задания
def add_task(task_type, description, link, reward, verification_needed):
    cursor.execute('''
    INSERT INTO tasks (task_type, description, link, reward, verification_needed)
    VALUES (?, ?, ?, ?, ?)
    ''', (task_type, description, link, reward, verification_needed))
    conn.commit()
def send_task_page(chat_id, user_id, task_type, page=1):
    offset = (page - 1) * tasks_per_page
    tasks = get_user_tasks(user_id,task_type=task_type, offset=offset, limit=tasks_per_page)
    total_tasks = count_user_tasks(user_id,task_type=task_type)
    total_pages = (total_tasks + tasks_per_page - 1) // tasks_per_page

    if tasks:
        for task in tasks:
            if task[1] == task_type:
                description, link, reward, verification_needed = task[2], task[3], task[4], task[5]
                markup = types.InlineKeyboardMarkup()
                button = types.InlineKeyboardButton(text="Выполнить задание", callback_data=f"complete_{task[0]}")
                if task[1] == "Просмотры":
                    button = types.InlineKeyboardButton(text="Выполнить задание", callback_data=f"view_{task[0]}")
                markup.add(button)
                bot.send_message(chat_id, f"{description}\nСсылка: {link}\nНаграда: ${reward}", reply_markup=markup)
        
        # Пагинация
        pagination_markup = types.InlineKeyboardMarkup()
        if page > 1:
            pagination_markup.add(types.InlineKeyboardButton(text="<", callback_data=f"prev_{task_type}_{page-1}"))
        if page < total_pages:
            pagination_markup.add(types.InlineKeyboardButton(text=">", callback_data=f"next_{task_type}_{page+1}"))
        bot.send_message(chat_id, f"Страница {page} из {total_pages}", reply_markup=pagination_markup)
    else:
        bot.send_message(chat_id, "Нет доступных заданий.")
def check_subscription(user_id, channel):
    try:
        # Извлекаем имя канала из URL
        if channel.startswith("https://t.me/"):
            parts = channel.split("/")
            channel_id = parts[3] if len(parts) > 3 else parts[2]
            if not channel_id.startswith("@"):
                channel_id = "@" + channel_id
        else:
            channel_id = channel

        status = bot.get_chat_member(channel_id, user_id).status
        return status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Error checking subscription: {e}")
        return False

# Получение списка каналов из базы данных
def get_start_channels():
    cursor.execute('SELECT channel_link FROM start_channels')
    return cursor.fetchall()

# Проверка подписки на стартовые каналы
def check_start_channels(user_id):
    channels = get_start_channels()
    for channel in channels:
        if not check_subscription(user_id, channel[0]):
            return False
    return True

# Функция отправки сообщения с каналами для подписки
def send_start_channels(user_id):
    channels = get_start_channels()
    markup = types.InlineKeyboardMarkup()
    for channel in channels:
        markup.add(types.InlineKeyboardButton(text="Подписаться", url=channel[0]))
    markup.add(types.InlineKeyboardButton(text="Проверить подписку ✅", callback_data="check_start_channels"))
    try:
        bot.send_message(user_id, "👋 Привет!\nРад видеть тебя в нашем боте! Тут ты можешь зарабатывать $$$ за выполнение простых заданий. Для работы с ботом подпишитесь на наш канал. Связь с администратором - @nickname.", reply_markup=markup)
    except telebot.apihelper.ApiTelegramException as e:
        if e.result_json['description'] == "Forbidden: bots can't send messages to bots":
            print(f"Cannot send message to bot: {user_id}")

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    global user_checking_subscription
    global referred_by
    user_id = message.from_user.id
    user_language_code = message.from_user.language_code
    user_checking_subscription[user_id] = False  # Инициализация состояния для пользователя
    allowed_languages = ['ru', 'uk', 'be', 'kk','en']
    print(user_language_code)
    if user_language_code not in allowed_languages:
       
        return
    if len(message.text.split()) > 1:
        try:
            referred_by = int(message.text.split()[1])
        except ValueError:
            referred_by = None

    if not is_registered(user_id):
        user_state[user_id] = 'awaiting_captcha'
                # Генерация капчи
        text, image = generate_captcha()
        captcha_answers[user_id] = text

        bot.send_photo(user_id, image, caption="Пожалуйста, введите текст с картинки:")
    elif is_registered(user_id):
        markup = types.ReplyKeyboardMarkup(row_width=2)
        if user_id == 5566384153 or user_id == 6011382957:
            markup.add('👤 Мой аккаунт', '📓 Информация', '🧑🏻‍💼 Поддержка', '🧩 Заработок', '🚨 Админка')
        else:
            markup.add('👤 Мой аккаунт', '📓 Информация', '🧑🏻‍💼 Поддержка', '🧩 Заработок')
        bot.send_message(user_id, "Для начало выберите любую из опций ниже:", reply_markup=markup)
        



@bot.message_handler(func=lambda message: user_state.get(message.from_user.id) == 'awaiting_captcha')
def check_captcha(message):
    user_id = message.from_user.id
    if message.text.upper() == captcha_answers[user_id]:
        bot.send_message(user_id, "Капча пройдена! Добро пожаловать!")
        user_state.pop(user_id, None)
        captcha_answers.pop(user_id, None)

        # Здесь можно продолжить регистрацию пользователя или отправку приветственного сообщения
        bot.send_message(user_id, "Теперь вы можете использовать бота.")
        if not is_registered(user_id):
            send_start_channels(user_id)
            return
    else:
        bot.send_message(user_id, "Неверный ответ. Пожалуйста, попробуйте снова.")
        text, image = generate_captcha()
        captcha_answers[user_id] = text
        bot.send_photo(user_id, image, caption="Пожалуйста, введите текст с картинки:")

# Обработчик проверки подписок на стартовые каналы
@bot.callback_query_handler(func=lambda call: call.data == "check_start_channels")
def check_start_channels_callback(call):
    global user_checking_subscription
    global referred_by
    user_id = call.from_user.id
    if check_start_channels(user_id):

        register_user(user_id, referred_by)
        user_info = get_user_info(user_id)
        if user_info and len(user_info) > 6 and not user_info[5]:  # first_reward_received
            update_balance(user_id, bonus_r)  # Начальная награда
            update_balance2(user_id,bonus_r)
            cursor.execute('UPDATE users SET first_reward_received = TRUE WHERE user_id = ?', (user_id,))
            conn.commit()
            markup = types.ReplyKeyboardMarkup(row_width=2)
            if user_id == 5566384153 or user_id == 6011382957:
                markup.add('👤 Мой аккаунт', '📓 Информация', '🧑🏻‍💼 Поддержка', '🧩 Заработок', '🚨 Админка')
            else:
                markup.add('👤 Мой аккаунт', '📓 Информация', '🧑🏻‍💼 Поддержка', '🧩 Заработок')
            bot.send_message(user_id, "☑️ Вы успешно подписались на канал!\nДля заработка выберите любую из опций ниже:", reply_markup=markup)
            if referred_by:
                update_balance(referred_by, referrals_earn)  # Награда за реферала
                cursor.execute('UPDATE users SET earnings = earnings + ? WHERE user_id = ?', (referrals_earn, referred_by))
                conn.commit()
                try:
                    bot.send_message(referred_by, f"Вы получили {referrals_earn} за приглашение нового пользователя.")
                except telebot.apihelper.ApiTelegramException as e:
                    if e.result_json['description'] == "Forbidden: bots can't send messages to bots":
                        print(f"Cannot send message to bot: {referred_by}")
    else:
        bot.send_message(user_id, "Вы не подписались на все необходимые каналы. Пожалуйста, подпишитесь и попробуйте снова.")





# Обработчик кнопки "Мой аккаунт"
@bot.message_handler(func=lambda message: message.text == '👤 Мой аккаунт')
def my_account(message):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    if user_info:
        # Use default values if user_info[4] or user_info[7] is None
        earnings_from_referrals = user_info[4] if user_info[4] is not None else 0.0
        earnings_from_tasks = user_info[7] if user_info[7] is not None else 0.0
        
        response = (f"📌 Информация о вашем аккаунте:\n\n"
                    f"🏦 Баланс: {user_info[1]}$\n"
                    f"🔗 Пригласить друга: {user_info[2]}\n"
                    f"👥 Приглашенных друзей: {user_info[3]}\n"
                    f"💳 Заработок с рефералов: {earnings_from_referrals}$\n"
                    f"💳 Заработок с заданий: ${earnings_from_tasks}\n"
                    f"💲Общий заработок: {earnings_from_tasks + earnings_from_referrals}$")
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💸 Вывести", callback_data="withdraw"))
        bot.send_message(user_id, response, reply_markup=markup)
# Обработчик кнопки "Информация"
@bot.message_handler(func=lambda message: message.text == '📓 Информация')
def information(message):
    response = ("Количество пользователей: X\nВыплачено: Y$\n[Чат](https://t.me/chat)\n[Канал](https://t.me/channel)\n[Контакт](https://t.me/@pandistt)")
    bot.send_message(message.from_user.id, response, parse_mode='Markdown')

# Обработчик кнопки "Поддержка"
@bot.message_handler(func=lambda message: message.text == '🧑🏻‍💼 Поддержка')
def support(message):
    response = (f"[Контакт админа](https://t.me/admin)\n[FAQ](https://example.com/faq)\n[Информация](https://t.me/bot_info)")
    bot.send_message(message.from_user.id, response, parse_mode='Markdown')

# Обработчик кнопки "Заработок"
@bot.message_handler(func=lambda message: message.text == '🧩 Заработок')
def earnings(message):
    markup = types.ReplyKeyboardMarkup(row_width=2)
    markup.add('🫂Подписки', '👀Просмотры', '✍️Комментарии', '📌Задания', 'Главное Меню')
    bot.send_message(message.from_user.id, "Выберите способ заработка:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == 'Главное Меню')
def main_menu(message):
    global user_state
    user_state = {}
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=2)
    if user_id == 5566384153 or user_id == 6011382957:
        markup.add('👤 Мой аккаунт', '📓 Информация', '🧑🏻‍💼 Поддержка', '🧩 Заработок', '🚨 Админка')
    else:
        markup.add('👤 Мой аккаунт', '📓 Информация', '🧑🏻‍💼 Поддержка', '🧩 Заработок')
    
    bot.send_message(user_id, "Выберите опцию:", reply_markup=markup)
def count_all_channels():
    cursor.execute('SELECT COUNT(*) FROM start_channels')
    return cursor.fetchone()[0]

# Получение всех каналов с пагинацией
def get_all_channels_with_pagination(offset=0, limit=channels_per_page):
    cursor.execute('SELECT channel_id, channel_link FROM start_channels LIMIT ? OFFSET ?', (limit, offset))
    return cursor.fetchall()

# Удаление канала по ID
def delete_channel(channel_id):
    cursor.execute('DELETE FROM start_channels WHERE channel_id = ?', (channel_id,))
    conn.commit()
# Обработчик кнопки "Подписки"
@bot.message_handler(func=lambda message: message.text == '🫂Подписки')
def subscriptions(message):
    send_task_page(message.chat.id, message.from_user.id, 'Подписки')

# Обработчик кнопки "Просмотры"
@bot.message_handler(func=lambda message: message.text == '👀Просмотры')
def views(message):
    send_task_page(message.chat.id, message.from_user.id, 'Просмотры')

# Обработчик кнопки "Комментарии"
@bot.message_handler(func=lambda message: message.text == '✍️Комментарии')
def comments(message):
    send_task_page(message.chat.id, message.from_user.id, 'Комментарии')

# Обработчик кнопки "Задания"
@bot.message_handler(func=lambda message: message.text == '📌Задания')
def tasks(message):
    send_task_page(message.chat.id, message.from_user.id, 'Задания')

# Обработчик кнопок пагинации
@bot.callback_query_handler(func=lambda call: call.data.startswith("prev_") or call.data.startswith("next_"))
def handle_pagination(call):
    data = call.data.split("_")
    direction, task_type, page = data[0], data[1], int(data[2])
    if direction == "prev":
        send_task_page(call.message.chat.id, call.from_user.id, task_type, page)
    elif direction == "next":
        send_task_page(call.message.chat.id, call.from_user.id, task_type, page)

# Обработчик завершения задания
@bot.callback_query_handler(func=lambda call: call.data.startswith("view_") or call.data.startswith("complete_") or call.data.startswith("report_"))
def complete_task(call):
    user_id = call.from_user.id
    task_id = int(call.data.split("_")[1])
    task = get_task_by_id(task_id)
    username = call.from_user.username
    admin_id = 5566384153
    admin_id2 = 6011382957 
    if task:
        # Проверка, выполнял ли пользователь уже это задание
        cursor.execute('SELECT status FROM user_tasks WHERE user_id = ? AND task_id = ?', (user_id, task_id))
        user_task = cursor.fetchone()
        if user_task and user_task[0] == 'completed':
            bot.send_message(user_id, "Вы уже выполнили это задание.")
            send_task_page(call.from_user.id, user_id, task[1])
            return
        
        if call.data.startswith("view_"):
            # Проверка подписки на канал перед выполнением задания
            if not check_subscription(user_id, task[3]):
                bot.send_message(user_id, "Пожалуйста, подпишитесь на канал и повторите попытку.")
                return

            # Извлечение channel_id и message_id из ссылки
            match = re.match(r'https://t.me/([^/]+)/(\d+)', task[3])
            if match:
                channel_id = '@' + match.group(1)
                message_id = int(match.group(2))

                # Пересылка сообщения из канала пользователю
                try:
                    bot.forward_message(user_id, channel_id, message_id)
                    markup = types.InlineKeyboardMarkup()
                    button = types.InlineKeyboardButton(text="Подтвердить выполнение", callback_data=f"complete_{task_id}")
                    markup.add(button)
                    bot.send_message(user_id, "Проверьте сообщение выше и подтвердите выполнение задания.", reply_markup=markup)
                except Exception as e:
                    bot.send_message(user_id, f"Ошибка при пересылке сообщения: {str(e)}")
            else:
                bot.send_message(user_id, "Некорректная ссылка на сообщение.")
        elif call.data.startswith("complete_"):
            if task[5]==1 or task[5]=='да':  # verification_needed
                if  task[1] == 'Просмотры':
                    update_balance(user_id, task[4])
                    update_balance2(user_id, task[4])
                    bot.send_message(user_id, f"Задание выполнено. Вы получили ${task[4]}")
                    cursor.execute('INSERT INTO user_tasks (user_id, task_id, status, channel_link,reward) VALUES (?, ?, ?, ?,?)', (user_id, task_id, 'completed',task[3],task[4]))
                elif task[5] == 1 or task[5] == 'да':
                    bot.send_message(user_id,"Отправьте отчет ниже")
                    user_state[user_id] = {'task_id': task_id, 'awaiting_report': True}
            elif task[5] == 0:
                if check_subscription(user_id, task[3]):
                    update_balance(user_id, task[4])
                    update_balance2(user_id, task[4])
                    bot.send_message(user_id, f"Задание выполнено. Вы получили ${task[4]}")
                    cursor.execute('INSERT INTO user_tasks (user_id, task_id, status, channel_link,reward) VALUES (?, ?, ?, ?,?)', (user_id, task_id, 'completed',task[3],task[4]))
                    send_task_page(call.from_user.id, user_id, task[1])
                else:
                    bot.send_message(user_id, "Пожалуйста, подпишитесь на канал и повторите попытку.")
            else:
                print("GGGG")
            conn.commit()
        elif call.data.startswith("report_"):
            user_state[user_id] = {
                'task_id': task_id,
                'report': True
            }
            #bot.send_message(user_id, "Пожалуйста, отправьте отчет в следующем сообщении.")

@bot.message_handler(content_types=['photo'], func=lambda message: user_state.get(message.from_user.id, {}).get('awaiting_report'))
def handle_report_photo(message):
    user_id = message.from_user.id
    task_id = user_state[user_id]['task_id']
    task = get_task_by_id(task_id)
    username = message.from_user.username
    admin_id = 5566384153
    admin_id2 = 6011382957
    
    # Get the file ID of the photo
    photo_file_id = message.photo[-1].file_id  # Telegram sends multiple sizes, we take the largest one
    report = photo_file_id  # Store the file ID as a string

    cursor.execute('''
        INSERT INTO user_tasks (user_id, task_id, status, report,checked) 
        VALUES (?, ?, ?, ?,?) 
        ON CONFLICT(user_id, task_id) DO UPDATE SET report = EXCLUDED.report
    ''', (user_id, task_id, 'completed', report,'no'))
    
    conn.commit()
    
    bot.send_message(user_id, "Ваш отчет был отправлен на проверку.")
    bot.send_photo(admin_id, photo_file_id)
    bot.send_photo(admin_id2, photo_file_id)
    
    send_task_page(message.from_user.id, user_id, task[1])
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Оплатить", callback_data=f"approve_{user_id}_{task_id}"),
               types.InlineKeyboardButton("Отклонить", callback_data=f"reject_{user_id}_{task_id}"))
    
    bot.send_message(admin_id, f"Отчет от пользователя @{username} для задания {task_id}:\nСкриншотом", reply_markup=markup)
    bot.send_message(admin_id2, f"Отчет от пользователя @{username} для задания {task_id}:\nСкриншотом", reply_markup=markup)
    
    user_state.pop(user_id)

# Обработчик сообщений с отчетами# Обработчик сообщений с отчетами
@bot.message_handler(func=lambda message: message.from_user.id in user_state and 'awaiting_report' in user_state[message.from_user.id])
def handle_report(message):
    admin_id = 5566384153
    admin_id2 = 6011382957 
    user_id = message.from_user.id
    username = message.from_user.username

    task_id = user_state[user_id]['task_id']
    task = get_task_by_id(task_id)
    if message.content_type == 'text':
        report = message.text
    # Handle photo reports
    elif message.content_type == 'photo':
        print("photo")
        # Get the photo file ID
        photo_file_id = message.photo[-1].file_id  # Telegram sends multiple sizes, we take the largest
        # Forward the photo to the admin
        bot.forward_photo(admin_id, photo_file_id)
        bot.forward_photo(admin_id2, photo_file_id)
        report = f"Photo report: {photo_file_id}"

    cursor.execute('''
        INSERT INTO user_tasks (user_id, task_id, status, report,checked) 
        VALUES (?, ?, ?, ?,?) 
        ON CONFLICT(user_id, task_id) DO UPDATE SET report = EXCLUDED.report
    ''', (user_id, task_id, 'completed', report,'no'))
    bot.send_message(user_id, "Ваш отчет был отправлен на проверку.")
    send_task_page(message.from_user.id, user_id, task[1])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Оплатить", callback_data=f"approve_{user_id}_{task_id}"),
               types.InlineKeyboardButton("Отклонить", callback_data=f"reject_{user_id}_{task_id}"))
    bot.send_message(admin_id, f"Отчет от пользователя @{username} для задания {task_id}:\n{report}", reply_markup=markup)
    bot.send_message(admin_id2, f"Отчет от пользователя @{username} для задания {task_id}:\n{report}", reply_markup=markup)
    user_state.pop(user_id)

# Уведомление администратора для ручной проверки
def notify_admin_for_manual_verification(user_id, task_id):
    admin_id = 5566384153  # ID администратора
    admin_id2 = 6011382957
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Оплатить", callback_data=f"approve_{user_id}_{task_id}"),
               types.InlineKeyboardButton("Отклонить", callback_data=f"reject_{user_id}_{task_id}"))
    bot.send_message(admin_id, f"Поступила новая заявка на проверку задания от пользователя {user_id} для задания {task_id}.", reply_markup=markup)
    bot.send_message(admin_id2, f"Поступила новая заявка на проверку задания от пользователя {user_id} для задания {task_id}.", reply_markup=markup)

# Обработчик админских решений
def get_user_taskl(user_id,task_id):
    cursor.execute('SELECT * from user_tasks  WHERE user_id = ? AND task_id = ? AND checked = ?', (user_id, task_id,'no'))
    return cursor.fetchone()
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def admin_decision(call):
    data = call.data.split("_")
    action, user_id, task_id = data[0], int(data[1]), int(data[2])
    task = get_task_by_id(task_id)
    utask = get_user_taskl(user_id,task_id)
    try:
        if action == "approve" and checked == False:
            if task and utask[7]=='no' and utask:
                update_balance(user_id, task[4])
                update_balance2(user_id, task[4])
                bot.send_message(user_id, f"Ваше задание {task_id} было одобрено. Вы получили ${task[4]}")
                cursor.execute('UPDATE user_tasks SET status = ?, checked = ? WHERE user_id = ? AND task_id = ? ', ('completed','yes', user_id, task_id))
                conn.commit()
                bot.send_message(call.from_user.id, f"Решение по заданию {task_id} для пользователя {user_id} принято.")
        elif action == "reject" and utask[7]=='no':
            bot.send_message(user_id, f"Ваше задание {task_id} было отклонено.")
            cursor.execute('UPDATE user_tasks SET status = ?,checked = ?  WHERE user_id = ? AND task_id = ?', ('completed','yes', user_id, task_id))
            conn.commit()
            bot.send_message(call.from_user.id, f"Решение по заданию {task_id} для пользователя {user_id} принято.")
        elif task and utask[7]=='yes':
            bot.send_message(call.from_user.id, f"Вы уже проверяли задание {task_id} для пользователя {user_id}.")
    except Exception as e:
        bot.send_message(call.from_user.id, f"Вы уже проверяли задание {task_id} для пользователя {user_id}.")
    

# Обработчик вывода средств
@bot.callback_query_handler(func=lambda call: call.data == "withdraw")
def withdraw(call):
    global withd
    user_id = call.from_user.id
    user_info = get_user_info(user_id)
    if user_info and user_info[1] >= min_withdraw and withd == True:  # Минимальная сумма вывода
        bot.send_message(user_id, f"Ваш баланс:{user_info[1]}\nВведите количество USDT для вывода:")
        user_state[user_id] = 'awaiting_withdraw_amount'
    elif withd == False:
        bot.send_message(user_id, "Выплаты выключены!")
    else:
        bot.send_message(user_id, "Недостаточно средств для вывода.")

@bot.message_handler(func=lambda message: user_state.get(message.from_user.id) == 'awaiting_withdraw_amount')
def handle_withdraw_amount(message):
    try:
        user_id = message.from_user.id
        user_info = get_user_info(user_id)
        amount = float(message.text)
        user_id = message.from_user.id
        admin_id = 5566384153
        admin_id2 = 6011382957
        if amount > 0 and amount <= user_info[1] :
            if amount >= min_withdraw:
                try:
                    transfer_result = Crypto.transfer(user_id, 'USDT', amount, str(uuid.uuid4()), params={'comment': 'Вывод от бота'})
                    if 'error' in transfer_result:
                        print(transfer_result)
                        if transfer_result['error']['name'] == 'INSUFFICIENT_FUNDS':
                            bot.send_message(user_id, "Произошла ошибка при выводе средств. Пожалуйста, попробуйте еще раз позже.")
                            bot.send_message(admin_id, "Внимание! У вас в Crypto Bot закончились деньги!\nЛюди нее могу выводить")
                            bot.send_message(admin_id2, "Внимание! У вас в Crypto Bot закончились деньги!\nЛюди нее могу выводить")
                        elif transfer_result['error']['name'] == 'AMOUNT_TOO_SMALL':
                            bot.send_message(user_id, "Минимальное количество для вывода 2$.")
                        elif transfer_result['error']['name'] == 'USER_NOT_FOUND':
                            bot.send_message(user_id, "Чтобы вывести баланс вы должны нажать /start в боте @CryptoBot.")
                    else:
                        bot.send_message(user_id, f"Вывод {amount} USDT успешно выполнен.")
                        update_balance(user_id, -amount)
                        conn.commit()
                        user_state.pop(user_id)
                except Exception as e:
                    print(f"Error during withdrawal: {e}")
                    bot.send_message(user_id, "Произошла ошибка при выводе средств. Пожалуйста, попробуйте еще раз позже.")
            else:
                bot.send_message(user_id, f"Минимальное количество для вывода {min_withdraw}")
        elif amount<0:
            bot.send_message(user_id, "Введите положительное число.")
        elif amount > user_info[1]:
            bot.send_message(user_id, f"У вас не хватает средств для вывода, ваш баланс {user_info[1]}.")
    except ValueError:
        bot.send_message(user_id, "Ошибка! Введите число.")

# Функция рассылки сообщений
@bot.message_handler(commands=['рассылка'])
def handle_broadcast(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        try:
            message_text = message.text.split(maxsplit=1)[1]
            cursor.execute('SELECT user_id FROM users')
            users = cursor.fetchall()
            for user in users:
                try:
                    bot.send_message(user[0], message_text,parse_mode='HTML')
                except Exception as e:
                    print(f"Failed to send message to user {user[0]}: {e}")
            bot.send_message(user_id, "Рассылка завершена.")
        except IndexError:
            bot.send_message(user_id, "Используйте команду в формате /рассылка <текст>")
    else:
        bot.send_message(user_id, "Мы не нашли ничего по этому запросу")

# Админ Меню
@bot.message_handler(func=lambda message: message.text == '🚨 Админка')
def admin_menu(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        markup = types.ReplyKeyboardMarkup(row_width=2)
        markup.add('Настройка бонуса','Настройка рефералов', 'Добавить задание', 'Добавить канал', 'Изменить минимальную сумму вывода', 'Удалить канал','Удалить задание','Главное Меню','Пополнить баланс бота','Остановить выплаты','Включить выплаты')
        bot.send_message(user_id, "Выберите что хотите сделать:", reply_markup=markup)
    else:
        bot.send_message(user_id, "Мы не нашли ничего по этому запросу")

@bot.message_handler(func=lambda message: message.text == 'Остановить выплаты')
def withdoff(message):
    global withd
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        withd = False
        markup = types.ReplyKeyboardMarkup(row_width=2)
        markup.add('Настройка бонуса','Настройка рефералов', 'Добавить задание', 'Добавить канал', 'Изменить минимальную сумму вывода', 'Удалить канал','Удалить задание','Главное Меню','Пополнить баланс бота','Остановить выплаты','Включить выплаты')
        bot.send_message(user_id, "Выплаты остановлены", reply_markup=markup)
    else:
        bot.send_message(user_id, "Мы не нашли ничего по этому запросу")
@bot.message_handler(func=lambda message: message.text == 'Включить выплаты')
def withdoff(message):
    global withd
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        withd = True
        markup = types.ReplyKeyboardMarkup(row_width=2)
        markup.add('Настройка бонуса','Настройка рефералов', 'Добавить задание', 'Добавить канал', 'Изменить минимальную сумму вывода', 'Удалить канал','Удалить задание','Главное Меню','Пополнить баланс бота','Остановить выплаты','Включить выплаты')
        bot.send_message(user_id, "Выплаты включены", reply_markup=markup)
    else:
        bot.send_message(user_id, "Мы не нашли ничего по этому запросу")
# Обработчик кнопки "Удалить задание"
@bot.message_handler(func=lambda message: message.text == 'Удалить задание')
def delete_task_step_1(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        send_tasks_page(message.chat.id, 1)
@bot.message_handler(func=lambda message: message.text == 'Пополнить баланс бота')
def add_funds(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        user_state[user_id] = 'awaiting_add_funds'
        bot.send_message(user_id, "Введите количесвто USDT которые хотите пополнить:")


def send_tasks_page(chat_id, page=1):
    offset = (page - 1) * tasks_per_page
    tasks = get_all_tasks_with_pagination(offset=offset, limit=tasks_per_page)
    total_tasks = count_all_tasks()
    total_pages = (total_tasks + tasks_per_page - 1) // tasks_per_page

    if tasks:
        for task in tasks:
            task_id, task_type, description, link, reward, verification_needed = task[:6]
            markup = types.InlineKeyboardMarkup()
            button = types.InlineKeyboardButton(text="Удалить", callback_data=f"delete_task_{task_id}")
            markup.add(button)
            bot.send_message(chat_id, f"Тип: {task_type}\nОписание: {description}\nСсылка: {link}\nНаграда: ${reward}", reply_markup=markup)
        
        # Пагинация
        pagination_markup = types.InlineKeyboardMarkup()
        if page > 1:
            pagination_markup.add(types.InlineKeyboardButton(text="<", callback_data=f"dprev_task_{page-1}"))
        if page < total_pages:
            pagination_markup.add(types.InlineKeyboardButton(text=">", callback_data=f"dnext_task_{page+1}"))
        bot.send_message(chat_id, f"Страница {page} из {total_pages}", reply_markup=pagination_markup)
    else:
        bot.send_message(chat_id, "Нет доступных заданий.")

# Получение всех заданий с пагинацией
def get_all_tasks_with_pagination(offset=0, limit=tasks_per_page):
    cursor.execute('SELECT task_id, task_type, description, link, reward, verification_needed FROM tasks LIMIT ? OFFSET ?', (limit, offset))
    return cursor.fetchall()

# Обработчик кнопок пагинации и удаления заданий
@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_task_") or call.data.startswith("dprev_task_") or call.data.startswith("dnext_task_"))
def handle_task_actions(call):
    if call.data.startswith("delete_task_"):
        task_id = int(call.data.split("_")[2])
        delete_task(task_id)
        bot.send_message(call.message.chat.id, f"Задание {task_id} было удалено.")
        send_tasks_page(call.message.chat.id, 1)  # Перезагрузить страницу с заданиями
    elif call.data.startswith("dprev_task_") or call.data.startswith("dnext_task_"):
        page = int(call.data.split("_")[2])
        send_tasks_page(call.message.chat.id, page)

# Обработчик кнопки "Настройка рефералов"
@bot.message_handler(func=lambda message: message.text == 'Настройка рефералов')
def referral_setting(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        user_state[user_id] = 'awaiting_referral_earn'
        bot.send_message(user_id, f"Нынешняя оплата за реферала: {referrals_earn}\nЧтобы изменить награду, отправьте цифрой на сколько хотите изменить.\nНапример '0.5'")
@bot.message_handler(func=lambda message: message.text == 'Настройка бонуса')
def referral_setting(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        user_state[user_id] = 'awaiting_bonus_earn'
        bot.send_message(user_id, f"Нынешный  бонус за привествия: {bonus_r}\nЧтобы изменить награду, отправьте цифрой на сколько хотите изменить.\nНапример '0.5'")
@bot.message_handler(func=lambda message: message.text == 'Изменить минимальную сумму вывода')
def minimum_withdraw(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        user_state[user_id] = 'awaiting_minimum_withdraw'
        bot.send_message(user_id, f"Нынешняя минимальная сумма для вывода: {min_withdraw}\nЧтобы изменить награду, отправьте цифрой на сколько хотите изменить.\nНапример '10'")
# Обработчик кнопки "Удалить канал"
@bot.message_handler(func=lambda message: message.text == 'Удалить канал')
def delete_channel_step_1(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        send_channels_page(message.chat.id, 1)

# Отправка страницы каналов с кнопками для удаления
def send_channels_page(chat_id, page=1):
    offset = (page - 1) * channels_per_page
    channels = get_all_channels_with_pagination(offset=offset, limit=channels_per_page)
    total_channels = count_all_channels()
    total_pages = (total_channels + channels_per_page - 1) // channels_per_page

    if total_channels == 0:
        bot.send_message(chat_id, "Нет доступных каналов.")
        return

    if channels:
        for channel in channels:
            channel_id, channel_link = channel
            markup = types.InlineKeyboardMarkup()
            button = types.InlineKeyboardButton(text="Удалить", callback_data=f"delete_channel_{channel_id}")
            markup.add(button)
            bot.send_message(chat_id, f"{channel_link}", reply_markup=markup)
        
        # Пагинация
        pagination_markup = types.InlineKeyboardMarkup()
        if page > 1:
            pagination_markup.add(types.InlineKeyboardButton(text="<", callback_data=f"1prev_channel_{page-1}"))
        if page < total_pages:
            pagination_markup.add(types.InlineKeyboardButton(text=">", callback_data=f"1next_channel_{page+1}"))
        bot.send_message(chat_id, f"Страница {page} из {total_pages}", reply_markup=pagination_markup)
    else:
        bot.send_message(chat_id, f"Нет доступных каналов на странице {page}.")
        if page > 1:
            pagination_markup = types.InlineKeyboardMarkup()
            pagination_markup.add(types.InlineKeyboardButton(text="<", callback_data=f"1prev_channel_{page-1}"))
            bot.send_message(chat_id, f"Страница {page} из {total_pages}", reply_markup=pagination_markup)


# Обработчик кнопок пагинации и удаления каналов
@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_channel_") or call.data.startswith("1prev_channel_") or call.data.startswith("1next_channel_"))
def handle_channel_actions(call):
    if call.data.startswith("delete_channel_"):
        channel_id = int(call.data.split("_")[2])
        delete_channel(channel_id)
        bot.send_message(call.message.chat.id, f"Канал {channel_id} был удален.")
        send_channels_page(call.message.chat.id, 1)  # Перезагрузить страницу с каналами
    elif call.data.startswith("1prev_channel_") or call.data.startswith("1next_channel_"):
        direction, page = call.data.split("_")[0], int(call.data.split("_")[2])
        send_channels_page(call.message.chat.id, page)

# Обработчик кнопки "Добавить канал"
@bot.message_handler(func=lambda message: message.text == 'Добавить канал')
def add_channel_step_1(message):
    user_id = message.from_user.id
    if user_id == 5566384153 or user_id == 6011382957:
        user_state[user_id] = 'awaiting_channel_link'
        bot.send_message(user_id, "Отправь ссылку на канал, которую хочешь добавить.")

@bot.message_handler(func=lambda message: message.text == 'bc')
def add_channel_step_12(message):
    user_id = message.from_user.id
    if user_id == 5566384153:
        res = Crypto.getBalance()
        balance_message=" "
        for currency in res['result']:
            balance_message += f"**{currency['currency_code']}**: Available - {currency['available']}, On hold - {currency['onhold']}\n"
        bot.send_message(user_id, balance_message, parse_mode='Markdown')
        print(res)

        
# Обработчик кнопки "Добавить задание"
@bot.message_handler(func=lambda message: message.text == 'Добавить задание')
def add_task_step_1(message):
    user_id = message.from_user.id
    print(user_id)
    if user_id == 5566384153 or user_id == 6011382957:
        user_state[user_id] = 'awaiting_task_type'
        bot.send_message(user_id, "Введите тип задания (Подписки, Просмотры, Комментарии, Задания):")

@bot.message_handler(func=lambda message: message.text in ['Подписки', 'Просмотры', 'Комментарии', 'Задания'])
def add_task_step_2(message):
    user_id = message.from_user.id
    print(user_id)
    if user_id in user_state and user_state[user_id] == 'awaiting_task_type':
        user_state[user_id] = {
            'task_type': message.text,
            'next_step': 'awaiting_description'
        }
        bot.send_message(user_id, "Введите описание задания:")


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id

    if user_id in user_state:
        state = user_state[user_id]
        print(state)
        if state == 'awaiting_channel_link':
            channel_link = message.text
            add_channel_to_db(channel_link)
            bot.send_message(user_id, f"Канал {channel_link} успешно добавлен.")
            user_state.pop(user_id)
        
        elif state == 'awaiting_referral_earn':
            try:
                new_earn = float(message.text.replace(',', '.'))
                global referrals_earn
                referrals_earn = new_earn
                bot.send_message(user_id, f"Награда за реферала успешно изменена на {referrals_earn}")
                user_state.pop(user_id)
            except ValueError:
                bot.send_message(user_id, "Ошибка! Пожалуйста, введите число, например, '0.5'.")
        elif state == 'awaiting_bonus_earn':
            try:
                new_earn2 = float(message.text.replace(',', '.'))
                global bonus_r
                bonus_r = new_earn2
                bot.send_message(user_id, f"Награда за приветсвенный бонус успешно изменена на {bonus_r}")
                user_state.pop(user_id)
            except ValueError:
                bot.send_message(user_id, "Ошибка! Пожалуйста, введите число, например, '0.5'.")
        elif state == 'awaiting_add_funds':
            try:
                new_funds = float(message.text.replace(',', '.'))
                invoice = Crypto.createInvoice("USDT", new_funds)
                pay_url = invoice['result']['pay_url']  # Получение ссылки на оплату
                bot.send_message(user_id, f"Ссылка для оплаты: {pay_url}")
                user_state.pop(user_id)
            except ValueError:
                bot.send_message(user_id, "Ошибка! Пожалуйста, введите число, например, '0.5'.")
        elif state == 'awaiting_minimum_withdraw':
            try:
                new_min = float(message.text.replace(',', '.'))
                global min_withdraw
                min_withdraw = new_min
                bot.send_message(user_id, f"Минимальное количество для вывода успешно изменено на {min_withdraw}")
                user_state.pop(user_id)
            except ValueError:
                bot.send_message(user_id, "Ошибка! Пожалуйста, введите число, например, '10'.")

        elif isinstance(state, dict) and state.get('next_step') == 'awaiting_description':
            user_state[user_id]['description'] = message.text
            user_state[user_id]['next_step'] = 'awaiting_link'
            bot.send_message(user_id, "Введите ссылку для задания:")

        elif isinstance(state, dict) and state.get('next_step') == 'awaiting_link':
            user_state[user_id]['link'] = message.text
            user_state[user_id]['next_step'] = 'awaiting_reward'
            bot.send_message(user_id, "Введите награду за выполнение задания:")

        elif isinstance(state, dict) and state.get('next_step') == 'awaiting_reward':
            try:
                reward = float(message.text.replace(',', '.'))
                user_state[user_id]['reward'] = reward
                if user_state[user_id]['task_type'] == 'Комментарии' or user_state[user_id]['task_type'] == "Задание":
                    user_state[user_id]['verification_needed'] = 'да'
                    try:
                        add_task(
                            task_type=user_state[user_id]['task_type'],
                            description=user_state[user_id]['description'],
                            link=user_state[user_id]['link'],
                            reward=user_state[user_id]['reward'],
                            verification_needed=user_state[user_id]['verification_needed']
                        )
                        bot.send_message(user_id, "Задание успешно добавлено!")
                        user_state.pop(user_id)
                    except ValueError:
                        bot.send_message(user_id, "Ошибка! Пожалуйста, введите целое число.")
                else:
                    user_state[user_id]['next_step'] = 'awaiting_verification_needed'
                    bot.send_message(user_id, "Нужна ли ручная проверка выполнения задания? (да/нет):")
            except ValueError:
                bot.send_message(user_id, "Ошибка! Пожалуйста, введите число, например, '0.5'.")

        elif isinstance(state, dict) and state.get('next_step') == 'awaiting_verification_needed':
            verification_needed = message.text.lower() == 'да'
            user_state[user_id]['verification_needed'] = verification_needed
            try:
                add_task(
                    task_type=user_state[user_id]['task_type'],
                    description=user_state[user_id]['description'],
                    link=user_state[user_id]['link'],
                    reward=user_state[user_id]['reward'],
                    verification_needed=user_state[user_id]['verification_needed']
                )
                bot.send_message(user_id, "Задание успешно добавлено!")
                user_state.pop(user_id)
            except ValueError:
                bot.send_message(user_id, "Ошибка! Пожалуйста, введите целое число.")
    else:
        bot.send_message(user_id, "Мы не нашли ничего по этому запросу")


# Добавление канала в базу данных
def add_channel_to_db(channel_link):
    cursor.execute('INSERT INTO start_channels (channel_link) VALUES (?)', (channel_link,))
    conn.commit()


# Инициализация базы данных
init_db()

# Запуск бота
bot.polling()
schedule.every().day.at("00:00").do(check_all_tasks)

while True:
    # Запуск всех задач, запланированных для выполнения
    schedule.run_pending()
    time.sleep(1)
