import random
import logging
import os
import psycopg2
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from apscheduler.schedulers.background import BackgroundScheduler

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Получение переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN = os.getenv("7596167926:AAGCtIVtPJ4EPfxFLu1pqwdYR2O2_G1mkjQ")

# Подключение к PostgreSQL
def init_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        points INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        tasks TEXT DEFAULT '',
        daily_task TEXT DEFAULT '',
        daily_task_completed BOOLEAN DEFAULT FALSE,
        last_daily_check DATE DEFAULT CURRENT_DATE
    )""")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_user(user_id, **kwargs):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    c = conn.cursor()
    fields = ", ".join([f"{k} = %s" for k in kwargs])
    values = list(kwargs.values()) + [user_id]
    c.execute(f"UPDATE users SET {fields} WHERE user_id=%s", values)
    conn.commit()
    conn.close()

def add_user(user_id, name):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, name) VALUES (%s, %s)", (user_id, name))
    conn.commit()
    conn.close()

# Уровни и награды
def calculate_level(points):
    return points // 10

def get_level_title(level):
    if level < 5: return "🌱 Новичок"
    elif level < 10: return "✨ Стажёр"
    elif level < 20: return "⚡️ Эксперт"
    else: return "🏆 Мастер"

# Гифки и API
DAD_JOKE_API = "https://icanhazdadjoke.com/ "
gif_facts = [
    "https://media.giphy.com/media/ABC123/fact1.gif ",
    "https://media.giphy.com/media/DEF456/fact2.gif "
]

# Ежедневные задания
daily_tasks = [
    "Выпей 2 литра воды", "Сделай 10 приседаний", "Запиши 3 цели на день",
    "Прогуляйся 20 минут", "Послушай музыку без телефона"
]

# Кнопки
def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☕ Факт", callback_data="fact")],
        [InlineKeyboardButton("😂 Шутка API", callback_data="api_joke")],
        [InlineKeyboardButton("📝 Задачи", callback_data="tasks")],
        [InlineKeyboardButton("🎮 Камень-ножницы-бумага", callback_data="game")],
        [InlineKeyboardButton("🏆 Лидерборд", callback_data="leaderboard")],
    ])

# Инициализация глобальных переменных
user_points = {}
user_games = {}
user_tasks = {}

async def load_data(context: ContextTypes.DEFAULT_TYPE):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    rows = c.fetchall()
    for row in rows:
        user_id, name, points, wins, losses, tasks, daily_task, d_task_comp, last_check = row
        user_points[user_id] = points
        user_games[user_id] = {"wins": wins, "losses": losses}
        user_tasks[user_id] = tasks.split(",") if tasks else []
        context.user_data[user_id] = {
            "daily_task": daily_task,
            "daily_task_completed": d_task_comp,
            "last_daily_check": last_check
        }
    conn.close()

async def save_data(context: ContextTypes.DEFAULT_TYPE):
    for user_id in user_points:
        update_user(
            user_id,
            points=user_points[user_id],
            wins=user_games[user_id]["wins"],
            losses=user_games[user_id]["losses"],
            tasks=",".join(user_tasks.get(user_id, [])),
            daily_task=context.user_data[user_id]["daily_task"],
            daily_task_completed=context.user_data[user_id]["daily_task_completed"],
            last_daily_check=context.user_data[user_id]["last_daily_check"]
        )
    logging.info("Данные сохранены в БД")

async def reset_daily_tasks(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().date()
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    c = conn.cursor()
    c.execute("UPDATE users SET daily_task='', daily_task_completed=FALSE WHERE last_daily_check < %s", (today,))
    c.execute("UPDATE users SET last_daily_check=%s", (today,))
    conn.commit()
    conn.close()
    logging.info("Ежедневные задания сброшены")

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not get_user(user.id): add_user(user.id, user.first_name)
    today = datetime.now().date()
    data = context.user_data.get(user.id, {})
    if data.get("last_daily_check", "2000-01-01") < str(today):
        await reset_daily_tasks(context)
    level = calculate_level(user_points.get(user.id, 0))
    title = get_level_title(level)
    await update.message.reply_text(
        f"Привет, {user.first_name}! 🧠 Уровень: {level} — {title}\n\nВыбери, что хочешь:",
        reply_markup=get_main_keyboard()
    )

async def myinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = context.user_data.get(user.id, {})
    level = calculate_level(user_points.get(user.id, 0))
    title = get_level_title(level)
    stats = f"""
