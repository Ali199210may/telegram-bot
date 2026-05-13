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

BOT_TOKEN = os.environ.get(“BOT_TOKEN”, “YOUR_BOT_TOKEN_HERE”)

bot = telebot.TeleBot(BOT_TOKEN)
logging.basicConfig(level=logging.INFO, format=’%(asctime)s - %(message)s’)

# ========== DATABASE ==========

def init_db():
conn = sqlite3.connect(‘cafe_debts.db’, check_same_thread=False)
c = conn.cursor()

```
# Foydalanuvchilar (admin + xodimlar)
c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    full_name TEXT,
    username TEXT,
    role TEXT DEFAULT 'worker',  -- 'admin' yoki 'worker'
    added_at TEXT,
    added_by INTEGER
)''')

# Tovarlar
c.execute('''CREATE TABLE IF NOT EXISTS products (
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
)''')

# To'lovlar
c.execute('''CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    payment_type TEXT DEFAULT 'cash',  -- 'cash' yoki 'click'
    receipt_file_id TEXT,
    note TEXT,
    paid_at TEXT NOT NULL,
    added_by INTEGER,
    FOREIGN KEY (product_id) REFERENCES products(id)
)''')

# Eslatma sozlamalari
c.execute('''CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    remind_at TEXT NOT NULL,
    sent INTEGER DEFAULT 0,
    FOREIGN KEY (product_id) REFERENCES products(id)
)''')

conn.commit()
conn.close()
```

DB_PATH = ‘cafe_debts.db’

def get_db():
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
return conn

# ========== ADMIN BOSHQARUVI ==========

def get_admins():
db = get_db()
rows = db.execute(“SELECT user_id FROM users WHERE role=‘admin’”).fetchall()
db.close()
return [r[‘user_id’] for r in rows]

def is_admin(user_id):
db = get_db()
row = db.execute(“SELECT role FROM users WHERE user_id=?”, (user_id,)).fetchone()
db.close()
return row and row[‘role’] == ‘admin’

def is_allowed(user_id):
db = get_db()
row = db.execute(“SELECT user_id FROM users WHERE user_id=?”, (user_id,)).fetchone()
db.close()
return row is not None

def register_admin(user_id, full_name, username):
db = get_db()
existing = db.execute(“SELECT user_id FROM users WHERE user_id=?”, (user_id,)).fetchone()
if not existing:
db.execute(“INSERT INTO users (user_id, full_name, username, role, added_at) VALUES (?,?,?,‘admin’,?)”,
(user_id, full_name, username or ‘’, datetime.now().isoformat()))
db.commit()
db.close()

# ========== USER STATE ==========

user_states = {}

def set_state(uid, state, data=None):
user_states[uid] = {‘state’: state, ‘data’: data or {}}

def get_state(uid):
return user_states.get(uid, {‘state’: None, ‘data’: {}})

def clear_state(uid):
user_states.pop(uid, None)

# ========== CHEK RASMI GENERATOR ==========

def generate_receipt(product, payments, remaining):
W = 560
pay_count = len(payments)
H = 780 + pay_count * 58

