import os
import sqlite3
from datetime import datetime
import telebot
from telebot import types

BOT_TOKEN = os.environ.get("BOT_TOKEN", "TOKENINGIZ")

bot = telebot.TeleBot(BOT_TOKEN)

DB = "cafe.db"

# ================= DATABASE =================

def init_db():

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        total_price REAL,
        paid_amount REAL DEFAULT 0,
        click_number TEXT,
        photo_file_id TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        amount REAL,
        receipt_file_id TEXT,
        paid_at TEXT
    )
    """)

    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ================= STATES =================

states = {}

def set_state(uid, state, data=None):
    states[uid] = {
        "state": state,
        "data": data or {}
    }

def get_state(uid):
    return states.get(uid, {
        "state": None,
        "data": {}
    })

def clear_state(uid):
    states.pop(uid, None)

# ================= MENU =================

def menu():

    m = types.ReplyKeyboardMarkup(resize_keyboard=True)

    m.add("➕ Tovar qo'shish")
    m.add("📦 Tovarlar")
    m.add("💸 To'lov qilish")
    m.add("👤 Odam qo'shish")

    return m

# ================= START =================

@bot.message_handler(commands=['start'])
def start(msg):

    uid = msg.from_user.id

    db = get_db()

    user = db.execute(
        "SELECT * FROM users WHERE user_id=?",
        (uid,)
    ).fetchone()

    if not user:

        db.execute(
            "INSERT INTO users VALUES (?, ?)",
            (
                uid,
                msg.from_user.first_name
            )
        )

        db.commit()

    db.close()

    bot.send_message(
        uid,
        "☕ Kafe botiga xush kelibsiz",
        reply_markup=menu()
    )

# ================= ODAM QO'SHISH =================

@bot.message_handler(func=lambda m: m.text == "👤 Odam qo'shish")
def add_user(msg):

    bot.send_message(
        msg.chat.id,
        "👤 Telegram ID yuboring:"
    )

    set_state(msg.chat.id, "add_user")

# ================= TOVAR QO'SHISH =================

@bot.message_handler(func=lambda m: m.text == "➕ Tovar qo'shish")
def add_product(msg):

    set_state(msg.chat.id, "product_name")

    bot.send_message(
        msg.chat.id,
        "📦 Tovar nomini yuboring:"
    )

# ================= TOVARLAR =================

@bot.message_handler(func=lambda m: m.text == "📦 Tovarlar")
def products(msg):

    db = get_db()

    rows = db.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()

    db.close()

    if not rows:

        bot.send_message(msg.chat.id, "📭 Tovar yo'q")
        return

    markup = types.InlineKeyboardMarkup()

    for r in rows:

        remain = r['total_price'] - r['paid_amount']

        markup.add(
            types.InlineKeyboardButton(
                f"{r['name']} | {remain:,.0f} so'm",
                callback_data=f"view_{r['id']}"
            )
        )

    bot.send_message(
        msg.chat.id,
        "📦 Tovarni tanlang:",
        reply_markup=markup
    )

# ================= TO'LOV =================

@bot.message_handler(func=lambda m: m.text == "💸 To'lov qilish")
def payment(msg):

    db = get_db()

    rows = db.execute(
        "SELECT * FROM products"
    ).fetchall()

    db.close()

    markup = types.InlineKeyboardMarkup()

    for r in rows:

        markup.add(
            types.InlineKeyboardButton(
                r['name'],
                callback_data=f"pay_{r['id']}"
            )
        )

    bot.send_message(
        msg.chat.id,
        "💸 Tovarni tanlang:",
        reply_markup=markup
    )

# ================= VIEW PRODUCT =================

@bot.callback_query_handler(func=lambda c: c.data.startswith("view_"))
def view_product(call):

    pid = int(call.data.split("_")[1])

    db = get_db()

    prod = db.execute(
        "SELECT * FROM products WHERE id=?",
        (pid,)
    ).fetchone()

    db.close()

    remain = prod['total_price'] - prod['paid_amount']

    text = (
        f"📦 {prod['name']}\n\n"
        f"💰 Jami: {prod['total_price']:,.0f} so'm\n"
        f"✅ To'langan: {prod['paid_amount']:,.0f} so'm\n"
        f"🔴 Qarz: {remain:,.0f} so'm\n\n"
        f"💳 Klik:\n"
        f"{prod['click_number']}\n\n"
        f"🕒 {prod['created_at']}"
    )

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "🧾 Cheklar",
            callback_data=f"checks_{pid}"
        )
    )

    if prod['photo_file_id']:

        bot.send_photo(
            call.message.chat.id,
            prod['photo_file_id'],
            caption=text,
            reply_markup=markup
        )

    else:

        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup
        )

# ================= CHEKLAR =================

@bot.callback_query_handler(func=lambda c: c.data.startswith("checks_"))
def checks(call):

    pid = int(call.data.split("_")[1])

    db = get_db()

    payments = db.execute(
        """
        SELECT *
        FROM payments
        WHERE product_id=?
        ORDER BY id DESC
        """,
        (pid,)
    ).fetchall()

    db.close()

    if not payments:

        bot.send_message(
            call.message.chat.id,
            "🧾 Chek yo'q"
        )

        return

    for p in payments:

        text = (
            f"💸 {p['amount']:,.0f} so'm\n\n"
            f"🕒 {p['paid_at']}"
        )

        if p['receipt_file_id']:

            bot.send_photo(
                call.message.chat.id,
                p['receipt_file_id'],
                caption=text
            )

        else:

            bot.send_message(
                call.message.chat.id,
                text
            )

# ================= PAY SELECT =================

@bot.callback_query_handler(func=lambda c: c.data.startswith("pay_"))
def pay_select(call):

    pid = int(call.data.split("_")[1])

    set_state(
        call.message.chat.id,
        "pay_amount",
        {
            "product_id": pid
        }
    )

    bot.send_message(
        call.message.chat.id,
        "💸 Summani yuboring:"
    )

# ================= TEXT HANDLER =================

@bot.message_handler(content_types=['text', 'photo'])
def handler(msg):

    uid = msg.chat.id

    st = get_state(uid)

    state = st['state']
    data = st['data']

    # ===== USER =====

    if state == "add_user":

        try:

            new_id = int(msg.text)

        except:

            bot.send_message(uid, "❌ ID noto'g'ri")
            return

        db = get_db()

        db.execute(
            "INSERT OR IGNORE INTO users VALUES (?, ?)",
            (
                new_id,
                "Xodim"
            )
        )

        db.commit()
        db.close()

        clear_state(uid)

        bot.send_message(uid, "✅ Odam qo'shildi")

    # ===== PRODUCT NAME =====

    elif state == "product_name":

        data['name'] = msg.text

        set_state(uid, "product_price", data)

        bot.send_message(uid, "💰 Narxni yuboring:")

    # ===== PRODUCT PRICE =====

    elif state == "product_price":

        data['price'] = float(msg.text)

        set_state(uid, "product_click", data)

        bot.send_message(uid, "💳 Klik raqamini yuboring:")

    # ===== CLICK NUMBER =====

    elif state == "product_click":

        data['click'] = msg.text

        set_state(uid, "product_photo", data)

        bot.send_message(uid, "🖼 Rasm yuboring:")

    # ===== PRODUCT PHOTO =====

    elif state == "product_photo":

        photo = None

        if msg.photo:
            photo = msg.photo[-1].file_id

        db = get_db()

        db.execute(
            """
            INSERT INTO products
            (
                name,
                total_price,
                click_number,
                photo_file_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data['name'],
                data['price'],
                data['click'],
                photo,
                datetime.now().strftime("%d.%m.%Y %H:%M")
            )
        )

        db.commit()
        db.close()

        clear_state(uid)

        bot.send_message(uid, "✅ Tovar qo'shildi")

    # ===== PAYMENT =====

    elif state == "pay_amount":

        amount = float(msg.text)

        data['amount'] = amount

        set_state(uid, "pay_photo", data)

        bot.send_message(uid, "🧾 Chek rasmini yuboring:")

    # ===== PAYMENT PHOTO =====

    elif state == "pay_photo":

        receipt = None

        if msg.photo:
            receipt = msg.photo[-1].file_id

        product_id = data['product_id']

        amount = data['amount']

        db = get_db()

        db.execute(
            """
            UPDATE products
            SET paid_amount = paid_amount + ?
            WHERE id=?
            """,
            (
                amount,
                product_id
            )
        )

        db.execute(
            """
            INSERT INTO payments
            (
                product_id,
                amount,
                receipt_file_id,
                paid_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                product_id,
                amount,
                receipt,
                datetime.now().strftime("%d.%m.%Y %H:%M")
            )
        )

        db.commit()
        db.close()

        clear_state(uid)

        bot.send_message(
            uid,
            "✅ To'lov saqlandi"
        )

# ================= MAIN =================

if __name__ == '__main__':

    init_db()

    print("BOT ISHLADI")

    bot.infinity_polling()

# ================= MENU =================

def menu():

    m = types.ReplyKeyboardMarkup(resize_keyboard=True)

    m.add("➕ Tovar qo'shish")
    m.add("📦 Tovarlar")
    m.add("💸 To'lov qilish")
    m.add("👤 Odam qo'shish")
    m.add("📊 Statistika")

    return m

# ================= ADMIN =================

ADMIN_ID = 123456789

# ================= TOVARLAR =================

@bot.message_handler(func=lambda m: m.text == "📦 Tovarlar")
def products(msg):

    db = get_db()

    rows = db.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()

    db.close()

    if not rows:

        bot.send_message(msg.chat.id, "📭 Tovar yo'q")
        return

    markup = types.InlineKeyboardMarkup()

    for r in rows:

        remain = r['total_price'] - r['paid_amount']

        icon = "✅" if remain <= 0 else "🔴"

        markup.add(
            types.InlineKeyboardButton(
                f"{icon} {r['name']} | {remain:,.0f} so'm",
                callback_data=f"view_{r['id']}"
            )
        )

    bot.send_message(
        msg.chat.id,
        "📦 Tovarni tanlang:",
        reply_markup=markup
    )

# ================= VIEW PRODUCT =================

@bot.callback_query_handler(func=lambda c: c.data.startswith("view_"))
def view_product(call):

    pid = int(call.data.split("_")[1])

    db = get_db()

    prod = db.execute(
        "SELECT * FROM products WHERE id=?",
        (pid,)
    ).fetchone()

    db.close()

    remain = prod['total_price'] - prod['paid_amount']

    text = (
        f"📦 {prod['name']}\n\n"
        f"💰 Jami: {prod['total_price']:,.0f} so'm\n"
        f"✅ To'langan: {prod['paid_amount']:,.0f} so'm\n"
        f"🔴 Qarz: {remain:,.0f} so'm\n\n"
        f"💳 Klik:\n"
        f"{prod['click_number']}\n\n"
        f"🕒 {prod['created_at']}"
    )

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "🧾 Cheklar",
            callback_data=f"checks_{pid}"
        )
    )

    if prod['photo_file_id']:

        bot.send_photo(
            call.message.chat.id,
            prod['photo_file_id'],
            caption=text,
            reply_markup=markup
        )

    else:

        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup
        )

# ================= CHEKLAR =================

@bot.callback_query_handler(func=lambda c: c.data.startswith("checks_"))
def checks(call):

    pid = int(call.data.split("_")[1])

    db = get_db()

    payments = db.execute(
        """
        SELECT *
        FROM payments
        WHERE product_id=?
        ORDER BY id DESC
        """,
        (pid,)
    ).fetchall()

    db.close()

    if not payments:

        bot.send_message(
            call.message.chat.id,
            "🧾 Chek yo'q"
        )

        return

    for p in payments:

        text = (
            f"💸 {p['amount']:,.0f} so'm\n\n"
            f"🕒 {p['paid_at']}"
        )

        if p['receipt_file_id']:

            bot.send_photo(
                call.message.chat.id,
                p['receipt_file_id'],
                caption=text
            )

        else:

            bot.send_message(
                call.message.chat.id,
                text
            )

# ================= STATISTIKA =================

@bot.message_handler(func=lambda m: m.text == "📊 Statistika")
def stats(msg):

    db = get_db()

    row = db.execute(
        """
        SELECT
        COUNT(*),
        SUM(total_price),
        SUM(paid_amount)
        FROM products
        """
    ).fetchone()

    db.close()

    total_products = row[0] or 0
    total_sum = row[1] or 0
    total_paid = row[2] or 0
    remain = total_sum - total_paid

    text = (
        f"📊 Statistika\n\n"
        f"📦 Tovarlar: {total_products}\n\n"
        f"💰 Jami: {total_sum:,.0f} so'm\n"
        f"✅ To'langan: {total_paid:,.0f} so'm\n"
        f"🔴 Qolgan qarz: {remain:,.0f} so'm"
    )

    bot.send_message(msg.chat.id, text)

# ================= ESLATMA =================

import threading
import time

def reminder_loop():

    while True:

        db = get_db()

        rows = db.execute(
            "SELECT * FROM products"
        ).fetchall()

        for r in rows:

            remain = r['total_price'] - r['paid_amount']

            if remain > 0:

                try:

                    bot.send_message(
                        ADMIN_ID,
                        f"🔔 Qarzdor:\n\n"
                        f"📦 {r['name']}\n"
                        f"🔴 {remain:,.0f} so'm"
                    )

                except:
                    pass

        db.close()

        time.sleep(43200)

# ================= MAIN =================

if __name__ == '__main__':

    init_db()

    t = threading.Thread(
        target=reminder_loop,
        daemon=True
    )

    t.start()

print("BOT ISHLADI")

from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot ishlayapti"

def run_web():
    app.run(host="0.0.0.0", port=10000)

Thread(target=run_web).start() 



# ===== TAVARNI TAHRIRLASH =====

@dp.message(F.text == "✏️ Tavarni tahrirlash")
async def edit_product(message: Message):
    await message.answer("Tavar ID sini yuboring:")

    @dp.message()
    async def get_product_id(message: Message):
        product_id = message.text

        if product_id not in products:
            await message.answer("Tavar topilmadi")
            return

        await message.answer(
            "Nimani o‘zgartirmoqchisiz?",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="📷 Rasm")],
                    [KeyboardButton(text="💰 Narx")],
                    [KeyboardButton(text="📞 Nomer")],
                    [KeyboardButton(text="📝 Nomi")]
                ],
                resize_keyboard=True
            )
        )

        @dp.message(F.text == "💰 Narx")
        async def edit_price(message: Message):
            await message.answer("Yangi narxni yuboring:")

            @dp.message()
            async def new_price(message: Message):
                products[product_id]["price"] = message.text
                await message.answer("Narx yangilandi ✅")

        @dp.message(F.text == "📞 Nomer")
        async def edit_phone(message: Message):
            await message.answer("Yangi nomerni yuboring:")

            @dp.message()
            async def new_phone(message: Message):
                products[product_id]["phone"] = message.text
                await message.answer("Nomer yangilandi ✅")

        @dp.message(F.text == "📝 Nomi")
        async def edit_name(message: Message):
            await message.answer("Yangi nomni yuboring:")

            @dp.message()
            async def new_name(message: Message):
                products[product_id]["name"] = message.text
                await message.answer("Nomi yangilandi ✅")

        @dp.message(F.photo)
        async def edit_photo(message: Message):
            products[product_id]["photo"] = message.photo[-1].file_id
            await message.answer("Rasm yangilandi ✅")

KeyboardButton(text="✏️ Tavarni tahrirlash")

bot.infinity_polling()

