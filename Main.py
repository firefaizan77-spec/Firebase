#!/usr/bin/env python3

import telebot, os, subprocess, re, time, requests
import threading, hashlib, sys, traceback
from telebot import types
from datetime import datetime

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ⚙️  CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOT_TOKEN      = '8611112162:AAE7kTFDs5RV6VluvKfXGLTqkBnel8obPN4'
BRAND_NAME     = "DEMON"
ADMIN          = "7507173935"

# ── Single admin only ──
_PROTECTED_IDS = {int(ADMIN)} if str(ADMIN).strip() else set()
APK_DIR        = os.path.join(os.path.expanduser('~'), '.codewraith_tmp')
os.makedirs(APK_DIR, exist_ok=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🎨  UI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
L1 = "━━━━━━━━━━━━━━━━━━━━━━━━"
L2 = "══════════════════════════"
SP = ["⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

def bar(p):
    f = int(p/10); return f"[{'█'*f}{'░'*(10-f)}] {p}%"

def box(title):
    t = title[:22]
    return f"╔{'═'*26}╗\n║  {t:<24}║\n╚{'═'*26}╝"

def R(label, val, e="▸"):
    return f"{e} <b>{label}:</b> <code>{val}</code>"

def fmt_elapsed(seconds):
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"

def simple_loading_text(step, started_at, frame_index=0):
    frame = SP[frame_index % len(SP)]
    elapsed = fmt_elapsed(time.time() - started_at)
    return (
        f"4️⃣ {step}\n"
        f"{frame} Processing in progress\n"
        f"⏱️ Elapsed: {elapsed}\n"
        f"Please wait..."
    )

def simple_result_text(fname, fsize, fmd5, data):
    lines = [
        f"<b>{BRAND_NAME}</b>",
        "",
        f"<b>File:</b> <code>{fname}</code>",
        f"<b>Size:</b> <code>{fsize} MB</code>",
        f"<b>MD5:</b> <code>{fmd5}</code>",
        "",
        "<b>Output</b>",
    ]
    found = 0
    for key, value in data.items():
        if value in ("─", "", None):
            continue
        label = re.sub(r"^[^\w]+", "", key).strip() or key
        lines.append(f"<b>{label}:</b>")
        lines.append(f"<code>{value}</code>")
        lines.append("")
        found += 1
    if found == 0:
        lines.append("<code>No data found.</code>")
    return "\n".join(lines).strip()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📡  STATE MACHINE  (replaces register_next_step_handler)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STATE[uid] = {'action': str, 'data': dict}
STATE     = {}
STATE_LCK = threading.Lock()

def set_state(uid, action, **data):
    with STATE_LCK:
        STATE[uid] = {'action': action, 'data': data}

def get_state(uid):
    with STATE_LCK:
        return STATE.get(uid)

def clear_state(uid):
    with STATE_LCK:
        STATE.pop(uid, None)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  💾  DATABASE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
G = dict(users=set(), scans=0, bots={}, banned=set(),
         history={}, log=[], maint=False, rate={},
         scheduled=[], messages={})
_dbl = threading.Lock()
START_TIME = datetime.now()

def load_db():
    return

def save_db():
    return

def log_act(uid, a):
    G['log'].append({'t':datetime.now().strftime('%d/%m %H:%M'),'u':uid,'a':a})

def binfo(tok):
    b = G['bots'].get(tok)
    if not isinstance(b, dict):
        b = {'name':'Bot','owner':int(ADMIN) if str(ADMIN).strip() else 0,'admins':[],'scans':0,'users':[]}
        G['bots'][tok] = b
    return b

def find_tok(key):
    for t in G['bots']:
        if t[:20] == key: return t
    return None

def is_adm(uid, tok=None):
    return uid == (int(ADMIN) if str(ADMIN).strip() else 0)

def safe_remove_admin(tok, target_uid):
    return False, "Only one admin is allowed."

def get_msg(tok, key, default=None):
    return G['messages'].get(tok,{}).get(key, default)

def set_msg(tok, key, val):
    G['messages'].setdefault(tok,{})[key] = val
    save_db()

# Rate limit
_rll = threading.Lock()
def is_limited(uid):
    k, now = str(uid), time.time()
    with _rll:
        G['rate'].setdefault(k,[])
        G['rate'][k] = [t for t in G['rate'][k] if now-t<60]
        if len(G['rate'][k]) >= 5: return True
        G['rate'][k].append(now)
    return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔬  SCAN ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PATTERNS = {
    '🌐 DB URL':       r'https://[a-zA-Z0-9-]+\.firebaseio\.com',
    '📦 Storage':      r'[a-zA-Z0-9-]+\.appspot\.com|[a-zA-Z0-9-]+\.firebasestorage\.app',
    '🔑 API Key':      r'AIza[0-9A-Za-z\-_]{35}',
    '🆔 Project ID':   r'"project_id"\s*:\s*"([^"]+)"',
    '🛡️ Auth Domain':  r'[a-zA-Z0-9-]+\.firebaseapp\.com',
    '🔐 Secret':       r'(?i)(password|admin_pass|secret_key)\s*[:=]\s*"([^"]+)"',
    '📲 GCM Token':    r'[0-9]{12}:APA91b[0-9A-Za-z\-_]{134}',
    '🔏 OAuth Client': r'[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com',
    '🗺️ Maps Key':     r'(?i)maps_api_key\s*[:=]\s*"?([A-Za-z0-9_\-]{30,})"?',
    '🪣 GS Bucket':    r'gs://[a-zA-Z0-9._\-]+',
    '📱 App ID':       r'"mobilesdk_app_id"\s*:\s*"([^"]+)"',
}
DB_KEY = '🌐 DB URL'

def get_md5(path):
    h = hashlib.md5()
    with open(path,'rb') as f:
        for c in iter(lambda: f.read(65536), b''): h.update(c)
    return h.hexdigest()

def scan_apk(path):
    res = {k:'─' for k in PATTERNS}
    try:
        raw = subprocess.check_output(f"strings '{path}'",shell=True,timeout=45).decode('utf-8','ignore')
        for k,v in PATTERNS.items():
            m = re.search(v, raw)
            if m:
                try: res[k] = m.group(1) or m.group(0)
                except: res[k] = m.group(0)
    except subprocess.TimeoutExpired: pass
    except Exception as e: print(f"[SCAN] {e}")
    return res

def check_fb(base, param):
    try:
        url = base.rstrip('/')+param
        r   = requests.get(url, timeout=10)
        if r.status_code==200 and r.text.strip() not in ('null','','false','{}','[]'):
            return url, r.text[:500]
        return url, None
    except Exception as e:
        return base.rstrip('/')+param, None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📢  BROADCAST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def do_bc_text(bot, text, admin_id, targets):
    ok=fail=0
    for u in list(targets):
        try: bot.send_message(u, text, parse_mode='HTML'); ok+=1
        except: fail+=1
        time.sleep(0.05)
    try:
        bot.send_message(admin_id,
            f"{box('📊 BROADCAST DONE')}\n\n✅ Delivered: <b>{ok}</b>\n❌ Failed: <b>{fail}</b>",
            parse_mode='HTML')
    except: pass

def do_bc_media(bot, fwd_chat, fwd_mid, admin_id, targets):
    ok=fail=0
    for u in list(targets):
        try: bot.forward_message(u, fwd_chat, fwd_mid); ok+=1
        except: fail+=1
        time.sleep(0.05)
    try:
        bot.send_message(admin_id,
            f"{box('📊 BROADCAST DONE')}\n\n✅ Delivered: <b>{ok}</b>\n❌ Failed: <b>{fail}</b>",
            parse_mode='HTML')
    except: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ⌨️  KEYBOARDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def mk(*rows):
    m = types.InlineKeyboardMarkup()
    for r in rows:
        m.row(*[types.InlineKeyboardButton(t, callback_data=d) for t,d in r])
    return m

def back(d="menu_main"): return mk([("🔙 Back", d)])

def owner_kb():
    return mk(
        [("📊 Stats","stats"),          ("⏳ Uptime","uptime")],
        [("🤖 Bot List","bot_list"),    ("➕ Add Bot","bot_add")],
        [("👥 All Users","users"),      ("🔍 Search User","search_user")],
        [("📢 Broadcast","bc_menu"),    ("📣 All-Bot BC","all_bot_bc")],
        [("📋 Admin Log","adm_log"),    ("📈 Top Scanners","top_scan")],
        [("📤 Export Script","export"), ("💾 Force Save","force_save")],
        [("📅 Schedule BC","sched_bc"), ("🗄️ Banned List","ban_list")],
        [("🚫 Ban","ban_u"),            ("✅ Unban","unban_u")],
        [("🌐 Firebase Check","fb_check"),("📜 Scan History","scan_hist")],
        [("🔇 Maintenance","toggle_maint"),("ℹ️ System Info","sys_info")],
        [("🔄 Restart","restart"),      ("🧹 Clear Limits","clear_rl")],
    )

def sub_kb():
    return mk(
        [("📊 Stats","stats"),         ("⏳ Uptime","uptime")],
        [("👥 My Users","users"),      ("📜 Scan History","scan_hist")],
        [("📢 Broadcast","bc_menu"),   ("🌐 Firebase Check","fb_check")],
        [("🚫 Ban","ban_u"),           ("✅ Unban","unban_u")],
    )

def bc_kb():
    return mk(
        [("📝 Text BC","bc_text"),      ("🖼️ Media BC","bc_media")],
        [("📣 All-Bot BC","all_bot_bc")],
        [("🔙 Back","menu_main")],
    )

def bot_list_kb():
    rows = []
    for tok, _ in G['bots'].items():
        bi = binfo(tok)
        rows.append([(f"🤖 {bi.get('name','Bot')} │ 🔍{bi.get('scans',0)} │ 👥{len(bi.get('users',[]))}",
                      f"bot_open:{tok[:20]}")])
    rows.append([("➕ Add Bot","bot_add"), ("🔙 Back","menu_main")])
    m = types.InlineKeyboardMarkup()
    for r in rows:
        m.row(*[types.InlineKeyboardButton(t, callback_data=d) for t,d in r])
    return m

def bot_manage_kb(tk):
    return mk(
        [("✏️ Rename","bot_rename:"+tk),    ("🗑️ Delete","bot_delete:"+tk)],
        [("👥 Users","bot_users:"+tk),      ("📊 Stats","bot_stats:"+tk)],
        [("📢 Broadcast","bot_bc:"+tk)],
        [("✉️ Welcome Msg","bot_welcome:"+tk),("📋 Result Msg","bot_result:"+tk)],
        [("👁️ View Msgs","bot_viewmsgs:"+tk)],
        [("🔙 Bot List","bot_list")],
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🛠️  HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def ssend(bot, cid, text, kb=None):
    try: return bot.send_message(cid, text, parse_mode='HTML', reply_markup=kb)
    except: return None

def sedit(bot, text, cid, mid, kb=None):
    try: bot.edit_message_text(text, cid, mid, parse_mode='HTML', reply_markup=kb)
    except: pass

def aok(bot, call, text=None):
    try: bot.answer_callback_query(call.id, text)
    except: pass

def anim(bot, cid, title, steps=3):
    """Send animated loader, return msg"""
    m = ssend(bot, cid, f"{box(title)}\n\n<code>{bar(0)}</code>\n{SP[0]} Loading...")
    for i in range(1, steps+1):
        time.sleep(0.3)
        pct = int(i*100//(steps+1))
        sedit(bot, f"{box(title)}\n\n<code>{bar(pct)}</code>\n{SP[i%8]} Loading...", cid, m.message_id if m else 0)
    return m

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔍  FIREBASE CHECKER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def firebase_check(bot, cid, base_url):
    started_at = time.time()
    m = ssend(bot, cid, simple_loading_text("Checking Firebase...", started_at, 0))
    if not m: return

    for i, txt in enumerate(["Checking connection...", "Checking /.json...", "Checking /all_pas.json..."], start=1):
        time.sleep(0.35)
        sedit(bot, simple_loading_text(txt, started_at, i), cid, m.message_id)

    u1, d1 = check_fb(base_url, "/.json")
    u2, d2 = check_fb(base_url, "/all_pas.json")

    time.sleep(0.3)
    sedit(bot, simple_loading_text("Building result...", started_at, 4), cid, m.message_id)
    time.sleep(0.25)

    def fmt(num, param, url, data):
        exposed = bool(data)
        s = "✅ <b>EXPOSED</b>" if exposed else "🔒 <b>PROTECTED</b>"
        lines = [f"<b>◈ Parameter {num}:</b>", f"{s} → <code>{param}</code>", f"🔗 <code>{url}</code>"]
        if exposed: lines.append(f"📄 <pre>{str(data).strip()[:350]}</pre>")
        return "\n".join(lines)

    result = (
        f"<b>{BRAND_NAME}</b>\n\n"
        f"<b>Firebase URL:</b> <code>{base_url}</code>\n\n"
        f"{fmt(1,'/.json',u1,d1)}\n\n"
        f"{fmt(2,'/all_pas.json',u2,d2)}"
    )
    sedit(bot, result, cid, m.message_id)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📦  APK SCAN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def do_scan(bot, m, token, is_main):
    if not m.document.file_name.lower().endswith('.apk'): return

    fname = m.document.file_name
    path  = os.path.join(APK_DIR, f'scan_{m.chat.id}_{int(time.time())}.apk')

    started_at = time.time()
    st = bot.reply_to(m, simple_loading_text("Checking APK...", started_at, 0), parse_mode='HTML')
    status = {'step': "Checking APK...", 'frame': 0}
    stop_loader = threading.Event()

    def show(step):
        status['step'] = step

    def loader_worker():
        while not stop_loader.is_set():
            sedit(bot, simple_loading_text(status['step'], started_at, status['frame']), m.chat.id, st.message_id)
            status['frame'] += 1
            stop_loader.wait(1)

    threading.Thread(target=loader_worker, daemon=True).start()

    try:
        for step in [
            "Checking APK...",
            "Downloading APK...",
            "Extracting data...",
        ]:
            time.sleep(0.35)
            show(step)

        fi = bot.get_file(m.document.file_id)
        with open(path,'wb') as f: f.write(bot.download_file(fi.file_path))

        for step in [
            "Reading strings...",
            "Scanning Firebase config...",
            "Building output...",
        ]:
            time.sleep(0.35)
            show(step)

        data  = scan_apk(path)
        fmd5  = get_md5(path)
        fsize = round(os.path.getsize(path)/(1024*1024),2)

        report = simple_result_text(fname, fsize, fmd5, data)
        stop_loader.set()
        sedit(bot, report, m.chat.id, st.message_id)

    except Exception as e:
        stop_loader.set()
        sedit(bot, f"❌ <b>Scan Error:</b>\n<code>{e}</code>", m.chat.id, st.message_id)
        traceback.print_exc()
    finally:
        stop_loader.set()
        try:
            if os.path.exists(path): os.remove(path)
        except: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📨  STATE INPUT PROCESSOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def handle_state(bot, m, token, is_main):
    uid = m.from_user.id
    st  = get_state(uid)
    if not st: return False
    clear_state(uid)
    act  = st['action']
    data = st['data']
    cid  = m.chat.id

    # ─── BROADCAST TEXT
    if act == 'bc_text':
        if not m.text: ssend(bot, cid, "❌ Please send text only."); return True
        targets = data['targets']
        ssend(bot, cid, f"{box('🚀 BROADCAST STARTED')}\n\n📊 Sending to <b>{len(targets)}</b> users...", kb=back())
        threading.Thread(target=do_bc_text, args=(bot, m.text, uid, targets), daemon=True).start()
        log_act(uid, f"bc_text → {len(targets)} users")
        return True

    # ─── BROADCAST MEDIA
    if act == 'bc_media':
        targets = data['targets']
        ssend(bot, cid, f"{box('🚀 MEDIA BC STARTED')}\n\n📊 Forwarding to <b>{len(targets)}</b> users...", kb=back())
        threading.Thread(target=do_bc_media, args=(bot, m.chat.id, m.message_id, uid, targets), daemon=True).start()
        log_act(uid, f"bc_media → {len(targets)} users")
        return True

    # ─── FIREBASE CHECK
    if act == 'fb_check':
        url = (m.text or '').strip()
        if not url or not url.startswith('http'): ssend(bot, cid, "❌ Invalid URL. Must start with http"); return True
        threading.Thread(target=firebase_check, args=(bot, cid, url), daemon=True).start()
        return True

    # ─── ADD BOT
    if act == 'add_bot':
        tok2 = (m.text or '').strip()
        if ':' not in tok2 or len(tok2) < 20:
            ssend(bot, cid, "❌ Invalid token format.\nFormat: <code>123456:ABC-DEF...</code>"); return True
        G['bots'][tok2] = {'name':'New Bot','owner':uid,'admins':[],'scans':0,'users':[]}
        save_db()
        log_act(uid, f"added bot {tok2[:15]}")
        ssend(bot, cid, f"{box('✅ BOT ADDED')}\n\n🤖 Token: <code>{tok2[:20]}...</code>\n\n⚡ Starting thread...", kb=back("bot_list"))
        threading.Thread(target=run_bot, args=(tok2, uid, False), daemon=True).start()
        return True

    # ─── BOT RENAME
    if act == 'bot_rename':
        tk  = data['tk']
        ftk = find_tok(tk)
        if ftk:
            binfo(ftk)['name'] = (m.text or 'Bot').strip()
            save_db()
            ssend(bot, cid, f"✅ <b>Bot renamed to:</b> {m.text.strip()}", kb=back("bot_manage:"+tk))
        return True

    # ─── BOT ADD ADMIN
    if act == 'bot_addadmin':
        ssend(bot, cid, "Only one admin is allowed.")
        return True

    # ─── BOT DEL ADMIN
    if act == 'bot_deladmin':
        ssend(bot, cid, "Only one admin is allowed.")
        return True

    # ─── BOT BROADCAST TEXT
    if act == 'bot_bc_text':
        tk  = data['tk']
        ftk = find_tok(tk)
        if ftk and m.text:
            targets = binfo(ftk).get('users',[])
            ssend(bot, cid, f"{box('🚀 BOT BC STARTED')}\n\n📊 Sending to <b>{len(targets)}</b> users...", kb=back("bot_manage:"+tk))
            threading.Thread(target=do_bc_text, args=(bot, m.text, uid, targets), daemon=True).start()
        return True

    # ─── BOT BROADCAST MEDIA
    if act == 'bot_bc_media':
        tk  = data['tk']
        ftk = find_tok(tk)
        if ftk:
            targets = binfo(ftk).get('users',[])
            ssend(bot, cid, f"{box('🚀 BOT MEDIA BC')}\n\n📊 Forwarding to <b>{len(targets)}</b> users...", kb=back("bot_manage:"+tk))
            threading.Thread(target=do_bc_media, args=(bot, m.chat.id, m.message_id, uid, targets), daemon=True).start()
        return True

    # ─── SET WELCOME
    if act == 'set_welcome':
        tk  = data['tk']
        ftk = find_tok(tk)
        if ftk and m.text:
            set_msg(ftk, 'welcome', m.text)
            ssend(bot, cid, f"✅ <b>Welcome message updated!</b>", kb=back("bot_manage:"+tk))
        return True

    # ─── SET RESULT HEADER
    if act == 'set_result':
        tk  = data['tk']
        ftk = find_tok(tk)
        if ftk and m.text:
            set_msg(ftk, 'result_hdr', m.text)
            ssend(bot, cid, f"✅ <b>Result header updated!</b>", kb=back("bot_manage:"+tk))
        return True

    # ─── BAN
    if act == 'ban_user':
        try:
            t = int((m.text or '').strip())
            G['banned'].add(t); save_db()
            log_act(uid, f"banned {t}")
            ssend(bot, cid, f"{box('🚫 USER BANNED')}\n\n◈ ID: <code>{t}</code>", kb=back())
        except: ssend(bot, cid, "❌ Invalid ID")
        return True

    # ─── UNBAN
    if act == 'unban_user':
        try:
            t = int((m.text or '').strip())
            G['banned'].discard(t); save_db()
            log_act(uid, f"unbanned {t}")
            ssend(bot, cid, f"{box('✅ USER UNBANNED')}\n\n◈ ID: <code>{t}</code>", kb=back())
        except: ssend(bot, cid, "❌ Invalid ID")
        return True

    # ─── SEARCH
    if act == 'search_user':
        try:
            t     = int((m.text or '').strip())
            in_mb = t in G['users']
            bnnd  = t in G['banned']
            bots_ = [binfo(tk2).get('name','?') for tk2 in G['bots'] if t in binfo(tk2).get('users',[])]
            scans_ = len(G['history'].get(str(t),[]))
            ssend(bot, cid,
                f"{box('🔍 USER SEARCH')}\n\n"
                f"{R('User ID', t,'🆔')}\n"
                f"{R('In Main Bot','✅ Yes' if in_mb else '❌ No','📌')}\n"
                f"{R('Banned','🚫 Yes' if bnnd else '🟢 No','⚠️')}\n"
                f"{R('Scans',scans_,'🔍')}\n"
                f"{R('In Sub-Bots',', '.join(bots_) or 'None','🤖')}",
                kb=back())
        except: ssend(bot, cid, "❌ Invalid ID")
        return True

    # ─── SCHEDULE BC
    if act == 'sched_bc':
        try:
            p = (m.text or '').split('|',1)
            t2 = p[0].strip(); msg2 = p[1].strip()
            datetime.strptime(t2, '%Y-%m-%d %H:%M')
            G['scheduled'].append({'time':t2,'text':msg2}); save_db()
            ssend(bot, cid, f"📅 <b>Scheduled for {t2}</b>", kb=back())
        except Exception as e:
            ssend(bot, cid, f"❌ Format: YYYY-MM-DD HH:MM | message\n{e}")
        return True

    return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🤖  BOT ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_bot(token, owner_id, is_main=False):
    retries = 0
    while True:
        try:
            bot = telebot.TeleBot(token, threaded=True, num_threads=40, skip_pending=True)
            retries = 0
            print(f"[{'MAIN' if is_main else 'SUB '}] online: {token[:20]}...")

            # ─── /start ─────────────────────────────────────────
            @bot.message_handler(commands=['start','panel'])
            def on_start(m):
                clear_state(m.from_user.id)
                panel = (
                    f"<b>{BRAND_NAME}</b>\n\n"
                    f"Send APK and process it.\n"
                    f"I will check it and return the output."
                )
                ssend(bot, m.chat.id, panel)

            # ─── /firebase ──────────────────────────────────────
            @bot.message_handler(commands=['firebase'])
            def on_firebase(m):
                parts = m.text.split(maxsplit=1)
                if len(parts) < 2:
                    set_state(m.from_user.id, 'fb_check')
                    ssend(bot, m.chat.id,
                        "Send Firebase DB URL:\n<code>https://yourapp.firebaseio.com</code>",
                        kb=mk([("❌ Cancel","cancel")]))
                    return
                threading.Thread(target=firebase_check, args=(bot, m.chat.id, parts[1].strip()), daemon=True).start()

            # ─── CALLBACK ───────────────────────────────────────
            @bot.callback_query_handler(func=lambda c: True)
            def on_cb(call):
                try: _cb(bot, call, token, is_main)
                except Exception as e:
                    print(f"[CB] {e}"); traceback.print_exc()
                    try: bot.answer_callback_query(call.id, "❌ Error")
                    except: pass

            # ─── MESSAGE (state router + APK) ───────────────────
            @bot.message_handler(content_types=['text','document','photo','video','audio','voice','sticker','animation'])
            def on_msg(m):
                uid = m.from_user.id
                # APK?
                if m.content_type == 'document' and m.document.file_name.lower().endswith('.apk'):
                    threading.Thread(target=do_scan, args=(bot, m, token, is_main), daemon=True).start()
                    return
                # State?
                if handle_state(bot, m, token, is_main): return
                # Media without state → maybe bc_media state
                if m.content_type in ('photo','video','audio','voice','sticker','animation','document'):
                    ssend(bot, m.chat.id, "Send an APK file.")
                    return

            if is_main:
                threading.Thread(target=sched_worker, args=(bot,), daemon=True).start()

            bot.polling(non_stop=True, timeout=60, long_polling_timeout=60, interval=0)

        except Exception as e:
            wait = min(60, 5*(retries+1))
            print(f"[CRASH {token[:15]}] {e} — retry in {wait}s")
            time.sleep(wait); retries += 1

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔄  CALLBACK DISPATCHER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _cb(bot, call, token, is_main):
    uid  = call.from_user.id
    d    = call.data
    cid  = call.message.chat.id
    mid  = call.message.message_id
    ow   = uid == (int(ADMIN) if str(ADMIN).strip() else 0)
    adm  = is_adm(uid, token)

    def ok(t=None): aok(bot, call, t)
    def send(text, kb=None): ssend(bot, cid, text, kb=kb)
    def edit(text, kb=None): sedit(bot, text, cid, mid, kb=kb)

    # ── cancel / clear state
    if d == "cancel":
        ok(); clear_state(uid)
        edit(f"{box('❌ CANCELLED')}\n\nAction cancelled.", kb=back())
        return

    # ── main menu
    if d == "menu_main":
        ok(); clear_state(uid)
        edit(f"<b>{BRAND_NAME}</b>\n\nSend APK and process it.\nI will check it and return the output.")
        return

    # ── stats
    if d == "stats":
        ok()
        m2 = send(f"{box('📊 LOADING STATS')}\n\n<code>{bar(0)}</code>\n⣾ Fetching...")
        time.sleep(0.5)
        if ow:
            bd = "".join(f"  ◈ {binfo(t).get('name','Bot')}: {binfo(t).get('scans',0)} scans | {len(binfo(t).get('users',[]))} users\n" for t in list(G['bots'])[:8])
            text = (f"{box('📊 GLOBAL STATS')}\n\n"
                    f"{R('Total Users',len(G['users']),'👥')}\n"
                    f"{R('Total Scans',G['scans'],'🔍')}\n"
                    f"{R('Sub-Bots',len(G['bots']),'🤖')}\n"
                    f"{R('Banned',len(G['banned']),'🚫')}\n"
                    f"{R('Maintenance','🔴 ON' if G['maint'] else '🟢 OFF','⚙️')}\n"
                    f"{L1}\n<b>Sub-Bot Breakdown:</b>\n{bd or '  ◈ None'}")
        else:
            bi = binfo(token)
            bi = binfo(token)
            text = (f"{box('📊 BOT STATS')}\n\n"
                    f"{R('Bot',bi.get('name','Bot'),'🤖')}\n"
                    f"{R('Users',len(bi.get('users',[])),'👥')}\n"
                    f"{R('Scans',bi.get('scans',0),'🔍')}\n"
                    f"{R('Admins',len(bi.get('admins',[])),'👮')}")
        return

    # ── uptime
    if d == "uptime":
        ok()
        upt = str(datetime.now()-START_TIME).split('.')[0]
        hrs = int(upt.split(':')[0]) if ':' in upt else 0
        send(f"{box('⏳ SYSTEM UPTIME')}\n\n{R('Uptime',upt,'⏱️')}\n{R('Hours Running',hrs,'🕐')}\n{R('Status','🟢 Online','📡')}", kb=back())
        return

    # ── users
    if d == "users":
        ok()
        if is_main and ow:
            us = list(G['users']); title = f"All Users ({len(us)})"
        else:
            us = binfo(token).get('users',[]); title = f"{binfo(token).get('name','Bot')} Users ({len(us)})"
        text = f"{box(title)}\n\n" + ("\n".join(f"◈ <code>{u}</code>" for u in us[:50]) or "◈ None")
        if len(us)>50: text += f"\n... +{len(us)-50} more"
        send(text, kb=back())
        return

    # ── scan history
    if d == "scan_hist":
        ok()
        rows = []
        for us_, hist in list(G['history'].items())[-15:]:
            for h in hist[-2:]: rows.append(f"◈ <code>{us_}</code> | {h.get('t','')} | {h.get('f','')}")
        send(f"{box('📜 SCAN HISTORY')}\n\n" + ("\n".join(rows[-20:]) or "◈ No scans yet"), kb=back())
        return

    # ── admin log
    if d == "adm_log" and ow:
        ok()
        last = G['log'][-15:]
        text = f"{box('📋 ADMIN LOG')}\n\n" + ("\n".join(f"[{e['t']}] <code>{e['u']}</code>: {e['a']}" for e in reversed(last)) or "◈ Empty")
        send(text, kb=back())
        return

    # ── top scanners
    if d == "top_scan" and ow:
        ok()
        top  = sorted(G['history'].items(), key=lambda x:len(x[1]), reverse=True)[:10]
        meds = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        text = f"{box('📈 TOP SCANNERS')}\n\n" + ("\n".join(f"{meds[i]} <code>{u}</code> — <b>{len(h)}</b> scans" for i,(u,h) in enumerate(top)) or "◈ No data")
        send(text, kb=back())
        return

    # ── system info
    if d == "sys_info" and ow:
        ok()
        try:
            cpu = subprocess.check_output('cat /proc/loadavg', shell=True).decode().split()[0]
            mem_raw = subprocess.check_output('free -m', shell=True).decode().split()
            mem = f"{mem_raw[15]}/{mem_raw[7]} MB"
        except: cpu = mem = "N/A"
        send(f"{box('ℹ️ SYSTEM INFO')}\n\n{R('CPU Load',cpu,'⚙️')}\n{R('Memory',mem,'💾')}\n{R('Python',sys.version.split()[0],'🐍')}\n{R('DB Size','Disabled','📂')}", kb=back())
        return

    # ── maintenance
    if d == "toggle_maint" and ow:
        ok()
        G['maint'] = not G['maint']; save_db()
        log_act(uid, f"maint {'ON' if G['maint'] else 'OFF'}")
        send(f"{box('⚙️ MAINTENANCE')}\n\n🔧 Mode: <b>{'🔴 ON — Bot paused' if G['maint'] else '🟢 OFF — Bot active'}</b>", kb=back())
        return

    # ── banned list
    if d == "ban_list" and ow:
        ok()
        text = f"{box('🚫 BANNED USERS')}\n\n" + ("\n".join(f"◈ <code>{u}</code>" for u in list(G['banned'])[:50]) or "◈ None")
        send(text, kb=back())
        return

    # ── ban/unban
    if d == "ban_u" and adm:
        ok(); set_state(uid, 'ban_user')
        send(f"{box('🚫 BAN USER')}\n\nSend the Telegram user ID to ban:", kb=mk([("❌ Cancel","cancel")]))
        return

    if d == "unban_u" and adm:
        ok(); set_state(uid, 'unban_user')
        send(f"{box('✅ UNBAN USER')}\n\nSend the Telegram user ID to unban:", kb=mk([("❌ Cancel","cancel")]))
        return

    # ── search user
    if d == "search_user" and ow:
        ok(); set_state(uid, 'search_user')
        send(f"{box('🔍 SEARCH USER')}\n\nEnter user Telegram ID:", kb=mk([("❌ Cancel","cancel")]))
        return

    # ── export
    if d == "export" and ow:
        ok()
        try:
            with open(os.path.abspath(__file__),'rb') as f:
                bot.send_document(cid, f, caption=f"<b>{BRAND_NAME}</b> script", parse_mode='HTML')
            log_act(uid, "exported script")
        except Exception as e: send(f"❌ {e}")
        return

    # ── force save
    if d == "force_save" and ow:
        save_db(); ok("Saved ✅")
        return

    # ── clear rate limits
    if d == "clear_rl" and ow:
        G['rate'].clear(); save_db(); ok("Cleared ✅")
        return

    # ── restart
    if d == "restart" and uid == (int(ADMIN) if str(ADMIN).strip() else 0):
        ok("Restarting..."); send("🔄 Restarting..."); save_db()
        os.execv(sys.executable, [sys.executable]+sys.argv)

    # ── firebase check
    if d == "fb_check":
        ok(); set_state(uid, 'fb_check')
        send(f"{box('🌐 FIREBASE CHECKER')}\n\nSend Firebase DB URL:\n<code>https://yourapp.firebaseio.com</code>", kb=mk([("❌ Cancel","cancel")]))
        return

    if d.startswith("check_fb:"):
        ok()
        url = d.split(":",1)[1]
        threading.Thread(target=firebase_check, args=(bot, cid, url), daemon=True).start()
        return

    # ── broadcast menu
    if d == "bc_menu" and adm:
        ok()
        all_u = set(G['users'])
        for t2 in G['bots']: all_u.update(binfo(t2).get('users',[]))
        edit(f"{box('📢 BROADCAST')}\n\n📊 Main bot users: <b>{len(G['users'])}</b>\n📊 All users total: <b>{len(all_u)}</b>\n\nChoose type:", kb=bc_kb())
        return

    if d == "bc_text" and adm:
        ok()
        targets = list(G['users']) if (is_main or ow) else binfo(token).get('users',[])
        set_state(uid, 'bc_text', targets=targets)
        send(f"{box('📝 TEXT BROADCAST')}\n\n📊 Targets: <b>{len(targets)}</b> users\n\n✍️ Send your text message now:\n<i>HTML supported</i>", kb=mk([("❌ Cancel","cancel")]))
        return

    if d == "bc_media" and adm:
        ok()
        targets = list(G['users']) if (is_main or ow) else binfo(token).get('users',[])
        set_state(uid, 'bc_media', targets=targets)
        send(f"{box('🖼️ MEDIA BROADCAST')}\n\n📊 Targets: <b>{len(targets)}</b> users\n\n📎 Send image/video/file/GIF now:", kb=mk([("❌ Cancel","cancel")]))
        return

    if d == "all_bot_bc" and ow:
        ok()
        all_u = set(G['users'])
        for t2 in G['bots']: all_u.update(binfo(t2).get('users',[]))
        all_list = list(all_u)
        edit(f"{box('📣 ALL-BOT BROADCAST')}\n\n📊 Total targets: <b>{len(all_list)}</b> users\n\nChoose broadcast type:",
            kb=mk(
                [("📝 Text","allbc_text")],
                [("🖼️ Media (img/video/file)","allbc_media")],
                [("❌ Cancel","cancel")]
            ))
        return

    if d == "allbc_text" and ow:
        ok()
        all_u = set(G['users'])
        for t2 in G['bots']: all_u.update(binfo(t2).get('users',[]))
        set_state(uid, 'bc_text', targets=list(all_u))
        send(f"{box('📝 ALL-BOT TEXT BC')}\n\n📊 Targets: <b>{len(all_u)}</b> users\n\n✍️ Send your message:", kb=mk([("❌ Cancel","cancel")]))
        return

    if d == "allbc_media" and ow:
        ok()
        all_u = set(G['users'])
        for t2 in G['bots']: all_u.update(binfo(t2).get('users',[]))
        set_state(uid, 'bc_media', targets=list(all_u))
        send(f"{box('🖼️ ALL-BOT MEDIA BC')}\n\n📊 Targets: <b>{len(all_u)}</b> users\n\n📎 Send image/video/file/GIF:", kb=mk([("❌ Cancel","cancel")]))
        return

    # ── schedule bc
    if d == "sched_bc" and ow:
        ok(); set_state(uid, 'sched_bc')
        send(f"{box('📅 SCHEDULE BC')}\n\nFormat:\n<code>YYYY-MM-DD HH:MM | message</code>\n\nExample:\n<code>2025-12-25 10:00 | Merry Christmas!</code>", kb=mk([("❌ Cancel","cancel")]))
        return

    # ── bot list
    if d == "bot_list" and ow:
        ok()
        cnt = len(G['bots'])
        edit(f"{box(f'🤖 BOT LIST ({cnt})')}\n\nClick any bot to manage:", kb=bot_list_kb())
        return

    # ── add bot
    if d == "bot_add" and ow:
        ok(); set_state(uid, 'add_bot')
        send(f"{box('🤖 ADD NEW BOT')}\n\nEnter bot token from @BotFather:\n<code>123456789:ABC-DEF...</code>", kb=mk([("❌ Cancel","cancel"),("🔙 Back","bot_list")]))
        return

    # ── open/manage bot
    if d.startswith("bot_open:") and ow:
        ok()
        tk  = d.split(":",1)[1]
        ftk = find_tok(tk)
        if not ftk: send("❌ Bot not found"); return
        bi  = binfo(ftk)
        adm_list = bi.get('admins',[])
        panel = (
            f"{box('🤖 BOT CONTROL PANEL')}\n\n"
            f"📛 <b>Name:</b> {bi.get('name','Bot')}\n"
            f"🔑 <b>Token:</b> <code>{ftk[:22]}...</code>\n"
            f"{L1}\n"
            f"{R('Users',len(bi.get('users',[])))}\n"
            f"{R('Scans',bi.get('scans',0))}\n"
            f"{R('Admins',len(adm_list),'👮')}\n"
            + ("\n".join(f"  ◈ <code>{a}</code>" for a in adm_list[:5]) or "  ◈ None")
            + f"\n{L1}\n"
            f"✉️ Welcome: {'✅ Custom' if get_msg(ftk,'welcome') else '📄 Default'} | "
            f"📋 Result: {'✅ Custom' if get_msg(ftk,'result_hdr') else '📄 Default'}\n"
            f"{L1}\n👇 Select action:"
        )
        send(panel, kb=bot_manage_kb(tk))
        return

    # also handle bot_manage: for backward compat
    if d.startswith("bot_manage:") and ow:
        call.data = "bot_open:" + d.split(":",1)[1]
        _cb(bot, call, token, is_main); return

    # ── bot rename
    if d.startswith("bot_rename:") and ow:
        ok(); tk = d.split(":",1)[1]
        set_state(uid, 'bot_rename', tk=tk)
        send(f"{box('✏️ RENAME BOT')}\n\nEnter new name:", kb=mk([("❌ Cancel","cancel"),("🔙 Back","bot_open:"+tk)]))
        return

    # ── bot delete
    if d.startswith("bot_delete:") and ow:
        ok(); tk = d.split(":",1)[1]
        ftk = find_tok(tk)
        if ftk:
            del G['bots'][ftk]; G['messages'].pop(ftk,None); save_db()
            log_act(uid, f"deleted bot {ftk[:15]}")
            send(f"🗑️ <b>Bot deleted.</b>", kb=back("bot_list"))
        return

    # ── bot admins view
    if d.startswith("bot_admins:") and ow:
        ok(); tk = d.split(":",1)[1]; ftk = find_tok(tk)
        adm_list = binfo(ftk).get('admins',[]) if ftk else []
        send(f"{box('👤 BOT ADMINS')}\n\n" + ("\n".join(f"◈ <code>{a}</code>" for a in adm_list) or "◈ None"), kb=back("bot_open:"+tk))
        return

    # ── bot add admin
    if d.startswith("bot_addadmin:") and ow:
        ok("Only one admin is allowed.")
        return

    # ── bot del admin
    if d.startswith("bot_deladmin:") and ow:
        ok("Only one admin is allowed.")
        return

    # ── bot stats
    if d.startswith("bot_stats:") and ow:
        ok(); tk = d.split(":",1)[1]; ftk = find_tok(tk)
        bi = binfo(ftk) if ftk else {}
        send(f"{box('📊 BOT STATS')}\n\n{R('Name',bi.get('name','Bot'))}\n{R('Scans',bi.get('scans',0))}\n{R('Users',len(bi.get('users',[])))}\n{R('Admins',len(bi.get('admins',[])))}", kb=back("bot_open:"+tk))
        return

    # ── bot users
    if d.startswith("bot_users:") and ow:
        ok(); tk = d.split(":",1)[1]; ftk = find_tok(tk)
        us = binfo(ftk).get('users',[]) if ftk else []
        text = f"{box(f'BOT USERS ({len(us)})')}\n\n" + ("\n".join(f"◈ <code>{u}</code>" for u in us[:50]) or "◈ None")
        if len(us)>50: text += f"\n...+{len(us)-50}"
        send(text, kb=back("bot_open:"+tk))
        return

    # ── bot broadcast
    if d.startswith("bot_bc:") and ow:
        ok(); tk = d.split(":",1)[1]; ftk = find_tok(tk)
        bi = binfo(ftk) if ftk else {}
        targets = bi.get('users',[])
        set_state(uid, 'bot_bc_text', tk=tk)
        send(
            f"{box('📢 BOT BROADCAST')}\n\n"
            f"Bot: <b>{bi.get('name','Bot')}</b>\n"
            f"📊 Targets: <b>{len(targets)}</b> users\n\n"
            f"Send text or media to broadcast:",
            kb=mk([("📝 Text","bot_bc_text:"+tk),("🖼️ Media","bot_bc_media:"+tk),("❌ Cancel","cancel")]))
        return

    if d.startswith("bot_bc_text:") and ow:
        ok(); tk = d.split(":",1)[1]
        set_state(uid, 'bot_bc_text', tk=tk)
        send(f"{box('📝 BOT TEXT BC')}\n\nSend text to broadcast to this bot's users:", kb=mk([("❌ Cancel","cancel")]))
        return

    if d.startswith("bot_bc_media:") and ow:
        ok(); tk = d.split(":",1)[1]
        set_state(uid, 'bot_bc_media', tk=tk)
        send(f"{box('🖼️ BOT MEDIA BC')}\n\nSend image/video/file to broadcast:", kb=mk([("❌ Cancel","cancel")]))
        return

    # ── set welcome
    if d.startswith("bot_welcome:") and ow:
        ok(); tk = d.split(":",1)[1]; ftk = find_tok(tk)
        cur = get_msg(ftk,'welcome','(default)') if ftk else '(default)'
        set_state(uid, 'set_welcome', tk=tk)
        send(f"{box('✉️ WELCOME MESSAGE')}\n\nCurrent:\n<i>{str(cur)[:150]}</i>\n\nSend new welcome message:", kb=mk([("❌ Cancel","cancel"),("🔙 Back","bot_open:"+tk)]))
        return

    # ── set result header
    if d.startswith("bot_result:") and ow:
        ok(); tk = d.split(":",1)[1]; ftk = find_tok(tk)
        cur = get_msg(ftk,'result_hdr','(default)') if ftk else '(default)'
        set_state(uid, 'set_result', tk=tk)
        send(f"{box('📋 RESULT HEADER')}\n\nCurrent:\n<i>{str(cur)[:150]}</i>\n\nSend new result header:", kb=mk([("❌ Cancel","cancel"),("🔙 Back","bot_open:"+tk)]))
        return

    # ── edit branding (from scan result button)
    if d.startswith("edit_brand:") and adm:
        ok()
        tk = d.split(":",1)[1]
        ftk = find_tok(tk) or token
        send(
            f"{box('✏️ EDIT BOT BRANDING')}\n\n"
            f"What do you want to edit?",
            kb=mk(
                [("✉️ Welcome Message","bot_welcome:"+tk)],
                [("📋 Result Header","bot_result:"+tk)],
                [("🔙 Back","cancel")]
            ))
        return

    # ── view msgs
    if d.startswith("bot_viewmsgs:") and ow:
        ok(); tk = d.split(":",1)[1]; ftk = find_tok(tk)
        msgs = G['messages'].get(ftk,{}) if ftk else {}
        send(f"{box('👁️ CUSTOM MESSAGES')}\n\n<b>Welcome:</b>\n{msgs.get('welcome','(default)')[:200]}\n\n<b>Result Header:</b>\n{msgs.get('result_hdr','(default)')[:200]}", kb=back("bot_open:"+tk))
        return

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📅  SCHEDULED BROADCAST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def sched_worker(bot):
    while True:
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M')
            for sb in list(G['scheduled']):
                if sb.get('time') == now:
                    threading.Thread(target=do_bc_text, args=(bot, sb['text'], int(ADMIN) if str(ADMIN).strip() else 0, list(G['users'])), daemon=True).start()
                    G['scheduled'].remove(sb); save_db()
        except: pass
        time.sleep(30)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🚀  LAUNCH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == '__main__':
    load_db()
    print(f"{BRAND_NAME} started")

    threading.Thread(target=run_bot, args=(BOT_TOKEN, int(ADMIN) if str(ADMIN).strip() else 0, True), daemon=True).start()
    for t, info in list(G['bots'].items()):
        owner = info.get('owner', int(ADMIN) if str(ADMIN).strip() else 0) if isinstance(info, dict) else int(ADMIN) if str(ADMIN).strip() else 0
        threading.Thread(target=run_bot, args=(t, owner, False), daemon=True).start()

    try:
        while True: time.sleep(10)
    except KeyboardInterrupt:
        print("\nBye!")