```
img = Image.new('RGB', (W, H), '#0d1117')
draw = ImageDraw.Draw(img)

# Background gradient effect
for i in range(H):
    r = int(13 + (26 - 13) * i / H)
    g = int(17 + (35 - 17) * i / H)
    b = int(23 + (50 - 23) * i / H)
    draw.line([(0, i), (W, i)], fill=(r, g, b))

def rr(x1, y1, x2, y2, r=12, fill=None, outline=None, w=2):
    draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=fill, outline=outline, width=w)

def load_font(size, bold=False):
    paths = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except:
            continue
    return ImageFont.load_default()

f36b = load_font(36, True)
f24b = load_font(24, True)
f20 = load_font(20)
f20b = load_font(20, True)
f16 = load_font(16)
f14 = load_font(14)

# === HEADER ===
rr(15, 15, W-15, 110, r=20, fill='#161b22', outline='#30363d')
draw.text((W//2, 45), "☕ KAFE NASIYA DAFTARI", font=f24b, fill='#f0883e', anchor='mm')
draw.text((W//2, 82), "Tovar Hisobi & To'lov Cheki", font=f16, fill='#8b949e', anchor='mm')

# Dekorativ chiziq
for i in range(0, W-30, 8):
    color = '#f0883e' if (i // 8) % 3 == 0 else '#21262d'
    draw.rectangle([i+15, 118, i+21, 121], fill=color)

# === TOVAR MA'LUMOTI ===
y = 135
rr(15, y, W-15, y+115, r=15, fill='#161b22', outline='#30363d')
draw.text((35, y+12), "📦  TOVAR", font=f14, fill='#8b949e')
draw.text((35, y+35), product['name'], font=f24b, fill='#e6edf3')
if product['supplier_name']:
    draw.text((35, y+70), f"🏪  Yetkazuvchi: {product['supplier_name']}", font=f16, fill='#8b949e')
if product['due_date']:
    draw.text((35, y+92), f"📅  Muddat: {product['due_date'][:10]}", font=f16, fill='#8b949e')
draw.text((W-35, y+35), f"{product['total_price']:,.0f}", font=f24b, fill='#f0883e', anchor='ra')
draw.text((W-35, y+65), "so'm (jami)", font=f14, fill='#8b949e', anchor='ra')

# === TO'LOVLAR TARIXI ===
y = 268
draw.text((35, y), "📋  TO'LOVLAR TARIXI", font=f16, fill='#8b949e')
y += 28
box_h = pay_count * 58 + 20 if pay_count > 0 else 55
rr(15, y, W-15, y+box_h, r=15, fill='#161b22', outline='#30363d')
y += 12

if not payments:
    draw.text((W//2, y+18), "Hali to'lov kiritilmagan", font=f16, fill='#484f58', anchor='mm')
    y += 40
else:
    for i, p in enumerate(payments):
        row_color = '#1c2128' if i % 2 == 0 else '#161b22'
        rr(25, y, W-25, y+50, r=8, fill=row_color)

        ptype_icon = "💳" if p['payment_type'] == 'click' else "💵"
        ptype_label = "Klik" if p['payment_type'] == 'click' else "Naqd"

        dt = p['paid_at'][:16].replace('T', ' ')
        draw.text((42, y+8), f"{ptype_icon} {dt}", font=f14, fill='#8b949e')
        draw.text((42, y+28), ptype_label, font=f14, fill='#3fb950' if p['payment_type'] == 'cash' else '#58a6ff')
        draw.text((W-40, y+18), f"+{p['amount']:,.0f} so'm", font=f20b, fill='#3fb950', anchor='rm')
        y += 54

y += 20

# === STATISTIKA ===
paid = product['paid_amount']
total = product['total_price']
percent = min((paid / total * 100) if total > 0 else 0, 100)

rr(15, y, W-15, y+175, r=15, fill='#161b22', outline='#30363d')
draw.text((35, y+15), "📊  HOLAT", font=f14, fill='#8b949e')

# Progress bar
bx, by = 35, y+42
bw = W - 70
bh = 22
rr(bx, by, bx+bw, by+bh, r=11, fill='#21262d')
fw = int(bw * percent / 100)
if fw > 12:
    bar_color = '#3fb950' if percent >= 90 else '#f0883e' if percent >= 50 else '#f85149'
    rr(bx, by, bx+fw, by+bh, r=11, fill=bar_color)

draw.text((W//2, by+bh+18), f"{percent:.1f}%  to'langan", font=f16, fill='#8b949e', anchor='mm')

draw.text((35, y+100), "✅  To'langan:", font=f20, fill='#8b949e')
draw.text((W-35, y+100), f"{paid:,.0f} so'm", font=f20b, fill='#3fb950', anchor='ra')

draw.text((35, y+132), "⏳  Qolgan qarz:", font=f20, fill='#8b949e')
if remaining <= 0:
    draw.text((W-35, y+132), "✅  To'liq to'landi!", font=f20b, fill='#3fb950', anchor='ra')
else:
    draw.text((W-35, y+132), f"{remaining:,.0f} so'm", font=f24b, fill='#f85149', anchor='ra')

y += 185

# === FOOTER ===
draw.line([(35, y), (W-35, y)], fill='#30363d', width=1)
now = datetime.now().strftime('%d.%m.%Y  %H:%M')
draw.text((W//2, y+18), f"🕐  {now}", font=f14, fill='#484f58', anchor='mm')
draw.text((W//2, y+40), "☕ Kafe Nasiya Daftari Bot", font=f14, fill='#30363d', anchor='mm')

# Border
rr(2, 2, W-3, H-3, r=22, outline='#f0883e', w=2)

buf = BytesIO()
img.save(buf, format='PNG')
buf.seek(0)
return buf
```

# ========== KLAVIATURA ==========

def admin_menu():
m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
m.add(
types.KeyboardButton(“➕ Yangi tovar”),
types.KeyboardButton(“📦 Tovarlar”),
types.KeyboardButton(“💸 To’lov kiritish”),
types.KeyboardButton(“📊 Umumiy holat”),
types.KeyboardButton(“👥 Xodimlar”),
types.KeyboardButton(“⚙️ Sozlamalar”)
)
return m

def worker_menu():
m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
m.add(
types.KeyboardButton(“📦 Tovarlar”),
types.KeyboardButton(“📊 Umumiy holat”)
)
return m

def get_menu(uid):
return admin_menu() if is_admin(uid) else worker_menu()

def cancel_kb():
m = types.ReplyKeyboardMarkup(resize_keyboard=True)
m.add(types.KeyboardButton(“❌ Bekor qilish”))
return m

