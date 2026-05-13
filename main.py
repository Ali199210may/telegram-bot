import os
import sqlite3
from datetime import datetime
from flask import Flask
from threading import Thread

import telebot
from telebot import types

# ======================
# FLASK
# ======================

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot ishlayapti"

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ======================
# TOKEN
# ======================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)

# ======================
# DATABASE
# ======================

DB_NAME = "database.db"

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():

    db = get_db()

    db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT DEFAULT 'watcher'
    )
    """)

    db.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        supplier TEXT,
        total_price REAL,
        paid REAL DEFAULT 0,
        click_number TEXT,
        note TEXT,
        photo TEXT,
        created_at TEXT
    )
    """)

    db.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        amount REAL,
        payment_type TEXT,
        receipt TEXT,
        created_at TEXT
    )
    """)

    db.commit()
    db.close()

# ======================
# USER STATES
# ======================

user_states = {}

def set_state(uid, state, data=None):

    user_states[uid] = {
        "state": state,
        "data": data or {}
    }

def get_state(uid):

    return user_states.get(uid, {
        "state": None,
        "data": {}
    })

def clear_state(uid):

    if uid in user_states:
        del user_states[uid]

# ======================
# ADMIN
# ======================

ADMIN_ID = 123456789

def is_admin(uid):

    return uid == ADMIN_ID

# ======================
# MENU
# ======================

def admin_menu():

    m = types.ReplyKeyboardMarkup(resize_keyboard=True)

    m.add("➕ Yangi tovar")
    m.add("📦 Barcha tovarlar")

    m.add("💸 To'lov qilish")
    m.add("📊 Umumiy qarz")

    m.add("👥 Kuzatuvchilar")

    return m

def watcher_menu():

    m = types.ReplyKeyboardMarkup(resize_keyboard=True)

    m.add("📦 Barcha tovarlar")
    m.add("📊 Umumiy qarz")

    return m

def get_menu(uid):

    if is_admin(uid):
        return admin_menu()

    return watcher_menu()

# ======================
# START
# ======================

@bot.message_handler(commands=['start'])
def start(msg):

    uid = msg.from_user.id

    bot.send_message(
        uid,
        "☕ Kafe nasiya botiga xush kelibsiz",
        reply_markup=get_menu(uid)
    )

# ======================
# ADD PRODUCT
# ======================

@bot.message_handler(func=lambda m: m.text == "➕ Yangi tovar")
def add_product(msg):

    if not is_admin(msg.from_user.id):
        return

    set_state(msg.from_user.id, "product_name")

    bot.send_message(
        msg.chat.id,
        "📦 Tovar nomini yuboring"
    )

# ======================
# ALL PRODUCTS
# ======================

@bot.message_handler(func=lambda m: m.text == "📦 Barcha tovarlar")
def all_products(msg):

    db = get_db()

    rows = db.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()

    db.close()

    if not rows:

        bot.send_message(
            msg.chat.id,
            "📭 Tovar yo'q"
        )

        return

    kb = types.InlineKeyboardMarkup()

    for r in rows:

        remain = r["total_price"] - r["paid"]

        icon = "✅" if remain <= 0 else "🔴"

        kb.add(
            types.InlineKeyboardButton(
                f"{icon} {r['name']}",
                callback_data=f"view_{r['id']}"
            )
        )

    bot.send_message(
        msg.chat.id,
        "📦 Tovarni tanlang",
        reply_markup=kb
    )

# ======================
# TOTAL DEBT
# ======================

@bot.message_handler(func=lambda m: m.text == "📊 Umumiy qarz")
def total_debt(msg):

    db = get_db()

    rows = db.execute(
        "SELECT * FROM products"
    ).fetchall()

    db.close()

    if not rows:

        bot.send_message(
            msg.chat.id,
            "📭 Tovar yo'q"
        )

        return

    text = "📊 Umumiy qarz\n\n"

    total = 0

    for r in rows:

        remain = r["total_price"] - r["paid"]

        total += remain

        text += (
            f"📦 {r['name']}\n"
            f"🔴 {remain:,.0f} so'm\n\n"
        )

    text += f"💰 Jami qarz: {total:,.0f} so'm"

    bot.send_message(
        msg.chat.id,
        text
    )
    # ======================
# PRODUCT DETAIL
# ======================

@bot.callback_query_handler(func=lambda c: c.data.startswith("view_"))
def product_detail(call):

    product_id = int(call.data.split("_")[1])

    db = get_db()

    product = db.execute(
        "SELECT * FROM products WHERE id=?",
        (product_id,)
    ).fetchone()

    payments = db.execute(
        "SELECT * FROM payments WHERE product_id=? ORDER BY id DESC",
        (product_id,)
    ).fetchall()

    db.close()

    remain = product["total_price"] - product["paid"]

    text = (
        f"📦 {product['name']}\n\n"
        f"🏪 Yetkazuvchi: {product['supplier'] or '-'}\n"
        f"💳 Click: {product['click_number'] or '-'}\n\n"
        f"💰 Jami: {product['total_price']:,.0f} so'm\n"
        f"✅ To'langan: {product['paid']:,.0f} so'm\n"
        f"🔴 Qolgan: {remain:,.0f} so'm\n\n"
    )

    if payments:

        text += "📋 To'lovlar:\n\n"

        for p in payments[:10]:

            icon = "💳" if p["payment_type"] == "click" else "💵"

            text += (
                f"{icon} {p['amount']:,.0f} so'm\n"
                f"🕒 {p['created_at']}\n\n"
            )

    kb = types.InlineKeyboardMarkup()

    if is_admin(call.from_user.id):

        kb.add(
            types.InlineKeyboardButton(
                "💸 To'lov qilish",
                callback_data=f"pay_{product_id}"
            )
        )

    if product["photo"]:

        bot.send_photo(
            call.message.chat.id,
            product["photo"],
            caption=text,
            reply_markup=kb
        )

    else:

        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=kb
        )

# ======================
# PAYMENT SELECT
# ======================

@bot.message_handler(func=lambda m: m.text == "💸 To'lov qilish")
def payment_menu(msg):

    if not is_admin(msg.from_user.id):
        return

    db = get_db()

    rows = db.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()

    db.close()

    if not rows:

        bot.send_message(
            msg.chat.id,
            "📭 Tovar yo'q"
        )

        return

    kb = types.InlineKeyboardMarkup()

    for r in rows:

        remain = r["total_price"] - r["paid"]

        if remain > 0:

            kb.add(
                types.InlineKeyboardButton(
                    f"📦 {r['name']}",
                    callback_data=f"pay_{r['id']}"
                )
            )

    bot.send_message(
        msg.chat.id,
        "💸 To'lov uchun tovar tanlang",
        reply_markup=kb
    )

# ======================
# PAYMENT START
# ======================

@bot.callback_query_handler(func=lambda c: c.data.startswith("pay_"))
def payment_start(call):

    product_id = int(call.data.split("_")[1])

    set_state(call.from_user.id, "payment_amount", {
        "product_id": product_id
    })

    bot.send_message(
        call.message.chat.id,
        "💰 To'lov summasini yuboring"
    )

# ======================
# TEXT HANDLER
# ======================

@bot.message_handler(content_types=['text', 'photo'])
def all_messages(msg):

    uid = msg.from_user.id

    state = get_state(uid)

    # ======================
    # PRODUCT NAME
    # ======================

    if state["state"] == "product_name":

        set_state(uid, "product_supplier", {
            "name": msg.text
        })

        bot.send_message(
            uid,
            "🏪 Yetkazuvchi nomi"
        )

    # ======================
    # PRODUCT SUPPLIER
    # ======================

    elif state["state"] == "product_supplier":

        data = state["data"]

        data["supplier"] = msg.text

        set_state(uid, "product_price", data)

        bot.send_message(
            uid,
            "💰 Jami narx"
        )

    # ======================
    # PRODUCT PRICE
    # ======================

    elif state["state"] == "product_price":

        try:

            price = float(
                msg.text.replace(",", "")
            )

        except:

            bot.send_message(
                uid,
                "❌ To'g'ri summa yuboring"
            )

            return

        data = state["data"]

        data["price"] = price

        set_state(uid, "product_click", data)

        bot.send_message(
            uid,
            "💳 Click yoki karta raqami"
        )

    # ======================
    # PRODUCT CLICK
    # ======================

    elif state["state"] == "product_click":

        data = state["data"]

        data["click"] = msg.text

        set_state(uid, "product_photo", data)

        bot.send_message(
            uid,
            "📸 Tovar rasmi yuboring yoki /skip"
        )

    # ======================
    # PRODUCT PHOTO
    # ======================

    elif state["state"] == "product_photo":

        data = state["data"]

        photo = None

        if msg.photo:
            photo = msg.photo[-1].file_id

        db = get_db()

        db.execute("""
        INSERT INTO products (
            name,
            supplier,
            total_price,
            click_number,
            photo,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data["name"],
            data["supplier"],
            data["price"],
            data["click"],
            photo,
            datetime.now().strftime("%d.%m.%Y %H:%M")
        ))

        db.commit()
        db.close()

        clear_state(uid)

        bot.send_message(
            uid,
            "✅ Tovar qo'shildi",
            reply_markup=get_menu(uid)
        )

    # ======================
    # PAYMENT AMOUNT
    # ======================

    elif state["state"] == "payment_amount":

        try:

            amount = float(
                msg.text.replace(",", "")
            )

        except:

            bot.send_message(
                uid,
                "❌ To'g'ri summa yuboring"
            )

            return

        data = state["data"]

        data["amount"] = amount

        set_state(uid, "payment_type", data)

        kb = types.InlineKeyboardMarkup()

        kb.add(
            types.InlineKeyboardButton(
                "💵 Naqd",
                callback_data="cash"
            ),
            types.InlineKeyboardButton(
                "💳 Click",
                callback_data="click"
            )
        )

        bot.send_message(
            uid,
            "💳 To'lov turini tanlang",
            reply_markup=kb
        )

