import os, sqlite3, logging, threading, time, secrets, urllib.request, json
from datetime import datetime, timedelta
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import telebot
from telebot import types
from flask import Flask, render_template_string, jsonify, request

BOT_TOKEN = os.environ.get(“BOT_TOKEN”, “YOUR_BOT_TOKEN_HERE”)
WEB_SECRET = os.environ.get(“WEB_SECRET”, “secret123”)
WEB_PORT   = int(os.environ.get(“WEB_PORT”, 5000))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(**name**)
logging.basicConfig(level=logging.INFO, format=’%(asctime)s - %(message)s’)
DB_PATH = ‘cafe_debts.db’

# ═══════════════════════════════════════════════════════════════════════════════

# DATABASE

# ═══════════════════════════════════════════════════════════════════════════════

def init_db():
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()
c.execute(’’‘CREATE TABLE IF NOT EXISTS users (
user_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT,
role TEXT DEFAULT ‘worker’, added_at TEXT, added_by INTEGER)’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS products (
id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
supplier_name TEXT, total_price REAL NOT NULL, paid_amount REAL DEFAULT 0,
due_date TEXT, photo_file_id TEXT, note TEXT,
naqd_account TEXT, online_account TEXT, online_bank TEXT,
created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by INTEGER)’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS payments (
id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
amount REAL NOT NULL, payment_type TEXT DEFAULT ‘cash’,
receipt_file_id TEXT, note TEXT, paid_at TEXT NOT NULL, added_by INTEGER,
FOREIGN KEY(product_id) REFERENCES products(id))’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS reminders (
id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
remind_at TEXT NOT NULL, sent INTEGER DEFAULT 0,
FOREIGN KEY(product_id) REFERENCES products(id))’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS sklad_items (
id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
quantity REAL DEFAULT 0, unit TEXT DEFAULT ‘dona’,
unit_type TEXT DEFAULT ‘dona’, min_alert REAL DEFAULT 10,
photo_file_id TEXT, created_at TEXT NOT NULL,
updated_at TEXT NOT NULL, created_by INTEGER)’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS sklad_kirim (
id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
quantity REAL NOT NULL, note TEXT, added_at TEXT NOT NULL, added_by INTEGER,
FOREIGN KEY(item_id) REFERENCES sklad_items(id))’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS sklad_chiqim (
id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
quantity REAL NOT NULL, note TEXT, added_at TEXT NOT NULL, added_by INTEGER,
FOREIGN KEY(item_id) REFERENCES sklad_items(id))’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS sklad_permissions (
user_id INTEGER PRIMARY KEY, full_name TEXT,
granted_at TEXT, granted_by INTEGER)’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS sklad_requests (
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
full_name TEXT, username TEXT, requested_at TEXT, status TEXT DEFAULT ‘pending’)’’’)
c.execute(’’‘CREATE TABLE IF NOT EXISTS yetkazuvchilar (
id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL,
phone TEXT, extra_phone TEXT, company TEXT, note TEXT,
created_at TEXT NOT NULL, created_by INTEGER)’’’)
for col in [(“min_alert”,“REAL DEFAULT 10”),(“unit_type”,“TEXT DEFAULT ‘dona’”)]:
try: c.execute(f”ALTER TABLE sklad_items ADD COLUMN {col[0]} {col[1]}”)
except: pass
conn.commit(); conn.close()

def get_db():
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
return conn

# ═══════════════════════════════════════════════════════════════════════════════

# RUXSATLAR

# ═══════════════════════════════════════════════════════════════════════════════

def get_admin_id():
db = get_db()
row = db.execute(“SELECT user_id FROM users WHERE role=‘admin’ LIMIT 1”).fetchone()
db.close()
return row[‘user_id’] if row else None

def is_admin(uid):
db = get_db()
row = db.execute(“SELECT role FROM users WHERE user_id=?”, (uid,)).fetchone()
db.close()
return row and row[‘role’] == ‘admin’

def is_allowed(uid):
db = get_db()
row = db.execute(“SELECT user_id FROM users WHERE user_id=?”, (uid,)).fetchone()
db.close()
return row is not None

def is_sklad_allowed(uid):
if is_admin(uid): return True
db = get_db()
row = db.execute(“SELECT user_id FROM sklad_permissions WHERE user_id=?”, (uid,)).fetchone()
db.close()
return row is not None

def register_admin(uid, full_name, username):
db = get_db()
if not db.execute(“SELECT user_id FROM users WHERE user_id=?”, (uid,)).fetchone():
db.execute(“INSERT INTO users(user_id,full_name,username,role,added_at) VALUES(?,?,?,‘admin’,?)”,
(uid, full_name, username or ‘’, datetime.now().isoformat()))
db.commit()
db.close()

def notify_admin(text, parse_mode=‘Markdown’):
aid = get_admin_id()
if aid:
try: bot.send_message(aid, text, parse_mode=parse_mode)
except: pass

# ═══════════════════════════════════════════════════════════════════════════════

# STATE

# ═══════════════════════════════════════════════════════════════════════════════

user_states = {}
def set_state(uid, s, data=None): user_states[uid] = {‘state’: s, ‘data’: data or {}}
def get_state(uid): return user_states.get(uid, {‘state’: None, ‘data’: {}})
def clear_state(uid): user_states.pop(uid, None)

# ═══════════════════════════════════════════════════════════════════════════════

# CHEK RASMI

# ═══════════════════════════════════════════════════════════════════════════════