def skip_kb():
m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
m.add(types.KeyboardButton(“⏭ O’tkazib yuborish”), types.KeyboardButton(“❌ Bekor qilish”))
return m

def products_markup(uid, action=“view”):
db = get_db()
rows = db.execute(“SELECT id, name, total_price, paid_amount FROM products ORDER BY created_at DESC”).fetchall()
db.close()
if not rows:
return None, []
m = types.InlineKeyboardMarkup(row_width=1)
for r in rows:
rem = r[‘total_price’] - r[‘paid_amount’]
icon = “✅” if rem <= 0 else “🔴”
m.add(types.InlineKeyboardButton(
f”{icon}  {r[‘name’]}  |  {rem:,.0f} so’m qolgan”,
callback_data=f”{action}:{r[‘id’]}”
))
return m, rows

# ========== ESLATMA TIZIMI ==========

def reminder_loop():
while True:
try:
db = get_db()
now = datetime.now().isoformat()
reminders = db.execute(
“SELECT r.id, r.product_id, p.name, p.total_price, p.paid_amount “
“FROM reminders r JOIN products p ON r.product_id=p.id “
“WHERE r.sent=0 AND r.remind_at <= ?”, (now,)
).fetchall()

```
        for rem in reminders:
            remaining = rem['total_price'] - rem['paid_amount']
            if remaining > 0:
                admins = get_admins()
                text = (
                    f"⏰ *ESLATMA!*\n\n"
                    f"📦 *{rem['name']}* uchun to'lov muddati yaqinlashdi!\n\n"
                    f"💰 Qolgan qarz: *{remaining:,.0f} so'm*\n"
                    f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                )
                for admin_id in admins:
                    try:
                        bot.send_message(admin_id, text, parse_mode='Markdown')
                    except:
                        pass

            db.execute("UPDATE reminders SET sent=1 WHERE id=?", (rem['id'],))
            db.commit()
        db.close()
    except Exception as e:
        logging.error(f"Reminder error: {e}")
    time.sleep(60)
```

# ========== /start ==========

@bot.message_handler(commands=[‘start’])
def cmd_start(msg):
uid = msg.from_user.id
name = msg.from_user.first_name
uname = msg.from_user.username or ‘’

```
admins = get_admins()

if not admins:
    # Birinchi foydalanuvchi — admin bo'ladi
    register_admin(uid, name, uname)
    bot.send_message(uid,
        f"👑 Assalomu alaykum, *{name}*!\n\n"
        f"Siz *Admin* sifatida ro'yxatdan o'tdingiz.\n\n"
        f"☕ *Kafe Nasiya Daftari* — barcha nasiya va to'lovlaringiz shu yerda!",
        parse_mode='Markdown', reply_markup=admin_menu())
elif not is_allowed(uid):
    bot.send_message(uid,
        f"🔒 Siz tizimda yo'qsiz.\n\n"
        f"Admin sizni qo'shishi kerak.")
else:
    role = "👑 Admin" if is_admin(uid) else "👤 Xodim"
    bot.send_message(uid,
        f"👋 Xush kelibsiz, *{name}*!\n"
        f"Rolингиз: {role}",
        parse_mode='Markdown', reply_markup=get_menu(uid))
```

# ========== TOVAR QO’SHISH (Admin) ==========

@bot.message_handler(func=lambda m: m.text == “➕ Yangi tovar”)
def add_product(msg):
uid = msg.from_user.id
if not is_admin(uid):
return
set_state(uid, ‘prod_name’)
bot.send_message(uid, “📦 *Tovar nomini kiriting:*\n\n_Misol: Tovuq go’shti_”,
parse_mode=‘Markdown’, reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: m.text == “📦 Tovarlar”)
def show_products(msg):
uid = msg.from_user.id
if not is_allowed(uid):
return
markup, rows = products_markup(uid, “view”)
if not rows:
bot.send_message(uid, “📭 Hali hech qanday tovar yo’q.”, reply_markup=get_menu(uid))
return
bot.send_message(uid, “📦 *Tovarlar ro’yxati:*\n\nTovar ustiga bosing → batafsil ko’ring 👇”,
parse_mode=‘Markdown’, reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == “💸 To’lov kiritish”)
def pay_start(msg):
uid = msg.from_user.id
if not is_admin(uid):
return
markup, rows = products_markup(uid, “pay”)
if not rows:
bot.send_message(uid, “📭 Avval tovar qo’shing.”, reply_markup=admin_menu())
return
bot.send_message(uid, “💸 *Qaysi tovar uchun to’lov?*”,
parse_mode=‘Markdown’, reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == “📊 Umumiy holat”)
def total_stats(msg):
uid = msg.from_user.id
if not is_allowed(uid):
return
db = get_db()
row = db.execute(“SELECT COUNT(*), SUM(total_price), SUM(paid_amount) FROM products”).fetchone()
db.close()
if not row or not row[0]:
bot.send_message(uid, “📭 Ma’lumot yo’q.”, reply_markup=get_menu(uid))
return
count = row[0] or 0
total = row[1] or 0
paid = row[2] or 0
remaining = total - paid
pct = (paid / total * 100) if total > 0 else 0
bar = “█” * int(pct / 5) + “░” * (20 - int(pct / 5))
bot.send_message(uid,
f”📊 *Umumiy holat*\n\n”
f”📦 Tovarlar: *{count} ta*\n\n”
f”💰 Jami nasiya: *{total:,.0f} so’m*\n”
f”✅ To’langan: *{paid:,.0f} so’m*\n”
f”🔴 Qolgan qarz: *{remaining:,.0f} so’m*\n\n”
f”`{bar}`\n”
f”*{pct:.1f}% to’langan*”,
parse_mode=‘Markdown’, reply_markup=get_menu(uid))