📊 Статистика {user.first_name}:
🧬 Уровень: {level} — {title}
💯 Баллов: {user_points.get(user.id, 0)}
🎮 Победы: {user_games[user.id]['wins']} | Поражения: {user_games[user.id]['losses']}
📌 Задачи: {len(user_tasks.get(user.id, []))}
🎯 Ежедневное задание: {data.get("daily_task", "Нет") if not data.get("daily_task_completed", False) else "✅ Выполнено!"}
"""
    await update.message.reply_text(stats, reply_markup=get_main_keyboard())

# Обработка кнопок
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "fact":
        user_points[user.id] += 1
        gif = random.choice(gif_facts)
        await query.edit_message_text("Лови факт!")
        await context.bot.send_animation(chat_id=query.message.chat_id, animation=gif)
        await context.bot.send_message(query.message.chat_id, "Хочешь ещё?", reply_markup=get_main_keyboard())

    elif query.data == "api_joke":
        user_points[user.id] += 1
        try:
            response = requests.get(DAD_JOKE_API, headers={"Accept": "application/json"})
            joke = response.json()["joke"] if response.status_code == 200 else "Ошибка."
        except:
            joke = "Ошибка получения шутки."
        await query.edit_message_text(f"😂 Вот тебе шутка:\n\n{joke}")
        await context.bot.send_message(query.message.chat_id, "Хочешь ещё?", reply_markup=get_main_keyboard())

    elif query.data == "tasks":
        tasks = user_tasks.get(user.id, [])
        text = "📝 Твои задачи:\n" + ("\n".join(tasks) if tasks else "Нет задач.")
        await query.edit_message_text(text)
        await context.bot.send_message(query.message.chat_id, "Напиши новую задачу или 'удалить N', чтобы очистить.", reply_markup=get_main_keyboard())

    elif query.data == "game":
        user_games[user.id] = user_games.get(user.id, {"wins": 0, "losses": 0})
        keyboard = [[InlineKeyboardButton(t, callback_data=t.lower()) for t in ["🪨 Камень", "✂️ Ножницы", "📄 Бумага"]]]
        await query.edit_message_text("🎮 Выбери: камень, ножницы или бумага?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data in ["камень", "ножницы", "бумага"]:
        bot_choice = random.choice(["камень", "ножницы", "бумага"])
        result = ""
        if query.data == bot_choice:
            result = "Ничья!"
        elif (query.data == "камень" and bot_choice == "ножницы") or \
             (query.data == "ножницы" and bot_choice == "бумага") or \
             (query.data == "бумага" and bot_choice == "камень"):
            result = "Ты выиграл! 🎉"
            user_games[user.id]["wins"] += 1
            user_points[user.id] += 3
        else:
            result = "Ты проиграл 😢"
            user_games[user.id]["losses"] += 1
            user_points[user.id] += 1
        await query.edit_message_text(f"Вы выбрали: {query.data.capitalize()}\nБот выбрал: {bot_choice.capitalize()}\n\n{result}")
        await context.bot.send_message(query.message.chat_id, "Хочешь ещё раз?", reply_markup=get_main_keyboard())

    elif query.data == "leaderboard":
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        c = conn.cursor()
        c.execute("SELECT user_id, points FROM users ORDER BY points DESC LIMIT 10")
        rows = c.fetchall()
        text = "🏆 Лидерборд:\n"
        for idx, (uid, points) in enumerate(rows, 1):
            level = calculate_level(points)
            title = get_level_title(level)
            try:
                name = (await context.bot.get_chat(uid)).first_name
            except:
                name = "Аноним"
            text += f"{idx}. {name} — {title} | 💯 {points} баллов\n"
        await query.edit_message_text(text, reply_markup=get_main_keyboard())

# Обработка текста
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.lower().strip()
    if text.startswith("удалить"):
        try:
            idx = int(text.split()[1]) - 1
            tasks = user_tasks.get(user.id, [])
            if 0 <= idx < len(tasks):
                tasks.pop(idx)
                user_tasks[user.id] = tasks
                await update.message.reply_text("🗑 Задача удалена.")
        except:
            await update.message.reply_text("Используй: удалить N")
    else:
        tasks = user_tasks.get(user.id, [])
        tasks.append(text)
        user_tasks[user.id] = tasks
        await update.message.reply_text(f"✅ Добавлена задача: {text}")

# Основной запуск
async def main():
    if not DATABASE_URL or not TELEGRAM_TOKEN:
        raise ValueError("DATABASE_URL или TELEGRAM_TOKEN не заданы")
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    await load_data(app)
    scheduler = BackgroundScheduler()
    scheduler.add_job(save_data, 'interval', minutes=10, args=[app])
    scheduler.add_job(reset_daily_tasks, 'cron', hour=0, minute=0, args=[app])
    scheduler.start()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myinfo", myinfo))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен!")
    await app.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
