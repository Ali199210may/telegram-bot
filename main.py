import os
import sqlite3
import logging
from datetime import datetime, timedelta
from io import BytesIO
import threading
import time

from PIL import Image, ImageDraw, ImageFont
import telebot
from telebot import types

# ========== SOZLAMALAR ==========

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

bot = telebot.TeleBot(BOT_TOKEN)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

# ========== DATABASE ==========

DB_PATH = 'cafe_debts.db'

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()

    # USERS
    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        username TEXT,
        role TEXT DEFAULT 'worker',
        added_at TEXT,
        added_by INTEGER
    )
    ''')

    # PRODUCTS
    c.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        supplier_name TEXT,
        total_price REAL NOT NULL,
        paid_amount REAL DEFAULT 0,
        due_date TEXT,
        photo_file_id TEXT,
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by INTEGER
    )
    ''')

    # PAYMENTS
    c.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_type TEXT DEFAULT 'cash',
        receipt_file_id TEXT,
        note TEXT,
        paid_at TEXT NOT NULL,
        added_by INTEGER
    )
    ''')

    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ========== ADMIN ==========

def get_admins():
    db = get_db()

    rows = db.execute(
        "SELECT user_id FROM users WHERE role='admin'"
    ).fetchall()

    db.close()

    return [r['user_id'] for r in rows]

def is_admin(user_id):
    db = get_db()

    row = db.execute(
        "SELECT role FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    db.close()

    return row and row['role'] == 'admin'

def is_allowed(user_id):
    db = get_db()

    row = db.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    db.close()

    return row is not None

def register_admin(user_id, full_name, username):
    db = get_db()

    existing = db.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not existing:
        db.execute(
            """
            INSERT INTO users
            (user_id, full_name, username, role, added_at)
            VALUES (?, ?, ?, 'admin', ?)
            """,
            (
                user_id,
                full_name,
                username or '',
                datetime.now().isoformat()
            )
        )

        db.commit()

    db.close()

# ========== USER STATE ==========

user_states = {}

def set_state(uid, state, data=None):
    user_states[uid] = {
        'state': state,
        'data': data or {}
    }

def get_state(uid):
    return user_states.get(
        uid,
        {
            'state': None,
            'data': {}
        }
    )

def clear_state(uid):
    user_states.pop(uid, None)

# ========== MENU ==========

def admin_menu():
    m = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    m.add(
        types.KeyboardButton("➕ Yangi tovar"),
        types.KeyboardButton("📦 Tovarlar")
    )

    m.add(
        types.KeyboardButton("💸 To'lov kiritish"),
        types.KeyboardButton("📊 Umumiy holat")
    )

    return m

def get_menu(uid):
    return admin_menu()

def cancel_kb():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)

    m.add(
        types.KeyboardButton("❌ Bekor qilish")
    )

    return m

# ========== START ==========

@bot.message_handler(commands=['start'])
def cmd_start(msg):

    uid = msg.from_user.id
    name = msg.from_user.first_name
    uname = msg.from_user.username or ''

    admins = get_admins()

    if not admins:
        register_admin(uid, name, uname)

        bot.send_message(
            uid,
            f"👑 Assalomu alaykum, {name}\n\n"
            f"Siz admin bo'ldingiz.",
            reply_markup=admin_menu()
        )

    elif not is_allowed(uid):

        bot.send_message(
            uid,
            "🔒 Sizga ruxsat yo'q."
        )

    else:

        bot.send_message(
            uid,
            f"👋 Xush kelibsiz, {name}",
            reply_markup=get_menu(uid)
        )

# ========== TOVAR QO'SHISH ==========

@bot.message_handler(func=lambda m: m.text == "➕ Yangi tovar")
def add_product(msg):

    uid = msg.from_user.id

    if not is_admin(uid):
        return

    set_state(uid, 'prod_name')

    bot.send_message(
        uid,
        "📦 Tovar nomini yuboring:",
        reply_markup=cancel_kb()
    )

@bot.message_handler(func=lambda m: m.text == "📦 Tovarlar")
def show_products(msg):

    uid = msg.from_user.id

    db = get_db()

    rows = db.execute(
        """
        SELECT id, name, total_price, paid_amount
        FROM products
        ORDER BY id DESC
        """
    ).fetchall()

    db.close()

    if not rows:
        bot.send_message(uid, "📭 Tovar yo'q")
        return

    text = "📦 Tovarlar:\n\n"

    for r in rows:

        remain = r['total_price'] - r['paid_amount']

        text += (
            f"📌 {r['name']}\n"
            f"💰 {r['total_price']:,.0f} so'm\n"
            f"🔴 Qarz: {remain:,.0f} so'm\n\n"
        )

    bot.send_message(uid, text)

@bot.message_handler(func=lambda m: m.text == "💸 To'lov kiritish")
def pay_start(msg):

    uid = msg.from_user.id

    if not is_admin(uid):
        return

    db = get_db()

    rows = db.execute(
        "SELECT id, name FROM products"
    ).fetchall()

    db.close()

    if not rows:
        bot.send_message(uid, "📭 Tovar yo'q")
        return

    text = "ID ni yuboring:\n\n"

    for r in rows:
        text += f"{r['id']} - {r['name']}\n"

    set_state(uid, 'pay_product')

    bot.send_message(uid, text)

# ========== TEXT HANDLER ==========

@bot.message_handler(content_types=['text'])
def handle_text(msg):

    uid = msg.from_user.id

    st = get_state(uid)

    state = st['state']
    data = st['data']

    # === TOVAR NOMI ===

    if state == 'prod_name':

        data['name'] = msg.text

        set_state(uid, 'prod_price', data)

        bot.send_message(
            uid,
            "💰 Narxini yuboring:"
        )

    # === TOVAR NARXI ===

    elif state == 'prod_price':

        try:
            price = float(msg.text)

        except:
            bot.send_message(
                uid,
                "❌ Raqam yuboring"
            )
            return

        data['price'] = price

        db = get_db()

        db.execute(
            """
            INSERT INTO products
            (
                name,
                total_price,
                paid_amount,
                created_at,
                updated_at,
                created_by
            )
            VALUES (?, ?, 0, ?, ?, ?)
            """,
            (
                data['name'],
                data['price'],
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                uid
            )
        )

        db.commit()
        db.close()

        clear_state(uid)

        bot.send_message(
            uid,
            "✅ Tovar qo'shildi",
            reply_markup=admin_menu()
        )

    # === TO'LOV PRODUCT ID ===

    elif state == 'pay_product':

        try:
            product_id = int(msg.text)

        except:
            bot.send_message(uid, "❌ ID yuboring")
            return

        data['product_id'] = product_id

        set_state(uid, 'pay_amount', data)

        bot.send_message(
            uid,
            "💸 Summa yuboring:"
        )

    # === TO'LOV SUMMA ===

    elif state == 'pay_amount':

        try:
            amount = float(msg.text)

        except:
            bot.send_message(uid, "❌ Raqam yuboring")
            return

        product_id = data['product_id']

        db = get_db()

        db.execute(
            """
            UPDATE products
            SET paid_amount = paid_amount + ?
            WHERE id=?
            """,
            (amount, product_id)
        )

        db.commit()

        prod = db.execute(
            """
            SELECT *
            FROM products
            WHERE id=?
            """,
            (product_id,)
        ).fetchone()

        db.close()

        remain = prod['total_price'] - prod['paid_amount']

        clear_state(uid)

        bot.send_message(
            uid,
            f"✅ To'lov qo'shildi\n\n"
            f"💸 {amount:,.0f} so'm\n"
            f"🔴 Qolgan: {remain:,.0f} so'm",
            reply_markup=admin_menu()
        )

# ========== MAIN ==========

if __name__ == '__main__':

    init_db()

    print("☕ Bot ishga tushdi")

    bot.infinity_polling()
