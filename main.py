import telebot
from telebot import types
import sqlite3
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)

# DATABASE
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    total INTEGER,
    paid INTEGER DEFAULT 0
)
""")

conn.commit()

# MENU
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ Yangi tovar", "📦 Tovarlar")
    kb.row("💸 To'lov qilish")
    return kb

# START
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "☕ Hisob kitob botiga xush kelibsiz",
        reply_markup=main_menu()
    )

# ADD PRODUCT
user_data = {}

@bot.message_handler(func=lambda m: m.text == "➕ Yangi tovar")
def add_product(message):
    msg = bot.send_message(message.chat.id, "📦 Tovar nomini kiriting:")
    bot.register_next_step_handler(msg, get_name)

def get_name(message):
    user_data[message.chat.id] = {
        "name": message.text
    }

    msg = bot.send_message(message.chat.id, "💰 Narxini kiriting:")
    bot.register_next_step_handler(msg, get_price)

def get_price(message):
    try:
        price = int(message.text)

        data = user_data[message.chat.id]

        cursor.execute(
            "INSERT INTO debts (name, total) VALUES (?, ?)",
            (data["name"], price)
        )

        conn.commit()

        bot.send_message(
            message.chat.id,
            "✅ Tovar saqlandi",
            reply_markup=main_menu()
        )

    except:
        bot.send_message(message.chat.id, "❌ Raqam kiriting")

# PRODUCTS
@bot.message_handler(func=lambda m: m.text == "📦 Tovarlar")
def products(message):

    cursor.execute("SELECT * FROM debts ORDER BY id DESC")
    rows = cursor.fetchall()

    if not rows:
        bot.send_message(message.chat.id, "📭 Tovar yo'q")
        return

    text = "📦 Tovarlar:\n\n"

    for row in rows:

        remain = row[2] - row[3]

        text += (
            f"🆔 {row[0]}\n"
            f"📦 {row[1]}\n"
            f"💰 Jami: {row[2]}\n"
            f"✅ To'langan: {row[3]}\n"
            f"🔴 Qolgan: {remain}\n\n"
        )

    bot.send_message(message.chat.id, text)

# PAYMENT
@bot.message_handler(func=lambda m: m.text == "💸 To'lov qilish")
def payment_start(message):

    msg = bot.send_message(
        message.chat.id,
        "🆔 Tovar ID sini yuboring:"
    )

    bot.register_next_step_handler(msg, get_payment_id)

def get_payment_id(message):

    try:
        product_id = int(message.text)

        user_data[message.chat.id] = {
            "product_id": product_id
        }

        msg = bot.send_message(
            message.chat.id,
            "💸 To'lov summasini kiriting:"
        )

        bot.register_next_step_handler(msg, get_payment_amount)

    except:
        bot.send_message(message.chat.id, "❌ ID noto'g'ri")

def get_payment_amount(message):

    try:
        amount = int(message.text)

        product_id = user_data[message.chat.id]["product_id"]

        cursor.execute(
            "SELECT total, paid FROM debts WHERE id=?",
            (product_id,)
        )

        row = cursor.fetchone()

        if not row:
            bot.send_message(message.chat.id, "❌ Tovar topilmadi")
            return

        total = row[0]
        paid = row[1]

        new_paid = paid + amount

        if new_paid > total:
            new_paid = total

        cursor.execute(
            "UPDATE debts SET paid=? WHERE id=?",
            (new_paid, product_id)
        )

        conn.commit()

        remain = total - new_paid

        bot.send_message(
            message.chat.id,
            f"✅ To'lov qo'shildi\n\n🔴 Qolgan qarz: {remain}",
            reply_markup=main_menu()
        )

    except:
        bot.send_message(message.chat.id, "❌ Summani to'g'ri kiriting")

print("🤖 Bot ishga tushdi...")

bot.infinity_polling()