# ========== XODIMLAR (Admin) ==========

@bot.message_handler(func=lambda m: m.text == “👥 Xodimlar”)
def workers_menu(msg):
uid = msg.from_user.id
if not is_admin(uid):
return
db = get_db()
workers = db.execute(“SELECT user_id, full_name, username, role FROM users”).fetchall()
db.close()

```
text = "👥 *Foydalanuvchilar:*\n\n"
for w in workers:
    role_icon = "👑" if w['role'] == 'admin' else "👤"
    uname = f"@{w['username']}" if w['username'] else "—"
    text += f"{role_icon} *{w['full_name']}* ({uname})\n"

markup = types.InlineKeyboardMarkup()
markup.add(types.InlineKeyboardButton("➕ Xodim qo'shish", callback_data="add_worker"))
markup.add(types.InlineKeyboardButton("🗑 Xodim o'chirish", callback_data="remove_worker"))
bot.send_message(uid, text, parse_mode='Markdown', reply_markup=markup)
```

@bot.message_handler(func=lambda m: m.text == “⚙️ Sozlamalar”)
def settings(msg):
uid = msg.from_user.id
if not is_admin(uid):
return
bot.send_message(uid,
“⚙️ *Sozlamalar*\n\n”
f”🆔 Sizning ID: `{uid}`\n\n”
“Xodim qo’shish uchun uning Telegram ID sini yuboring yoki “
“👥 Xodimlar menyusidan foydalaning.”,
parse_mode=‘Markdown’, reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == “❌ Bekor qilish”)
def cancel_action(msg):
uid = msg.from_user.id
clear_state(uid)
bot.send_message(uid, “❌ Bekor qilindi.”, reply_markup=get_menu(uid))

@bot.message_handler(func=lambda m: m.text == “⏭ O’tkazib yuborish”)
def skip_step(msg):
uid = msg.from_user.id
st = get_state(uid)
state = st[‘state’]
data = st[‘data’]

```
if state == 'prod_supplier':
    set_state(uid, 'prod_price', data)
    bot.send_message(uid, "💰 *Jami narxini kiriting (so'mda):*\n_Misol: 15000000_",
                     parse_mode='Markdown', reply_markup=skip_kb())
elif state == 'prod_due':
    set_state(uid, 'prod_photo', data)
    bot.send_message(uid, "📷 *Tovar rasmini yuboring:*\n_(O'tkazib yuborsa ham bo'ladi)_",
                     parse_mode='Markdown', reply_markup=skip_kb())
elif state == 'prod_photo':
    _save_product(uid, data)
elif state == 'prod_note':
    _save_product(uid, data)
```

# ========== MATN HANDLERLARI ==========

@bot.message_handler(content_types=[‘text’, ‘photo’])
def handle_all(msg):
uid = msg.from_user.id
if not is_allowed(uid):
bot.send_message(uid, “🔒 Kirish taqiqlangan. Admindan ruxsat so’rang.”)
return

