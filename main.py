import os, logging, threading, time, secrets, urllib.request, json 
from psycopg2 import pool
from datetime import datetime, timedelta
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import telebot
from telebot import types
from flask import Flask, render_template_string, jsonify, request
import psycopg2
from psycopg2.extras import RealDictCursor

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
WEB_SECRET = os.environ.get("WEB_SECRET", "secret123")
WEB_PORT = int(os.environ.get("WEB_PORT", 5000))
DATABASE_URL = os.environ.get("DATABASE_URL", "")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# MA'LUMOTLAR BAZASI UCHUN "HOVUZ" (POOL) YARATAMIZ
db_pool = psycopg2.pool.ThreadedConnectionPool(1, 20, DATABASE_URL, cursor_factory=RealDictCursor)

class PooledConnection:
    def __init__(self):
        self.conn = db_pool.getconn()
        
    def cursor(self, *args, **kwargs):
        return self.conn.cursor(*args, **kwargs)
        
    def commit(self):
        self.conn.commit()
        
    def close(self):
        # Eng muhim joyi: endi db.close() qilinganda ulanish uzilmaydi, 
        # shunchaki hovuzga qaytarib qo'yiladi va soniyaning mingdan bir qismida ishlaydi.
        db_pool.putconn(self.conn)

def get_db():
    return PooledConnection()
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, full_name TEXT, username TEXT,
        role TEXT DEFAULT 'worker', added_at TEXT, added_by BIGINT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY, name TEXT NOT NULL,
        supplier_name TEXT, total_price REAL NOT NULL, paid_amount REAL DEFAULT 0,
        due_date TEXT, photo_file_id TEXT, note TEXT,
        naqd_account TEXT, online_account TEXT, online_bank TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by BIGINT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id SERIAL PRIMARY KEY, product_id INTEGER NOT NULL,
        amount REAL NOT NULL, payment_type TEXT DEFAULT 'cash',
        receipt_file_id TEXT, note TEXT, paid_at TEXT NOT NULL, added_by BIGINT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS reminders (
        id SERIAL PRIMARY KEY, product_id INTEGER NOT NULL,
        remind_at TEXT NOT NULL, sent INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sklad_items (
        id SERIAL PRIMARY KEY, name TEXT NOT NULL,
        quantity REAL DEFAULT 0, unit TEXT DEFAULT 'dona',
        unit_type TEXT DEFAULT 'dona', min_alert REAL DEFAULT 10,
        photo_file_id TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, created_by BIGINT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sklad_kirim (
        id SERIAL PRIMARY KEY, item_id INTEGER NOT NULL,
        quantity REAL NOT NULL, note TEXT, added_at TEXT NOT NULL, added_by BIGINT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sklad_chiqim (
        id SERIAL PRIMARY KEY, item_id INTEGER NOT NULL,
        quantity REAL NOT NULL, note TEXT, added_at TEXT NOT NULL, added_by BIGINT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sklad_permissions (
        user_id BIGINT PRIMARY KEY, full_name TEXT,
        role TEXT DEFAULT 'viewer', granted_at TEXT, granted_by BIGINT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sklad_requests (
        id SERIAL PRIMARY KEY, user_id BIGINT,
        full_name TEXT, username TEXT, requested_at TEXT, status TEXT DEFAULT 'pending')""")
    c.execute("""CREATE TABLE IF NOT EXISTS yetkazuvchilar (
        id SERIAL PRIMARY KEY, full_name TEXT NOT NULL,
        phone TEXT, extra_phone TEXT, company TEXT, note TEXT,
        created_at TEXT NOT NULL, created_by BIGINT)""")
    conn.commit(); conn.close()

def get_admin_id():
    db = get_db(); c = db.cursor()
    c.execute("SELECT user_id FROM users WHERE role='admin' LIMIT 1")
    row = c.fetchone(); db.close()
    return row['user_id'] if row else None

def is_admin(uid):
    db = get_db(); c = db.cursor()
    c.execute("SELECT role FROM users WHERE user_id=%s", (uid,))
    row = c.fetchone(); db.close()
    return row and row['role'] == 'admin'

def is_allowed(uid):
    db = get_db(); c = db.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=%s", (uid,))
    row = c.fetchone(); db.close()
    return row is not None

def is_sklad_allowed(uid):
    if is_admin(uid): return True
    db = get_db(); c = db.cursor()
    c.execute("SELECT user_id FROM sklad_permissions WHERE user_id=%s", (uid,))
    row = c.fetchone(); db.close()
    return row is not None

def is_sklad_admin(uid):
    if is_admin(uid): return True
    db = get_db(); c = db.cursor()
    c.execute("SELECT role FROM sklad_permissions WHERE user_id=%s", (uid,))
    row = c.fetchone(); db.close()
    return row and row['role'] == 'sklad_admin'

def register_admin(uid, full_name, username):
    db = get_db(); c = db.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=%s", (uid,))
    if not c.fetchone():
        c.execute("INSERT INTO users(user_id,full_name,username,role,added_at) VALUES(%s,%s,%s,'admin',%s)",
                  (uid, full_name, username or '', datetime.now().isoformat()))
        db.commit()
    db.close()

def notify_admin(text, parse_mode='Markdown'):
    aid = get_admin_id()
    if aid:
        try: bot.send_message(aid, text, parse_mode=parse_mode)
        except: pass

user_states = {}
def set_state(uid, s, data=None): user_states[uid] = {'state': s, 'data': data or {}}
def get_state(uid): return user_states.get(uid, {'state': None, 'data': {}})
def clear_state(uid): user_states.pop(uid, None)

def generate_receipt(product, payments, remaining):
    W=600; H=800+len(payments)*62
    img=Image.new('RGB',(W,H),'#0d1117'); draw=ImageDraw.Draw(img)
    for i in range(H):
        draw.line([(0,i),(W,i)],fill=(int(13+(20-13)*i/H),int(17+(28-17)*i/H),int(23+(45-23)*i/H)))
    def rr(x1,y1,x2,y2,r=12,fill=None,outline=None,w=2):
        draw.rounded_rectangle([x1,y1,x2,y2],radius=r,fill=fill,outline=outline,width=w)
    def lf(sz,bold=False):
        for p in [f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'Bold' if bold else ''}.ttf"]:
            try: return ImageFont.truetype(p,sz)
            except: pass
        return ImageFont.load_default()
    f24b=lf(24,True);f20b=lf(20,True);f16=lf(16);f14=lf(14);f20=lf(20)
    rr(15,15,W-15,110,r=20,fill='#161b22',outline='#30363d')
    draw.text((W//2,48),"KAFE NASIYA DAFTARI",font=f24b,fill='#f0883e',anchor='mm')
    draw.text((W//2,84),"Tovar Hisobi & Tolov Cheki",font=f16,fill='#8b949e',anchor='mm')
    y=128;rr(15,y,W-15,y+110,r=15,fill='#161b22',outline='#30363d')
    draw.text((35,y+10),"TOVAR",font=f14,fill='#8b949e')
    draw.text((35,y+34),str(product['name']),font=f24b,fill='#e6edf3')
    draw.text((W-35,y+34),f"{product['total_price']:,.0f}",font=f24b,fill='#f0883e',anchor='ra')
    draw.text((W-35,y+64),"som (jami)",font=f14,fill='#8b949e',anchor='ra')
    y+=140
    bh=len(payments)*58+18 if payments else 46
    rr(15,y,W-15,y+bh,r=15,fill='#161b22',outline='#30363d');y+=10
    if not payments:
        draw.text((W//2,y+14),"Hali tolov kiritilmagan",font=f16,fill='#484f58',anchor='mm');y+=36
    else:
        for i,p in enumerate(payments):
            rr(25,y,W-25,y+50,r=8,fill='#1c2128' if i%2==0 else '#161b22')
            draw.text((42,y+7),f"{str(p['paid_at'])[:16].replace('T',' ')}",font=f14,fill='#8b949e')
            draw.text((W-40,y+16),f"+{p['amount']:,.0f} som",font=f20b,fill='#3fb950',anchor='rm');y+=54
    y+=16
    paid=product['paid_amount'];total=product['total_price']
    pct=min((paid/total*100) if total>0 else 0,100)
    rr(15,y,W-15,y+160,r=15,fill='#161b22',outline='#30363d')
    bx,by=35,y+40;bw=W-70;bfh=18
    rr(bx,by,bx+bw,by+bfh,r=9,fill='#21262d')
    fw=int(bw*pct/100)
    if fw>10:
        bc='#3fb950' if pct>=90 else '#f0883e' if pct>=50 else '#f85149'
        rr(bx,by,bx+fw,by+bfh,r=9,fill=bc)
    draw.text((W//2,by+bfh+14),f"{pct:.1f}% tolangan",font=f16,fill='#8b949e',anchor='mm')
    draw.text((35,y+90),"Tolangan:",font=f20,fill='#8b949e')
    draw.text((W-35,y+90),f"{paid:,.0f} som",font=f20b,fill='#3fb950',anchor='ra')
    draw.text((35,y+124),"Qolgan:",font=f20,fill='#8b949e')
    if remaining<=0: draw.text((W-35,y+124),"Toliq tolandi!",font=f20b,fill='#3fb950',anchor='ra')
    else: draw.text((W-35,y+124),f"{remaining:,.0f} som",font=f24b,fill='#f85149',anchor='ra')
    buf=BytesIO();img.save(buf,format='PNG');buf.seek(0);return buf

def admin_menu():
    m=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
    m.add("➕ Yangi tovar","📦 Tovarlar","💸 To'lov kiritish",
          "📊 Umumiy holat","👥 Xodimlar","🏪 Sklad","🌐 Web sahifa","💵 Dollar kursi")
    return m

def worker_menu():
    m=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
    m.add("📦 Tovarlar","📊 Umumiy holat","🏪 Sklad","💵 Dollar kursi")
    return m

def get_menu(uid): return admin_menu() if is_admin(uid) else worker_menu()
def cancel_kb():
    m=types.ReplyKeyboardMarkup(resize_keyboard=True); m.add("❌ Bekor qilish"); return m
def skip_kb():
    m=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
    m.add("⏭ O'tkazib yuborish","❌ Bekor qilish"); return m

def products_markup(action="view"):
    db=get_db(); c=db.cursor()
    c.execute("SELECT id,name,total_price,paid_amount FROM products ORDER BY created_at DESC")
    rows=c.fetchall(); db.close()
    if not rows: return None,[]
    m=types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        rem=r['total_price']-r['paid_amount']
        m.add(types.InlineKeyboardButton(
            f"{'✅' if rem<=0 else '🔴'}  {r['name']}  |  {rem:,.0f} so'm qolgan",
            callback_data=f"{action}:{r['id']}"))
    return m,rows

def check_sklad_alert(item_id):
    db=get_db(); c=db.cursor()
    c.execute("SELECT * FROM sklad_items WHERE id=%s",(item_id,))
    item=c.fetchone(); db.close()
    if item and item['quantity']<=item['min_alert']:
        notify_admin(f"⚠️ *SKLAD!*\n📦 *{item['name']}* kam qoldi!\n📊 *{item['quantity']} {item['unit']}* qoldi")

def reminder_loop():
    while True:
        try:
            db=get_db(); c=db.cursor(); now=datetime.now().isoformat()
            c.execute("SELECT r.id,p.name,p.total_price,p.paid_amount FROM reminders r "
                      "JOIN products p ON r.product_id=p.id WHERE r.sent=0 AND r.remind_at<=%s",(now,))
            rems=c.fetchall()
            for rem in rems:
                left=rem['total_price']-rem['paid_amount']
                if left>0: notify_admin(f"⏰ *ESLATMA!*\n📦 *{rem['name']}*\n💰 Qolgan: *{left:,.0f} so'm*")
                c.execute("UPDATE reminders SET sent=1 WHERE id=%s",(rem['id'],))
            db.commit(); db.close()
        except Exception as e: logging.error(f"Reminder: {e}")
        time.sleep(60)

def get_dollar_rate():
    try:
        url="https://api.exchangerate-api.com/v4/latest/USD"
        with urllib.request.urlopen(url,timeout=5) as r:
            data=json.loads(r.read())
        return data['rates']['UZS']
    except: return None

@bot.message_handler(commands=['start'])
def cmd_start(msg):
    uid=msg.from_user.id; name=msg.from_user.first_name; uname=msg.from_user.username or ''
    uzs=get_dollar_rate()
    kurs=f"\n\n`1 USD = {uzs:,.0f} UZS`" if uzs else ""
    if not get_admin_id():
        register_admin(uid,name,uname)
        bot.send_message(uid,f"👑 Assalomu alaykum, *{name}*!\nSiz *Admin* sifatida ro'yxatdan o'tdingiz.{kurs}",
            parse_mode='Markdown',reply_markup=admin_menu())
    elif not is_allowed(uid):
        bot.send_message(uid,"🔒 Siz tizimda yo'qsiz. Admin sizni qo'shishi kerak.")
    else:
        bot.send_message(uid,f"👋 Xush kelibsiz, *{name}*!\nRolingiz: {'👑 Admin' if is_admin(uid) else '👤 Xodim'}{kurs}",
            parse_mode='Markdown',reply_markup=get_menu(uid))

@bot.message_handler(func=lambda m: m.text=="➕ Yangi tovar")
def add_product(msg):
    if not is_admin(msg.from_user.id): return
    set_state(msg.from_user.id,'prod_name')
    bot.send_message(msg.from_user.id,"📦 *Tovar nomini kiriting:*",parse_mode='Markdown',reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: m.text=="📦 Tovarlar")
def show_products(msg):
    uid=msg.from_user.id
    if not is_allowed(uid): return
    markup,rows=products_markup("view")
    if not rows: bot.send_message(uid,"📭 Hali hech qanday tovar yo'q.",reply_markup=get_menu(uid)); return
    bot.send_message(uid,"📦 *Tovarlar ro'yxati:*",parse_mode='Markdown',reply_markup=markup)

@bot.message_handler(func=lambda m: m.text=="💸 To'lov kiritish")
def pay_start(msg):
    uid=msg.from_user.id
    if not is_admin(uid): return
    markup,rows=products_markup("pay")
    if not rows: bot.send_message(uid,"📭 Avval tovar qo'shing.",reply_markup=admin_menu()); return
    bot.send_message(uid,"💸 *Qaysi tovar uchun to'lov?*",parse_mode='Markdown',reply_markup=markup)

@bot.message_handler(func=lambda m: m.text=="📊 Umumiy holat")
def total_stats(msg):
    uid=msg.from_user.id
    if not is_allowed(uid): return
    db=get_db(); c=db.cursor()
    c.execute("SELECT COUNT(*) as cnt, SUM(total_price) as total, SUM(paid_amount) as paid FROM products")
    row=c.fetchone(); db.close()
    if not row or not row['cnt']: bot.send_message(uid,"📭 Ma'lumot yo'q.",reply_markup=get_menu(uid)); return
    count=row['cnt'] or 0; total=row['total'] or 0; paid=row['paid'] or 0; rem=total-paid
    pct=(paid/total*100) if total>0 else 0; bar="█"*int(pct/5)+"░"*(20-int(pct/5))
    bot.send_message(uid,
        f"📊 *Umumiy holat*\n\n📦 Tovarlar: *{count} ta*\n"
        f"💰 Jami: *{total:,.0f} so'm*\n✅ To'langan: *{paid:,.0f} so'm*\n"
        f"🔴 Qolgan: *{rem:,.0f} so'm*\n\n`{bar}`\n*{pct:.1f}% to'langan*",
        parse_mode='Markdown',reply_markup=get_menu(uid))

@bot.message_handler(func=lambda m: m.text=="🌐 Web sahifa")
def web_info(msg):
    uid=msg.from_user.id
    if not is_admin(uid): return
    host=os.environ.get("WEB_HOST","http://localhost:5000")
    bot.send_message(uid,f"🌐 *Web Dashboard*\n\n🔗 `{host}`\n🔑 Parol: `{WEB_SECRET}`",
        parse_mode='Markdown',reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text=="💵 Dollar kursi")
def dollar_kurs(msg):
    uid=msg.from_user.id
    if not is_allowed(uid): return
    try:
        url="https://api.exchangerate-api.com/v4/latest/USD"
        with urllib.request.urlopen(url,timeout=5) as r:
            data=json.loads(r.read())
        uzs=data['rates']['UZS']; eur=data['rates']['EUR']; rub=data['rates']['RUB']
        now=datetime.now().strftime('%d.%m.%Y %H:%M')
        bot.send_message(uid,
            f"💵 *Valyuta kurslari*\n_{now}_\n\n"
            f"🇺🇸 1 USD = *{uzs:,.0f} so'm*\n"
            f"🇪🇺 1 EUR = *{uzs/eur:,.0f} so'm*\n"
            f"🇷🇺 1 RUB = *{uzs/rub:,.2f} so'm*",
            parse_mode='Markdown',reply_markup=get_menu(uid))
    except: bot.send_message(uid,"❌ Kursni olishda xatolik.",reply_markup=get_menu(uid))

@bot.message_handler(func=lambda m: m.text=="👥 Xodimlar")
def workers_menu_handler(msg):
    uid=msg.from_user.id
    if not is_admin(uid): return
    db=get_db(); c=db.cursor()
    c.execute("SELECT user_id,full_name,username,role FROM users")
    workers=c.fetchall(); db.close()
    text="👥 *Foydalanuvchilar:*\n\n"
    for w in workers:
        text+=f"{'👑' if w['role']=='admin' else '👤'} *{w['full_name']}* ({'@'+w['username'] if w['username'] else '-'})\n"
    m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("➕ Xodim qo'shish",callback_data="add_worker"))
    m.add(types.InlineKeyboardButton("🗑 Xodim o'chirish",callback_data="remove_worker"))
    bot.send_message(uid,text,parse_mode='Markdown',reply_markup=m)

@bot.message_handler(func=lambda m: m.text=="❌ Bekor qilish")
def cancel_action(msg):
    clear_state(msg.from_user.id)
    bot.send_message(msg.from_user.id,"❌ Bekor qilindi.",reply_markup=get_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text=="⏭ O'tkazib yuborish")
def skip_step(msg):
    uid=msg.from_user.id; st=get_state(uid); state=st['state']; data=st['data']
    if state=='prod_supplier':
        data['supplier']=''; set_state(uid,'prod_price',data)
        bot.send_message(uid,"💰 *Jami narx (so'mda):*",parse_mode='Markdown',reply_markup=cancel_kb())
    elif state=='prod_due':
        data['due_date']=None; set_state(uid,'prod_naqd_acc',data)
        bot.send_message(uid,"💵 *Naqd karta:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='prod_naqd_acc':
        data['naqd_account']=None; set_state(uid,'prod_online_bank',data)
        bot.send_message(uid,"🏦 *Online bank:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='prod_online_bank':
        data['online_bank']=None; set_state(uid,'prod_online_acc',data)
        bot.send_message(uid,"💳 *Online hisob:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='prod_online_acc':
        data['online_account']=None; set_state(uid,'prod_photo',data)
        bot.send_message(uid,"📷 *Tovar rasmi:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='prod_photo':
        data['photo']=None; set_state(uid,'prod_note',data)
        bot.send_message(uid,"📝 *Izoh:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='prod_note':
        data['note']=''; _save_product(uid,data)
    elif state=='sklad_item_photo':
        data['photo']=None; _save_sklad_item(uid,data)
    elif state=='sklad_kirim_note':
        data['note']=''; _save_sklad_kirim(uid,data)
    elif state=='sklad_chiqim_note':
        data['note']=''; _save_sklad_chiqim(uid,data)
    elif state=='sklad_contact_phone2':
        data['extra_phone']=None; set_state(uid,'sklad_contact_company',data)
        bot.send_message(uid,"🏢 *Kompaniya:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='sklad_contact_company':
        data['company']=None; set_state(uid,'sklad_contact_note',data)
        bot.send_message(uid,"📝 *Izoh:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='sklad_contact_note':
        data['note']=None; _save_contact(uid,data)
    elif state=='edit_supplier': _finish_edit(uid,data,'supplier_name',None)
    elif state=='edit_due': _finish_edit(uid,data,'due_date',None)
    elif state=='edit_naqd_acc': _finish_edit(uid,data,'naqd_account',None)
    elif state=='edit_online_bank':
        db=get_db(); c=db.cursor()
        c.execute("UPDATE products SET online_bank=%s,updated_at=%s WHERE id=%s",(None,datetime.now().isoformat(),data['product_id']))
        db.commit(); db.close(); set_state(uid,'edit_online_acc',data)
        bot.send_message(uid,"💳 *Online hisob:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='edit_online_acc': _finish_edit(uid,data,'online_account',None)
    elif state=='edit_photo': _ask_edit_note(uid,data)
    elif state=='edit_note': _finish_edit(uid,data,'note','')
    elif state=='pay_receipt': _save_payment(uid,data)

@bot.message_handler(func=lambda m: m.text=="🏪 Sklad")
def sklad_main(msg):
    uid=msg.from_user.id
    if not is_allowed(uid): return
    if not is_sklad_allowed(uid):
        m=types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("📩 Ruxsat so'rash",callback_data="sklad_request_access"))
        bot.send_message(uid,"🔒 Sklad bo'limiga kirish uchun admin ruxsati kerak.",reply_markup=m); return
    _send_sklad_main(uid)

def _send_sklad_main(uid):
    m=types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("🔍 Mahsulot qidirish",callback_data="sklad:search"),
        types.InlineKeyboardButton("📋 Barcha mahsulotlar",callback_data="sklad:all_items"),
        types.InlineKeyboardButton("📞 Yetkazuvchi kontaktlar",callback_data="sklad:yetkazuvchilar"),
    )
    if is_sklad_admin(uid):
        m.add(
            types.InlineKeyboardButton("📥 Mahsulot kirim",callback_data="sklad:kirim_menu"),
            types.InlineKeyboardButton("📤 Mahsulot chiqim",callback_data="sklad:chiqim_list"),
        )
    if is_admin(uid):
        m.add(types.InlineKeyboardButton("⚙️ Sklad boshqaruvi",callback_data="sklad:admin_panel"))
    bot.send_message(uid,"🏪 *Sklad boshqaruvi*",parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data=="sklad_request_access")
def cb_sklad_request(call):
    uid=call.from_user.id; name=call.from_user.first_name; uname=call.from_user.username or ''
    db=get_db(); c=db.cursor()
    c.execute("SELECT id FROM sklad_requests WHERE user_id=%s AND status='pending'",(uid,))
    if c.fetchone():
        bot.answer_callback_query(call.id,"Siz allaqachon so'rov yuborgansiz."); db.close(); return
    c.execute("INSERT INTO sklad_requests(user_id,full_name,username,requested_at) VALUES(%s,%s,%s,%s)",
              (uid,name,uname,datetime.now().isoformat()))
    db.commit(); db.close()
    bot.answer_callback_query(call.id,"So'rovingiz adminga yuborildi!")
    bot.send_message(uid,"📩 So'rovingiz adminga yuborildi.")
    m=types.InlineKeyboardMarkup()
    m.add(
        types.InlineKeyboardButton("👁 Faqat ko'rish",callback_data=f"sklad_grant_viewer:{uid}"),
        types.InlineKeyboardButton("⚙️ Sklad admin",callback_data=f"sklad_grant_admin:{uid}"),
        types.InlineKeyboardButton("❌ Rad etish",callback_data=f"sklad_deny:{uid}")
    )
    aid=get_admin_id()
    if aid:
        try: bot.send_message(aid,f"📩 *{name}* sklad ruxsati so'ramoqda:",parse_mode='Markdown',reply_markup=m)
        except: pass

def _grant_sklad(uid, target_id, role, call):
    db=get_db(); c=db.cursor()
    c.execute("SELECT full_name FROM users WHERE user_id=%s",(target_id,))
    user=c.fetchone(); name=user['full_name'] if user else str(target_id)
    c.execute("SELECT user_id FROM sklad_permissions WHERE user_id=%s",(target_id,))
    if c.fetchone():
        c.execute("UPDATE sklad_permissions SET role=%s,granted_at=%s,granted_by=%s WHERE user_id=%s",
                  (role,datetime.now().isoformat(),uid,target_id))
    else:
        c.execute("INSERT INTO sklad_permissions(user_id,full_name,role,granted_at,granted_by) VALUES(%s,%s,%s,%s,%s)",
                  (target_id,name,role,datetime.now().isoformat(),uid))
    c.execute("UPDATE sklad_requests SET status='approved' WHERE user_id=%s",(target_id,))
    db.commit(); db.close()
    role_text="👁 Faqat ko'rish" if role=='viewer' else "⚙️ Sklad admin"
    bot.answer_callback_query(call.id,"Ruxsat berildi!")
    bot.edit_message_reply_markup(call.message.chat.id,call.message.message_id,reply_markup=None)
    bot.send_message(uid,f"✅ *{name}* ga ruxsat berildi! Rol: *{role_text}*",parse_mode='Markdown')
    try: bot.send_message(target_id,"✅ Sklad bo'limiga ruxsat berildi!",parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("sklad_grant_viewer:"))
def cb_sgv(call):
    if not is_admin(call.from_user.id): bot.answer_callback_query(call.id,"Ruxsat yo'q!"); return
    _grant_sklad(call.from_user.id,int(call.data.split(":")[1]),'viewer',call)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sklad_grant_admin:"))
def cb_sga(call):
    if not is_admin(call.from_user.id): bot.answer_callback_query(call.id,"Ruxsat yo'q!"); return
    _grant_sklad(call.from_user.id,int(call.data.split(":")[1]),'sklad_admin',call)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sklad_deny:"))
def cb_sd(call):
    if not is_admin(call.from_user.id): bot.answer_callback_query(call.id,"Ruxsat yo'q!"); return
    target_id=int(call.data.split(":")[1])
    db=get_db(); c=db.cursor()
    c.execute("UPDATE sklad_requests SET status='denied' WHERE user_id=%s",(target_id,))
    db.commit(); db.close()
    bot.answer_callback_query(call.id,"Rad etildi!")
    bot.edit_message_reply_markup(call.message.chat.id,call.message.message_id,reply_markup=None)
    try: bot.send_message(target_id,"❌ Sklad bo'limiga ruxsat berilmadi.")
    except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("sklad:"))
def sklad_callback(call):
    uid=call.from_user.id; action=call.data.split(":",1)[1]
    bot.answer_callback_query(call.id)

    if action=="back_main": _send_sklad_main(uid)

    elif action=="search":
        set_state(uid,'sklad_search')
        m=types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
        bot.send_message(uid,"🔍 Mahsulot nomini kiriting:",reply_markup=m)

    elif action=="all_items":
        db=get_db(); c=db.cursor()
        c.execute("SELECT id,name,quantity,unit FROM sklad_items ORDER BY name")
        items=c.fetchall(); db.close()
        if not items: bot.send_message(uid,"📭 Sklad bo'sh."); return
        m=types.InlineKeyboardMarkup(row_width=1)
        for item in items:
            icon="✅" if item['quantity']>0 else "⚠️"
            m.add(types.InlineKeyboardButton(f"{icon} {item['name']} | {item['quantity']} {item['unit']}",
                callback_data=f"sklad:item_detail:{item['id']}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
        bot.send_message(uid,"📋 *Barcha mahsulotlar:*",parse_mode='Markdown',reply_markup=m)

    elif action.startswith("item_detail:"):
        _show_item_detail(uid,int(action.split(":")[1]))

    elif action=="kirim_menu":
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        m=types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("➕ Yangi mahsulot",callback_data="sklad:add_item"),
              types.InlineKeyboardButton("📥 Mavjud mahsulotga kirim",callback_data="sklad:kirim_existing"),
              types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
        bot.send_message(uid,"📥 *Mahsulot kirim*",parse_mode='Markdown',reply_markup=m)

    elif action=="add_item":
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        set_state(uid,'sklad_item_name')
        bot.send_message(uid,"📦 *Yangi mahsulot nomi:*",parse_mode='Markdown',reply_markup=cancel_kb())

    elif action=="add_item_dona":
        st=get_state(uid); data=st['data']; data['unit']='dona'
        set_state(uid,'sklad_item_photo',data)
        bot.send_message(uid,"📷 Rasm yuboring yoki o'tkazib yuboring:",reply_markup=skip_kb())

    elif action=="add_item_kg":
        st=get_state(uid); data=st['data']; data['unit']='kg'
        set_state(uid,'sklad_item_photo',data)
        bot.send_message(uid,"📷 Rasm yuboring yoki o'tkazib yuboring:",reply_markup=skip_kb())

    elif action.startswith("add_item_custom:"):
        unit=action.split(":",1)[1]; st=get_state(uid); data=st['data']; data['unit']=unit
        set_state(uid,'sklad_item_photo',data)
        bot.send_message(uid,"📷 Rasm yuboring yoki o'tkazib yuboring:",reply_markup=skip_kb())

    elif action=="kirim_existing":
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        db=get_db(); c=db.cursor()
        c.execute("SELECT id,name,quantity,unit FROM sklad_items ORDER BY name")
        items=c.fetchall(); db.close()
        if not items: bot.send_message(uid,"📭 Hali mahsulot yo'q."); return
        m=types.InlineKeyboardMarkup(row_width=1)
        for item in items:
            m.add(types.InlineKeyboardButton(f"📦 {item['name']} | {item['quantity']} {item['unit']}",
                callback_data=f"sklad:kirim_item:{item['id']}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:kirim_menu"))
        bot.send_message(uid,"📦 Qaysi mahsulotga kirim?",reply_markup=m)

    elif action.startswith("kirim_item:"):
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        item_id=int(action.split(":")[1])
        db=get_db(); c=db.cursor()
        c.execute("SELECT * FROM sklad_items WHERE id=%s",(item_id,))
        item=c.fetchone(); db.close()
        set_state(uid,'sklad_kirim_qty',{'item_id':item_id,'item_name':item['name'],'unit':item['unit']})
        bot.send_message(uid,f"📥 *{item['name']}*\nZaxira: *{item['quantity']} {item['unit']}*\n\nNecha {item['unit']} keldi?",
            parse_mode='Markdown',reply_markup=cancel_kb())

    elif action=="chiqim_list":
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        db=get_db(); c=db.cursor()
        c.execute("SELECT id,name,quantity,unit FROM sklad_items WHERE quantity>0 ORDER BY name")
        items=c.fetchall(); db.close()
        if not items: bot.send_message(uid,"📭 Zaxirada mahsulot yo'q."); return
        m=types.InlineKeyboardMarkup(row_width=1)
        for item in items:
            m.add(types.InlineKeyboardButton(f"📦 {item['name']} | {item['quantity']} {item['unit']}",
                callback_data=f"sklad:chiqim_item:{item['id']}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
        bot.send_message(uid,"📤 Qaysi mahsulotdan chiqim?",reply_markup=m)

    elif action.startswith("chiqim_item:"):
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        item_id=int(action.split(":")[1])
        db=get_db(); c=db.cursor()
        c.execute("SELECT * FROM sklad_items WHERE id=%s",(item_id,))
        item=c.fetchone(); db.close()
        set_state(uid,'sklad_chiqim_qty',{'item_id':item_id,'item_name':item['name'],'unit':item['unit'],'current_qty':item['quantity']})
        bot.send_message(uid,f"📤 *{item['name']}*\nZaxira: *{item['quantity']} {item['unit']}*\n\nNecha {item['unit']} chiqdi?",
            parse_mode='Markdown',reply_markup=cancel_kb())

    elif action=="yetkazuvchilar":
        db=get_db(); c=db.cursor()
        c.execute("SELECT * FROM yetkazuvchilar ORDER BY full_name")
        contacts=c.fetchall(); db.close()
        if not contacts: text="📞 Hali kontakt qo'shilmagan."
        else:
            text="📞 *Yetkazuvchi kontaktlari:*\n\n"
            for ct in contacts:
                text+=f"👤 *{ct['full_name']}*"
                if ct['company']: text+=f" — _{ct['company']}_"
                text+=f"\n📱 {ct['phone']}"
                if ct['extra_phone']: text+=f" | {ct['extra_phone']}"
                if ct['note']: text+=f"\n📝 {ct['note']}"
                text+="\n\n"
        m=types.InlineKeyboardMarkup(row_width=1)
        if is_sklad_admin(uid):
            m.add(types.InlineKeyboardButton("➕ Kontakt qo'shish",callback_data="sklad:add_contact"))
            m.add(types.InlineKeyboardButton("🗑 Kontakt o'chirish",callback_data="sklad:del_contact"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
        bot.send_message(uid,text,parse_mode='Markdown',reply_markup=m)

    elif action=="add_contact":
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        set_state(uid,'sklad_contact_name')
        bot.send_message(uid,"📞 Yetkazuvchi ismi:",reply_markup=cancel_kb())

    elif action=="del_contact":
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        db=get_db(); c=db.cursor()
        c.execute("SELECT id,full_name FROM yetkazuvchilar ORDER BY full_name")
        contacts=c.fetchall(); db.close()
        if not contacts: bot.send_message(uid,"📭 Kontakt yo'q."); return
        m=types.InlineKeyboardMarkup(row_width=1)
        for ct in contacts:
            m.add(types.InlineKeyboardButton(f"🗑 {ct['full_name']}",callback_data=f"sklad:delcontact:{ct['id']}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:yetkazuvchilar"))
        bot.send_message(uid,"Qaysi kontaktni o'chirish?",reply_markup=m)

    elif action.startswith("delcontact:"):
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        cid=int(action.split(":")[1]); db=get_db(); c=db.cursor()
        c.execute("DELETE FROM yetkazuvchilar WHERE id=%s",(cid,)); db.commit(); db.close()
        bot.send_message(uid,"✅ Kontakt o'chirildi.",reply_markup=get_menu(uid))

    elif action=="admin_panel":
        if not is_admin(uid): bot.send_message(uid,"🔒 Faqat admin uchun."); return
        db=get_db(); c=db.cursor()
        c.execute("SELECT user_id,full_name,role FROM sklad_permissions")
        perms=c.fetchall(); db.close()
        text="⚙️ *Sklad boshqaruvi*\n\n"
        if perms:
            for p in perms:
                ri="⚙️" if p['role']=='sklad_admin' else "👁"
                rn="Sklad admin" if p['role']=='sklad_admin' else "Faqat ko'rish"
                text+=f"  {ri} {p['full_name']} — _{rn}_\n"
        else: text+="Hali hech kimga ruxsat berilmagan.\n"
        m=types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("➕ Ruxsat berish",callback_data="sklad:grant_manual"),
              types.InlineKeyboardButton("🔄 Rolni o'zgartirish",callback_data="sklad:change_role"),
              types.InlineKeyboardButton("🗑 Ruxsatni olib tashlash",callback_data="sklad:revoke_perm"),
              types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
        bot.send_message(uid,text,parse_mode='Markdown',reply_markup=m)

    elif action=="grant_manual":
        if not is_admin(uid): return
        db=get_db(); c=db.cursor()
        c.execute("SELECT user_id,full_name FROM users WHERE role='worker'"); workers=c.fetchall()
        c.execute("SELECT user_id FROM sklad_permissions"); perms=[p['user_id'] for p in c.fetchall()]; db.close()
        candidates=[w for w in workers if w['user_id'] not in perms]
        if not candidates: bot.send_message(uid,"📭 Ruxsat berilmagan xodim yo'q."); return
        m=types.InlineKeyboardMarkup(row_width=1)
        for w in candidates:
            m.add(types.InlineKeyboardButton(f"👤 {w['full_name']}",callback_data=f"sklad:grant_select:{w['user_id']}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:admin_panel"))
        bot.send_message(uid,"Kimga ruxsat berish?",reply_markup=m)

    elif action.startswith("grant_select:"):
        if not is_admin(uid): return
        target_id=int(action.split(":")[1])
        m=types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("👁 Faqat ko'rish",callback_data=f"sklad_grant_viewer:{target_id}"),
              types.InlineKeyboardButton("⚙️ Sklad admin",callback_data=f"sklad_grant_admin:{target_id}"))
        bot.send_message(uid,"Rol tanlang:",reply_markup=m)

    elif action=="change_role":
        if not is_admin(uid): return
        db=get_db(); c=db.cursor()
        c.execute("SELECT user_id,full_name,role FROM sklad_permissions"); perms=c.fetchall(); db.close()
        if not perms: bot.send_message(uid,"📭 Foydalanuvchi yo'q."); return
        m=types.InlineKeyboardMarkup(row_width=1)
        for p in perms:
            ri="⚙️" if p['role']=='sklad_admin' else "👁"
            m.add(types.InlineKeyboardButton(f"{ri} {p['full_name']}",callback_data=f"sklad:role_select:{p['user_id']}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:admin_panel"))
        bot.send_message(uid,"Kimning rolini o'zgartirish?",reply_markup=m)

    elif action.startswith("role_select:"):
        if not is_admin(uid): return
        target_id=int(action.split(":")[1])
        m=types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("👁 Faqat ko'rish",callback_data=f"sklad_grant_viewer:{target_id}"),
              types.InlineKeyboardButton("⚙️ Sklad admin",callback_data=f"sklad_grant_admin:{target_id}"))
        bot.send_message(uid,"Yangi rol tanlang:",reply_markup=m)

    elif action=="revoke_perm":
        if not is_admin(uid): return
        db=get_db(); c=db.cursor()
        c.execute("SELECT user_id,full_name FROM sklad_permissions"); perms=c.fetchall(); db.close()
        if not perms: bot.send_message(uid,"📭 Ruxsat berilgan foydalanuvchi yo'q."); return
        m=types.InlineKeyboardMarkup(row_width=1)
        for p in perms:
            m.add(types.InlineKeyboardButton(f"🗑 {p['full_name']}",callback_data=f"sklad:revoke_ok:{p['user_id']}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:admin_panel"))
        bot.send_message(uid,"Kimning ruxsatini olib tashlash?",reply_markup=m)

    elif action.startswith("revoke_ok:"):
        if not is_admin(uid): return
        rid=int(action.split(":")[1]); db=get_db(); c=db.cursor()
        c.execute("DELETE FROM sklad_permissions WHERE user_id=%s",(rid,)); db.commit(); db.close()
        bot.send_message(uid,"✅ Ruxsat olib tashlandi.",reply_markup=get_menu(uid))

    elif action.startswith("edit_item:"):
        item_id=int(action.split(":")[1])
        if not is_sklad_admin(uid): bot.send_message(uid,"🔒 Ruxsat yo'q."); return
        m=types.InlineKeyboardMarkup(row_width=2)
        m.add(types.InlineKeyboardButton("📝 Nom",callback_data=f"sklad:edititem_name:{item_id}"),
              types.InlineKeyboardButton("📏 Birlik",callback_data=f"sklad:edititem_unit:{item_id}"),
              types.InlineKeyboardButton("🔔 Chegara",callback_data=f"sklad:edititem_alert:{item_id}"),
              types.InlineKeyboardButton("📷 Rasm",callback_data=f"sklad:edititem_photo:{item_id}"))
        m.add(types.InlineKeyboardButton("🗑 O'chirish",callback_data=f"sklad:del_item:{item_id}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data=f"sklad:item_detail:{item_id}"))
        bot.send_message(uid,"Neni tahrirlaysiz?",reply_markup=m)

    elif action.startswith("edititem_name:"):
        set_state(uid,'sklad_edit_name',{'item_id':int(action.split(":")[1])}); bot.send_message(uid,"Yangi nom:",reply_markup=cancel_kb())
    elif action.startswith("edititem_unit:"):
        set_state(uid,'sklad_edit_unit',{'item_id':int(action.split(":")[1])}); bot.send_message(uid,"Yangi birlik:",reply_markup=cancel_kb())
    elif action.startswith("edititem_alert:"):
        set_state(uid,'sklad_edit_alert',{'item_id':int(action.split(":")[1])}); bot.send_message(uid,"Yangi chegara:",reply_markup=cancel_kb())
    elif action.startswith("edititem_photo:"):
        set_state(uid,'sklad_edit_photo',{'item_id':int(action.split(":")[1])}); bot.send_message(uid,"Yangi rasm:",reply_markup=cancel_kb())

    elif action.startswith("del_item:"):
        item_id=int(action.split(":")[1])
        m=types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("✅ Ha",callback_data=f"sklad:del_item_ok:{item_id}"),
              types.InlineKeyboardButton("❌ Yo'q",callback_data=f"sklad:item_detail:{item_id}"))
        bot.send_message(uid,"Mahsulotni o'chirishni tasdiqlaysizmi?",reply_markup=m)

    elif action.startswith("del_item_ok:"):
        item_id=int(action.split(":")[1]); db=get_db(); c=db.cursor()
        c.execute("DELETE FROM sklad_kirim WHERE item_id=%s",(item_id,))
        c.execute("DELETE FROM sklad_chiqim WHERE item_id=%s",(item_id,))
        c.execute("DELETE FROM sklad_items WHERE id=%s",(item_id,))
        db.commit(); db.close()
        bot.send_message(uid,"🗑 Mahsulot o'chirildi.",reply_markup=get_menu(uid))

def _show_item_detail(uid, item_id):
    db=get_db(); c=db.cursor()
    c.execute("SELECT * FROM sklad_items WHERE id=%s",(item_id,)); item=c.fetchone()
    c.execute("SELECT * FROM sklad_kirim WHERE item_id=%s ORDER BY added_at DESC LIMIT 5",(item_id,)); kirims=c.fetchall()
    c.execute("SELECT * FROM sklad_chiqim WHERE item_id=%s ORDER BY added_at DESC LIMIT 5",(item_id,)); chiqims=c.fetchall()
    db.close()
    if not item: bot.send_message(uid,"❌ Topilmadi."); return
    text=(f"📦 *{item['name']}*\n📊 Zaxira: *{item['quantity']} {item['unit']}*\n"
          f"🔔 Chegara: *{item['min_alert']} {item['unit']}*\n\n")
    if kirims:
        text+="📥 *So'nggi kirimlar:*\n"
        for k in kirims: text+=f"  +{k['quantity']} {item['unit']} — {str(k['added_at'])[:16].replace('T',' ')}\n"
        text+="\n"
    if chiqims:
        text+="📤 *So'nggi chiqimlar:*\n"
        for ch in chiqims: text+=f"  -{ch['quantity']} {item['unit']} — {str(ch['added_at'])[:16].replace('T',' ')}\n"
    m=types.InlineKeyboardMarkup(row_width=2)
    if is_sklad_admin(uid):
        m.add(types.InlineKeyboardButton("📥 Kirim",callback_data=f"sklad:kirim_item:{item_id}"),
              types.InlineKeyboardButton("📤 Chiqim",callback_data=f"sklad:chiqim_item:{item_id}"))
        m.add(types.InlineKeyboardButton("✏️ Tahrirlash",callback_data=f"sklad:edit_item:{item_id}"))
    m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:all_items"))
    if item['photo_file_id']: bot.send_photo(uid,item['photo_file_id'],caption=text,parse_mode='Markdown',reply_markup=m)
    else: bot.send_message(uid,text,parse_mode='Markdown',reply_markup=m)

@bot.message_handler(content_types=['text','photo'])
def handle_all(msg):
    uid=msg.from_user.id
    if not is_allowed(uid): bot.send_message(uid,"🔒 Kirish taqiqlangan."); return
    st=get_state(uid); state=st['state']; data=st['data']

    if state=='prod_name':
        name=(msg.text or '').strip()
        if len(name)<2: bot.send_message(uid,"Nom juda qisqa."); return
        data['name']=name; set_state(uid,'prod_supplier',data)
        bot.send_message(uid,f"✅ *{name}*\n\n🏪 *Yetkazuvchi:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='prod_supplier':
        data['supplier']=(msg.text or '').strip(); set_state(uid,'prod_price',data)
        bot.send_message(uid,"💰 *Jami narx (so'mda):*",parse_mode='Markdown',reply_markup=cancel_kb())
    elif state=='prod_price':
        try:
            price=float((msg.text or '').replace(',','').replace(' ',''))
            if price<=0: raise ValueError
        except: bot.send_message(uid,"To'g'ri raqam kiriting.",reply_markup=cancel_kb()); return
        data['price']=price; set_state(uid,'prod_due',data)
        bot.send_message(uid,"📅 *Muddat:*\n_Format: 25.12.2024_\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='prod_due':
        try: data['due_date']=datetime.strptime((msg.text or '').strip(),'%d.%m.%Y').isoformat()
        except: data['due_date']=None
        set_state(uid,'prod_naqd_acc',data)
        bot.send_message(uid,"💵 *Naqd karta:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='prod_naqd_acc':
        data['naqd_account']=(msg.text or '').strip() or None; set_state(uid,'prod_online_bank',data)
        bot.send_message(uid,"🏦 *Online bank:*\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
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
        except: bot.send_message(uid,"To'g'ri summa kiriting.",reply_markup=cancel_kb()); return
        db=get_db(); c=db.cursor()
        c.execute("SELECT * FROM products WHERE id=%s",(data['product_id'],)); prod=c.fetchone(); db.close()
        if not prod: clear_state(uid); bot.send_message(uid,"Topilmadi.",reply_markup=admin_menu()); return
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
        except: bot.send_message(uid,"ID raqam bo'lishi kerak.",reply_markup=cancel_kb()); return
        set_state(uid,'add_worker_name',{'worker_id':wid})
        bot.send_message(uid,"👤 Xodim ismi:",reply_markup=cancel_kb())

    elif state=='add_worker_name':
        wname=(msg.text or '').strip(); wid=data['worker_id']
        db=get_db(); c=db.cursor()
        c.execute("SELECT user_id FROM users WHERE user_id=%s",(wid,))
        if c.fetchone():
            bot.send_message(uid,"Bu foydalanuvchi allaqachon mavjud.",reply_markup=admin_menu())
        else:
            c.execute("INSERT INTO users(user_id,full_name,username,role,added_at,added_by) VALUES(%s,%s,'','worker',%s,%s)",
                      (wid,wname,datetime.now().isoformat(),uid)); db.commit()
            try: bot.send_message(wid,"✅ Siz tizimga xodim sifatida qo'shildingiz!",reply_markup=worker_menu())
            except: pass
            bot.send_message(uid,f"✅ *{wname}* xodim qo'shildi!",parse_mode='Markdown',reply_markup=admin_menu())
        db.close(); clear_state(uid)

    elif state=='sklad_search':
        query=(msg.text or '').strip().lower()
        db=get_db(); c=db.cursor()
        c.execute("SELECT * FROM sklad_items WHERE LOWER(name) LIKE %s ORDER BY name",(f'%{query}%',))
        items=c.fetchall(); db.close(); clear_state(uid)
        if not items:
            m=types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
            bot.send_message(uid,"Hech narsa topilmadi.",reply_markup=m); return
        m=types.InlineKeyboardMarkup(row_width=1)
        for item in items:
            icon="✅" if item['quantity']>0 else "⚠️"
            m.add(types.InlineKeyboardButton(f"{icon} {item['name']} | {item['quantity']} {item['unit']}",
                callback_data=f"sklad:item_detail:{item['id']}"))
        m.add(types.InlineKeyboardButton("🔙 Orqaga",callback_data="sklad:back_main"))
        bot.send_message(uid,f"*{len(items)} ta topildi:*",parse_mode='Markdown',reply_markup=m)

    elif state=='sklad_item_name':
        name=(msg.text or '').strip()
        if len(name)<2: bot.send_message(uid,"Nom juda qisqa.",reply_markup=cancel_kb()); return
        data['name']=name; set_state(uid,'sklad_item_unit_select',data)
        m=types.InlineKeyboardMarkup(row_width=2)
        m.add(types.InlineKeyboardButton("🔢 Donali",callback_data="sklad:add_item_dona"),
              types.InlineKeyboardButton("⚖️ Kilogrammli",callback_data="sklad:add_item_kg"))
        m.add(types.InlineKeyboardButton("📏 Boshqa",callback_data="sklad:add_item_custom:litr"))
        bot.send_message(uid,f"*{name}*\n\nO'lchov turini tanlang:",parse_mode='Markdown',reply_markup=m)

    elif state=='sklad_item_photo':
        if msg.photo: data['photo']=msg.photo[-1].file_id
        _save_sklad_item(uid,data)

    elif state=='sklad_kirim_qty':
        try:
            qty=float((msg.text or '').replace(',','').replace(' ',''))
            if qty<=0: raise ValueError
        except: bot.send_message(uid,"To'g'ri miqdor kiriting.",reply_markup=cancel_kb()); return
        data['qty']=qty; set_state(uid,'sklad_kirim_note',data)
        bot.send_message(uid,"📝 Izoh:\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='sklad_kirim_note':
        data['note']=(msg.text or '').strip(); _save_sklad_kirim(uid,data)

    elif state=='sklad_chiqim_qty':
        try:
            qty=float((msg.text or '').replace(',','').replace(' ',''))
            if qty<=0: raise ValueError
        except: bot.send_message(uid,"To'g'ri miqdor kiriting.",reply_markup=cancel_kb()); return
        if qty>data.get('current_qty',0):
            bot.send_message(uid,f"Zaxirada faqat *{data['current_qty']} {data['unit']}* bor!",parse_mode='Markdown',reply_markup=cancel_kb()); return
        data['qty']=qty; set_state(uid,'sklad_chiqim_note',data)
        bot.send_message(uid,"📝 Izoh:\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='sklad_chiqim_note':
        data['note']=(msg.text or '').strip(); _save_sklad_chiqim(uid,data)

    elif state=='sklad_contact_name':
        name=(msg.text or '').strip()
        if len(name)<2: bot.send_message(uid,"Ism juda qisqa.",reply_markup=cancel_kb()); return
        data['full_name']=name; set_state(uid,'sklad_contact_phone',data)
        bot.send_message(uid,"📱 Telefon:",reply_markup=cancel_kb())
    elif state=='sklad_contact_phone':
        data['phone']=(msg.text or '').strip(); set_state(uid,'sklad_contact_phone2',data)
        bot.send_message(uid,"📱 Qo'shimcha telefon:\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='sklad_contact_phone2':
        data['extra_phone']=(msg.text or '').strip() or None; set_state(uid,'sklad_contact_company',data)
        bot.send_message(uid,"🏢 Kompaniya:\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='sklad_contact_company':
        data['company']=(msg.text or '').strip() or None; set_state(uid,'sklad_contact_note',data)
        bot.send_message(uid,"📝 Izoh:\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='sklad_contact_note':
        data['note']=(msg.text or '').strip() or None; _save_contact(uid,data)

    elif state=='sklad_edit_name':
        new=(msg.text or '').strip(); db=get_db(); c=db.cursor()
        c.execute("UPDATE sklad_items SET name=%s,updated_at=%s WHERE id=%s",(new,datetime.now().isoformat(),data['item_id']))
        db.commit(); db.close(); clear_state(uid)
        bot.send_message(uid,f"✅ Nom yangilandi: *{new}*",parse_mode='Markdown',reply_markup=get_menu(uid))
    elif state=='sklad_edit_unit':
        new=(msg.text or '').strip(); db=get_db(); c=db.cursor()
        c.execute("UPDATE sklad_items SET unit=%s,updated_at=%s WHERE id=%s",(new,datetime.now().isoformat(),data['item_id']))
        db.commit(); db.close(); clear_state(uid)
        bot.send_message(uid,f"✅ Birlik: *{new}*",parse_mode='Markdown',reply_markup=get_menu(uid))
    elif state=='sklad_edit_alert':
        try: alert=float((msg.text or '').replace(',','').replace(' ',''))
        except: bot.send_message(uid,"Raqam kiriting.",reply_markup=cancel_kb()); return
        db=get_db(); c=db.cursor()
        c.execute("UPDATE sklad_items SET min_alert=%s,updated_at=%s WHERE id=%s",(alert,datetime.now().isoformat(),data['item_id']))
        db.commit(); db.close(); clear_state(uid)
        bot.send_message(uid,f"✅ Chegara: *{alert}*",parse_mode='Markdown',reply_markup=get_menu(uid))
    elif state=='sklad_edit_photo':
        if msg.photo:
            db=get_db(); c=db.cursor()
            c.execute("UPDATE sklad_items SET photo_file_id=%s,updated_at=%s WHERE id=%s",(msg.photo[-1].file_id,datetime.now().isoformat(),data['item_id']))
            db.commit(); db.close(); clear_state(uid)
            bot.send_message(uid,"✅ Rasm yangilandi!",reply_markup=get_menu(uid))
        else: bot.send_message(uid,"Rasm yuboring.",reply_markup=cancel_kb())

    elif state=='edit_name':
        v=(msg.text or '').strip()
        if len(v)<2: bot.send_message(uid,"Nom juda qisqa.",reply_markup=cancel_kb()); return
        _finish_edit(uid,data,'name',v)
    elif state=='edit_supplier': _finish_edit(uid,data,'supplier_name',(msg.text or '').strip() or None)
    elif state=='edit_price':
        try:
            p=float((msg.text or '').replace(',','').replace(' ',''))
            if p<=0: raise ValueError
        except: bot.send_message(uid,"To'g'ri raqam kiriting.",reply_markup=cancel_kb()); return
        _finish_edit(uid,data,'total_price',p)
    elif state=='edit_due':
        try: v=datetime.strptime((msg.text or '').strip(),'%d.%m.%Y').isoformat()
        except: v=None
        _finish_edit(uid,data,'due_date',v)
    elif state=='edit_naqd_acc': _finish_edit(uid,data,'naqd_account',(msg.text or '').strip() or None)
    elif state=='edit_online_bank':
        v=(msg.text or '').strip() or None
        db=get_db(); c=db.cursor()
        c.execute("UPDATE products SET online_bank=%s,updated_at=%s WHERE id=%s",(v,datetime.now().isoformat(),data['product_id']))
        db.commit(); db.close(); set_state(uid,'edit_online_acc',data)
        bot.send_message(uid,"💳 Online hisob:\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())
    elif state=='edit_online_acc': _finish_edit(uid,data,'online_account',(msg.text or '').strip() or None)
    elif state=='edit_photo':
        if msg.photo: data['new_photo']=msg.photo[-1].file_id
        _ask_edit_note(uid,data)
    elif state=='edit_note': _finish_edit(uid,data,'note',(msg.text or '').strip() or '')

def _save_sklad_item(uid, data):
    now=datetime.now().isoformat(); db=get_db(); c=db.cursor()
    c.execute("INSERT INTO sklad_items(name,quantity,unit,unit_type,min_alert,photo_file_id,created_at,updated_at,created_by) VALUES(%s,0,%s,%s,10,%s,%s,%s,%s)",
              (data.get('name'),data.get('unit','dona'),data.get('unit','dona'),data.get('photo'),now,now,uid))
    db.commit(); db.close(); clear_state(uid)
    bot.send_message(uid,f"✅ *{data.get('name')}* qo'shildi! Birlik: *{data.get('unit','dona')}*",
        parse_mode='Markdown',reply_markup=get_menu(uid))

def _save_sklad_kirim(uid, data):
    item_id=data['item_id']; qty=data['qty']; note=data.get('note',''); now=datetime.now().isoformat()
    db=get_db(); c=db.cursor()
    c.execute("UPDATE sklad_items SET quantity=quantity+%s,updated_at=%s WHERE id=%s",(qty,now,item_id))
    c.execute("INSERT INTO sklad_kirim(item_id,quantity,note,added_at,added_by) VALUES(%s,%s,%s,%s,%s)",(item_id,qty,note,now,uid))
    db.commit()
    c.execute("SELECT * FROM sklad_items WHERE id=%s",(item_id,)); item=c.fetchone(); db.close()
    clear_state(uid)
    bot.send_message(uid,f"✅ Kirim!\n📦 *{item['name']}*\n+{qty} {item['unit']}\nZaxira: *{item['quantity']} {item['unit']}*",
        parse_mode='Markdown',reply_markup=get_menu(uid))
    notify_admin(f"📥 Sklad kirim\n📦 *{item['name']}*\n+{qty} {item['unit']}\nZaxira: *{item['quantity']} {item['unit']}*")
    check_sklad_alert(item_id)

def _save_sklad_chiqim(uid, data):
    item_id=data['item_id']; qty=data['qty']; note=data.get('note',''); now=datetime.now().isoformat()
    db=get_db(); c=db.cursor()
    c.execute("UPDATE sklad_items SET quantity=quantity-%s,updated_at=%s WHERE id=%s",(qty,now,item_id))
    c.execute("INSERT INTO sklad_chiqim(item_id,quantity,note,added_at,added_by) VALUES(%s,%s,%s,%s,%s)",(item_id,qty,note,now,uid))
    db.commit()
    c.execute("SELECT * FROM sklad_items WHERE id=%s",(item_id,)); item=c.fetchone(); db.close()
    clear_state(uid)
    bot.send_message(uid,f"✅ Chiqim!\n📦 *{item['name']}*\n-{qty} {item['unit']}\nQolgan: *{item['quantity']} {item['unit']}*",
        parse_mode='Markdown',reply_markup=get_menu(uid))
    notify_admin(f"📤 Sklad chiqim\n📦 *{item['name']}*\n-{qty} {item['unit']}\nQolgan: *{item['quantity']} {item['unit']}*")
    check_sklad_alert(item_id)

def _save_contact(uid, data):
    now=datetime.now().isoformat(); db=get_db(); c=db.cursor()
    c.execute("INSERT INTO yetkazuvchilar(full_name,phone,extra_phone,company,note,created_at,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s)",
              (data.get('full_name'),data.get('phone'),data.get('extra_phone'),data.get('company'),data.get('note'),now,uid))
    db.commit(); db.close(); clear_state(uid)
    bot.send_message(uid,f"✅ Kontakt qo'shildi: *{data.get('full_name')}*",parse_mode='Markdown',reply_markup=get_menu(uid))

def _save_product(uid, data):
    now=datetime.now().isoformat(); db=get_db(); c=db.cursor()
    c.execute("INSERT INTO products(name,supplier_name,total_price,paid_amount,due_date,naqd_account,online_account,online_bank,photo_file_id,note,created_at,updated_at,created_by) VALUES(%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
              (data.get('name'),data.get('supplier'),data.get('price'),data.get('due_date'),
               data.get('naqd_account'),data.get('online_account'),data.get('online_bank'),data.get('photo'),data.get('note'),now,now,uid))
    pid=c.fetchone()['id']
    if data.get('due_date'):
        due=datetime.fromisoformat(data['due_date'])
        c.execute("INSERT INTO reminders(product_id,remind_at) VALUES(%s,%s)",(pid,(due-timedelta(days=1)).isoformat()))
    db.commit(); db.close(); clear_state(uid)
    bot.send_message(uid,f"✅ Tovar qo'shildi!\n📦 *{data.get('name')}*\n💰 *{data.get('price',0):,.0f} so'm*",
        parse_mode='Markdown',reply_markup=admin_menu())

def _save_payment(uid, data):
    pid=data['product_id']; amount=data['amount']; ptype=data.get('ptype','cash'); receipt=data.get('receipt'); now=datetime.now().isoformat()
    db=get_db(); c=db.cursor()
    c.execute("UPDATE products SET paid_amount=paid_amount+%s,updated_at=%s WHERE id=%s",(amount,now,pid))
    c.execute("INSERT INTO payments(product_id,amount,payment_type,receipt_file_id,paid_at,added_by) VALUES(%s,%s,%s,%s,%s,%s)",(pid,amount,ptype,receipt,now,uid))
    db.commit()
    c.execute("SELECT * FROM products WHERE id=%s",(pid,)); prod=c.fetchone()
    c.execute("SELECT * FROM payments WHERE product_id=%s ORDER BY paid_at",(pid,)); payments=c.fetchall()
    db.close(); remaining=prod['total_price']-prod['paid_amount']; clear_state(uid)
    try:
        img=generate_receipt(dict(prod),[dict(p) for p in payments],remaining)
        bot.send_photo(uid,img,caption=f"Tolov kiritildi!\n💸 *{amount:,.0f} so'm*\nQolgan: *{remaining:,.0f} so'm*",
            parse_mode='Markdown',reply_markup=admin_menu())
    except Exception as e:
        logging.error(f"Receipt: {e}")
        bot.send_message(uid,f"✅ Tolov kiritildi!\n💸 {amount:,.0f} so'm\nQolgan: {remaining:,.0f} so'm",
            parse_mode='Markdown',reply_markup=admin_menu())

def _ask_edit_note(uid, data):
    if data.get('new_photo'):
        db=get_db(); c=db.cursor()
        c.execute("UPDATE products SET photo_file_id=%s,updated_at=%s WHERE id=%s",(data['new_photo'],datetime.now().isoformat(),data['product_id']))
        db.commit(); db.close()
    set_state(uid,'edit_note',data)
    bot.send_message(uid,"📝 Yangi izoh:\n_(O'tkazish mumkin)_",parse_mode='Markdown',reply_markup=skip_kb())

def _finish_edit(uid, data, field, value):
    if field=='note' and value is None: value=''
    db=get_db(); c=db.cursor()
    c.execute(f"UPDATE products SET {field}=%s,updated_at=%s WHERE id=%s",(value,datetime.now().isoformat(),data['product_id']))
    db.commit()
    c.execute("SELECT * FROM products WHERE id=%s",(data['product_id'],)); prod=c.fetchone(); db.close(); clear_state(uid)
    bot.send_message(uid,f"✅ Yangilandi!\n📦 *{prod['name']}*",parse_mode='Markdown',reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda c: c.data.startswith("view:"))
def cb_view(call):
    uid=call.from_user.id; pid=int(call.data.split(":")[1])
    db=get_db(); c=db.cursor()
    c.execute("SELECT * FROM products WHERE id=%s",(pid,)); prod=c.fetchone()
    c.execute("SELECT * FROM payments WHERE product_id=%s ORDER BY paid_at DESC",(pid,)); payments=c.fetchall()
    db.close()
    if not prod: bot.answer_callback_query(call.id,"Topilmadi!"); return
    rem=prod['total_price']-prod['paid_amount']
    pct=min((prod['paid_amount']/prod['total_price']*100) if prod['total_price']>0 else 0,100)
    bar="█"*int(pct/5)+"░"*(20-int(pct/5))
    ph=""
    for p in payments[:5]:
        ph+=f"  {'💳' if p['payment_type']=='click' else '💵'} {str(p['paid_at'])[:16].replace('T',' ')} — *{p['amount']:,.0f}* so'm\n"
    acc=""
    if prod['naqd_account']: acc+=f"\n💵 Naqd: `{prod['naqd_account']}`"
    if prod['online_account']: acc+=f"\n💳 {prod['online_bank'] or 'Online'}: `{prod['online_account']}`"
    text=(f"📦 *{prod['name']}*\n{'🏪 '+prod['supplier_name'] if prod['supplier_name'] else ''}\n\n"
          f"💰 Jami: *{prod['total_price']:,.0f} so'm*\n✅ Tolangan: *{prod['paid_amount']:,.0f} so'm*\n"
          f"🔴 Qolgan: *{rem:,.0f} so'm*\n\n`{bar}` {pct:.0f}%")
    if acc: text+=f"\n\n🏦 Hisob:{acc}"
    if ph: text+=f"\n\nSonggi tolovlar:\n{ph}"
    m=types.InlineKeyboardMarkup(row_width=2)
    if is_admin(uid):
        m.add(types.InlineKeyboardButton("💸 Tolov",callback_data=f"pay:{pid}"),
              types.InlineKeyboardButton("🧾 Chek",callback_data=f"receipt:{pid}"))
        m.add(types.InlineKeyboardButton("✏️ Tahrirlash",callback_data=f"edit:{pid}"),
              types.InlineKeyboardButton("🗑 Ochirish",callback_data=f"del:{pid}"))
        m.add(types.InlineKeyboardButton("📋 Barcha tolovlar",callback_data=f"history:{pid}"))
    else:
        m.add(types.InlineKeyboardButton("🧾 Chek",callback_data=f"receipt:{pid}"),
              types.InlineKeyboardButton("📋 Barcha tolovlar",callback_data=f"history:{pid}"))
    bot.answer_callback_query(call.id)
    if prod['photo_file_id']: bot.send_photo(uid,prod['photo_file_id'],caption=text,parse_mode='Markdown',reply_markup=m)
    else: bot.send_message(uid,text,parse_mode='Markdown',reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit:"))
def cb_edit(call):
    uid=call.from_user.id
    if not is_admin(uid): bot.answer_callback_query(call.id,"Ruxsat yoq!"); return
    pid=int(call.data.split(":")[1]); bot.answer_callback_query(call.id)
    m=types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("📦 Nom",callback_data=f"editf:name:{pid}"),
          types.InlineKeyboardButton("🏪 Yetkazuvchi",callback_data=f"editf:supplier:{pid}"))
    m.add(types.InlineKeyboardButton("💰 Narx",callback_data=f"editf:price:{pid}"),
          types.InlineKeyboardButton("📅 Muddat",callback_data=f"editf:due:{pid}"))
    m.add(types.InlineKeyboardButton("💵 Naqd hisob",callback_data=f"editf:naqd:{pid}"),
          types.InlineKeyboardButton("💳 Online",callback_data=f"editf:online:{pid}"))
    m.add(types.InlineKeyboardButton("📷 Rasm",callback_data=f"editf:photo:{pid}"),
          types.InlineKeyboardButton("📝 Izoh",callback_data=f"editf:note:{pid}"))
    bot.send_message(uid,"Qaysi maydon?",reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("editf:"))
def cb_editf(call):
    uid=call.from_user.id
    if not is_admin(uid): bot.answer_callback_query(call.id,"Ruxsat yoq!"); return
    parts=call.data.split(":"); field=parts[1]; pid=int(parts[2]); bot.answer_callback_query(call.id)
    data={'product_id':pid}
    pm={'name':('edit_name',"Yangi nom:",cancel_kb()),
        'supplier':('edit_supplier',"Yangi yetkazuvchi:\n_(O'tkazish mumkin)_",skip_kb()),
        'price':('edit_price',"Yangi narx:",cancel_kb()),
        'due':('edit_due',"Yangi muddat (25.12.2024):\n_(O'tkazish mumkin)_",skip_kb()),
        'naqd':('edit_naqd_acc',"Naqd karta:\n_(O'tkazish mumkin)_",skip_kb()),
        'online':('edit_online_bank',"Online bank:\n_(O'tkazish mumkin)_",skip_kb()),
        'note':('edit_note',"Yangi izoh:\n_(O'tkazish mumkin)_",skip_kb()),
        'photo':('edit_photo',"Yangi rasm:\n_(O'tkazish mumkin)_",skip_kb())}
    if field not in pm: return
    s,p,kb=pm[field]; set_state(uid,s,data); bot.send_message(uid,p,parse_mode='Markdown',reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("pay:"))
def cb_pay(call):
    uid=call.from_user.id
    if not is_admin(uid): bot.answer_callback_query(call.id,"Ruxsat yoq!"); return
    pid=int(call.data.split(":")[1]); db=get_db(); c=db.cursor()
    c.execute("SELECT name,total_price,paid_amount FROM products WHERE id=%s",(pid,)); prod=c.fetchone(); db.close()
    rem=prod['total_price']-prod['paid_amount']
    if rem<=0: bot.answer_callback_query(call.id,"Toliq tolangan!"); return
    set_state(uid,'pay_amount',{'product_id':pid}); bot.answer_callback_query(call.id)
    bot.send_message(uid,f"💸 *{prod['name']}*\nQolgan: *{rem:,.0f} so'm*\n\nSumma kiriting:",parse_mode='Markdown',reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("ptype:"))
def cb_ptype(call):
    uid=call.from_user.id; ptype=call.data.split(":")[1]; data=get_state(uid)['data']
    data['ptype']=ptype; bot.answer_callback_query(call.id)
    if ptype=='click':
        set_state(uid,'pay_receipt',data)
        acc=f"\n\n🏦 `{data['online_account']}` ({data.get('online_bank','Online')})" if data.get('online_account') else ""
        bot.send_message(uid,f"Chek rasmini yuboring:\n_(O'tkazish mumkin)_{acc}",parse_mode='Markdown',reply_markup=skip_kb())
    else:
        if data.get('naqd_account'): bot.send_message(uid,f"💵 Karta: `{data['naqd_account']}`",parse_mode='Markdown')
        _save_payment(uid,data)

@bot.callback_query_handler(func=lambda c: c.data.startswith("receipt:"))
def cb_receipt(call):
    uid=call.from_user.id; pid=int(call.data.split(":")[1])
    db=get_db(); c=db.cursor()
    c.execute("SELECT * FROM products WHERE id=%s",(pid,)); prod=c.fetchone()
    c.execute("SELECT * FROM payments WHERE product_id=%s ORDER BY paid_at",(pid,)); payments=c.fetchall(); db.close()
    bot.answer_callback_query(call.id,"Chek tayyorlanmoqda...")
    try:
        img=generate_receipt(dict(prod),[dict(p) for p in payments],prod['total_price']-prod['paid_amount'])
        bot.send_photo(uid,img,caption=f"🧾 *{prod['name']}*\nQolgan: *{prod['total_price']-prod['paid_amount']:,.0f} so'm*",parse_mode='Markdown')
    except Exception as e: bot.send_message(uid,f"Xatolik: {e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("history:"))
def cb_history(call):
    uid=call.from_user.id; pid=int(call.data.split(":")[1])
    db=get_db(); c=db.cursor()
    c.execute("SELECT name FROM products WHERE id=%s",(pid,)); prod=c.fetchone()
    c.execute("SELECT * FROM payments WHERE product_id=%s ORDER BY paid_at DESC",(pid,)); payments=c.fetchall(); db.close()
    if not payments: bot.answer_callback_query(call.id,"Hali tolov yoq!"); return
    text=f"📋 *{prod['name']}* — Barcha tolovlar:\n\n"; total=0
    for i,p in enumerate(payments,1):
        text+=f"{i}. {'💳' if p['payment_type']=='click' else '💵'} *{p['amount']:,.0f} so'm* — {str(p['paid_at'])[:16].replace('T',' ')}\n"
        total+=p['amount']
    text+=f"\nJami: *{total:,.0f} so'm*"; bot.answer_callback_query(call.id)
    bot.send_message(uid,text,parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("del:"))
def cb_del(call):
    uid=call.from_user.id
    if not is_admin(uid): bot.answer_callback_query(call.id,"Ruxsat yoq!"); return
    pid=int(call.data.split(":")[1]); bot.answer_callback_query(call.id)
    m=types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("✅ Ha",callback_data=f"delok:{pid}"),
          types.InlineKeyboardButton("❌ Yoq",callback_data="delno"))
    bot.send_message(uid,"Haqiqatan ham o'chirmoqchimisiz?",reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("delok:"))
def cb_delok(call):
    pid=int(call.data.split(":")[1]); db=get_db(); c=db.cursor()
    c.execute("DELETE FROM payments WHERE product_id=%s",(pid,))
    c.execute("DELETE FROM reminders WHERE product_id=%s",(pid,))
    c.execute("DELETE FROM products WHERE id=%s",(pid,)); db.commit(); db.close()
    bot.answer_callback_query(call.id,"Ochirildi!")
    bot.send_message(call.from_user.id,"🗑 Tovar o'chirildi.",reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda c: c.data=="delno")
def cb_delno(call): bot.answer_callback_query(call.id,"Bekor")

@bot.callback_query_handler(func=lambda c: c.data=="add_worker")
def cb_add_worker(call):
    uid=call.from_user.id
    if not is_admin(uid): bot.answer_callback_query(call.id,"Ruxsat yoq!"); return
    set_state(uid,'add_worker_id'); bot.answer_callback_query(call.id)
    bot.send_message(uid,"Xodim Telegram ID sini yuboring:\n(@userinfobot dan olish mumkin)",reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data=="remove_worker")
def cb_remove_worker(call):
    uid=call.from_user.id
    if not is_admin(uid): bot.answer_callback_query(call.id,"Ruxsat yoq!"); return
    db=get_db(); c=db.cursor()
    c.execute("SELECT user_id,full_name FROM users WHERE role='worker'"); workers=c.fetchall(); db.close()
    if not workers: bot.answer_callback_query(call.id,"Xodim yoq!"); return
    m=types.InlineKeyboardMarkup()
    for w in workers: m.add(types.InlineKeyboardButton(f"🗑 {w['full_name']}",callback_data=f"delworker:{w['user_id']}"))
    bot.answer_callback_query(call.id); bot.send_message(uid,"Qaysi xodimni o'chirish?",reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("delworker:"))
def cb_delworker(call):
    wid=int(call.data.split(":")[1]); db=get_db(); c=db.cursor()
    c.execute("DELETE FROM users WHERE user_id=%s AND role='worker'",(wid,)); db.commit(); db.close()
    bot.answer_callback_query(call.id,"Ochirildi!")
    bot.send_message(call.from_user.id,"✅ Xodim o'chirildi.",reply_markup=admin_menu())

active_tokens={}

@app.route('/')
def web_index(): return render_template_string(WEB_HTML)

@app.route('/api/login',methods=['POST'])
def api_login():
    d=request.get_json()
    if d and d.get('password')==WEB_SECRET:
        tok=secrets.token_hex(24); active_tokens[tok]=datetime.now()
        return jsonify({'ok':True,'token':tok})
    return jsonify({'ok':False}),401

def chk(): return request.headers.get('X-Token','') in active_tokens

@app.route('/api/products')
def api_products():
    if not chk(): return jsonify({'error':'Unauthorized'}),401
    db=get_db(); c=db.cursor()
    c.execute("SELECT id,name,supplier_name,total_price,paid_amount,due_date,note FROM products ORDER BY created_at DESC")
    rows=c.fetchall(); db.close()
    return jsonify({'products':[dict(r) for r in rows]})

@app.route('/api/sklad')
def api_sklad():
    if not chk(): return jsonify({'error':'Unauthorized'}),401
    db=get_db(); c=db.cursor()
    c.execute("SELECT id,name,quantity,unit,min_alert FROM sklad_items ORDER BY name")
    items=c.fetchall(); db.close()
    return jsonify({'items':[dict(i) for i in items]})

@app.route('/api/contacts')
def api_contacts():
    if not chk(): return jsonify({'error':'Unauthorized'}),401
    db=get_db(); c=db.cursor()
    c.execute("SELECT * FROM yetkazuvchilar ORDER BY full_name")
    contacts=c.fetchall(); db.close()
    return jsonify({'contacts':[dict(c) for c in contacts]})

WEB_HTML='''<!DOCTYPE html>
<html lang="uz"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Kafe Nasiya Daftari</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#080c12;color:#e6edf3;font-family:sans-serif;min-height:100vh}
.lw{min-height:100vh;display:flex;align-items:center;justify-content:center}
.lb{background:#141c28;border:1px solid #1e2d42;border-radius:20px;padding:40px;width:360px;text-align:center}
.lb h1{font-size:20px;font-weight:800;margin-bottom:8px}
.lb p{color:#7d8fa8;font-size:13px;margin-bottom:24px}
input{width:100%;padding:12px 16px;background:#0f1520;border:1px solid #1e2d42;border-radius:10px;color:#e6edf3;font-size:14px;margin-bottom:12px;outline:none}
.btn{width:100%;padding:12px;background:#f0883e;border:none;border-radius:10px;color:#fff;font-weight:700;font-size:14px;cursor:pointer}
.dash{display:none}
.top{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;border-bottom:1px solid #1e2d42}
.top h2{font-size:16px;font-weight:800}
.lo{background:transparent;border:1px solid #1e2d42;color:#7d8fa8;padding:6px 12px;border-radius:8px;font-size:12px;cursor:pointer}
.tabs{display:flex;gap:4px;padding:16px 24px 0;border-bottom:1px solid #1e2d42}
.tb{background:transparent;border:none;border-bottom:2px solid transparent;color:#7d8fa8;padding:8px 12px;font-size:13px;font-weight:600;cursor:pointer}
.tb.active{color:#f0883e;border-bottom-color:#f0883e}
.tc{display:none}.tc.active{display:block}
.con{max-width:1100px;margin:0 auto;padding:24px 16px}
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}
.sc{background:#141c28;border:1px solid #1e2d42;border-radius:14px;padding:20px}
.sl{font-size:11px;color:#7d8fa8;text-transform:uppercase;margin-bottom:6px}
.sv{font-size:24px;font-weight:800}
.or{color:#f0883e}.gr{color:#3fb950}.rd{color:#f85149}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:10px 12px;font-size:10px;color:#7d8fa8;text-transform:uppercase;border-bottom:1px solid #1e2d42}
td{padding:12px;border-bottom:1px solid #1e2d42;font-size:13px}
.badge{display:inline-block;padding:3px 8px;border-radius:99px;font-size:11px;font-weight:600}
.bg{background:rgba(63,185,80,.15);color:#3fb950}.br{background:rgba(248,81,73,.15);color:#f85149}
</style></head>
<body>
<div class="lw" id="lw">
  <div class="lb">
    <h1>Kafe Nasiya Daftari</h1>
    <p>Parol kiriting</p>
    <input type="password" id="pw" placeholder="Parol..." onkeydown="if(event.key=='Enter')login()">
    <button class="btn" onclick="login()">Kirish</button>
    <div id="err" style="color:#f85149;font-size:12px;margin-top:8px"></div>
  </div>
</div>
<div class="dash" id="dash">
  <div class="top"><h2>Kafe Nasiya Daftari</h2><button class="lo" onclick="logout()">Chiqish</button></div>
  <div class="tabs">
    <button class="tb active" onclick="tab('products',this)">Tovarlar</button>
    <button class="tb" onclick="tab('sklad',this)">Sklad</button>
    <button class="tb" onclick="tab('contacts',this)">Kontaktlar</button>
  </div>
  <div id="tp" class="tc active"><div class="con"><div class="sg" id="sg"></div>
    <table><thead><tr><th>Tovar</th><th>Yetkazuvchi</th><th>Jami</th><th>Tolangan</th><th>Qolgan</th><th>Holat</th></tr></thead>
    <tbody id="pb"></tbody></table></div></div>
  <div id="ts" class="tc"><div class="con">
    <table><thead><tr><th>Mahsulot</th><th>Zaxira</th><th>Birlik</th><th>Chegara</th><th>Holat</th></tr></thead>
    <tbody id="sb"></tbody></table></div></div>
  <div id="tc2" class="tc"><div class="con">
    <table><thead><tr><th>Ism</th><th>Telefon</th><th>Kompaniya</th><th>Izoh</th></tr></thead>
    <tbody id="cb"></tbody></table></div></div>
</div>
<script>
let tok='';
async function login(){
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:document.getElementById('pw').value})});
  const d=await r.json();
  if(d.ok){tok=d.token;document.getElementById('lw').style.display='none';document.getElementById('dash').style.display='block';load();}
  else{document.getElementById('err').textContent='Notogri parol!';}
}
function logout(){tok='';location.reload();}
function tab(n,b){
  document.querySelectorAll('.tc').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tb').forEach(x=>x.classList.remove('active'));
  document.getElementById('t'+n[0]).classList.add('active');b.classList.add('active');
}
function fmt(n){return Number(n).toLocaleString();}
async function load(){
  const h={'X-Token':tok};
  const [pr,sk,ct]=await Promise.all([
    fetch('/api/products',{headers:h}).then(r=>r.json()),
    fetch('/api/sklad',{headers:h}).then(r=>r.json()),
    fetch('/api/contacts',{headers:h}).then(r=>r.json())
  ]);
  let tot=0,paid=0,rem=0;
  (pr.products||[]).forEach(p=>{tot+=p.total_price;paid+=p.paid_amount;rem+=(p.total_price-p.paid_amount);});
  document.getElementById('sg').innerHTML=`
    <div class="sc"><div class="sl">Jami nasiya</div><div class="sv or">${fmt(tot)} som</div></div>
    <div class="sc"><div class="sl">Tolangan</div><div class="sv gr">${fmt(paid)} som</div></div>
    <div class="sc"><div class="sl">Qolgan</div><div class="sv rd">${fmt(rem)} som</div></div>
    <div class="sc"><div class="sl">Tovarlar</div><div class="sv">${(pr.products||[]).length} ta</div></div>`;
  document.getElementById('pb').innerHTML=(pr.products||[]).map(p=>{
    const r=p.total_price-p.paid_amount;
    return `<tr><td><b>${p.name}</b></td><td>${p.supplier_name||'-'}</td>
    <td>${fmt(p.total_price)} som</td><td class="gr">${fmt(p.paid_amount)} som</td>
    <td class="rd">${fmt(r)} som</td>
    <td><span class="badge ${r<=0?'bg':'br'}">${r<=0?'Toliq':'Qarz bor'}</span></td></tr>`;
  }).join('');
  document.getElementById('sb').innerHTML=(sk.items||[]).map(i=>`<tr>
    <td><b>${i.name}</b></td><td>${i.quantity}</td><td>${i.unit}</td><td>${i.min_alert}</td>
    <td><span class="badge ${i.quantity>i.min_alert?'bg':'br'}">${i.quantity>i.min_alert?'Yetarli':'Kam'}</span></td></tr>`).join('');
  document.getElementById('cb').innerHTML=(ct.contacts||[]).map(c=>`<tr>
    <td><b>${c.full_name}</b></td><td>${c.phone||'-'}${c.extra_phone?' | '+c.extra_phone:''}</td>
    <td>${c.company||'-'}</td><td>${c.note||'-'}</td></tr>`).join('');
}
</script></body></html>'''

def run_web(): app.run(host='0.0.0.0',port=WEB_PORT,debug=False,use_reloader=False)

if __name__ == '__main__':
    init_db()
    print(f"Bot ishga tushdi!")
    threading.Thread(target=reminder_loop,daemon=True).start()
    threading.Thread(target=run_web,daemon=True).start()
    bot.infinity_polling(timeout=30,long_polling_timeout=20)