# ======================
# PAYMENT TYPE
# ======================

@bot.callback_query_handler(func=lambda c: c.data in ["cash", "click"])
def payment_type(call):

    uid = call.from_user.id

    state = get_state(uid)

    data = state["data"]

    data["payment_type"] = call.data

    set_state(uid, "payment_receipt", data)

    bot.send_message(
        uid,
        "📸 Chek rasmi yuboring"
    )

# ======================
# RECEIPT SAVE
# ======================

@bot.message_handler(content_types=['photo'])
def save_receipt(msg):

    uid = msg.from_user.id

    state = get_state(uid)

    if state["state"] != "payment_receipt":
        return

    data = state["data"]

    receipt = msg.photo[-1].file_id

    db = get_db()

    db.execute("""
    INSERT INTO payments (
        product_id,
        amount,
        payment_type,
        receipt,
        created_at
    )
    VALUES (?, ?, ?, ?, ?)
    """, (
        data["product_id"],
        data["amount"],
        data["payment_type"],
        receipt,
        datetime.now().strftime("%d.%m.%Y %H:%M")
    ))

    db.execute("""
    UPDATE products
    SET paid = paid + ?
    WHERE id=?
    """, (
        data["amount"],
        data["product_id"]
    ))

    db.commit()
    db.close()

    clear_state(uid)

    bot.send_message(
        uid,
        "✅ To'lov saqlandi",
        reply_markup=get_menu(uid)
    )

# ======================
# RUN
# ======================

if __name__ == "__main__":

    init_db()

    keep_alive()

    print("Bot ishladi")

    bot.infinity_polling()