```
st = get_state(uid)
state = st['state']
data = st['data']

# === TOVAR QO'SHISH BOSQICHLARI ===
if state == 'prod_name':
    name = msg.text.strip() if msg.text else ''
    if len(name) < 2:
        bot.send_message(uid, "⚠️ Iltimos, tovar nomini to'g'ri kiriting.")
        return
    data['name'] = name
    set_state(uid, 'prod_supplier', data)
    bot.send_message(uid, f"✅ Tovar: *{name}*\n\n🏪 *Yetkazuvchi ismini kiriting:*\n_(O'tkazish mumkin)_",
                     parse_mode='Markdown', reply_markup=skip_kb())

elif state == 'prod_supplier':
    data['supplier'] = msg.text.strip() if msg.text else ''
    set_state(uid, 'prod_price', data)
    bot.send_message(uid, "💰 *Jami narxini kiriting (so'mda):*\n_Misol: 15000000_",
                     parse_mode='Markdown', reply_markup=skip_kb())

elif state == 'prod_price':
    try:
        price = float((msg.text or '').replace(',', '').replace(' ', ''))
        if price <= 0:
            raise ValueError
    except:
        bot.send_message(uid, "⚠️ To'g'ri raqam kiriting. _Misol: 15000000_", parse_mode='Markdown')
        return
    data['price'] = price
    set_state(uid, 'prod_due', data)
    bot.send_message(uid,
        "📅 *To'lov muddatini kiriting:*\n_Format: 25.12.2024_\n_(O'tkazish mumkin)_",
        parse_mode='Markdown', reply_markup=skip_kb())

elif state == 'prod_due':
    text = (msg.text or '').strip()
    try:
        due = datetime.strptime(text, '%d.%m.%Y').isoformat()
        data['due_date'] = due
    except:
        data['due_date'] = None
    set_state(uid, 'prod_photo', data)
    bot.send_message(uid, "📷 *Tovar rasmini yuboring:*\n_(O'tkazish mumkin)_",
                     parse_mode='Markdown', reply_markup=skip_kb())

elif state == 'prod_photo':
    if msg.photo:
        data['photo'] = msg.photo[-1].file_id
    set_state(uid, 'prod_note', data)
    bot.send_message(uid, "📝 *Izoh yozing:*\n_(O'tkazish mumkin)_",
                     parse_mode='Markdown', reply_markup=skip_kb())

elif state == 'prod_note':
    data['note'] = msg.text.strip() if msg.text else ''
    _save_product(uid, data)

# === TO'LOV BOSQICHLARI ===
elif state == 'pay_amount':
    try:
        amount = float((msg.text or '').replace(',', '').replace(' ', ''))
        if amount <= 0:
            raise ValueError
    except:
        bot.send_message(uid, "⚠️ To'g'ri summa kiriting.", reply_markup=cancel_kb())
        return

    db = get_db()
    prod = db.execute("SELECT total_price, paid_amount FROM products WHERE id=?",
                      (data['product_id'],)).fetchone()
    db.close()

    if not prod:
        bot.send_message(uid, "❌ Tovar topilmadi.", reply_markup=admin_menu())
        clear_state(uid)
        return

    remaining = prod['total_price'] - prod['paid_amount']
    if amount > remaining:
        amount = remaining

    data['amount'] = amount
    set_state(uid, 'pay_type', data)

    m = types.InlineKeyboardMarkup()
    m.add(
        types.InlineKeyboardButton("💵 Naqd pul", callback_data="ptype:cash"),
        types.InlineKeyboardButton("💳 Klik/Karta", callback_data="ptype:click")
    )
    bot.send_message(uid,
        f"💸 Summa: *{amount:,.0f} so'm*\n\n"
        f"💳 *To'lov turi?*",
        parse_mode='Markdown', reply_markup=m)

elif state == 'pay_receipt':
    if msg.photo:
        data['receipt'] = msg.photo[-1].file_id
    _save_payment(uid, data)

# === XODIM QO'SHISH ===
elif state == 'add_worker_id':
    try:
        worker_id = int((msg.text or '').strip())
    except:
        bot.send_message(uid, "⚠️ Telegram ID raqam bo'lishi kerak.", reply_markup=cancel_kb())
        return
    set_state(uid, 'add_worker_name', {'worker_id': worker_id})
    bot.send_message(uid, "👤 *Xodim ismini kiriting:*", parse_mode='Markdown', reply_markup=cancel_kb())

elif state == 'add_worker_name':
    worker_name = (msg.text or '').strip()
    worker_id = data['worker_id']
    db = get_db()
    existing = db.execute("SELECT user_id FROM users WHERE user_id=?", (worker_id,)).fetchone()
    if existing:
        bot.send_message(uid, "⚠️ Bu foydalanuvchi allaqachon mavjud.", reply_markup=admin_menu())
    else:
        db.execute("INSERT INTO users (user_id, full_name, username, role, added_at, added_by) VALUES (?,?,'','worker',?,?)",
                   (worker_id, worker_name, datetime.now().isoformat(), uid))
        db.commit()
        try:
            bot.send_message(worker_id,
                f"✅ Siz *Kafe Nasiya Daftari*ga xodim sifatida qo'shildingiz!\n\n"
                f"Endi botdan foydalanishingiz mumkin.",
                parse_mode='Markdown', reply_markup=worker_menu())
        except:
            pass
        bot.send_message(uid, f"✅ *{worker_name}* xodim sifatida qo'shildi!", parse_mode='Markdown', reply_markup=admin_menu())
    db.close()
    clear_state(uid)
```

def _save_product(uid, data):
now = datetime.now().isoformat()
db = get_db()
db.execute(
“INSERT INTO products (name, supplier_name, total_price, paid_amount, due_date, photo_file_id, note, created_at, updated_at, created_by) “
“VALUES (?,?,?,0,?,?,?,?,?,?)”,
(data.get(‘name’), data.get(‘supplier’), data.get(‘price’),
data.get(‘due_date’), data.get(‘photo’), data.get(‘note’), now, now, uid)
)
pid = db.execute(“SELECT last_insert_rowid()”).fetchone()[0]

