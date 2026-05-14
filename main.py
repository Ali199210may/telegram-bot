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
from flask import Flask, render_template_string, jsonify, request

# ========== SOZLAMALAR ==========

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
WEB_SECRET = os.environ.get("WEB_SECRET", "secret123")
WEB_PORT = int(os.environ.get("WEB_PORT", 5000))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(name)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

# ========== DATABASE ==========

DB_PATH = "cafe_debts.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        username TEXT,
        role TEXT DEFAULT 'worker',
        added_at TEXT,
        added_by INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        supplier_name TEXT,
        total_price REAL NOT NULL,
        paid_amount REAL DEFAULT 0,
        due_date TEXT,
        photo_file_id TEXT,
        note TEXT,

        naqd_account TEXT,
        online_account TEXT,
        online_bank TEXT,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_type TEXT DEFAULT 'cash',
        receipt_file_id TEXT,
        note TEXT,
        paid_at TEXT NOT NULL,
        added_by INTEGER,

        FOREIGN KEY (product_id) REFERENCES products(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        remind_at TEXT NOT NULL,
        sent INTEGER DEFAULT 0,

        FOREIGN KEY (product_id) REFERENCES products(id)
    )
    """)

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

    return [r["user_id"] for r in rows]

def is_admin(user_id):
    db = get_db()

    row = db.execute(
        "SELECT role FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    db.close()

    return row and row["role"] == "admin"

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
        db.execute("""
            INSERT INTO users
            (user_id, full_name, username, role, added_at)
            VALUES (?, ?, ?, 'admin', ?)
        """, (
            user_id,
            full_name,
            username or '',
            datetime.now().isoformat()
        ))

        db.commit()

    db.close()

# ========== USER STATE ==========

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
    user_states.pop(uid, None)

# ========== TAHRIRLASH FUNKSIYA ==========

def _ask_edit_note(uid, data):
    pid = data["product_id"]

    if data.get("new_photo"):
        db = get_db()

        db.execute("""
            UPDATE products
            SET photo_file_id=?, updated_at=?
            WHERE id=?
        """, (
            data["new_photo"],
            datetime.now().isoformat(),
            pid
        ))

        db.commit()
        db.close()

    set_state(uid, "edit_note", data)

    bot.send_message(
        uid,
        "📝 Yangi izoh:",
        parse_mode="Markdown"
    )

# ========== WEB ==========

WEB_HTML = """
<!DOCTYPE html>
<html lang="uz">

<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Kafe Nasiya Daftari</title>

<style>
:root{
    --bg:#080c12;
    --surface:#0f1520;
    --card:#141c28;
    --border:#1e2d42;
    --accent:#f0883e;
    --accent2:#58a6ff;
    --green:#3fb950;
    --red:#f85149;
    --text:#e6edf3;
    --muted:#7d8fa8;
}

body{
    background:var(--bg);
    color:var(--text);
    font-family:Arial,sans-serif;
}
</style>

</head>

<body>

<h1>☕ Kafe Nasiya Daftari</h1>

</body>
</html>
"""

# ========== API ==========

import secrets

active_tokens = {}

@app.route("/")
def web_index():
    return render_template_string(WEB_HTML)

@app.route("/api/login", methods=["POST"])
def api_login():

    data = request.get_json()

    if data and data.get("password") == WEB_SECRET:

        tok = secrets.token_hex(24)

        active_tokens[tok] = datetime.now()

        return jsonify({
            "ok": True,
            "token": tok
        })

    return jsonify({
        "ok": False
    }), 401

def check_token():
    tok = request.headers.get("X-Token", "")
    return tok in active_tokens

# ========== WEB SERVER ==========

def run_web():
    app.run(
        host="0.0.0.0",
        port=WEB_PORT,
        debug=False,
        use_reloader=False
    )

# ========== START ==========

if name == "main":

    init_db()

    print("☕ Kafe Nasiya Daftari Bot ishga tushdi!")
    print(f"🌐 Web dashboard: http://0.0.0.0:{WEB_PORT}")
    print(f"🔑 Web parol: {WEB_SECRET}")

    t2 = threading.Thread(
        target=run_web,
        daemon=True
    )

    t2.start()

    bot.infinity_polling(
        timeout=30,
        long_polling_timeout=20
    )