def generate_receipt(product, payments, remaining):
W=600; H=800+len(payments)*62
img=Image.new(‘RGB’,(W,H),’#0d1117’); draw=ImageDraw.Draw(img)
for i in range(H):
draw.line([(0,i),(W,i)],fill=(int(13+(20-13)*i/H),int(17+(28-17)*i/H),int(23+(45-23)*i/H)))
def rr(x1,y1,x2,y2,r=12,fill=None,outline=None,w=2):
draw.rounded_rectangle([x1,y1,x2,y2],radius=r,fill=fill,outline=outline,width=w)
def lf(sz,bold=False):
for p in [f”/usr/share/fonts/truetype/dejavu/DejaVuSans{‘Bold’ if bold else ‘’}.ttf”,
f”/usr/share/fonts/truetype/liberation/LiberationSans-{‘Bold’ if bold else ‘Regular’}.ttf”]:
try: return ImageFont.truetype(p,sz)
except: pass
return ImageFont.load_default()
f24b=lf(24,True); f20b=lf(20,True); f16=lf(16); f14=lf(14); f20=lf(20)
rr(15,15,W-15,110,r=20,fill=’#161b22’,outline=’#30363d’)
draw.text((W//2,48),“☕ KAFE NASIYA DAFTARI”,font=f24b,fill=’#f0883e’,anchor=‘mm’)
draw.text((W//2,84),“Tovar Hisobi & To’lov Cheki”,font=f16,fill=’#8b949e’,anchor=‘mm’)
y=128; rr(15,y,W-15,y+110,r=15,fill=’#161b22’,outline=’#30363d’)
draw.text((35,y+10),“📦  TOVAR”,font=f14,fill=’#8b949e’)
draw.text((35,y+34),product[‘name’],font=f24b,fill=’#e6edf3’)
if product.get(‘supplier_name’): draw.text((35,y+70),f”🏪  {product[‘supplier_name’]}”,font=f16,fill=’#8b949e’)
draw.text((W-35,y+34),f”{product[‘total_price’]:,.0f}”,font=f24b,fill=’#f0883e’,anchor=‘ra’)
draw.text((W-35,y+64),“so’m (jami)”,font=f14,fill=’#8b949e’,anchor=‘ra’)
y+=122; draw.text((35,y+4),“📋  TO’LOVLAR”,font=f16,fill=’#8b949e’); y+=26
bh=len(payments)*58+18 if payments else 46
rr(15,y,W-15,y+bh,r=15,fill=’#161b22’,outline=’#30363d’); y+=10
if not payments:
draw.text((W//2,y+14),“Hali to’lov kiritilmagan”,font=f16,fill=’#484f58’,anchor=‘mm’); y+=36
else:
for i,p in enumerate(payments):
rr(25,y,W-25,y+50,r=8,fill=’#1c2128’ if i%2==0 else ‘#161b22’)
draw.text((42,y+7),f”{‘💳’ if p[‘payment_type’]==‘click’ else ‘💵’} {str(p[‘paid_at’])[:16].replace(‘T’,’ ‘)}”,font=f14,fill=’#8b949e’)
draw.text((W-40,y+16),f”+{p[‘amount’]:,.0f} so’m”,font=f20b,fill=’#3fb950’,anchor=‘rm’); y+=54
y+=16
paid=product[‘paid_amount’]; total=product[‘total_price’]
pct=min((paid/total*100) if total>0 else 0,100)
rr(15,y,W-15,y+170,r=15,fill=’#161b22’,outline=’#30363d’)
bx,by=35,y+40; bw=W-70; bfh=18
rr(bx,by,bx+bw,by+bfh,r=9,fill=’#21262d’)
fw=int(bw*pct/100)
if fw>10:
bc=’#3fb950’ if pct>=90 else ‘#f0883e’ if pct>=50 else ‘#f85149’
rr(bx,by,bx+fw,by+bfh,r=9,fill=bc)
draw.text((W//2,by+bfh+14),f”{pct:.1f}%  to’langan”,font=f16,fill=’#8b949e’,anchor=‘mm’)
draw.text((35,y+94),“✅  To’langan:”,font=f20,fill=’#8b949e’)
draw.text((W-35,y+94),f”{paid:,.0f} so’m”,font=f20b,fill=’#3fb950’,anchor=‘ra’)
draw.text((35,y+128),“⏳  Qolgan:”,font=f20,fill=’#8b949e’)
if remaining<=0: draw.text((W-35,y+128),“✅ To’liq to’landi!”,font=f20b,fill=’#3fb950’,anchor=‘ra’)
else: draw.text((W-35,y+128),f”{remaining:,.0f} so’m”,font=f24b,fill=’#f85149’,anchor=‘ra’)
y+=180
draw.line([(35,y),(W-35,y)],fill=’#30363d’,width=1)
draw.text((W//2,y+14),f”🕐  {datetime.now().strftime(’%d.%m.%Y  %H:%M’)}”,font=f14,fill=’#484f58’,anchor=‘mm’)
draw.rounded_rectangle([2,2,W-3,H-3],radius=22,outline=’#f0883e’,width=2)
buf=BytesIO(); img.save(buf,format=‘PNG’); buf.seek(0); return buf

# ═══════════════════════════════════════════════════════════════════════════════

# KLAVIATURA

# ═══════════════════════════════════════════════════════════════════════════════

def admin_menu():
m=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
m.add(“➕ Yangi tovar”,“📦 Tovarlar”,“💸 To’lov kiritish”,
“📊 Umumiy holat”,“👥 Xodimlar”,“🏪 Sklad”,“🌐 Web sahifa”,
“💵 Dollar kursi”)
return m

def worker_menu():
m=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
m.add(“📦 Tovarlar”,“📊 Umumiy holat”,“🏪 Sklad”,“💵 Dollar kursi”)
return m

def get_menu(uid): return admin_menu() if is_admin(uid) else worker_menu()

def cancel_kb():
m=types.ReplyKeyboardMarkup(resize_keyboard=True); m.add(“❌ Bekor qilish”); return m

def skip_kb():
m=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
m.add(“⏭ O’tkazib yuborish”,“❌ Bekor qilish”); return m

def products_markup(action=“view”):
db=get_db()
rows=db.execute(“SELECT id,name,total_price,paid_amount FROM products ORDER BY created_at DESC”).fetchall()
db.close()
if not rows: return None,[]
m=types.InlineKeyboardMarkup(row_width=1)
for r in rows:
rem=r[‘total_price’]-r[‘paid_amount’]
m.add(types.InlineKeyboardButton(
f”{‘✅’ if rem<=0 else ‘🔴’}  {r[‘name’]}  |  {rem:,.0f} so’m qolgan”,
callback_data=f”{action}:{r[‘id’]}”))
return m,rows

# ═══════════════════════════════════════════════════════════════════════════════

# SKLAD OGOHLANTIRISH

# ═══════════════════════════════════════════════════════════════════════════════

def check_sklad_alert(item_id):
db=get_db()
item=db.execute(“SELECT * FROM sklad_items WHERE id=?”,(item_id,)).fetchone()
db.close()
if item and item[‘quantity’] <= item[‘min_alert’]:
notify_admin(
f”⚠️ *SKLAD OGOHLANTIRISH!*\n\n”
f”📦 *{item[‘name’]}* kam qoldi!\n”
f”📊 Qolgan: *{item[‘quantity’]} {item[‘unit’]}*\n”
f”🔔 Chegara: *{item[‘min_alert’]} {item[‘unit’]}*\n\n”
f”🛒 Zakaz berish kerak!”)

# ═══════════════════════════════════════════════════════════════════════════════

# ESLATMA

# ═══════════════════════════════════════════════════════════════════════════════

def reminder_loop():
while True:
try:
db=get_db(); now=datetime.now().isoformat()
rems=db.execute(
“SELECT r.id,p.name,p.total_price,p.paid_amount FROM reminders r “
“JOIN products p ON r.product_id=p.id WHERE r.sent=0 AND r.remind_at<=?”,(now,)).fetchall()
for rem in rems:
left=rem[‘total_price’]-rem[‘paid_amount’]
if left>0: notify_admin(f”⏰ *ESLATMA!*\n📦 *{rem[‘name’]}* to’lov muddati yaqinlashdi!\n💰 Qolgan: *{left:,.0f} so’m*”)
db.execute(“UPDATE reminders SET sent=1 WHERE id=?”,(rem[‘id’],)); db.commit()
db.close()
except Exception as e: logging.error(f”Reminder: {e}”)
time.sleep(60)

# ═══════════════════════════════════════════════════════════════════════════════

# /start

# ═══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(commands=[‘start’])
def cmd_start(msg):
uid=msg.from_user.id; name=msg.from_user.first_name; uname=msg.from_user.username or ‘’
if not get_admin_id():
register_admin(uid,name,uname)
bot.send_message(uid,f”👑 Assalomu alaykum, *{name}*!\nSiz *Admin* sifatida ro’yxatdan o’tdingiz.\n☕ *Kafe Nasiya Daftari*”,
parse_mode=‘Markdown’,reply_markup=admin_menu())
elif not is_allowed(uid):
bot.send_message(uid,“🔒 Siz tizimda yo’qsiz. Admin sizni qo’shishi kerak.”)
else:
bot.send_message(uid,f”👋 Xush kelibsiz, *{name}*!\nRolingiz: {‘👑 Admin’ if is_admin(uid) else ‘👤 Xodim’}”,
parse_mode=‘Markdown’,reply_markup=get_menu(uid))

# ═══════════════════════════════════════════════════════════════════════════════

# ASOSIY TUGMALAR

# ═══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text==“➕ Yangi tovar”)
def add_product(msg):
uid=msg.from_user.id
if not is_admin(uid): return
set_state(uid,‘prod_name’)
bot.send_message(uid,“📦 *Tovar nomini kiriting:*”,parse_mode=‘Markdown’,reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: m.text==“📦 Tovarlar”)
def show_products(msg):
uid=msg.from_user.id
if not is_allowed(uid): return
markup,rows=products_markup(“view”)
if not rows: bot.send_message(uid,“📭 Hali hech qanday tovar yo’q.”,reply_markup=get_menu(uid)); return
bot.send_message(uid,“📦 *Tovarlar ro’yxati:*”,parse_mode=‘Markdown’,reply_markup=markup)

@bot.message_handler(func=lambda m: m.text==“💸 To’lov kiritish”)
def pay_start(msg):
uid=msg.from_user.id
if not is_admin(uid): return
markup,rows=products_markup(“pay”)
if not rows: bot.send_message(uid,“📭 Avval tovar qo’shing.”,reply_markup=admin_menu()); return
bot.send_message(uid,“💸 *Qaysi tovar uchun to’lov?*”,parse_mode=‘Markdown’,reply_markup=markup)

@bot.message_handler(func=lambda m: m.text==“📊 Umumiy holat”)
def total_stats(msg):
uid=msg.from_user.id
if not is_allowed(uid): return
db=get_db(); row=db.execute(“SELECT COUNT(*),SUM(total_price),SUM(paid_amount) FROM products”).fetchone(); db.close()
if not row or not row[0]: bot.send_message(uid,“📭 Ma’lumot yo’q.”,reply_markup=get_menu(uid)); return
count=row[0] or 0; total=row[1] or 0; paid=row[2] or 0; rem=total-paid
pct=(paid/total*100) if total>0 else 0; bar=“█”*int(pct/5)+“░”*(20-int(pct/5))
bot.send_message(uid,
f”📊 *Umumiy holat*\n\n📦 Tovarlar: *{count} ta*\n”
f”💰 Jami nasiya: *{total:,.0f} so’m*\n✅ To’langan: *{paid:,.0f} so’m*\n”
f”🔴 Qolgan qarz: *{rem:,.0f} so’m*\n\n`{bar}`\n*{pct:.1f}% to’langan*”,
parse_mode=‘Markdown’,reply_markup=get_menu(uid))

@bot.message_handler(func=lambda m: m.text==“🌐 Web sahifa”)
def web_info(msg):
uid=msg.from_user.id
if not is_admin(uid): return
host=os.environ.get(“WEB_HOST”,“http://localhost:5000”)
bot.send_message(uid,f”🌐 *Web Dashboard*\n\n🔗 `{host}`\n🔑 Parol: `{WEB_SECRET}`”,
parse_mode=‘Markdown’,reply_markup=admin_menu())

# ═══════════════════════════════════════════════════════════════════════════════

# 💵 DOLLAR KURSI

# ═══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text==“💵 Dollar kursi”)
def dollar_kurs(msg):
uid=msg.from_user.id
if not is_allowed(uid): return
try:
url=“https://api.exchangerate-api.com/v4/latest/USD”
with urllib.request.urlopen(url, timeout=5) as r:
data=json.loads(r.read())
uzs=data[‘rates’][‘UZS’]
eur=data[‘rates’][‘EUR’]
rub=data[‘rates’][‘RUB’]
kzt=data[‘rates’][‘KZT’]
now=datetime.now().strftime(’%d.%m.%Y %H:%M’)
bot.send_message(uid,
f”💵 *Valyuta kurslari*\n”
f”*{now} holatiga ko’ra*\n\n”
f”🇺🇸 1 USD = *{uzs:,.0f} so’m*\n”
f”🇪🇺 1 EUR = *{uzs/eur:,.0f} so’m*\n”
f”🇷🇺 1 RUB = *{uzs/rub:,.2f} so’m*\n”
f”🇰🇿 1 KZT = *{uzs/kzt:,.2f} so’m*\n\n”
f”📡 *Kurs avtomatik yangilanadi*”,
parse_mode=‘Markdown’,reply_markup=get_menu(uid))
except:
bot.send_message(uid,
“❌ Kursni olishda xatolik. Internet aloqasini tekshiring.”,
reply_markup=get_menu(uid))

@bot.message_handler(func=lambda m: m.text==“👥 Xodimlar”)
def workers_menu_handler(msg):
uid=msg.from_user.id
if not is_admin(uid): return
db=get_db(); workers=db.execute(“SELECT user_id,full_name,username,role FROM users”).fetchall(); db.close()
text=“👥 *Foydalanuvchilar:*\n\n”
for w in workers:
text+=f”{‘👑’ if w[‘role’]==‘admin’ else ‘👤’} *{w[‘full_name’]}* ({’@’+w[‘username’] if w[‘username’] else ‘—’})\n”
m=types.InlineKeyboardMarkup()
m.add(types.InlineKeyboardButton(“➕ Xodim qo’shish”,callback_data=“add_worker”))
m.add(types.InlineKeyboardButton(“🗑 Xodim o’chirish”,callback_data=“remove_worker”))
bot.send_message(uid,text,parse_mode=‘Markdown’,reply_markup=m)

@bot.message_handler(func=lambda m: m.text==“❌ Bekor qilish”)
def cancel_action(msg):
clear_state(msg.from_user.id)
bot.send_message(msg.from_user.id,“❌ Bekor qilindi.”,reply_markup=get_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text==“⏭ O’tkazib yuborish”)
def skip_step(msg):
uid=msg.from_user.id; st=get_state(uid); state=st[‘state’]; data=st[‘data’]
skip_map = {
‘prod_supplier’: (‘prod_price’, “💰 *Jami narxini kiriting:*”),
‘prod_naqd_acc’: (‘prod_online_bank’, “🏦 *Online bank:*\n_(O’tkazish mumkin)*”),
‘prod_online_bank’: (‘prod_online_acc’, “💳 *Online hisob:*\n*(O’tkazish mumkin)*”),
‘prod_online_acc’: (‘prod_photo’, “📷 *Tovar rasmi:*\n*(O’tkazish mumkin)*”),
‘prod_photo’: (‘prod_note’, “📝 *Izoh:*\n*(O’tkazish mumkin)*”),
‘sklad_item_unit’: (‘sklad_item_photo’, “📷 *Mahsulot rasmi:* *(O’tkazish mumkin)*\n512x512 pixel”),
‘sklad_item_photo’: (None, None),
‘sklad_kirim_note’: (None, None),
‘sklad_chiqim_note’: (None, None),
‘sklad_contact_phone2’: (‘sklad_contact_company’, “🏢 *Kompaniya:*\n*(O’tkazish mumkin)*”),
‘sklad_contact_company’: (‘sklad_contact_note’, “📝 *Izoh:*\n*(O’tkazish mumkin)*”),
‘sklad_contact_note’: (None, None),
‘edit_supplier’: (None, None),
‘edit_due’: (None, None),
‘edit_naqd_acc’: (None, None),
‘edit_online_bank’: (None, None),
‘edit_online_acc’: (None, None),
‘edit_photo’: (None, None),
‘edit_note’: (None, None),
}
if state == ‘prod_due’:
data[‘due_date’] = None
set_state(uid,‘prod_naqd_acc’,data)
bot.send_message(uid,“💵 *Naqd karta:*\n*(O’tkazish mumkin)_”,parse_mode=‘Markdown’,reply_markup=skip_kb()); return
if state == ‘prod_note’: _save_product(uid,data); return
if state == ‘sklad_item_photo’: _save_sklad_item(uid,data); return
if state == ‘sklad_kirim_note’: data[‘note’]=’’; _save_sklad_kirim(uid,data); return
if state == ‘sklad_chiqim_note’: data[‘note’]=’’; _save_sklad_chiqim(uid,data); return
if state == ‘sklad_contact_note’: _save_contact(uid,data); return
if state in (‘edit_supplier’,‘edit_due’,‘edit_naqd_acc’,‘edit_online_bank’,‘edit_online_acc’,‘edit_note’):
_finish_edit(uid,data,{
‘edit_supplier’:‘supplier_name’,‘edit_due’:‘due_date’,‘edit_naqd_acc’:‘naqd_account’,
‘edit_online_bank’:‘online_bank’,‘edit_online_acc’:‘online_account’,‘edit_note’:‘note’
}[state], None); return
if state == ‘edit_photo’: _ask_edit_note(uid,data); return
if state in (‘sklad_contact_phone2’,‘sklad_contact_company’):
if state==‘sklad_contact_phone2’: data[‘extra_phone’]=None
if state==‘sklad_contact_company’: data[‘company’]=None
nxt,prm = skip_map[state]
set_state(uid,nxt,data); bot.send_message(uid,prm,parse_mode=‘Markdown’,reply_markup=skip_kb()); return
if state in skip_map:
nxt,prm = skip_map[state]
if state==‘sklad_item_unit’: data[‘unit’]=‘dona’
set_state(uid,nxt,data)
bot.send_message(uid,prm,parse_mode=‘Markdown’,reply_markup=skip_kb())

# ═══════════════════════════════════════════════════════════════════════════════

# SKLAD TUGMASI

# ═══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(func=lambda m: m.text==“🏪 Sklad”)
def sklad_main(msg):
uid=msg.from_user.id
if not is_allowed(uid): return
if not is_sklad_allowed(uid):
m=types.InlineKeyboardMarkup()
m.add(types.InlineKeyboardButton(“📩 Ruxsat so’rash”,callback_data=“sklad_request_access”))
bot.send_message(uid,“🔒 Sklad bo’limiga kirish uchun admin ruxsati kerak.”,reply_markup=m)
return
_send_sklad_main(uid)

def _send_sklad_main(uid):
m=types.InlineKeyboardMarkup(row_width=1)
m.add(
types.InlineKeyboardButton(“📥 Mahsulot kirim”,callback_data=“sklad:kirim_menu”),
types.InlineKeyboardButton(“📤 Mahsulot chiqim”,callback_data=“sklad:chiqim_list”),
types.InlineKeyboardButton(“📋 Barcha mahsulotlar”,callback_data=“sklad:all_items”),
types.InlineKeyboardButton(“📞 Yetkazuvchi kontaktlar”,callback_data=“sklad:yetkazuvchilar”),
)
if is_admin(uid):
m.add(types.InlineKeyboardButton(“⚙️ Sklad boshqaruvi”,callback_data=“sklad:admin_panel”))
bot.send_message(uid,“🏪 *Sklad boshqaruvi*\n\nQuyidagi bo’limlardan birini tanlang:”,
parse_mode=‘Markdown’,reply_markup=m)

# ═══════════════════════════════════════════════════════════════════════════════

# SKLAD CALLBACK

# ═══════════════════════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data==“sklad_request_access”)
def cb_sklad_request(call):
uid=call.from_user.id; name=call.from_user.first_name; uname=call.from_user.username or ‘’
db=get_db()
existing=db.execute(“SELECT id FROM sklad_requests WHERE user_id=? AND status=‘pending’”,(uid,)).fetchone()
if existing:
bot.answer_callback_query(call.id,“✅ Siz allaqachon so’rov yuborgansiz. Admin ko’rib chiqadi.”)
db.close(); return
db.execute(“INSERT INTO sklad_requests(user_id,full_name,username,requested_at) VALUES(?,?,?,?)”,
(uid,name,uname,datetime.now().isoformat()))
db.commit(); db.close()
bot.answer_callback_query(call.id,“✅ So’rovingiz adminga yuborildi!”)
bot.send_message(uid,“📩 So’rovingiz adminga yuborildi. Admin ruxsat berganidan so’ng sklad bo’limiga kira olasiz.”)
m=types.InlineKeyboardMarkup()
m.add(
types.InlineKeyboardButton(“✅ Ruxsat berish”,callback_data=f”sklad_grant:{uid}”),
types.InlineKeyboardButton(“❌ Rad etish”,callback_data=f”sklad_deny:{uid}”)
)
notify_admin(f”📩 *Sklad ruxsati so’rovi*\n\n👤 *{name}*\n{’@’+uname if uname else ‘’}\n\nSklad bo’limiga kirish ruxsati so’ramoqda.”)
aid=get_admin_id()
if aid:
try: bot.send_message(aid,f”📩 *{name}* sklad ruxsati so’ramoqda:”,parse_mode=‘Markdown’,reply_markup=m)
except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith(“sklad_grant:”))
def cb_sklad_grant(call):
uid=call.from_user.id
if not is_admin(uid): bot.answer_callback_query(call.id,“❌ Ruxsat yo’q!”); return
target_id=int(call.data.split(”:”)[1])
db=get_db()
user=db.execute(“SELECT full_name FROM users WHERE user_id=?”,(target_id,)).fetchone()
name=user[‘full_name’] if user else str(target_id)
existing=db.execute(“SELECT user_id FROM sklad_permissions WHERE user_id=?”,(target_id,)).fetchone()
if not existing:
db.execute(“INSERT INTO sklad_permissions(user_id,full_name,granted_at,granted_by) VALUES(?,?,?,?)”,
(target_id,name,datetime.now().isoformat(),uid))
db.execute(“UPDATE sklad_requests SET status=‘approved’ WHERE user_id=?”,(target_id,))
db.commit(); db.close()
bot.answer_callback_query(call.id,“✅ Ruxsat berildi!”)
bot.edit_message_reply_markup(call.message.chat.id,call.message.message_id,reply_markup=None)
bot.send_message(uid,f”✅ *{name}* ga sklad ruxsati berildi!”,parse_mode=‘Markdown’)
try: bot.send_message(target_id,“✅ *Sklad bo’limiga ruxsat berildi!*\n\nEndi 🏪 Sklad tugmasini bosib kira olasiz.”,parse_mode=‘Markdown’)
except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith(“sklad_deny:”))
def cb_sklad_deny(call):
uid=call.from_user.id
if not is_admin(uid): bot.answer_callback_query(call.id,“❌ Ruxsat yo’q!”); return
target_id=int(call.data.split(”:”)[1])
db=get_db()
db.execute(“UPDATE sklad_requests SET status=‘denied’ WHERE user_id=?”,(target_id,))
db.commit(); db.close()
bot.answer_callback_query(call.id,“❌ Rad etildi!”)
bot.edit_message_reply_markup(call.message.chat.id,call.message.message_id,reply_markup=None)
try: bot.send_message(target_id,“❌ Sklad bo’limiga ruxsat berilmadi. Admin bilan bog’laning.”)
except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith(“sklad:”))
def sklad_callback(call):
uid=call.from_user.id; action=call.data.split(”:”,1)[1]
bot.answer_callback_query(call.id)

```
if action=="back_main":
    _send_sklad_main(uid); return

elif action=="kirim_menu":
    if not is_sklad_allowed(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
    m=types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("➕ Yangi mahsulot qo'shish",callback_data="sklad:add_item"),
        types.InlineKeyboardButton("📥 Mavjud mahsulotga kirim",callback_data="sklad:kirim_existing"),
        types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
    bot.send_message(uid,"📥 *Mahsulot kirim*",parse_mode='Markdown',reply_markup=m)

elif action=="add_item":
    if not is_sklad_allowed(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
    set_state(uid,'sklad_item_name')
    bot.send_message(uid,"📦 *Yangi mahsulot nomi:*\n_Misol: Un, Shakar, Go'sht..._",
        parse_mode='Markdown',reply_markup=cancel_kb())

elif action=="add_item_dona":
    st=get_state(uid); data=st['data']; data['unit_type']='dona'; data['unit']='dona'
    set_state(uid,'sklad_item_photo',data)
    bot.send_message(uid,"📷 *Mahsulot rasmi:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())

elif action=="add_item_kg":
    st=get_state(uid); data=st['data']; data['unit_type']='kg'; data['unit']='kg'
    set_state(uid,'sklad_item_photo',data)
    bot.send_message(uid,"📷 *Mahsulot rasmi:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())

elif action.startswith("add_item_custom:"):
    unit=action.split(":",1)[1]; st=get_state(uid); data=st['data']
    data['unit_type']=unit; data['unit']=unit
    set_state(uid,'sklad_item_photo',data)
    bot.send_message(uid,"📷 *Mahsulot rasmi:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())

elif action=="kirim_existing":
    if not is_sklad_allowed(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
    db=get_db(); items=db.execute("SELECT id,name,quantity,unit FROM sklad_items ORDER BY name").fetchall(); db.close()
    if not items: bot.send_message(uid,"📭 Hali mahsulot yo'q. Avval yangi mahsulot qo'shing."); return
    m=types.InlineKeyboardMarkup(row_width=1)
    for item in items:
        m.add(types.InlineKeyboardButton(f"📦 {item['name']} | {item['quantity']} {item['unit']}",
            callback_data=f"sklad:kirim_item:{item['id']}"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:kirim_menu"))
    bot.send_message(uid,"📦 *Qaysi mahsulotga kirim?*",parse_mode='Markdown',reply_markup=m)

elif action.startswith("kirim_item:"):
    item_id=int(action.split(":")[1])
    db=get_db(); item=db.execute("SELECT * FROM sklad_items WHERE id=?",(item_id,)).fetchone(); db.close()
    set_state(uid,'sklad_kirim_qty',{'item_id':item_id,'item_name':item['name'],'unit':item['unit']})
    bot.send_message(uid,
        f"📥 *{item['name']}* uchun kirim\nHozirgi zaxira: *{item['quantity']} {item['unit']}*\n\nNecha {item['unit']} keldi?",
        parse_mode='Markdown',reply_markup=cancel_kb())

elif action=="chiqim_list":
    if not is_sklad_allowed(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
    db=get_db(); items=db.execute("SELECT id,name,quantity,unit FROM sklad_items WHERE quantity>0 ORDER BY name").fetchall(); db.close()
    if not items: bot.send_message(uid,"📭 Zaxirada mahsulot yo'q."); return
    m=types.InlineKeyboardMarkup(row_width=1)
    for item in items:
        m.add(types.InlineKeyboardButton(f"📦 {item['name']}",callback_data=f"sklad:chiqim_detail:{item['id']}"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
    bot.send_message(uid,"📤 *Qaysi mahsulotdan chiqim?*\n\nMahsulot tanlang:",parse_mode='Markdown',reply_markup=m)

elif action.startswith("chiqim_detail:"):
    item_id=int(action.split(":")[1])
    db=get_db(); item=db.execute("SELECT * FROM sklad_items WHERE id=?",(item_id,)).fetchone(); db.close()
    if not item: bot.send_message(uid,"❌ Topilmadi."); return
    text=(f"📦 *{item['name']}*\n\n"
          f"📊 Zaxirada: *{item['quantity']} {item['unit']}*\n"
          f"🔔 Ogohlantirish chegarasi: *{item['min_alert']} {item['unit']}*")
    m=types.InlineKeyboardMarkup(row_width=2)
    if is_sklad_allowed(uid):
        m.add(
            types.InlineKeyboardButton("➖ Ayirish (chiqim)",callback_data=f"sklad:chiqim_item:{item_id}"),
            types.InlineKeyboardButton("✏️ Tahrirlash",callback_data=f"sklad:edit_item:{item_id}")
        )
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:chiqim_list"))
    if item['photo_file_id']:
        bot.send_photo(uid,item['photo_file_id'],caption=text,parse_mode='Markdown',reply_markup=m)
    else:
        bot.send_message(uid,text,parse_mode='Markdown',reply_markup=m)

elif action.startswith("chiqim_item:"):
    item_id=int(action.split(":")[1])
    db=get_db(); item=db.execute("SELECT * FROM sklad_items WHERE id=?",(item_id,)).fetchone(); db.close()
    set_state(uid,'sklad_chiqim_qty',{'item_id':item_id,'item_name':item['name'],'unit':item['unit'],'current_qty':item['quantity']})
    bot.send_message(uid,
        f"📤 *{item['name']}* chiqim\nZaxirada: *{item['quantity']} {item['unit']}*\n\nNecha {item['unit']} chiqdi?",
        parse_mode='Markdown',reply_markup=cancel_kb())

elif action=="all_items":
    db=get_db(); items=db.execute("SELECT id,name,quantity,unit FROM sklad_items ORDER BY name").fetchall(); db.close()
    if not items: bot.send_message(uid,"📭 Sklad bo'sh."); return
    m=types.InlineKeyboardMarkup(row_width=1)
    for item in items:
        icon="✅" if item['quantity']>0 else "⚠️"
        m.add(types.InlineKeyboardButton(f"{icon} {item['name']}",callback_data=f"sklad:item_detail:{item['id']}"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
    bot.send_message(uid,"📋 *Barcha mahsulotlar:*\nMahsulot nomiga bosing → batafsil ko'ring",
        parse_mode='Markdown',reply_markup=m)

elif action.startswith("item_detail:"):
    item_id=int(action.split(":")[1])
    _show_item_detail(uid,item_id)

elif action=="yetkazuvchilar":
    db=get_db(); contacts=db.execute("SELECT * FROM yetkazuvchilar ORDER BY full_name").fetchall(); db.close()
    if not contacts: text="📞 *Yetkazuvchi kontaktlari*\n\nHali kontakt qo'shilmagan."
    else:
        text="📞 *Yetkazuvchi kontaktlari:*\n\n"
        for c in contacts:
            text+=f"👤 *{c['full_name']}*"
            if c['company']: text+=f" — _{c['company']}_"
            text+=f"\n📱 {c['phone']}"
            if c['extra_phone']: text+=f" | {c['extra_phone']}"
            if c['note']: text+=f"\n📝 {c['note']}"
            text+="\n\n"
    m=types.InlineKeyboardMarkup(row_width=1)
    if is_sklad_allowed(uid):
        m.add(types.InlineKeyboardButton("➕ Kontakt qo'shish",callback_data="sklad:add_contact"))
        m.add(types.InlineKeyboardButton("🗑 Kontakt o'chirish",callback_data="sklad:del_contact"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
    bot.send_message(uid,text,parse_mode='Markdown',reply_markup=m)

elif action=="add_contact":
    if not is_sklad_allowed(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
    set_state(uid,'sklad_contact_name')
    bot.send_message(uid,"📞 *Yetkazuvchi to'liq ismi:*",parse_mode='Markdown',reply_markup=cancel_kb())

elif action=="del_contact":
    db=get_db(); contacts=db.execute("SELECT id,full_name FROM yetkazuvchilar ORDER BY full_name").fetchall(); db.close()
    if not contacts: bot.send_message(uid,"📭 Kontakt yo'q."); return
    m=types.InlineKeyboardMarkup(row_width=1)
    for c in contacts:
        m.add(types.InlineKeyboardButton(f"🗑 {c['full_name']}",callback_data=f"sklad:delcontact:{c['id']}"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:yetkazuvchilar"))
    bot.send_message(uid,"🗑 Qaysi kontaktni o'chirish?",reply_markup=m)

elif action.startswith("delcontact:"):
    cid=int(action.split(":")[1]); db=get_db()
    db.execute("DELETE FROM yetkazuvchilar WHERE id=?",(cid,)); db.commit(); db.close()
    bot.send_message(uid,"✅ Kontakt o'chirildi.",reply_markup=get_menu(uid))

elif action=="admin_panel":
    if not is_admin(uid): bot.send_message(uid,"🔒 Faqat admin uchun."); return
    db=get_db(); perms=db.execute("SELECT user_id,full_name FROM sklad_permissions").fetchall(); db.close()
    text="⚙️ *Sklad boshqaruvi*\n\n"
    if perms:
        text+="👷 *Sklad ruxsati berilganlar:*\n"
        for p in perms: text+=f"  • {p['full_name']}\n"
    else: text+="👷 Hali hech kimga ruxsat berilmagan.\n"
    m=types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("➕ Foydalanuvchiga ruxsat berish",callback_data="sklad:grant_manual"))
    m.add(types.InlineKeyboardButton("🗑 Ruxsatni olib tashlash",callback_data="sklad:revoke_perm"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
    bot.send_message(uid,text,parse_mode='Markdown',reply_markup=m)

elif action=="grant_manual":
    if not is_admin(uid): return
    db=get_db()
    workers=db.execute("SELECT user_id,full_name FROM users WHERE role='worker'").fetchall()
    perms=[p['user_id'] for p in db.execute("SELECT user_id FROM sklad_permissions").fetchall()]
    db.close()
    candidates=[w for w in workers if w['user_id'] not in perms]
    if not candidates: bot.send_message(uid,"📭 Ruxsat berilmagan xodim yo'q yoki hammaga berilgan."); return
    m=types.InlineKeyboardMarkup(row_width=1)
    for w in candidates:
        m.add(types.InlineKeyboardButton(f"✅ {w['full_name']}",callback_data=f"sklad_grant:{w['user_id']}"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:admin_panel"))
    bot.send_message(uid,"👤 Kimga ruxsat berish?",reply_markup=m)

elif action=="revoke_perm":
    if not is_admin(uid): return
    db=get_db(); perms=db.execute("SELECT user_id,full_name FROM sklad_permissions").fetchall(); db.close()
    if not perms: bot.send_message(uid,"📭 Ruxsat berilgan foydalanuvchi yo'q."); return
    m=types.InlineKeyboardMarkup(row_width=1)
    for p in perms:
        m.add(types.InlineKeyboardButton(f"🗑 {p['full_name']}",callback_data=f"sklad:revoke_ok:{p['user_id']}"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:admin_panel"))
    bot.send_message(uid,"🗑 Kimning ruxsatini olib tashlash?",reply_markup=m)

elif action.startswith("revoke_ok:"):
    rid=int(action.split(":")[1]); db=get_db()
    db.execute("DELETE FROM sklad_permissions WHERE user_id=?",(rid,)); db.commit(); db.close()
    bot.send_message(uid,"✅ Ruxsat olib tashlandi.",reply_markup=get_menu(uid))

elif action.startswith("edit_item:"):
    item_id=int(action.split(":")[1])
    if not is_sklad_allowed(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
    m=types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("📝 Nom",callback_data=f"sklad:edititem_name:{item_id}"),
        types.InlineKeyboardButton("📏 Birlik",callback_data=f"sklad:edititem_unit:{item_id}"),
        types.InlineKeyboardButton("🔔 Chegara",callback_data=f"sklad:edititem_alert:{item_id}"),
        types.InlineKeyboardButton("📷 Rasm",callback_data=f"sklad:edititem_photo:{item_id}")
    )
    m.add(types.InlineKeyboardButton("🗑 O'chirish",callback_data=f"sklad:del_item:{item_id}"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data=f"sklad:chiqim_detail:{item_id}"))
    bot.send_message(uid,"✏️ Neni tahrirlaysiz?",reply_markup=m)

elif action.startswith("edititem_name:"):
    set_state(uid,'sklad_edit_name',{'item_id':int(action.split(":")[1])})
    bot.send_message(uid,"📝 Yangi nom:",reply_markup=cancel_kb())
elif action.startswith("edititem_unit:"):
    set_state(uid,'sklad_edit_unit',{'item_id':int(action.split(":")[1])})
    bot.send_message(uid,"📏 Yangi birlik (dona/kg/litr...):",reply_markup=cancel_kb())
elif action.startswith("edititem_alert:"):
    set_state(uid,'sklad_edit_alert',{'item_id':int(action.split(":")[1])})
    bot.send_message(uid,"🔔 Ogohlantirish chegarasini kiriting:\n_Misol: 10 (10 ta/kg qolganda ogohlantiradi)_",
        parse_mode='Markdown',reply_markup=cancel_kb())
elif action.startswith("edititem_photo:"):
    set_state(uid,'sklad_edit_photo',{'item_id':int(action.split(":")[1])})
    bot.send_message(uid,"📷 Yangi rasm yuboring:",reply_markup=cancel_kb())

elif action.startswith("del_item:"):
    item_id=int(action.split(":")[1])
    m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("✅ Ha",callback_data=f"sklad:del_item_ok:{item_id}"),
          types.InlineKeyboardButton("❌ Yo'q",callback_data=f"sklad:item_detail:{item_id}"))
    bot.send_message(uid,"⚠️ Mahsulotni o'chirishni tasdiqlaysizmi?",reply_markup=m)

elif action.startswith("del_item_ok:"):
    item_id=int(action.split(":")[1]); db=get_db()
    db.execute("DELETE FROM sklad_kirim WHERE item_id=?",(item_id,))
    db.execute("DELETE FROM sklad_chiqim WHERE item_id=?",(item_id,))
    db.execute("DELETE FROM sklad_items WHERE id=?",(item_id,))
    db.commit(); db.close()
    bot.send_message(uid,"🗑 Mahsulot o'chirildi.",reply_markup=get_menu(uid))
```

def _show_item_detail(uid, item_id):
db=get_db()
item=db.execute(“SELECT * FROM sklad_items WHERE id=?”,(item_id,)).fetchone()
kirims=db.execute(“SELECT * FROM sklad_kirim WHERE item_id=? ORDER BY added_at DESC LIMIT 5”,(item_id,)).fetchall()
chiqims=db.execute(“SELECT * FROM sklad_chiqim WHERE item_id=? ORDER BY added_at DESC LIMIT 5”,(item_id,)).fetchall()
db.close()
if not item: bot.send_message(uid,“❌ Topilmadi.”); return
text=(f”📦 *{item[‘name’]}*\n”
f”📊 Zaxira: *{item[‘quantity’]} {item[‘unit’]}*\n”
f”🔔 Chegara: *{item[‘min_alert’]} {item[‘unit’]}*\n\n”)
if kirims:
text+=“📥 *So’nggi kirimlar:*\n”
for k in kirims: text+=f”  +{k[‘quantity’]} {item[‘unit’]} — {str(k[‘added_at’])[:16].replace(‘T’,’ ‘)}\n”
text+=”\n”
if chiqims:
text+=“📤 *So’nggi chiqimlar:*\n”
for c in chiqims: text+=f”  -{c[‘quantity’]} {item[‘unit’]} — {str(c[‘added_at’])[:16].replace(‘T’,’ ’)}\n”
m=types.InlineKeyboardMarkup(row_width=2)
if is_sklad_allowed(uid):
m.add(types.InlineKeyboardButton(“📥 Kirim”,callback_data=f”sklad:kirim_item:{item_id}”),
types.InlineKeyboardButton(“📤 Chiqim”,callback_data=f”sklad:chiqim_item:{item_id}”))
m.add(types.InlineKeyboardButton(“✏️ Tahrirlash”,callback_data=f”sklad:edit_item:{item_id}”))
m.add(types.InlineKeyboardButton(“🔙 Orqaga”,callback_data=“sklad:all_items”))
if item[‘photo_file_id’]:
bot.send_photo(uid,item[‘photo_file_id’],caption=text,parse_mode=‘Markdown’,reply_markup=m)
else:
bot.send_message(uid,text,parse_mode=‘Markdown’,reply_markup=m)

# ═══════════════════════════════════════════════════════════════════════════════

# MATN HANDLERLARI

# ═══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(content_types=[‘text’,‘photo’])
def handle_all(msg):
uid=msg.from_user.id
if not is_allowed(uid): bot.send_message(uid,“🔒 Kirish taqiqlangan.”); return
st=get_state(uid); state=st[‘state’]; data=st[‘data’]

```
if state=='prod_name':
    name=(msg.text or '').strip()
    if len(name)<2: bot.send_message(uid,"⚠️ Nom juda qisqa."); return
    data['name']=name; set_state(uid,'prod_supplier',data)
    bot.send_message(uid,f"✅ *{name}*\n\n🏪 *Yetkazuvchi:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='prod_supplier':
    data['supplier']=(msg.text or '').strip(); set_state(uid,'prod_price',data)
    bot.send_message(uid,"💰 *Jami narx (so'mda):*",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='prod_price':
    try:
        price=float((msg.text or '').replace(',','').replace(' ',''))
        if price<=0: raise ValueError
    except: bot.send_message(uid,"⚠️ To'g'ri raqam kiriting.",reply_markup=cancel_kb()); return
    data['price']=price; set_state(uid,'prod_due',data)
    bot.send_message(uid,"📅 *Muddat:*\n_Format: 25.12.2024_\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='prod_due':
    try: data['due_date']=datetime.strptime((msg.text or '').strip(),'%d.%m.%Y').isoformat()
    except: data['due_date']=None
    set_state(uid,'prod_naqd_acc',data)
    bot.send_message(uid,"💵 *Naqd karta:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='prod_naqd_acc':
    data['naqd_account']=(msg.text or '').strip() or None; set_state(uid,'prod_online_bank',data)
    bot.send_message(uid,"🏦 *Online bank:*\n_(Payme, Click, Uzum...)_\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='prod_online_bank':
    data['online_bank']=(msg.text or '').strip() or None; set_state(uid,'prod_online_acc',data)
    bot.send_message(uid,"💳 *Online hisob:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='prod_online_acc':
    data['online_account']=(msg.text or '').strip() or None; set_state(uid,'prod_photo',data)
    bot.send_message(uid,"📷 *Tovar rasmi:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='prod_photo':
    if msg.photo: data['photo']=msg.photo[-1].file_id
    set_state(uid,'prod_note',data)
    bot.send_message(uid,"📝 *Izoh:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='prod_note':
    data['note']=(msg.text or '').strip(); _save_product(uid,data)

elif state=='pay_amount':
    try:
        amount=float((msg.text or '').replace(',','').replace(' ',''))
        if amount<=0: raise ValueError
    except: bot.send_message(uid,"⚠️ To'g'ri summa kiriting.",reply_markup=cancel_kb()); return
    db=get_db(); prod=db.execute("SELECT * FROM products WHERE id=?",(data['product_id'],)).fetchone(); db.close()
    if not prod: bot.send_message(uid,"❌ Tovar topilmadi.",reply_markup=admin_menu()); clear_state(uid); return
    remaining=prod['total_price']-prod['paid_amount']
    if amount>remaining: amount=remaining
    data.update({'amount':amount,'naqd_account':prod['naqd_account'],'online_account':prod['online_account'],'online_bank':prod['online_bank']})
    set_state(uid,'pay_type',data)
    m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("💵 Naqd",callback_data="ptype:cash"),
          types.InlineKeyboardButton("💳 Online",callback_data="ptype:click"))
    acc=""
    if prod['naqd_account']: acc+=f"\n💵 Naqd: `{prod['naqd_account']}`"
    if prod['online_account']: acc+=f"\n💳 {prod['online_bank'] or 'Online'}: `{prod['online_account']}`"
    bot.send_message(uid,f"💸 Summa: *{amount:,.0f} so'm*{acc}\n\n*To'lov turi:*",parse_mode='Markdown',reply_markup=m)
elif state=='pay_receipt':
    if msg.photo: data['receipt']=msg.photo[-1].file_id
    _save_payment(uid,data)

elif state=='add_worker_id':
    try: wid=int((msg.text or '').strip())
    except: bot.send_message(uid,"⚠️ ID raqam bo'lishi kerak.",reply_markup=cancel_kb()); return
    set_state(uid,'add_worker_name',{'worker_id':wid})
    bot.send_message(uid,"👤 *Xodim ismi:*",parse_mode='Markdown',reply_markup=cancel_kb())
elif state=='add_worker_name':
    wname=(msg.text or '').strip(); wid=data['worker_id']
    db=get_db()
    if db.execute("SELECT user_id FROM users WHERE user_id=?",(wid,)).fetchone():
        bot.send_message(uid,"⚠️ Bu foydalanuvchi allaqachon mavjud.",reply_markup=admin_menu())
    else:
        db.execute("INSERT INTO users(user_id,full_name,username,role,added_at,added_by) VALUES(?,?,'','worker',?,?)",
                   (wid,wname,datetime.now().isoformat(),uid)); db.commit()
        try: bot.send_message(wid,f"✅ Siz *Kafe Nasiya Daftari*ga xodim sifatida qo'shildingiz!",parse_mode='Markdown',reply_markup=worker_menu())
        except: pass
        bot.send_message(uid,f"✅ *{wname}* xodim qo'shildi!",parse_mode='Markdown',reply_markup=admin_menu())
    db.close(); clear_state(uid)

elif state=='sklad_item_name':
    name=(msg.text or '').strip()
    if len(name)<2: bot.send_message(uid,"⚠️ Nom juda qisqa.",reply_markup=cancel_kb()); return
    data['name']=name; set_state(uid,'sklad_item_unit_select',data)
    m=types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🔢 Donali (soni)",callback_data="sklad:add_item_dona"),
          types.InlineKeyboardButton("⚖️ Kilogrammli (kg)",callback_data="sklad:add_item_kg"))
    m.add(types.InlineKeyboardButton("📏 Boshqa birlik",callback_data="sklad:add_item_custom:litr"))
    bot.send_message(uid,f"✅ Mahsulot: *{name}*\n\n📏 *O'lchov turini tanlang:*",parse_mode='Markdown',reply_markup=m)

elif state=='sklad_item_photo':
    if msg.photo: data['photo']=msg.photo[-1].file_id
    _save_sklad_item(uid,data)

elif state=='sklad_kirim_qty':
    try:
        qty=float((msg.text or '').replace(',','').replace(' ',''))
        if qty<=0: raise ValueError
    except: bot.send_message(uid,"⚠️ To'g'ri miqdor kiriting.",reply_markup=cancel_kb()); return
    data['qty']=qty; set_state(uid,'sklad_kirim_note',data)
    bot.send_message(uid,f"📥 Kirim: *{qty} {data['unit']}*\n\n📝 *Izoh:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='sklad_kirim_note':
    data['note']=(msg.text or '').strip(); _save_sklad_kirim(uid,data)

elif state=='sklad_chiqim_qty':
    try:
        qty=float((msg.text or '').replace(',','').replace(' ',''))
        if qty<=0: raise ValueError
    except: bot.send_message(uid,"⚠️ To'g'ri miqdor kiriting.",reply_markup=cancel_kb()); return
    if qty>data.get('current_qty',0):
        bot.send_message(uid,f"⚠️ Zaxirada faqat *{data['current_qty']} {data['unit']}* bor!",parse_mode='Markdown',reply_markup=cancel_kb()); return
    data['qty']=qty; set_state(uid,'sklad_chiqim_note',data)
    bot.send_message(uid,f"📤 Chiqim: *{qty} {data['unit']}*\n\n📝 *Izoh:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='sklad_chiqim_note':
    data['note']=(msg.text or '').strip(); _save_sklad_chiqim(uid,data)

elif state=='sklad_contact_name':
    name=(msg.text or '').strip()
    if len(name)<2: bot.send_message(uid,"⚠️ Ism juda qisqa.",reply_markup=cancel_kb()); return
    data['full_name']=name; set_state(uid,'sklad_contact_phone',data)
    bot.send_message(uid,f"✅ *{name}*\n\n📱 *Telefon:*\n_Misol: +998901234567_",parse_mode='Markdown',reply_markup=cancel_kb())
elif state=='sklad_contact_phone':
    data['phone']=(msg.text or '').strip(); set_state(uid,'sklad_contact_phone2',data)
    bot.send_message(uid,"📱 *Qo'shimcha telefon:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='sklad_contact_phone2':
    data['extra_phone']=(msg.text or '').strip() or None; set_state(uid,'sklad_contact_company',data)
    bot.send_message(uid,"🏢 *Kompaniya:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='sklad_contact_company':
    data['company']=(msg.text or '').strip() or None; set_state(uid,'sklad_contact_note',data)
    bot.send_message(uid,"📝 *Izoh:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='sklad_contact_note':
    data['note']=(msg.text or '').strip() or None; _save_contact(uid,data)

elif state=='sklad_edit_name':
    new=(msg.text or '').strip()
    if len(new)<2: bot.send_message(uid,"⚠️ Juda qisqa.",reply_markup=cancel_kb()); return
    db=get_db(); db.execute("UPDATE sklad_items SET name=?,updated_at=? WHERE id=?",(new,datetime.now().isoformat(),data['item_id'])); db.commit(); db.close()
    clear_state(uid); bot.send_message(uid,f"✅ Nom yangilandi: *{new}*",parse_mode='Markdown',reply_markup=get_menu(uid))
elif state=='sklad_edit_unit':
    new=(msg.text or '').strip()
    db=get_db(); db.execute("UPDATE sklad_items SET unit=?,updated_at=? WHERE id=?",(new,datetime.now().isoformat(),data['item_id'])); db.commit(); db.close()
    clear_state(uid); bot.send_message(uid,f"✅ Birlik yangilandi: *{new}*",parse_mode='Markdown',reply_markup=get_menu(uid))
elif state=='sklad_edit_alert':
    try: alert=float((msg.text or '').replace(',','').replace(' ',''))
    except: bot.send_message(uid,"⚠️ Raqam kiriting.",reply_markup=cancel_kb()); return
    db=get_db(); db.execute("UPDATE sklad_items SET min_alert=?,updated_at=? WHERE id=?",(alert,datetime.now().isoformat(),data['item_id'])); db.commit(); db.close()
    clear_state(uid); bot.send_message(uid,f"✅ Ogohlantirish chegarasi: *{alert}*",parse_mode='Markdown',reply_markup=get_menu(uid))
elif state=='sklad_edit_photo':
    if msg.photo:
        db=get_db(); db.execute("UPDATE sklad_items SET photo_file_id=?,updated_at=? WHERE id=?",(msg.photo[-1].file_id,datetime.now().isoformat(),data['item_id'])); db.commit(); db.close()
        clear_state(uid); bot.send_message(uid,"✅ Rasm yangilandi!",reply_markup=get_menu(uid))
    else: bot.send_message(uid,"⚠️ Rasm yuboring.",reply_markup=cancel_kb())

elif state=='edit_name':
    v=(msg.text or '').strip()
    if len(v)<2: bot.send_message(uid,"⚠️ Nom juda qisqa.",reply_markup=cancel_kb()); return
    _finish_edit(uid,data,'name',v)
elif state=='edit_supplier': _finish_edit(uid,data,'supplier_name',(msg.text or '').strip() or None)
elif state=='edit_price':
    try:
        p=float((msg.text or '').replace(',','').replace(' ',''))
        if p<=0: raise ValueError
    except: bot.send_message(uid,"⚠️ To'g'ri raqam kiriting.",reply_markup=cancel_kb()); return
    _finish_edit(uid,data,'total_price',p)
elif state=='edit_due':
    try: v=datetime.strptime((msg.text or '').strip(),'%d.%m.%Y').isoformat()
    except: v=None
    _finish_edit(uid,data,'due_date',v)
elif state=='edit_naqd_acc': _finish_edit(uid,data,'naqd_account',(msg.text or '').strip() or None)
elif state=='edit_online_bank':
    v=(msg.text or '').strip() or None
    db=get_db(); db.execute("UPDATE products SET online_bank=?,updated_at=? WHERE id=?",(v,datetime.now().isoformat(),data['product_id'])); db.commit(); db.close()
    set_state(uid,'edit_online_acc',data)
    bot.send_message(uid,"💳 *Online hisob raqami:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
elif state=='edit_online_acc': _finish_edit(uid,data,'online_account',(msg.text or '').strip() or None)
elif state=='edit_photo':
    if msg.photo: data['new_photo']=msg.photo[-1].file_id
    _ask_edit_note(uid,data)
elif state=='edit_note': _finish_edit(uid,data,'note',(msg.text or '').strip() or '')
```

# ═══════════════════════════════════════════════════════════════════════════════

# SKLAD SAQLASH

# ═══════════════════════════════════════════════════════════════════════════════

def _save_sklad_item(uid,data):
now=datetime.now().isoformat(); db=get_db()
db.execute(“INSERT INTO sklad_items(name,quantity,unit,unit_type,min_alert,photo_file_id,created_at,updated_at,created_by) VALUES(?,0,?,?,10,?,?,?,?)”,
(data.get(‘name’),data.get(‘unit’,‘dona’),data.get(‘unit_type’,‘dona’),data.get(‘photo’),now,now,uid))
db.commit(); db.close(); clear_state(uid)
bot.send_message(uid,f”✅ *{data.get(‘name’)}* sklad mahsuloti qo’shildi!\n📏 Birlik: *{data.get(‘unit’,‘dona’)}*\n📊 Boshlang’ich zaxira: *0*”,
parse_mode=‘Markdown’,reply_markup=get_menu(uid))

def _save_sklad_kirim(uid,data):
item_id=data[‘item_id’]; qty=data[‘qty’]; note=data.get(‘note’,’’); now=datetime.now().isoformat()
db=get_db()
db.execute(“UPDATE sklad_items SET quantity=quantity+?,updated_at=? WHERE id=?”,(qty,now,item_id))
db.execute(“INSERT INTO sklad_kirim(item_id,quantity,note,added_at,added_by) VALUES(?,?,?,?,?)”,(item_id,qty,note,now,uid))
db.commit(); item=db.execute(“SELECT * FROM sklad_items WHERE id=?”,(item_id,)).fetchone(); db.close()
clear_state(uid)
bot.send_message(uid,f”✅ *Kirim qilindi!*\n📦 *{item[‘name’]}*\n📥 +{qty} {item[‘unit’]}\n📊 Yangi zaxira: *{item[‘quantity’]} {item[‘unit’]}*”,
parse_mode=‘Markdown’,reply_markup=get_menu(uid))
notify_admin(f”📥 *Sklad kirim*\n\n📦 *{item[‘name’]}*\n+{qty} {item[‘unit’]}\n📊 Zaxira: *{item[‘quantity’]} {item[‘unit’]}*”)
check_sklad_alert(item_id)

def _save_sklad_chiqim(uid,data):
item_id=data[‘item_id’]; qty=data[‘qty’]; note=data.get(‘note’,’’); now=datetime.now().isoformat()
db=get_db()
db.execute(“UPDATE sklad_items SET quantity=quantity-?,updated_at=? WHERE id=?”,(qty,now,item_id))
db.execute(“INSERT INTO sklad_chiqim(item_id,quantity,note,added_at,added_by) VALUES(?,?,?,?,?)”,(item_id,qty,note,now,uid))
db.commit(); item=db.execute(“SELECT * FROM sklad_items WHERE id=?”,(item_id,)).fetchone(); db.close()
clear_state(uid)
bot.send_message(uid,f”✅ *Chiqim qilindi!*\n📦 *{item[‘name’]}*\n📤 -{qty} {item[‘unit’]}\n📊 Qolgan: *{item[‘quantity’]} {item[‘unit’]}*”,
parse_mode=‘Markdown’,reply_markup=get_menu(uid))
notify_admin(f”📤 *Sklad chiqim*\n\n📦 *{item[‘name’]}*\n-{qty} {item[‘unit’]}\n📊 Qolgan: *{item[‘quantity’]} {item[‘unit’]}*”)
check_sklad_alert(item_id)

def _save_contact(uid,data):
now=datetime.now().isoformat(); db=get_db()
db.execute(“INSERT INTO yetkazuvchilar(full_name,phone,extra_phone,company,note,created_at,created_by) VALUES(?,?,?,?,?,?,?)”,
(data.get(‘full_name’),data.get(‘phone’),data.get(‘extra_phone’),data.get(‘company’),data.get(‘note’),now,uid))
db.commit(); db.close(); clear_state(uid)
bot.send_message(uid,f”✅ *Kontakt qo’shildi!*\n👤 *{data.get(‘full_name’)}*\n📱 {data.get(‘phone’)}”,
parse_mode=‘Markdown’,reply_markup=get_menu(uid))

# ═══════════════════════════════════════════════════════════════════════════════

# TOVAR SAQLASH / TAHRIRLASH

# ═══════════════════════════════════════════════════════════════════════════════

def _save_product(uid,data):
now=datetime.now().isoformat(); db=get_db()
db.execute(“INSERT INTO products(name,supplier_name,total_price,paid_amount,due_date,naqd_account,online_account,online_bank,photo_file_id,note,created_at,updated_at,created_by) VALUES(?,?,?,0,?,?,?,?,?,?,?,?,?)”,
(data.get(‘name’),data.get(‘supplier’),data.get(‘price’),data.get(‘due_date’),
data.get(‘naqd_account’),data.get(‘online_account’),data.get(‘online_bank’),data.get(‘photo’),data.get(‘note’),now,now,uid))
pid=db.execute(“SELECT last_insert_rowid()”).fetchone()[0]
if data.get(‘due_date’):
due=datetime.fromisoformat(data[‘due_date’])
db.execute(“INSERT INTO reminders(product_id,remind_at) VALUES(?,?)”,(pid,(due-timedelta(days=1)).isoformat()))
db.commit(); db.close(); clear_state(uid)
bot.send_message(uid,f”✅ *Tovar qo’shildi!*\n📦 *{data.get(‘name’)}*\n💰 *{data.get(‘price’,0):,.0f} so’m*”,
parse_mode=‘Markdown’,reply_markup=admin_menu())

def _save_payment(uid,data):
pid=data[‘product_id’]; amount=data[‘amount’]; ptype=data.get(‘ptype’,‘cash’); receipt=data.get(‘receipt’); now=datetime.now().isoformat()
db=get_db()
db.execute(“UPDATE products SET paid_amount=paid_amount+?,updated_at=? WHERE id=?”,(amount,now,pid))
db.execute(“INSERT INTO payments(product_id,amount,payment_type,receipt_file_id,paid_at,added_by) VALUES(?,?,?,?,?,?)”,(pid,amount,ptype,receipt,now,uid))
db.commit()
prod=db.execute(“SELECT * FROM products WHERE id=?”,(pid,)).fetchone()
payments=db.execute(“SELECT * FROM payments WHERE product_id=? ORDER BY paid_at”,(pid,)).fetchall()
db.close(); remaining=prod[‘total_price’]-prod[‘paid_amount’]; clear_state(uid)
bot.send_message(uid,“🧾 *Chek tayyorlanmoqda…*”,parse_mode=‘Markdown’)
try:
img=generate_receipt(dict(prod),[dict(p) for p in payments],remaining)
bot.send_photo(uid,img,caption=f”🧾 *{prod[‘name’]}*\n💸 To’langan: *{amount:,.0f} so’m*\n⏳ Qolgan: *{remaining:,.0f} so’m*”,
parse_mode=‘Markdown’,reply_markup=admin_menu())
except Exception as e:
logging.error(f”Receipt: {e}”)
bot.send_message(uid,f”✅ *To’lov kiritildi!*\n💸 {amount:,.0f} so’m\n⏳ Qolgan: {remaining:,.0f} so’m”,
parse_mode=‘Markdown’,reply_markup=admin_menu())

def *ask_edit_note(uid,data):
if data.get(‘new_photo’):
db=get_db(); db.execute(“UPDATE products SET photo_file_id=?,updated_at=? WHERE id=?”,(data[‘new_photo’],datetime.now().isoformat(),data[‘product_id’])); db.commit(); db.close()
set_state(uid,‘edit_note’,data)
bot.send_message(uid,“📝 *Yangi izoh:*\n*(O’tkazish mumkin)_”,parse_mode=‘Markdown’,reply_markup=skip_kb())

def _finish_edit(uid,data,field,value):
if field==‘note’ and value is None: value=’’
db=get_db(); db.execute(f”UPDATE products SET {field}=?,updated_at=? WHERE id=?”,(value,datetime.now().isoformat(),data[‘product_id’])); db.commit()
prod=db.execute(“SELECT * FROM products WHERE id=?”,(data[‘product_id’],)).fetchone(); db.close(); clear_state(uid)
names={‘name’:‘Nom’,‘supplier_name’:‘Yetkazuvchi’,‘total_price’:‘Narx’,‘due_date’:‘Muddat’,
‘naqd_account’:‘Naqd hisob’,‘online_bank’:‘Online bank’,‘online_account’:‘Online hisob’,‘note’:‘Izoh’}
bot.send_message(uid,f”✅ *{names.get(field,field)}* yangilandi!\n📦 *{prod[‘name’]}*”,parse_mode=‘Markdown’,reply_markup=admin_menu())

# ═══════════════════════════════════════════════════════════════════════════════

# TOVAR CALLBACK

# ═══════════════════════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data.startswith(“view:”))
def cb_view(call):
uid=call.from_user.id; pid=int(call.data.split(”:”)[1])
db=get_db(); prod=db.execute(“SELECT * FROM products WHERE id=?”,(pid,)).fetchone()
payments=db.execute(“SELECT * FROM payments WHERE product_id=? ORDER BY paid_at DESC”,(pid,)).fetchall(); db.close()
if not prod: bot.answer_callback_query(call.id,“Topilmadi!”); return
rem=prod[‘total_price’]-prod[‘paid_amount’]; pct=min((prod[‘paid_amount’]/prod[‘total_price’]*100) if prod[‘total_price’]>0 else 0,100)
bar=“█”*int(pct/5)+“░”*(20-int(pct/5))
ph=””
for p in payments[:5]:
ph+=f”  {‘💳’ if p[‘payment_type’]==‘click’ else ‘💵’} {str(p[‘paid_at’])[:16].replace(‘T’,’ ‘)} — *{p[‘amount’]:,.0f}* so’m\n”
acc=””
if prod[‘naqd_account’]: acc+=f”\n💵 Naqd: `{prod['naqd_account']}`”
if prod[‘online_account’]: acc+=f”\n💳 {prod[‘online_bank’] or ‘Online’}: `{prod['online_account']}`”
text=(f”📦 *{prod[‘name’]}*\n{‘🏪 ‘+prod[‘supplier_name’] if prod[‘supplier_name’] else ‘’}\n\n”
f”💰 Jami: *{prod[‘total_price’]:,.0f} so’m*\n✅ To’langan: *{prod[‘paid_amount’]:,.0f} so’m*\n”
f”🔴 Qolgan: *{rem:,.0f} so’m*\n\n`{bar}` {pct:.0f}%”)
if acc: text+=f”\n\n🏦 *Hisob:*{acc}”
if ph: text+=f”\n\n📋 *So’nggi to’lovlar:*\n{ph}”
m=types.InlineKeyboardMarkup(row_width=2)
if is_admin(uid):
m.add(types.InlineKeyboardButton(“💸 To’lov”,callback_data=f”pay:{pid}”),
types.InlineKeyboardButton(“🧾 Chek”,callback_data=f”receipt:{pid}”))
m.add(types.InlineKeyboardButton(“✏️ Tahrirlash”,callback_data=f”edit:{pid}”),
types.InlineKeyboardButton(“🗑 O’chirish”,callback_data=f”del:{pid}”))
m.add(types.InlineKeyboardButton(“📋 Barcha to’lovlar”,callback_data=f”history:{pid}”))
else:
m.add(types.InlineKeyboardButton(“🧾 Chek”,callback_data=f”receipt:{pid}”),
types.InlineKeyboardButton(“📋 Barcha to’lovlar”,callback_data=f”history:{pid}”))
bot.answer_callback_query(call.id)
if prod[‘photo_file_id’]: bot.send_photo(uid,prod[‘photo_file_id’],caption=text,parse_mode=‘Markdown’,reply_markup=m)
else: bot.send_message(uid,text,parse_mode=‘Markdown’,reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“edit:”))
def cb_edit(call):
uid=call.from_user.id
if not is_admin(uid): bot.answer_callback_query(call.id,“❌ Ruxsat yo’q!”); return
pid=int(call.data.split(”:”)[1]); bot.answer_callback_query(call.id)
m=types.InlineKeyboardMarkup(row_width=2)
m.add(types.InlineKeyboardButton(“📦 Nom”,callback_data=f”editf:name:{pid}”),
types.InlineKeyboardButton(“🏪 Yetkazuvchi”,callback_data=f”editf:supplier:{pid}”))
m.add(types.InlineKeyboardButton(“💰 Narx”,callback_data=f”editf:price:{pid}”),
types.InlineKeyboardButton(“📅 Muddat”,callback_data=f”editf:due:{pid}”))
m.add(types.InlineKeyboardButton(“💵 Naqd hisob”,callback_data=f”editf:naqd:{pid}”),
types.InlineKeyboardButton(“💳 Online”,callback_data=f”editf:online:{pid}”))
m.add(types.InlineKeyboardButton(“📷 Rasm”,callback_data=f”editf:photo:{pid}”),
types.InlineKeyboardButton(“📝 Izoh”,callback_data=f”editf:note:{pid}”))
bot.send_message(uid,“✏️ *Qaysi maydon?*”,parse_mode=‘Markdown’,reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“editf:”))
def cb_editf(call):
uid=call.from_user.id
if not is_admin(uid): bot.answer_callback_query(call.id,“❌ Ruxsat yo’q!”); return
parts=call.data.split(”:”); field=parts[1]; pid=int(parts[2]); bot.answer_callback_query(call.id)
data={‘product_id’:pid}
pm={‘name’:(‘edit_name’,“📦 *Yangi nom:*”,cancel_kb()),
‘supplier’:(‘edit_supplier’,“🏪 *Yangi yetkazuvchi:*\n_(O’tkazish mumkin)*”,skip_kb()),
‘price’:(‘edit_price’,“💰 *Yangi narx:*”,cancel_kb()),
‘due’:(‘edit_due’,“📅 *Yangi muddat:*\n_Format: 25.12.2024*\n_(O’tkazish mumkin)*”,skip_kb()),
‘naqd’:(‘edit_naqd_acc’,“💵 *Naqd karta:*\n*(O’tkazish mumkin)*”,skip_kb()),
‘online’:(‘edit_online_bank’,“🏦 *Online bank:*\n*(O’tkazish mumkin)*”,skip_kb()),
‘note’:(‘edit_note’,“📝 *Yangi izoh:*\n*(O’tkazish mumkin)*”,skip_kb()),
‘photo’:(‘edit_photo’,“📷 *Yangi rasm:*\n*(O’tkazish mumkin)_”,skip_kb())}
if field not in pm: return
s,p,kb=pm[field]; set_state(uid,s,data); bot.send_message(uid,p,parse_mode=‘Markdown’,reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“pay:”))
def cb_pay(call):
uid=call.from_user.id
if not is_admin(uid): bot.answer_callback_query(call.id,“❌ Ruxsat yo’q!”); return
pid=int(call.data.split(”:”)[1]); db=get_db()
prod=db.execute(“SELECT name,total_price,paid_amount FROM products WHERE id=?”,(pid,)).fetchone(); db.close()
rem=prod[‘total_price’]-prod[‘paid_amount’]
if rem<=0: bot.answer_callback_query(call.id,“✅ To’liq to’langan!”); return
set_state(uid,‘pay_amount’,{‘product_id’:pid}); bot.answer_callback_query(call.id)
bot.send_message(uid,f”💸 *{prod[‘name’]}*\n⏳ Qolgan: *{rem:,.0f} so’m*\n\nSumma kiriting:”,parse_mode=‘Markdown’,reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith(“ptype:”))
def cb_ptype(call):
uid=call.from_user.id; ptype=call.data.split(”:”)[1]; data=get_state(uid)[‘data’]; data[‘ptype’]=ptype; bot.answer_callback_query(call.id)
if ptype==‘click’:
set_state(uid,‘pay_receipt’,data)
acc=f”\n\n🏦 To’lov: `{data['online_account']}` ({data.get(‘online_bank’,‘Online’)})” if data.get(‘online_account’) else “”
bot.send_message(uid,f”📎 *Chek rasmini yuboring:*\n_(O’tkazish mumkin)_{acc}”,parse_mode=‘Markdown’,reply_markup=skip_kb())
else:
if data.get(‘naqd_account’): bot.send_message(uid,f”💵 Karta: `{data['naqd_account']}`”,parse_mode=‘Markdown’)
_save_payment(uid,data)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“receipt:”))
def cb_receipt(call):
uid=call.from_user.id; pid=int(call.data.split(”:”)[1])
db=get_db(); prod=db.execute(“SELECT * FROM products WHERE id=?”,(pid,)).fetchone()
payments=db.execute(“SELECT * FROM payments WHERE product_id=? ORDER BY paid_at”,(pid,)).fetchall(); db.close()
bot.answer_callback_query(call.id,“🧾 Chek tayyorlanmoqda…”)
try:
img=generate_receipt(dict(prod),[dict(p) for p in payments],prod[‘total_price’]-prod[‘paid_amount’])
bot.send_photo(uid,img,caption=f”🧾 *{prod[‘name’]}*\n⏳ Qolgan: *{prod[‘total_price’]-prod[‘paid_amount’]:,.0f} so’m*”,parse_mode=‘Markdown’)
except Exception as e: bot.send_message(uid,f”❌ Xatolik: {e}”)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“history:”))
def cb_history(call):
uid=call.from_user.id; pid=int(call.data.split(”:”)[1])
db=get_db(); prod=db.execute(“SELECT name FROM products WHERE id=?”,(pid,)).fetchone()
payments=db.execute(“SELECT * FROM payments WHERE product_id=? ORDER BY paid_at DESC”,(pid,)).fetchall(); db.close()
if not payments: bot.answer_callback_query(call.id,“Hali to’lov yo’q!”); return
text=f”📋 *{prod[‘name’]}* — Barcha to’lovlar:\n\n”; total=0
for i,p in enumerate(payments,1):
text+=f”{i}. {‘💳’ if p[‘payment_type’]==‘click’ else ‘💵’} *{p[‘amount’]:,.0f} so’m* — {str(p[‘paid_at’])[:16].replace(‘T’,’ ‘)}\n”
total+=p[‘amount’]
text+=f”\n✅ Jami: *{total:,.0f} so’m*”; bot.answer_callback_query(call.id)
bot.send_message(uid,text,parse_mode=‘Markdown’)
for p in payments:
if p[‘receipt_file_id’]:
try: bot.send_photo(uid,p[‘receipt_file_id’],caption=f”💳 {str(p[‘paid_at’])[:10]} | {p[‘amount’]:,.0f} so’m”)
except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith(“del:”))
def cb_del(call):
uid=call.from_user.id
if not is_admin(uid): bot.answer_callback_query(call.id,“❌ Ruxsat yo’q!”); return
pid=int(call.data.split(”:”)[1]); bot.answer_callback_query(call.id)
m=types.InlineKeyboardMarkup()
m.add(types.InlineKeyboardButton(“✅ Ha”,callback_data=f”delok:{pid}”),
types.InlineKeyboardButton(“❌ Yo’q”,callback_data=“delno”))
bot.send_message(uid,“⚠️ *Haqiqatan ham o’chirmoqchimisiz?*”,parse_mode=‘Markdown’,reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“delok:”))
def cb_delok(call):
pid=int(call.data.split(”:”)[1]); db=get_db()
db.execute(“DELETE FROM payments WHERE product_id=?”,(pid,))
db.execute(“DELETE FROM reminders WHERE product_id=?”,(pid,))
db.execute(“DELETE FROM products WHERE id=?”,(pid,)); db.commit(); db.close()
bot.answer_callback_query(call.id,“🗑 O’chirildi!”)
bot.send_message(call.from_user.id,“🗑 Tovar o’chirildi.”,reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda c: c.data==“delno”)
def cb_delno(call): bot.answer_callback_query(call.id,“❌ Bekor”)

@bot.callback_query_handler(func=lambda c: c.data==“add_worker”)
def cb_add_worker(call):
uid=call.from_user.id
if not is_admin(uid): bot.answer_callback_query(call.id,“❌ Ruxsat yo’q!”); return
set_state(uid,‘add_worker_id’); bot.answer_callback_query(call.id)
bot.send_message(uid,“👤 *Xodim qo’shish*\n\nXodim Telegram ID sini yuboring:\n_ID uchun @userinfobot ga /start yuboring_”,
parse_mode=‘Markdown’,reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data==“remove_worker”)
def cb_remove_worker(call):
uid=call.from_user.id
if not is_admin(uid): bot.answer_callback_query(call.id,“Ruxsat yo’q!”); return
db=get_db(); workers=db.execute(“SELECT user_id,full_name FROM users WHERE role=‘worker’”).fetchall(); db.close()
if not workers: bot.answer_callback_query(call.id,“Xodim yo’q!”); return
m=types.InlineKeyboardMarkup()
for w in workers: m.add(types.InlineKeyboardButton(f”🗑 {w[‘full_name’]}”,callback_data=f”delworker:{w[‘user_id’]}”))
bot.answer_callback_query(call.id); bot.send_message(uid,“👤 Qaysi xodimni o’chirish?”,reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith(“delworker:”))
def cb_delworker(call):
wid=int(call.data.split(”:”)[1]); db=get_db()
db.execute(“DELETE FROM users WHERE user_id=? AND role=‘worker’”,(wid,)); db.commit(); db.close()
bot.answer_callback_query(call.id,“✅ O’chirildi!”)
bot.send_message(call.from_user.id,“✅ Xodim o’chirildi.”,reply_markup=admin_menu())

# ═══════════════════════════════════════════════════════════════════════════════

# WEB

# ═══════════════════════════════════════════════════════════════════════════════

active_tokens={}

@app.route(’/’)
def web_index(): return render_template_string(WEB_HTML)

@app.route(’/api/login’,methods=[‘POST’])
def api_login():
d=request.get_json()
if d and d.get(‘password’)==WEB_SECRET:
tok=secrets.token_hex(24); active_tokens[tok]=datetime.now()
return jsonify({‘ok’:True,‘token’:tok})
return jsonify({‘ok’:False}),401

def chk(): return request.headers.get(‘X-Token’,’’) in active_tokens

@app.route(’/api/products’)
def api_products():
if not chk(): return jsonify({‘error’:‘Unauthorized’}),401
db=get_db(); rows=db.execute(“SELECT id,name,supplier_name,total_price,paid_amount,due_date,naqd_account,online_account,online_bank,note FROM products ORDER BY created_at DESC”).fetchall(); db.close()
return jsonify({‘products’:[dict(r) for r in rows]})

@app.route(’/api/product/<int:pid>’)
def api_product(pid):
if not chk(): return jsonify({‘error’:‘Unauthorized’}),401
db=get_db(); prod=db.execute(“SELECT * FROM products WHERE id=?”,(pid,)).fetchone()
pays=db.execute(“SELECT amount,payment_type,paid_at FROM payments WHERE product_id=? ORDER BY paid_at DESC”,(pid,)).fetchall(); db.close()
if not prod: return jsonify({‘error’:‘Not found’}),404
return jsonify({‘product’:dict(prod),‘payments’:[dict(p) for p in pays]})

@app.route(’/api/sklad’)
def api_sklad():
if not chk(): return jsonify({‘error’:‘Unauthorized’}),401
db=get_db(); items=db.execute(“SELECT id,name,quantity,unit,min_alert FROM sklad_items ORDER BY name”).fetchall(); db.close()
return jsonify({‘items’:[dict(i) for i in items]})

@app.route(’/api/contacts’)
def api_contacts():
if not chk(): return jsonify({‘error’:‘Unauthorized’}),401
db=get_db(); contacts=db.execute(“SELECT * FROM yetkazuvchilar ORDER BY full_name”).fetchall(); db.close()
return jsonify({‘contacts’:[dict(c) for c in contacts]})

WEB_HTML = ‘’’<!DOCTYPE html>

<html lang="uz">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>☕ Kafe Nasiya Daftari</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#080c12;--surface:#0f1520;--card:#141c28;--border:#1e2d42;--accent:#f0883e;--accent2:#58a6ff;--green:#3fb950;--red:#f85149;--text:#e6edf3;--muted:#7d8fa8;--radius:16px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif;min-height:100vh;background-image:radial-gradient(ellipse at 20% 10%,rgba(240,136,62,.08) 0%,transparent 50%),radial-gradient(ellipse at 80% 80%,rgba(88,166,255,.06) 0%,transparent 50%)}
.login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center}
.login-box{background:var(--card);border:1px solid var(--border);border-radius:24px;padding:48px 40px;width:380px;text-align:center}
.login-box .logo{font-size:48px;margin-bottom:16px}
.login-box h1{font-size:22px;font-weight:800;margin-bottom:6px}
.login-box p{color:var(--muted);font-size:14px;margin-bottom:32px}
.login-box input{width:100%;padding:14px 18px;background:var(--surface);border:1px solid var(--border);border-radius:12px;color:var(--text);font-family:'DM Mono',monospace;font-size:15px;margin-bottom:16px;outline:none;transition:border-color .2s}
.login-box input:focus{border-color:var(--accent)}
.btn{width:100%;padding:14px;background:linear-gradient(135deg,var(--accent),#e07020);border:none;border-radius:12px;color:#fff;font-family:'Syne',sans-serif;font-weight:700;font-size:15px;cursor:pointer;transition:opacity .2s}
.btn:hover{opacity:.9}
.login-err{color:var(--red);font-size:13px;margin-top:12px}
.dash{display:none}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:20px 32px;border-bottom:1px solid var(--border);background:rgba(15,21,32,.8);backdrop-filter:blur(12px);position:sticky;top:0;z-index:100}
.topbar .brand{font-size:18px;font-weight:800}
.topbar .brand span{color:var(--accent)}
.logout{background:transparent;border:1px solid var(--border);color:var(--muted);padding:8px 16px;border-radius:8px;font-family:'Syne',sans-serif;font-size:13px;cursor:pointer;transition:all .2s}
.logout:hover{border-color:var(--red);color:var(--red)}
.tabs{display:flex;gap:8px;padding:20px 32px 0;border-bottom:1px solid var(--border)}
.tab-btn{background:transparent;border:none;border-bottom:2px solid transparent;color:var(--muted);padding:10px 16px;font-family:'Syne',sans-serif;font-size:14px;font-weight:600;cursor:pointer;transition:all .2s}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-content{display:none}.tab-content.active{display:block}
.container{max-width:1200px;margin:0 auto;padding:32px 24px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:32px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px;position:relative;overflow:hidden;transition:transform .2s}
.stat-card:hover{transform:translateY(-3px)}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.stat-card.orange::before{background:var(--accent)}.stat-card.blue::before{background:var(--accent2)}.stat-card.green::before{background:var(--green)}.stat-card.red::before{background:var(--red)}
.stat-label{font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px}
.stat-val{font-size:28px;font-weight:800;line-height:1}
.stat-val.orange{color:var(--accent)}.stat-val.blue{color:var(--accent2)}.stat-val.green{color:var(--green)}.stat-val.red{color:var(--red)}
.progress-wrap{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px;margin-bottom:32px}
.progress-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.progress-title{font-size:16px;font-weight:700}
.progress-pct{font-family:'DM Mono',monospace;color:var(--accent);font-size:20px}
.progress-bar{height:12px;background:var(--surface);border-radius:99px;overflow:hidden}
.progress-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--green));transition:width 1s}
.filters{display:flex;gap:10px;margin-bottom:24px;flex-wrap:wrap;align-items:center}
.filter-btn{background:var(--card);border:1px solid var(--border);color:var(--muted);padding:8px 16px;border-radius:99px;font-family:'Syne',sans-serif;font-size:13px;cursor:pointer;transition:all .2s}
.filter-btn.active,.filter-btn:hover{border-color:var(--accent);color:var(--accent)}
.search-box{flex:1;min-width:200px;background:var(--card);border:1px solid var(--border);border-radius:99px;padding:8px 18px;color:var(--text);font-family:'Syne',sans-serif;font-size:14px;outline:none}
.search-box:focus{border-color:var(--accent2)}
.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
table{width:100%;border-collapse:collapse}
thead{background:var(--surface)}
th{padding:14px 18px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);text-align:left}
td{padding:16px 18px;font-size:14px;border-top:1px solid var(--border);vertical-align:middle}
tr:hover td{background:rgba(255,255,255,.02)}
.badge{display:inline-block;padding:4px 10px;border-radius:99px;font-size:11px;font-weight:700}
.badge.paid{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.3)}
.badge.unpaid{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.3)}
.badge.partial{background:rgba(240,136,62,.15);color:var(--accent);border:1px solid rgba(240,136,62,.3)}
.mini-bar{height:6px;background:var(--surface);border-radius:99px;min-width:80px;margin-top:6px}
.mini-fill{height:100%;border-radius:99px}
.no-data{text-align:center;padding:60px;color:var(--muted);font-size:15px}
.loader{text-align:center;padding:60px;color:var(--muted)}
.spin{display:inline-block;width:32px;height:32px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:768px){.topbar{padding:14px 16px}.container{padding:16px}.stats-grid{grid-template-columns:1fr 1fr}th,td{padding:10px}}
</style>
</head>
<body>
<div class="login-wrap" id="loginWrap">
  <div class="login-box">
    <div class="logo">☕</div>
    <h1>Kafe Nasiya Daftari</h1>
    <p>Web Dashboard</p>
    <input type="password" id="passInput" placeholder="Parol..." onkeydown="if(event.key==='Enter')login()">
    <button class="btn" onclick="login()">Kirish →</button>
    <div class="login-err" id="loginErr"></div>
  </div>
</div>
<div class="dash" id="dash">
  <div class="topbar"><div class="brand">☕ <span>Nasiya</span> Daftari</div><button class="logout" onclick="logout()">Chiqish</button></div>
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('nasiya',this)">💳 Nasiya</button>
    <button class="tab-btn" onclick="switchTab('sklad',this)">🏪 Sklad</button>
    <button class="tab-btn" onclick="switchTab('contacts',this)">📞 Kontaktlar</button>
  </div>
  <div class="tab-content active" id="tab-nasiya">
    <div class="container">
      <div class="stats-grid">
        <div class="stat-card orange"><div class="stat-label">Jami tovarlar</div><div class="stat-val orange" id="sCount">—</div></div>
        <div class="stat-card red"><div class="stat-label">Jami nasiya</div><div class="stat-val red" id="sTotal">—</div></div>
        <div class="stat-card green"><div class="stat-label">To'langan</div><div class="stat-val green" id="sPaid">—</div></div>
        <div class="stat-card blue"><div class="stat-label">Qolgan qarz</div><div class="stat-val blue" id="sRem">—</div></div>
      </div>
      <div class="progress-wrap">
        <div class="progress-header"><div class="progress-title">Umumiy to'lov holati</div><div class="progress-pct" id="pPct">0%</div></div>
        <div class="progress-bar"><div class="progress-fill" id="pFill" style="width:0%"></div></div>
      </div>
      <div class="filters">
        <button class="filter-btn active" onclick="setFilter('all',this)">Hammasi</button>
        <button class="filter-btn" onclick="setFilter('unpaid',this)">Qarzli</button>
        <button class="filter-btn" onclick="setFilter('paid',this)">To'langan</button>
        <input class="search-box" type="text" placeholder="🔍 Qidirish..." id="searchBox" oninput="renderTable()">
      </div>
      <div class="table-wrap">
        <div class="loader" id="loader"><div class="spin"></div></div>
        <table id="prodTable" style="display:none"><thead><tr><th>#</th><th>Tovar</th><th>Jami</th><th>To'langan</th><th>Qolgan</th><th>Holat</th><th>Muddat</th></tr></thead><tbody id="prodBody"></tbody></table>
        <div class="no-data" id="noData" style="display:none">📭 Topilmadi</div>
      </div>
    </div>
  </div>
  <div class="tab-content" id="tab-sklad">
    <div class="container">
      <div class="stats-grid">
        <div class="stat-card orange"><div class="stat-label">Jami mahsulotlar</div><div class="stat-val orange" id="skCount">—</div></div>
        <div class="stat-card green"><div class="stat-label">Zaxirada bor</div><div class="stat-val green" id="skIn">—</div></div>
        <div class="stat-card red"><div class="stat-label">Tugagan</div><div class="stat-val red" id="skOut">—</div></div>
      </div>
      <div class="table-wrap">
        <div class="loader" id="skladLoader"><div class="spin"></div></div>
        <table id="skladTable" style="display:none"><thead><tr><th>#</th><th>Mahsulot</th><th>Zaxira</th><th>Birlik</th><th>Chegara</th><th>Holat</th></tr></thead><tbody id="skladBody"></tbody></table>
      </div>
    </div>
  </div>
  <div class="tab-content" id="tab-contacts">
    <div class="container">
      <div class="table-wrap">
        <div class="loader" id="contactsLoader"><div class="spin"></div></div>
        <table id="contactsTable" style="display:none"><thead><tr><th>#</th><th>Ism</th><th>Telefon</th><th>Qo'shimcha</th><th>Kompaniya</th><th>Izoh</th></tr></thead><tbody id="contactsBody"></tbody></table>
        <div class="no-data" id="noContacts" style="display:none">📭 Kontakt yo'q</div>
      </div>
    </div>
  </div>
</div>
<script>
let token=sessionStorage.getItem('wt')||'',products=[],filter='all';
const fmt=n=>Number(n).toLocaleString('uz')+" so'm";
const fmtS=n=>n>=1e9?(n/1e9).toFixed(1)+' mlrd':n>=1e6?(n/1e6).toFixed(1)+' mln':Number(n).toLocaleString('uz');
async function login(){
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.getElementById('passInput').value})});
  const d=await r.json();
  if(d.ok){token=d.token;sessionStorage.setItem('wt',token);showDash();}
  else document.getElementById('loginErr').textContent="❌ Parol noto'g'ri!";
}
function logout(){token='';sessionStorage.removeItem('wt');document.getElementById('loginWrap').style.display='flex';document.getElementById('dash').style.display='none';}
async function showDash(){document.getElementById('loginWrap').style.display='none';document.getElementById('dash').style.display='block';await loadData();}
async function loadData(){
  const r=await fetch('/api/products',{headers:{'X-Token':token}});
  if(r.status===401){logout();return;}
  const d=await r.json();products=d.products||[];renderStats();renderTable();
  document.getElementById('loader').style.display='none';document.getElementById('prodTable').style.display='table';
}
async function loadSklad(){
  const r=await fetch('/api/sklad',{headers:{'X-Token':token}});const d=await r.json();const items=d.items||[];
  document.getElementById('skCount').textContent=items.length+' ta';
  document.getElementById('skIn').textContent=items.filter(i=>i.quantity>0).length+' ta';
  document.getElementById('skOut').textContent=items.filter(i=>i.quantity<=0).length+' ta';
  document.getElementById('skladBody').innerHTML=items.map((item,i)=>`<tr>
    <td style="color:var(--muted)">${i+1}</td>
    <td><b>${item.name}</b></td>
    <td style="font-family:'DM Mono',monospace;color:var(--green)">${item.quantity}</td>
    <td style="color:var(--muted)">${item.unit}</td>
    <td style="font-family:'DM Mono',monospace;color:var(--muted)">${item.min_alert}</td>
    <td>${item.quantity>0?'<span class="badge paid">✅ Bor</span>':'<span class="badge unpaid">⚠️ Tugagan</span>'}</td>
  </tr>`).join('');
  document.getElementById('skladLoader').style.display='none';document.getElementById('skladTable').style.display='table';
}
async function loadContacts(){
  const r=await fetch('/api/contacts',{headers:{'X-Token':token}});const d=await r.json();const contacts=d.contacts||[];
  if(!contacts.length){document.getElementById('contactsLoader').style.display='none';document.getElementById('noContacts').style.display='block';return;}
  document.getElementById('contactsBody').innerHTML=contacts.map((c,i)=>`<tr>
    <td style="color:var(--muted)">${i+1}</td><td><b>${c.full_name}</b></td>
    <td style="font-family:'DM Mono',monospace">${c.phone||'—'}</td>
    <td style="font-family:'DM Mono',monospace;color:var(--muted)">${c.extra_phone||'—'}</td>
    <td>${c.company||'—'}</td><td style="color:var(--muted)">${c.note||'—'}</td>
  </tr>`).join('');
  document.getElementById('contactsLoader').style.display='none';document.getElementById('contactsTable').style.display='table';
}
function switchTab(tab,btn){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');document.getElementById('tab-'+tab).classList.add('active');
  if(tab==='sklad')loadSklad();if(tab==='contacts')loadContacts();
}
function renderStats(){
  const total=products.reduce((s,p)=>s+p.total_price,0),paid=products.reduce((s,p)=>s+p.paid_amount,0);
  const pct=total>0?Math.min(paid/total*100,100):0;
  document.getElementById('sCount').textContent=products.length+' ta';
  document.getElementById('sTotal').textContent=fmtS(total);
  document.getElementById('sPaid').textContent=fmtS(paid);
  document.getElementById('sRem').textContent=fmtS(total-paid);
  document.getElementById('pPct').textContent=pct.toFixed(1)+'%';
  setTimeout(()=>document.getElementById('pFill').style.width=pct+'%',100);
}
function setFilter(f,btn){filter=f;document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');renderTable();}
function renderTable(){
  const q=document.getElementById('searchBox').value.toLowerCase();
  const rows=products.filter(p=>{
    const rem=p.total_price-p.paid_amount;
    if(filter==='paid'&&rem>0)return false;if(filter==='unpaid'&&rem<=0)return false;
    if(q&&!p.name.toLowerCase().includes(q)&&!(p.supplier_name||'').toLowerCase().includes(q))return false;
    return true;
  });
  if(!rows.length){document.getElementById('prodTable').style.display='none';document.getElementById('noData').style.display='block';return;}
  document.getElementById('prodTable').style.display='table';document.getElementById('noData').style.display='none';
  document.getElementById('prodBody').innerHTML=rows.map((p,i)=>{
    const rem=p.total_price-p.paid_amount,pct=p.total_price>0?Math.min(p.paid_amount/p.total_price*100,100):0;
    const bc=pct>=90?'#3fb950':pct>=50?'#f0883e':'#f85149';
    const badge=rem<=0?'<span class="badge paid">\'liq</span>':pct>0?'<span class="badge partial">⚠️ Qisman</span>':'<span class="badge unpaid">🔴 To\'lanmagan</span>';
    return`<tr><td style="color:var(--muted)">${i+1}</td>
      <td><b>${p.name}</b>${p.supplier_name?`<div style="color:var(--muted);font-size:12px">🏪 ${p.supplier_name}</div>`:''}</td>
      <td style="font-family:'DM Mono',monospace">${fmt(p.total_price)}</td>
      <td style="font-family:'DM Mono',monospace;color:var(--green)">${fmt(p.paid_amount)}</td>
      <td style="font-family:'DM Mono',monospace;color:${rem>0?'var(--red)':'var(--green)'}">${rem>0?fmt(rem):'—'}</td>
      <td>${badge}<div class="mini-bar"><div class="mini-fill" style="width:${pct}%;background:${bc}"></div></div></td>
      <td style="color:var(--muted)">${p.due_date?p.due_date.slice(0,10):'—'}</td></tr>`;
  }).join('');
}
if(token)showDash();
</script>
</body>
</html>'''

def run_web(): app.run(host=‘0.0.0.0’,port=WEB_PORT,debug=False,use_reloader=False)

if **name**==’**main**’:
init_db()
print(f”☕ Bot ishga tushdi! Web: http://0.0.0.0:{WEB_PORT}”)
threading.Thread(target=reminder_loop,daemon=True).start()
threading.Thread(target=run_web,daemon=True).start()
bot.infinity_polling(timeout=30,long_polling_timeout=20)