```
# Eslatma qo'shish (muddat 1 kun oldin)
if data.get('due_date'):
    due = datetime.fromisoformat(data['due_date'])
    remind_at = (due - timedelta(days=1)).isoformat()
    db.execute("INSERT INTO reminders (product_id, remind_at) VALUES (?,?)", (pid, remind_at))

db.commit()
db.close()
clear_state(uid)

bot.send_message(uid,
    f"✅ *Tovar qo'shildi!*\n\n"
    f"📦 *{data.get('name')}*\n"
    f"💰 Jami: *{data.get('price', 0):,.0f} so'm*\n\n"
    f"To'lov kiritish uchun *💸 To'lov kiritish* tugmasini bosing.",
    parse_mode='Markdown', reply_markup=admin_menu())
```

def _save_payment(uid, data):
product_id = data[‘product_id’]
amount = data[‘amount’]
ptype = data.get(‘ptype’, ‘cash’)
receipt = data.get(‘receipt’)
now = datetime.now().isoformat()

```
db = get_db()
db.execute("UPDATE products SET paid_amount = paid_amount + ?, updated_at=? WHERE id=?",
           (amount, now, product_id))
db.execute("INSERT INTO payments (product_id, amount, payment_type, receipt_file_id, paid_at, added_by) VALUES (?,?,?,?,?,?)",
           (product_id, amount, ptype, receipt, now, uid))
db.commit()

prod = db.execute("SELECT name, total_price, paid_amount FROM products WHERE id=?", (product_id,)).fetchone()
payments = db.execute("SELECT amount, payment_type, paid_at FROM payments WHERE product_id=? ORDER BY paid_at",
                      (product_id,)).fetchall()
db.close()

remaining = prod['total_price'] - prod['paid_amount']
clear_state(uid)

bot.send_message(uid, "🧾 *Chek tayyorlanmoqda...*", parse_mode='Markdown')

try:
    prod_dict = dict(prod)
    pay_list = [dict(p) for p in payments]
    receipt_img = generate_receipt(prod_dict, pay_list, remaining)
    caption = (
        f"🧾 *{prod['name']}* — To'lov cheki\n\n"
        f"💸 To'langan: *{amount:,.0f} so'm*\n"
        f"⏳ Qolgan: *{remaining:,.0f} so'm*\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    bot.send_photo(uid, receipt_img, caption=caption, parse_mode='Markdown', reply_markup=admin_menu())
except Exception as e:
    logging.error(f"Receipt error: {e}")
    bot.send_message(uid,
        f"✅ *To'lov kiritildi!*\n\n"
        f"💸 {amount:,.0f} so'm\n"
        f"⏳ Qolgan: {remaining:,.0f} so'm",
        parse_mode='Markdown', reply_markup=admin_menu())
```

# ========== CALLBACK HANDLERS ==========

@bot.callback_query_handler(func=lambda c: c.data.startswith(“view:”))
def cb_view(call):
uid = call.from_user.id
pid = int(call.data.split(”:”)[1])
db = get_db()
prod = db.execute(“SELECT * FROM products WHERE id=?”, (pid,)).fetchone()
payments = db.execute(“SELECT * FROM payments WHERE product_id=? ORDER BY paid_at DESC”, (pid,)).fetchall()
db.close()

```
if not prod:
    bot.answer_callback_query(call.id, "Topilmadi!")
    return

remaining = prod['total_price'] - prod['paid_amount']
pct = min((prod['paid_amount'] / prod['total_price'] * 100) if prod['total_price'] > 0 else 0, 100)
bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))

pay_history = ""
for p in payments[:5]:
    icon = "💳" if p['payment_type'] == 'click' else "💵"
    dt = p['paid_at'][:16].replace('T', ' ')
    pay_history += f"  {icon} {dt} — *{p['amount']:,.0f}* so'm\n"

text = (
    f"📦 *{prod['name']}*\n"
    f"{'🏪 ' + prod['supplier_name'] if prod['supplier_name'] else ''}\n\n"
    f"💰 Jami nasiya: *{prod['total_price']:,.0f} so'm*\n"
    f"✅ To'langan: *{prod['paid_amount']:,.0f} so'm*\n"
    f"🔴 Qolgan qarz: *{remaining:,.0f} so'm*\n\n"
    f"`{bar}` {pct:.0f}%\n\n"
)
if pay_history:
    text += f"📋 *So'nggi to'lovlar:*\n{pay_history}"

m = types.InlineKeyboardMarkup(row_width=2)
if is_admin(uid):
    m.add(
        types.InlineKeyboardButton("💸 To'lov", callback_data=f"pay:{pid}"),
        types.InlineKeyboardButton("🧾 Chek", callback_data=f"receipt:{pid}")
    )
    m.add(
        types.InlineKeyboardButton("📋 Barcha to'lovlar", callback_data=f"history:{pid}"),
        types.InlineKeyboardButton("🗑 O'chirish", callback_data=f"del:{pid}")
    )
else:
    m.add(
        types.InlineKeyboardButton("🧾 Chek", callback_data=f"receipt:{pid}"),
        types.InlineKeyboardButton("📋 Barcha to'lovlar", callback_data=f"history:{pid}")
    )

bot.answer_callback_query(call.id)
if prod['photo_file_id']:
    bot.send_photo(uid, prod['photo_file_id'], caption=text, parse_mode='Markdown', reply_markup=m)
else:
    bot.send_message(uid, text, parse_mode='Markdown', reply_markup=m)
```

@bot.callback_query_handler(func=lambda c: c.data.startswith(“pay:”))
def cb_pay(call):
uid = call.from_user.id
if not is_admin(uid):
bot.answer_callback_query(call.id, “❌ Ruxsat yo’q!”)
return
pid = int(call.data.split(”:”)[1])
db = get_db()
prod = db.execute(“SELECT name, total_price, paid_amount FROM products WHERE id=?”, (pid,)).fetchone()
db.close()
remaining = prod[‘total_price’] - prod[‘paid_amount’]
if remaining <= 0:
bot.answer_callback_query(call.id, “✅ Bu tovar to’liq to’langan!”)
return
set_state(uid, ‘pay_amount’, {‘product_id’: pid})
bot.answer_callback_query(call.id)
bot.send_message(uid,
f”💸 *{prod[‘name’]}* uchun to’lov\n\n”
f”⏳ Qolgan qarz: *{remaining:,.0f} so’m*\n\n”
f”💰 To’lov summasini kiriting:”,
parse_mode=‘Markdown’, reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith(“ptype:”))
def cb_ptype(call):
uid = call.from_user.id
ptype = call.data.split(”:”)[1]
st = get_state(uid)
data = st[‘data’]
data[‘ptype’] = ptype
set_state(uid, ‘pay_receipt’ if ptype == ‘click’ else ‘pay_done’, data)
bot.answer_callback_query(call.id)

```
if ptype == 'click':
    set_state(uid, 'pay_receipt', data)
    bot.send_message(uid,
        "📎 *Klik cheki rasmini yuboring:*\n_(O'tkazish mumkin)_",
        parse_mode='Markdown', reply_markup=skip_kb())
else:
    _save_payment(uid, data)
```

@bot.callback_query_handler(func=lambda c: c.data.startswith(“receipt:”))
def cb_receipt(call):
uid = call.from_user.id
pid = int(call.data.split(”:”)[1])
db = get_db()
prod = db.execute(“SELECT * FROM products WHERE id=?”, (pid,)).fetchone()
payments = db.execute(“SELECT * FROM payments WHERE product_id=? ORDER BY paid_at”, (pid,)).fetchall()
db.close()
remaining = prod[‘total_price’] - prod[‘paid_amount’]
bot.answer_callback_query(call.id, “🧾 Chek tayyorlanmoqda…”)
try:
img = generate_receipt(dict(prod), [dict(p) for p in payments], remaining)
caption = (
f”🧾 *{prod[‘name’]}* — Chek\n”
f”⏳ Qolgan qarz: *{remaining:,.0f} so’m*\n”
f”🕐 {datetime.now().strftime(’%d.%m.%Y %H:%M’)}”
)
bot.send_photo(uid, img, caption=caption, parse_mode=‘Markdown’)
except Exception as e:
bot.send_message(uid, f”❌ Xatolik: {e}”)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“history:”))
def cb_history(call):
uid = call.from_user.id
pid = int(call.data.split(”:”)[1])
db = get_db()
prod = db.execute(“SELECT name FROM products WHERE id=?”, (pid,)).fetchone()
payments = db.execute(“SELECT * FROM payments WHERE product_id=? ORDER BY paid_at DESC”, (pid,)).fetchall()
db.close()

```
if not payments:
    bot.answer_callback_query(call.id, "Hali to'lov yo'q!")
    return

text = f"📋 *{prod['name']}* — Barcha to'lovlar:\n\n"
total_paid = 0
for i, p in enumerate(payments, 1):
    icon = "💳" if p['payment_type'] == 'click' else "💵"
    dt = p['paid_at'][:16].replace('T', ' ')
    text += f"{i}. {icon} *{p['amount']:,.0f} so'm* — {dt}\n"
    if p['receipt_file_id']:
        text += f"   🧾 Klik cheki mavjud\n"
    total_paid += p['amount']

text += f"\n✅ Jami to'langan: *{total_paid:,.0f} so'm*"

bot.answer_callback_query(call.id)
bot.send_message(uid, text, parse_mode='Markdown')

# Klik cheklarini yuborish
for p in payments:
    if p['receipt_file_id']:
        try:
            bot.send_photo(uid, p['receipt_file_id'],
                           caption=f"💳 Klik cheki — {p['paid_at'][:10]} | {p['amount']:,.0f} so'm")
        except:
            pass
```

@bot.callback_query_handler(func=lambda c: c.data.startswith(“del:”))
def cb_delete(call):
uid = call.from_user.id
if not is_admin(uid):
bot.answer_callback_query(call.id, “❌ Ruxsat yo’q!”)
return
pid = int(call.data.split(”:”)[1])
m = types.InlineKeyboardMarkup()
m.add(
types.InlineKeyboardButton(“✅ Ha, o’chirish”, callback_data=f”delok:{pid}”),
types.InlineKeyboardButton(“❌ Yo’q”, callback_data=“delno”)
)
bot.answer_callback_query(call.id)
bot.send_message(uid, “⚠️ *Haqiqatan ham bu tovarni o’chirmoqchimisiz?*\n\nBarcha to’lov tarixi ham o’chadi!”,
parse_mode=‘Markdown’, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“delok:”))
def cb_delok(call):
uid = call.from_user.id
pid = int(call.data.split(”:”)[1])
db = get_db()
db.execute(“DELETE FROM payments WHERE product_id=?”, (pid,))
db.execute(“DELETE FROM reminders WHERE product_id=?”, (pid,))
db.execute(“DELETE FROM products WHERE id=?”, (pid,))
db.commit()
db.close()
bot.answer_callback_query(call.id, “🗑 O’chirildi!”)
bot.send_message(uid, “🗑 Tovar o’chirildi.”, reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda c: c.data == “delno”)
def cb_delno(call):
bot.answer_callback_query(call.id, “❌ Bekor qilindi”)

@bot.callback_query_handler(func=lambda c: c.data == “add_worker”)
def cb_add_worker(call):
uid = call.from_user.id
if not is_admin(uid):
bot.answer_callback_query(call.id, “❌ Ruxsat yo’q!”)
return
set_state(uid, ‘add_worker_id’)
bot.answer_callback_query(call.id)
bot.send_message(uid,
“👤 *Xodim qo’shish*\n\n”
“Xodimingizga botga `/start` yuborishni so’rang.\n”
“Keyin uning *Telegram ID* sini yuboring:\n\n”
“*ID ni bilish uchun @userinfobot ga /start yuboring*”,
parse_mode=‘Markdown’, reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data == “remove_worker”)
def cb_remove_worker(call):
uid = call.from_user.id
if not is_admin(uid):
bot.answer_callback_query(call.id, “Ruxsat yo’q!”)
return
db = get_db()
workers = db.execute(“SELECT user_id, full_name FROM users WHERE role=‘worker’”).fetchall()
db.close()
if not workers:
bot.answer_callback_query(call.id, “Xodim yo’q!”)
return
m = types.InlineKeyboardMarkup()
for w in workers:
m.add(types.InlineKeyboardButton(f”🗑 {w[‘full_name’]}”, callback_data=f”delworker:{w[‘user_id’]}”))
bot.answer_callback_query(call.id)
bot.send_message(uid, “👤 Qaysi xodimni o’chirasiz?”, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“delworker:”))
def cb_delworker(call):
uid = call.from_user.id
wid = int(call.data.split(”:”)[1])
db = get_db()
db.execute(“DELETE FROM users WHERE user_id=? AND role=‘worker’”, (wid,))
db.commit()
db.close()
bot.answer_callback_query(call.id, “✅ O’chirildi!”)
bot.send_message(uid, “✅ Xodim o’chirildi.”, reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda c: c.data.startswith(“pay:”) and “:” in c.data)
def cb_pay_from_list(call):
uid = call.from_user.id
pid = int(call.data.split(”:”)[1])
db = get_db()
prod = db.execute(“SELECT name, total_price, paid_amount FROM products WHERE id=?”, (pid,)).fetchone()
db.close()
remaining = prod[‘total_price’] - prod[‘paid_amount’]
set_state(uid, ‘pay_amount’, {‘product_id’: pid})
bot.answer_callback_query(call.id)
bot.send_message(uid,
f”💸 *{prod[‘name’]}* uchun to’lov\n\n”
f”Qolgan: *{remaining:,.0f} so’m*\n\nSumma kiriting:”,
parse_mode=‘Markdown’, reply_markup=cancel_kb())

# ========== ISHGA TUSHIRISH ==========

if **name** == ‘**main**’:
init_db()
print(“☕ Kafe Nasiya Daftari Bot ishga tushdi!”)

```
# Eslatma thread
t = threading.Thread(target=reminder_loop, daemon=True)
t.start()

bot.infinity_polling(timeout=30, long_polling_timeout=20)
```
