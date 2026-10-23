#!/usr/bin/env python3
"""MMC Offline Clinic Desk — self-contained LAN clinic workflow app.

Python 3.11+ standard-library only. Run with start-mmc-server.ps1.
"""
from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import secrets
import sqlite3
import ssl
import time
import uuid
from datetime import date, datetime, timedelta
from email import policy
from email.parser import BytesParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

APP_DIR = Path(__file__).resolve().parent
try:
    SETTINGS = json.loads((APP_DIR / "settings.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    SETTINGS = {}

def setting(env: str, key: str, default: str) -> str:
    return os.environ.get(env, str(SETTINGS.get(key, default)))

def app_path(value: str) -> Path:
    candidate=Path(value)
    return candidate if candidate.is_absolute() else APP_DIR/candidate

DATA_DIR = app_path(setting("MMC_DATA_DIR", "data_dir", "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = app_path(setting("MMC_DB_PATH", "database_path", "data/clinic.db"))
ARCHIVE_DIR = Path(setting("MMC_ARCHIVE_DIR", "archive_dir", "F:\\lab test")) if setting("MMC_ARCHIVE_DIR", "archive_dir", "F:\\lab test").strip() else None
HOST = setting("MMC_HOST", "host", "0.0.0.0")
PORT = int(setting("MMC_PORT", "port", "8000"))
MAX_UPLOAD = int(SETTINGS.get("max_upload_mb", 30)) * 1024 * 1024
SESSION_HOURS = int(SETTINGS.get("session_hours", 12))
DEFAULT_PIN = setting("MMC_DEFAULT_PIN", "default_pin", "1122")
ADMIN_PIN = setting("MMC_ADMIN_PIN", "admin_pin", "3344")
TLS_CERT = setting("MMC_TLS_CERT", "tls_cert", "")
TLS_KEY = setting("MMC_TLS_KEY", "tls_key", "")

DEFAULT_DEPARTMENTS = [
    ("Doctors", "doctor"), ("Nursing", "nurse"), ("Secretariat", "secretary"),
    ("Echo lab 1", "lab"), ("Blood test lab 1", "lab"), ("TMT lab 1", "lab"),
    ("Radiology", "lab"), ("Sonar", "lab"), ("Sleep room", "lab"), ("Pharmacy", "pharmacy"),
    ("Accounting", "accountant"), ("Human resources", "hr"), ("IT administration", "admin"),
]
DEFAULT_USERS = [
    ("D.Shwan", "doctor", "Doctors"), ("Payam", "secretary", "Secretariat"),
    ("Resident doctor", "resident", "Doctors"), ("Sakar", "head_secretary", "Secretariat"),
    ("Echo lab", "lab", "Echo lab 1"), ("Blood test lab", "lab", "Blood test lab 1"),
    ("TMT", "lab", "TMT lab 1"),
    ("Radiology", "lab", "Radiology"), ("Sonar", "lab", "Sonar"),
    ("Sleep room", "lab", "Sleep room"), ("Pharmacy", "pharmacy", "Pharmacy"),
    ("M.Ramazan", "accountant", "Accounting"), ("IT", "admin", "IT administration"),
    ("Kak Othman", "staff", "Human resources"),
]
TESTS = {
    "echo": ("Echo", "Echo lab 1"), "pft": ("PFT", "Echo lab 1"),
    "ecg": ("ECG", "Echo lab 1"), "holter": ("Holter", "Echo lab 1"),
    "tmt": ("TMT", "TMT lab 1"), "sleep": ("Sleep study", "Sleep room"),
    "blood": ("Blood test", "Blood test lab 1"), "pressure": ("Pressure monitoring", "Echo lab 1"),
    "sonar": ("Sonar", "Sonar"), "radiology": ("Radiology scan", "Radiology"),
}
LANG = {
    "en": {"patients": "Today’s patients", "all_patients": "All patients", "new_patient": "Register patient", "queue": "Doctor queues", "video": "Video call", "signout": "Sign out", "open": "Open", "patient": "Patient", "doctor": "Doctor", "department": "Department", "status": "Status", "save": "Save", "login": "Choose your name", "pin": "Enter PIN", "offline": "OFFLINE SYSTEM", "reports": "Reports", "tests": "Tests and reports"},
    "ar": {"patients": "مرضى اليوم", "all_patients": "جميع المرضى", "new_patient": "تسجيل مريض", "queue": "قوائم الأطباء", "video": "مكالمة فيديو", "signout": "تسجيل الخروج", "open": "فتح", "patient": "المريض", "doctor": "الطبيب", "department": "القسم", "status": "الحالة", "save": "حفظ", "login": "اختر اسمك", "pin": "أدخل الرقم السري", "offline": "النظام غير المتصل", "reports": "التقارير", "tests": "الفحوصات والتقارير"},
    "ku": {"patients": "نەخۆشانی ئەمڕۆ", "all_patients": "هەموو نەخۆشان", "new_patient": "تۆمارکردنی نەخۆش", "queue": "ڕیزی پزیشک", "video": "پەیوەندی ڤیدیۆیی", "signout": "چوونەدەرەوە", "open": "کردنەوە", "patient": "نەخۆش", "doctor": "پزیشک", "department": "بەش", "status": "دۆخ", "save": "پاشەکەوتکردن", "login": "ناوت هەڵبژێرە", "pin": "پینی ژمارەیی بنووسە", "offline": "سیستەمی ئۆفلاین", "reports": "ڕاپۆرتەکان", "tests": "تاقیکردنەوە و ڕاپۆرتەکان"},
}

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS departments(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, role TEXT NOT NULL, department_id INTEGER REFERENCES departments(id), doctor_id INTEGER REFERENCES users(id), pin_salt BLOB NOT NULL, pin_hash BLOB NOT NULL, active INTEGER NOT NULL DEFAULT 1, last_seen TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, csrf TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,patient_id INTEGER REFERENCES patients(id) ON DELETE CASCADE,order_id INTEGER REFERENCES lab_orders(id) ON DELETE CASCADE,message TEXT NOT NULL,created_at TEXT NOT NULL,read_at TEXT);
CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT NOT NULL, dob TEXT NOT NULL DEFAULT '', age INTEGER, phone TEXT NOT NULL DEFAULT '', sex TEXT NOT NULL DEFAULT '', doctor_id INTEGER REFERENCES users(id), registered_by INTEGER REFERENCES users(id), status TEXT NOT NULL DEFAULT 'waiting', queue_position INTEGER NOT NULL DEFAULT 100, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS encounters(id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, doctor_id INTEGER REFERENCES users(id), diagnosis TEXT NOT NULL DEFAULT '', clinical_notes TEXT NOT NULL DEFAULT '', plan TEXT NOT NULL DEFAULT '', created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS intake(id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, recorded_by INTEGER REFERENCES users(id), bp TEXT NOT NULL DEFAULT '', pulse TEXT NOT NULL DEFAULT '', temperature TEXT NOT NULL DEFAULT '', spo2 TEXT NOT NULL DEFAULT '', weight TEXT NOT NULL DEFAULT '', questions TEXT NOT NULL DEFAULT '{}', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lab_orders(id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, encounter_id INTEGER REFERENCES encounters(id), test_code TEXT NOT NULL, department_id INTEGER REFERENCES departments(id), details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ordered', queue_position INTEGER NOT NULL DEFAULT 100, ordered_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, completed_at TEXT);
CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES lab_orders(id) ON DELETE CASCADE, file_name TEXT NOT NULL, relative_path TEXT NOT NULL, content_type TEXT NOT NULL, uploaded_by INTEGER REFERENCES users(id), uploaded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prescriptions(id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, encounter_id INTEGER REFERENCES encounters(id), medicine_id INTEGER, medicine TEXT NOT NULL, dose TEXT NOT NULL DEFAULT '', quantity INTEGER NOT NULL DEFAULT 1, instructions TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ordered', prescribed_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, sold_at TEXT);
CREATE TABLE IF NOT EXISTS vendors(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS medicines(id INTEGER PRIMARY KEY AUTOINCREMENT, barcode TEXT NOT NULL DEFAULT '', name TEXT NOT NULL, batch_no TEXT NOT NULL DEFAULT '', expiry_date TEXT NOT NULL DEFAULT '', quantity INTEGER NOT NULL DEFAULT 0, buy_price REAL NOT NULL DEFAULT 0, sell_price REAL NOT NULL DEFAULT 0, vendor_id INTEGER REFERENCES vendors(id), updated_at TEXT NOT NULL, UNIQUE(barcode,batch_no));
CREATE TABLE IF NOT EXISTS purchase_invoices(id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER REFERENCES vendors(id), invoice_no TEXT NOT NULL DEFAULT '', total REAL NOT NULL DEFAULT 0, received_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS purchase_lines(id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL REFERENCES purchase_invoices(id) ON DELETE CASCADE, medicine_id INTEGER NOT NULL REFERENCES medicines(id), quantity INTEGER NOT NULL, unit_price REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pharmacy_sales(id INTEGER PRIMARY KEY AUTOINCREMENT, prescription_id INTEGER REFERENCES prescriptions(id), patient_id INTEGER REFERENCES patients(id), medicine_id INTEGER REFERENCES medicines(id), medicine TEXT NOT NULL, quantity INTEGER NOT NULL, amount REAL NOT NULL, sold_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER REFERENCES patients(id), service TEXT NOT NULL, amount REAL NOT NULL, note TEXT NOT NULL DEFAULT '', collected_by INTEGER REFERENCES users(id), handed_to INTEGER REFERENCES users(id), created_at TEXT NOT NULL, handover_id INTEGER);
CREATE TABLE IF NOT EXISTS cash_handovers(id INTEGER PRIMARY KEY AUTOINCREMENT, from_user INTEGER REFERENCES users(id), to_user INTEGER REFERENCES users(id), total REAL NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hr_records(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), record_type TEXT NOT NULL, note TEXT NOT NULL, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER REFERENCES users(id), receiver_id INTEGER REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT);
CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, caller_id INTEGER REFERENCES users(id), recipient_id INTEGER REFERENCES users(id), state TEXT NOT NULL DEFAULT 'ringing', offer TEXT NOT NULL DEFAULT '', answer TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS call_signals(id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE, sender_id INTEGER REFERENCES users(id), recipient_id INTEGER REFERENCES users(id), payload TEXT NOT NULL, created_at TEXT NOT NULL, received INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, entity TEXT NOT NULL DEFAULT '', entity_id INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_patients_today ON patients(created_at,doctor_id,status);
CREATE INDEX IF NOT EXISTS ix_patient_queue ON patients(doctor_id,status,queue_position,created_at);
CREATE INDEX IF NOT EXISTS ix_orders_dept_queue ON lab_orders(department_id,status,queue_position,created_at);
CREATE INDEX IF NOT EXISTS ix_orders_patient ON lab_orders(patient_id,created_at);
CREATE INDEX IF NOT EXISTS ix_results_order ON results(order_id,uploaded_at);
CREATE INDEX IF NOT EXISTS ix_messages_inbox ON messages(receiver_id,read_at,created_at);
CREATE INDEX IF NOT EXISTS ix_calls_inbox ON calls(recipient_id,state,updated_at);
CREATE INDEX IF NOT EXISTS ix_payments_day ON payments(created_at,collected_by,service);
"""


def stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    return c


def pin_digest(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 180_000)


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        for name, kind in DEFAULT_DEPARTMENTS:
            c.execute("INSERT OR IGNORE INTO departments(name,kind) VALUES(?,?)", (name, kind))
        # Hide the removed duplicate sign-in tiles on existing installations while
        # retaining the accounts and completed clinical history in the database.
        removed_users = ("Blood test lab 2", "Echo lab 2", "Nurse station", "TMT lab 2")
        marks = ",".join("?" for _ in removed_users)
        c.execute(f"UPDATE users SET active=0 WHERE name IN ({marks})", removed_users)
        c.execute(f"DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE name IN ({marks}))", removed_users)

        # Keep the existing TMT account and department, but shorten its display name.
        old_tmt_user = c.execute("SELECT id FROM users WHERE name='TMT lab 1'").fetchone()
        new_tmt_user = c.execute("SELECT id FROM users WHERE name='TMT'").fetchone()
        if old_tmt_user and not new_tmt_user:
            c.execute("UPDATE users SET name='TMT' WHERE id=?", (old_tmt_user["id"],))
        elif old_tmt_user and new_tmt_user:
            c.execute("UPDATE users SET active=0 WHERE id=?", (old_tmt_user["id"],))

        # Send any unfinished work from the retired second labs to the remaining lab.
        retired_labs = (("Echo lab 2", "Echo lab 1"), ("Blood test lab 2", "Blood test lab 1"), ("TMT lab 2", "TMT lab 1"))
        for retired_name, active_name in retired_labs:
            retired = c.execute("SELECT id FROM departments WHERE name=?", (retired_name,)).fetchone()
            active = c.execute("SELECT id FROM departments WHERE name=? AND active=1", (active_name,)).fetchone()
            if not retired:
                continue
            if active:
                c.execute("UPDATE lab_orders SET department_id=? WHERE department_id=? AND status!='completed'", (active["id"], retired["id"]))
            c.execute("UPDATE departments SET active=0 WHERE id=?", (retired["id"],))
        for name, role, dept in DEFAULT_USERS:
            if c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
                continue
            d = c.execute("SELECT id FROM departments WHERE name=?", (dept,)).fetchone()
            salt = secrets.token_bytes(16)
            pin = ADMIN_PIN if role == "admin" else DEFAULT_PIN
            c.execute("INSERT INTO users(name,role,department_id,pin_salt,pin_hash,created_at) VALUES(?,?,?,?,?,?)",
                      (name, role, d["id"] if d else None, salt, pin_digest(pin, salt), stamp()))
        c.commit()


def e(v: object) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def field(name: str, label: str, value: str = "", typ: str = "text", required: bool = False, **attrs: str) -> str:
    extra = "".join(f' {e(k)}="{e(v)}"' for k, v in attrs.items())
    req = " required" if required else ""
    return f'<label class="field"><span>{e(label)}</span><input name="{e(name)}" type="{e(typ)}" value="{e(value)}"{req}{extra}></label>'


def area(name: str, label: str, value: str = "", rows: int = 4) -> str:
    return f'<label class="field"><span>{e(label)}</span><textarea name="{e(name)}" rows="{rows}">{e(value)}</textarea></label>'


def btn(label: str, cls: str = "") -> str:
    return f'<button class="btn {e(cls)}" type="submit">{e(label)}</button>'


def form_csrf(user: sqlite3.Row) -> str:
    return f'<input type="hidden" name="_csrf" value="{e(user["csrf"])}">'


def page(user: sqlite3.Row | None, title: str, body: str, notice: str = "", lang: str = "en") -> bytes:
    tr = LANG.get(lang, LANG["en"])
    rtl = " dir=\"rtl\"" if lang == "ar" else ""
    nav = ""
    if user:
        links = [f'<a href="/patients">{tr["patients"]}</a>', f'<a href="/queue">{tr["queue"]}</a>',
                 f'<a href="/video">◉ {tr["video"]}</a>', '<a href="/chat">Chat</a>']
        with connect() as c:
            unread=c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL",(user["id"],)).fetchone()[0]
        links.append(f'<a href="/notifications">Notifications{f" ({unread})" if unread else ""}</a>')
        if user["role"] in ("secretary", "head_secretary"):
            links.insert(1, f'<a href="/patient/new">{tr["new_patient"]}</a>')
        if user["role"] == "lab": links.insert(1, '<a href="/lab">My lab</a>')
        if user["role"] == "pharmacy": links.insert(1, '<a href="/pharmacy">Pharmacy</a>')
        if user["role"] in ("accountant", "secretary", "head_secretary"): links.insert(1, '<a href="/accounting">Reports</a>')
        if user["role"] == "hr": links.insert(1, '<a href="/hr">HR</a>')
        if user["role"] == "admin": links.insert(1, '<a href="/admin">Administration</a>')
        nav = "".join(links)
    who = f'<span class="user-status"><i class="live-dot"></i>{e(user["name"])}<small>{e(user["role"].replace("_"," ").title())}</small></span>' if user else '<span class="offline-pill">● OFFLINE SYSTEM</span>'
    langs = '<form class="lang-switch" action="/language" method="post">'
    if user: langs += form_csrf(user)
    langs += ''.join(f'<button name="lang" value="{k}" type="submit" class="lang-button">{label}</button>' for k, label in [("en", "EN"), ("ar", "عربي"), ("ku", "کوردی")]) + '</form>'
    msg = f'<div class="notice">{e(notice)}</div>' if notice else ""
    csrf = e(user["csrf"]) if user else ""
    doc = f'''<!doctype html><html lang="{e(lang)}"{rtl}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · MMC Offline</title><link rel="stylesheet" href="/style.css"></head>
    <body><header class="topbar"><a class="brand" href="/"><span class="brand-mark">M</span><span>MMC <small>OFFLINE CLINIC</small></span></a><nav>{nav}</nav><div class="header-right">{langs}{who}{'<a class="sign-out" href="/logout">'+tr['signout']+'</a>' if user else ''}</div></header><main class="container" data-csrf="{csrf}" data-user-id="{user['id'] if user else ''}">{msg}{body}</main><footer>MMC · Mamostayan Medical Complex · Local clinic network</footer><script src="/app.js" defer></script></body></html>'''
    return doc.encode("utf-8")


def login_page() -> bytes:
    with connect() as c: users = c.execute("SELECT id,name,role FROM users WHERE active=1 ORDER BY name COLLATE NOCASE").fetchall()
    cards = "".join(f'<button class="user-card user-choice" type="button" data-id="{r["id"]}" data-name="{e(r["name"])}"><span class="user-icon">{e(r["name"][:1].upper())}</span><strong>{e(r["name"])}</strong></button>' for r in users)
    body = f'''<section class="user-grid">{cards}</section>
    <dialog class="pin-dialog" id="pin-dialog"><form method="post" action="/login" id="pin-form"><button class="dialog-close" type="button" id="pin-close" aria-label="Close">×</button><span class="user-icon" id="pin-icon"></span><h2 id="pin-name"></h2><p>Enter your four-digit PIN.</p><input class="pin-entry" id="pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{{4}}" maxlength="4" autocomplete="off" autofocus required><input id="pin-user-id" name="user_id" type="hidden"></form></dialog>
    <script>const dlg=document.querySelector('#pin-dialog'),pin=document.querySelector('#pin'),form=document.querySelector('#pin-form');document.querySelectorAll('.user-choice').forEach(b=>b.addEventListener('click',()=>{{document.querySelector('#pin-user-id').value=b.dataset.id;document.querySelector('#pin-name').textContent=b.dataset.name;document.querySelector('#pin-icon').textContent=b.dataset.name[0].toUpperCase();pin.value='';dlg.showModal();pin.focus()}}));pin.addEventListener('input',()=>{{if(pin.value.length===4&&/^\\d{{4}}$/.test(pin.value))form.requestSubmit()}});document.querySelector('#pin-close').onclick=()=>dlg.close();</script>'''
    return page(None, "Sign in", body)


def login_user(token: str | None) -> sqlite3.Row | None:
    if not token: return None
    with connect() as c:
        row = c.execute("SELECT s.token,s.csrf,s.created_at,u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND u.active=1", (token,)).fetchone()
        if not row: return None
        try: created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError: return None
        if datetime.now() - created > timedelta(hours=SESSION_HOURS):
            c.execute("DELETE FROM sessions WHERE token=?", (token,)); return None
        c.execute("UPDATE users SET last_seen=? WHERE id=?", (stamp(), row["id"]))
        return row


def has_role(u: sqlite3.Row, *roles: str) -> bool:
    return u["role"] == "admin" or u["role"] in roles


def audit(c: sqlite3.Connection, uid: int, action: str, entity: str = "", entity_id: int | None = None) -> None:
    c.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,created_at) VALUES(?,?,?,?,?)", (uid, action, entity, entity_id, stamp()))


def notify(c: sqlite3.Connection, uid: int | None, patient_id: int | None, message: str, order_id: int | None = None) -> None:
    if uid is not None:
        c.execute("INSERT INTO notifications(user_id,patient_id,order_id,message,created_at) VALUES(?,?,?,?,?)",(uid,patient_id,order_id,message[:500],stamp()))


def notice_html(text: str) -> str:
    return f'<div class="notice">{e(text)}</div>' if text else ""


def patient_rows(user: sqlite3.Row, all_patients: bool = False) -> str:
    with connect() as c:
        where, args = ("", []) if all_patients else ("WHERE date(p.created_at)=date('now','localtime')", [])
        rows = c.execute(f"SELECT p.*,u.name doctor FROM patients p LEFT JOIN users u ON u.id=p.doctor_id {where} ORDER BY p.created_at DESC LIMIT 250", args).fetchall()
    if not rows: return '<div class="empty-state"><span>◎</span><h3>No patients in this list</h3><p>New registrations will appear here for the clinic team.</p></div>'
    lines = "".join(f'<tr><td>{e(r["code"])}</td><td><a href="/patient?id={r["id"]}">{e(r["name"])}</a></td><td>{e(r["age"] if r["age"] is not None else "—")}</td><td>{e(r["phone"])}</td><td>{e(r["doctor"] or "—")}</td><td><span class="status {e(r["status"])}">{e(r["status"].replace("_"," ").title())}</span></td><td>{e(r["created_at"])}</td></tr>' for r in rows)
    return '<div class="table-scroll"><table><thead><tr><th>ID</th><th>Patient</th><th>Age</th><th>Phone</th><th>Doctor</th><th>Status</th><th>Registered</th></tr></thead><tbody>'+lines+'</tbody></table></div>'


def dashboard(u: sqlite3.Row) -> str:
    today = date.today().isoformat()
    with connect() as c:
        patients = c.execute("SELECT COUNT(*) n FROM patients WHERE date(created_at)=?", (today,)).fetchone()["n"]
        waiting = c.execute("SELECT COUNT(*) n FROM patients WHERE status IN ('waiting','nurse','doctor')").fetchone()["n"]
        results = c.execute("SELECT COUNT(*) n FROM results WHERE date(uploaded_at)=?", (today,)).fetchone()["n"]
        online = c.execute("SELECT name,role FROM users WHERE active=1 AND last_seen>=? ORDER BY name", ((datetime.now()-timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()
    roster = ''.join(f'<span class="online-chip"><i class="live-dot"></i>{e(r["name"])}</span>' for r in online) or '<span class="muted">No colleagues active right now.</span>'
    return f'''<section class="hero"><p class="kicker gold-text">{date.today().strftime('%A, %d %B %Y')} · {e(u['name'])}</p><h1>Mamostayan Medical Complex <span class="accent">Offline System</span></h1><p>Shared patient records, doctor queues, lab work and pharmacy on the local clinic network.</p><div class="hero-actions"><a class="btn gold" href="/patients">Open today’s patients</a><a class="btn outline" href="/video">◉ Video call</a></div></section>
    <section class="metric-grid"><article class="metric"><small>Patients registered today</small><strong>{patients}</strong><span>Clinic-wide</span></article><article class="metric"><small>Patients in workflow</small><strong>{waiting}</strong><span>Waiting, nurse room or doctor</span></article><article class="metric"><small>Reports uploaded today</small><strong>{results}</strong><span>Attached to patient records</span></article></section>
    <div class="split"><section class="panel"><div class="panel-heading"><div><p class="kicker">Shared record</p><h2>Today’s patients</h2></div><a href="/patients">See all →</a></div>{patient_rows(u)}</section><section class="panel"><p class="kicker">Local team</p><h2>Online colleagues</h2><p class="online-roster">{roster}</p><a class="btn outline" href="/video">Start a call</a></section></div>'''


def new_patient_form(u: sqlite3.Row) -> str:
    with connect() as c: doctors=c.execute("SELECT id,name FROM users WHERE role='doctor' AND active=1 ORDER BY name").fetchall()
    opts=''.join(f'<option value="{d["id"]}">{e(d["name"])}</option>' for d in doctors)
    return f'''<section class="page-title"><p class="kicker">Front desk</p><h1>Register a patient</h1><p class="muted">The patient receives a permanent MMC number and enters the selected doctor’s queue.</p></section><section class="panel"><form method="post" action="/patient/create" class="form-grid">{form_csrf(u)}{field('name','Patient full name',required=True)}{field('phone','Phone number')}{field('dob','Date of birth','', 'date')}{field('age','Age','', 'number',min='0',max='130')}<label class="field"><span>Sex</span><select name="sex"><option value="">Not recorded</option><option>Female</option><option>Male</option><option>Other</option></select></label><label class="field"><span>Assigned doctor</span><select name="doctor_id" required>{opts}</select></label><div class="full">{btn('Register and add to queue','gold')}</div></form></section>'''


def patient_profile(u: sqlite3.Row, pid: int) -> str:
    with connect() as c:
        p=c.execute("SELECT p.*,d.name doctor FROM patients p LEFT JOIN users d ON d.id=p.doctor_id WHERE p.id=?",(pid,)).fetchone()
        if not p: return '<section class="panel"><h1>Patient not found</h1></section>'
        orders=c.execute("SELECT o.*,d.name department FROM lab_orders o LEFT JOIN departments d ON d.id=o.department_id WHERE o.patient_id=? ORDER BY o.created_at DESC",(pid,)).fetchall()
        results=c.execute("SELECT r.*,o.patient_id,o.test_code FROM results r JOIN lab_orders o ON o.id=r.order_id WHERE o.patient_id=? ORDER BY r.uploaded_at DESC",(pid,)).fetchall()
        intakes=c.execute("SELECT i.*,u.name author FROM intake i LEFT JOIN users u ON u.id=i.recorded_by WHERE i.patient_id=? ORDER BY i.created_at DESC",(pid,)).fetchall()
        encounters=c.execute("SELECT e.*,u.name doctor FROM encounters e LEFT JOIN users u ON u.id=e.doctor_id WHERE e.patient_id=? ORDER BY e.created_at DESC",(pid,)).fetchall()
        rx=c.execute("SELECT * FROM prescriptions WHERE patient_id=? ORDER BY created_at DESC",(pid,)).fetchall()
        depts=c.execute("SELECT id,name FROM departments WHERE active=1 AND kind='lab' ORDER BY name").fetchall()
        meds=c.execute("SELECT id,name,quantity FROM medicines ORDER BY name").fetchall()
    role=u["role"]
    sensitive=has_role(u,"doctor","resident","nurse")
    history=''
    if sensitive:
        history='<section class="panel"><p class="kicker">Clinical record</p><h2>Nursing intake and history</h2>'+''.join(f'<article class="history-card"><h3>Vitals · {e(i["created_at"])} · {e(i["author"] or "Staff")}</h3><div class="vital-grid">'+''.join(f'<div><small>{label}</small><strong>{e(i[key] or "—")}</strong></div>' for key,label in [('bp','Blood pressure'),('pulse','Pulse'),('temperature','Temperature °C'),('spo2','SpO₂'),('weight','Weight kg')])+'</div>'+''.join(f'<p><b>{e(k)}:</b> {e(v)}</p>' for k,v in json.loads(i['questions'] or '{}').items())+f'<p>{e(i["notes"])}</p></article>' for i in intakes)+'</section>'
        history+='<section class="panel"><p class="kicker">Doctor record</p><h2>Diagnoses and plans</h2>'+''.join(f'<article class="history-card"><h3>{e(x["doctor"] or "Doctor")} · {e(x["created_at"])}</h3><p><b>Diagnosis:</b> {e(x["diagnosis"] or "—")}</p><p>{e(x["clinical_notes"])}</p><p><b>Plan:</b> {e(x["plan"])}</p></article>' for x in encounters)+'</section>'
    order_rows=[]
    for o in orders:
        if role=="lab" and o["department_id"]!=u["department_id"]: continue
        links=[]
        for r in results:
            if r["order_id"]==o["id"]: links.append(f'<a class="btn outline small" href="/file?id={r["id"]}" target="_blank">Open result</a>')
        lab_controls=''
        if role=="lab" and o["status"] not in ("completed",):
            lab_controls=f'<form method="post" action="/lab/complete" enctype="multipart/form-data" class="upload-row">{form_csrf(u)}<input type="hidden" name="order_id" value="{o["id"]}"><input type="file" name="report" accept=".pdf,.doc,.docx" required><button class="btn gold small">Upload and complete</button></form>'
        if role in ("doctor","resident","nurse","head_secretary","secretary","admin") or (role=="lab" and o["department_id"]==u["department_id"]):
            order_rows.append(f'<tr><td>{e(TESTS.get(o["test_code"],(o["test_code"],""))[0])}</td><td>{e(o["department"] or "—")}</td><td><span class="status {e(o["status"])}">{e(o["status"].title())}</span></td><td>{e(o["details"] or "—")}</td><td>{e(o["created_at"])}</td><td>{" ".join(links)}{lab_controls}</td></tr>')
    workflow=''
    if role in ("doctor","resident","nurse","head_secretary","secretary","admin") or role=="lab":
        workflow=f'<section class="panel"><p class="kicker">Team workflow</p><h2>Tests and reports</h2><div class="table-scroll"><table><thead><tr><th>Test</th><th>Department</th><th>Status</th><th>Specification</th><th>Ordered</th><th>Results / action</th></tr></thead><tbody>{"".join(order_rows) or "<tr><td colspan=6>No tests ordered.</td></tr>"}</tbody></table></div></section>'
    forms=[]
    if role=="nurse":
        forms.append(f'<section class="panel"><p class="kicker">Nursing</p><h2>Record preparation and vitals</h2><form class="form-grid" method="post" action="/patient/intake">{form_csrf(u)}<input type="hidden" name="patient_id" value="{pid}">{field("bp","Blood pressure")}{field("pulse","Pulse / min")}{field("temperature","Temperature °C")}{field("spo2","Oxygen saturation %")}{field("weight","Weight kg")}{area("questions","Preparation questions and answers")}{area("notes","Nursing notes")}<div class="full">{btn("Save nursing intake and send to doctor","gold")}</div></form></section>')
    if role=="resident":
        forms.append(f'<section class="panel"><p class="kicker">Resident doctor</p><h2>Intake and examination</h2><form class="form-grid" method="post" action="/patient/intake">{form_csrf(u)}<input type="hidden" name="patient_id" value="{pid}">{field("bp","Blood pressure")}{field("pulse","Pulse / min")}{field("temperature","Temperature °C")}{field("spo2","Oxygen saturation %")}{area("questions","History, drugs, surgeries and other details")}{area("notes","Resident notes")}<div class="full">{btn("Save notes and send to doctor","gold")}</div></form></section>')
    if role=="doctor":
        test_opts=''.join(f'<option value="{k}">{e(v[0])} · {e(v[1])}</option>' for k,v in TESTS.items())
        forms.append(f'<section class="panel"><p class="kicker">Doctor desk</p><h2>Diagnosis and plan</h2><form method="post" action="/doctor/visit" class="form-grid">{form_csrf(u)}<input type="hidden" name="patient_id" value="{pid}">{area("diagnosis","Diagnosis")}{area("clinical_notes","Clinical notes")}{area("plan","Treatment plan")}<div class="full"><h3>Order a test</h3><div class="order-form-row"><select name="test_code"><option value="">No new test</option>{test_opts}</select>{field("test_details","Test specification")}</div></div><div class="full"><h3>Prescribe medicine</h3><div class="order-form-row"><select name="medicine_id"><option value="">Choose from stock</option>{''.join(f'<option value="{m["id"]}">{e(m["name"])} · stock {m["quantity"]}</option>' for m in meds)}</select>{field("medicine","Medicine (if not in stock)")}</div><div class="form-grid compact">{field("dose","Dose")}{field("quantity","Quantity","1","number",min="1")}{area("instructions","Instructions",rows=2)}</div></div><div class="full">{btn("Save visit and send orders","gold")}</div></form></section>')
    if role in ("secretary","head_secretary"):
        with connect() as c: docs=c.execute("SELECT id,name FROM users WHERE role='doctor' AND active=1").fetchall()
        forms.append(f'<section class="panel"><h2>Queue assignment</h2><form method="post" action="/patient/assign">{form_csrf(u)}<input type="hidden" name="patient_id" value="{pid}"><select name="doctor_id">'+''.join(f'<option value="{d["id"]}" {"selected" if d["id"]==p["doctor_id"] else ""}>{e(d["name"])}</option>' for d in docs)+'</select>'+btn('Assign doctor and queue','gold')+'</form></section>')
    if role=="pharmacy":
        forms.append(f'<section class="panel"><h2>Prescription fulfilment</h2><div class="table-scroll"><table><thead><tr><th>Medicine</th><th>Dose</th><th>Qty</th><th>Instructions</th><th>Status</th><th>Action</th></tr></thead><tbody>'+''.join(f'<tr><td>{e(r["medicine"])}</td><td>{e(r["dose"])}</td><td>{r["quantity"]}</td><td>{e(r["instructions"])}</td><td>{e(r["status"])}</td><td>{"<form method=post action=/pharmacy/dispense>"+form_csrf(u)+f"<input type=hidden name=prescription_id value={r['id']}>{field('amount','Sale amount','0','number',min='0')}"+btn('Complete sale','gold')+'</form>' if r['status']=='ordered' else '—'}</td></tr>' for r in rx)+'</tbody></table></div></section>')
    if role in ("payam","accountant","secretary","head_secretary"):
        forms.append(f'<section class="panel"><h2>Record collected payment</h2><form method="post" action="/payment" class="form-grid">{form_csrf(u)}<input type="hidden" name="patient_id" value="{pid}"><select name="service">'+''.join(f'<option value="{e(k)}">{e(v[0])}</option>' for k,v in TESTS.items())+'<option value="doctor">Doctor visit</option></select>'+field('amount','Amount IQD','0','number',min='0')+field('note','Note')+f'<div class="full">{btn("Record payment","gold")}</div></form></section>')
    return f'''<section class="patient-hero"><p class="kicker gold-text">Permanent patient ID · {e(p['code'])}</p><h1>{e(p['name'])}</h1><p>Age {e(p['age'] or "—")} · Phone {e(p['phone'] or "—")} · DOB {e(p['dob'] or "—")} · Doctor {e(p['doctor'] or "—")}</p></section>{history}{''.join(forms)}{workflow}'''


def queue_page(u: sqlite3.Row) -> str:
    with connect() as c:
        if u["role"] == "lab":
            rows=c.execute("SELECT o.*,p.code,p.name,d.name department FROM lab_orders o JOIN patients p ON p.id=o.patient_id LEFT JOIN departments d ON d.id=o.department_id WHERE o.department_id=? AND o.status!='completed' ORDER BY o.queue_position,o.created_at",(u["department_id"],)).fetchall()
        else:
            q="" if u["role"] in ("head_secretary","secretary","admin","staff") else "WHERE p.doctor_id=?"
            args=() if not q else (u["id"],)
            rows=c.execute(f"SELECT p.*,d.name doctor FROM patients p LEFT JOIN users d ON d.id=p.doctor_id {q} ORDER BY CASE p.status WHEN 'waiting' THEN 0 ELSE 1 END,p.queue_position,p.created_at",args).fetchall()
    if u["role"]=="lab":
        lines=''.join(f'<tr><td><a href="/patient?id={r["patient_id"]}">{e(r["code"])} · {e(r["name"])}</a></td><td>{e(TESTS.get(r["test_code"],(r["test_code"],""))[0])}</td><td>{e(r["details"] or "—")}</td><td>{e(r["status"])}</td><td><a class="btn outline small" href="/patient?id={r["patient_id"]}">Open patient and upload</a></td></tr>' for r in rows)
        return '<section class="page-title"><p class="kicker">Lab queue</p><h1>My assigned tests</h1></section><section class="panel"><div class="table-scroll"><table><thead><tr><th>Patient</th><th>Test</th><th>Specification</th><th>Status</th><th>Action</th></tr></thead><tbody>'+lines+'</tbody></table></div></section>'
    lines=''.join(f'<tr><td>{r["queue_position"]}</td><td><a href="/patient?id={r["id"]}">{e(r["code"])} · {e(r["name"])}</a></td><td>{e(r["doctor"] or "—")}</td><td>{e(r["phone"])}</td><td><span class="status {e(r["status"])}">{e(r["status"].title())}</span></td><td><a class="btn outline small" href="/patient?id={r["id"]}">Open</a></td></tr>' for r in rows)
    if u["role"]=="doctor":
        nextform=f'<form method="post" action="/queue/next">{form_csrf(u)}{btn("Next patient · DING", "gold")}</form>'
    else: nextform=''
    return f'<section class="page-title"><p class="kicker">Patient flow</p><h1>Doctor queues</h1>{nextform}</section><section class="panel"><div class="table-scroll"><table><thead><tr><th>Position</th><th>Patient</th><th>Doctor</th><th>Phone</th><th>Status</th><th></th></tr></thead><tbody>{lines or "<tr><td colspan=6>No patients are waiting.</td></tr>"}</tbody></table></div></section>'


def lab_page(u: sqlite3.Row) -> str:
    return queue_page(u)


def pharmacy_page(u: sqlite3.Row) -> str:
    with connect() as c:
        rx=c.execute("SELECT r.*,p.code,p.name FROM prescriptions r JOIN patients p ON p.id=r.patient_id WHERE r.status='ordered' ORDER BY r.created_at").fetchall()
        meds=c.execute("SELECT m.*,v.name vendor FROM medicines m LEFT JOIN vendors v ON v.id=m.vendor_id ORDER BY m.name,m.expiry_date").fetchall()
        vendors=c.execute("SELECT * FROM vendors ORDER BY name").fetchall()
        invoices=c.execute("SELECT i.*,v.name vendor FROM purchase_invoices i LEFT JOIN vendors v ON v.id=i.vendor_id ORDER BY i.created_at DESC LIMIT 50").fetchall()
    rxrows=''.join(f'<tr><td><a href="/patient?id={r["patient_id"]}">{e(r["code"])} · {e(r["name"])}</a></td><td>{e(r["medicine"])}</td><td>{e(r["dose"])}</td><td>{r["quantity"]}</td><td>{e(r["instructions"])}</td><td><form method="post" action="/pharmacy/dispense" class="inline-form">{form_csrf(u)}<input type="hidden" name="prescription_id" value="{r["id"]}"><input name="amount" type="number" min="0" placeholder="IQD" required><button class="btn gold small">Sell</button></form></td></tr>' for r in rx)
    stock=''.join(f'<tr><td>{e(m["barcode"] or "—")}</td><td>{e(m["name"])}</td><td>{e(m["batch_no"])}</td><td>{e(m["expiry_date"])}</td><td>{m["quantity"]}</td><td>{m["buy_price"]:,.0f}</td><td>{m["sell_price"]:,.0f}</td><td>{e(m["vendor"] or "—")}</td></tr>' for m in meds)
    vendor_opts=''.join(f'<option value="{v["id"]}">{e(v["name"])}</option>' for v in vendors)
    return f'''<section class="page-title"><p class="kicker">Pharmacy and inventory</p><h1>Pharmacy desk</h1></section><section class="panel"><h2>Prescriptions to dispense</h2><div class="table-scroll"><table><thead><tr><th>Patient</th><th>Medicine</th><th>Dose</th><th>Qty</th><th>Instructions</th><th>Sale</th></tr></thead><tbody>{rxrows or '<tr><td colspan="6">No waiting prescriptions.</td></tr>'}</tbody></table></div></section><section class="panel"><h2>Medicine stock</h2><div class="table-scroll"><table><thead><tr><th>Barcode</th><th>Name</th><th>Batch</th><th>Expiry</th><th>Qty</th><th>Buy IQD</th><th>Sell IQD</th><th>Vendor</th></tr></thead><tbody>{stock or '<tr><td colspan="8">No stock recorded yet.</td></tr>'}</tbody></table></div></section><div class="split"><section class="panel"><h2>Add supplier</h2><form method="post" action="/pharmacy/vendor" class="form-grid">{form_csrf(u)}{field('name','Company name',required=True)}{field('phone','Phone')}{field('address','Address')}<div class="full">{btn('Save company','gold')}</div></form></section><section class="panel"><h2>Receive stock</h2><form method="post" action="/pharmacy/stock" class="form-grid">{form_csrf(u)}{field('barcode','Barcode (scan or type)')}{field('name','Medicine name',required=True)}{field('batch_no','Batch number')}{field('expiry_date','Expiry date','','date')}{field('quantity','Quantity','1','number',min='1')}{field('buy_price','Buying price','0','number',min='0',step='0.01')}{field('sell_price','Selling price','0','number',min='0',step='0.01')}<label class="field"><span>Supplier</span><select name="vendor_id"><option value="">Select supplier</option>{vendor_opts}</select></label><div class="full">{btn('Receive medicine into stock','gold')}</div></form></section></div>'''


def accounting_page(u: sqlite3.Row) -> str:
    with connect() as c:
        total=c.execute("SELECT COALESCE(SUM(amount),0) amount,COUNT(*) n FROM payments").fetchone()
        day=c.execute("SELECT COALESCE(SUM(amount),0) amount,COUNT(*) n FROM payments WHERE date(created_at)=date('now','localtime')").fetchone()
        rows=c.execute("SELECT p.*,u.name collector,x.name patient FROM payments p LEFT JOIN users u ON u.id=p.collected_by LEFT JOIN patients x ON x.id=p.patient_id ORDER BY p.created_at DESC LIMIT 300").fetchall()
        hand=c.execute("SELECT h.*,a.name sender,b.name recipient FROM cash_handovers h LEFT JOIN users a ON a.id=h.from_user LEFT JOIN users b ON b.id=h.to_user ORDER BY h.created_at DESC LIMIT 100").fetchall()
        staff=c.execute("SELECT id,name,role FROM users WHERE role IN ('accountant','secretary','head_secretary','admin') AND active=1 ORDER BY name").fetchall()
        invoices=c.execute("SELECT i.*,v.name vendor,u.name receiver FROM purchase_invoices i LEFT JOIN vendors v ON v.id=i.vendor_id LEFT JOIN users u ON u.id=i.received_by ORDER BY i.created_at DESC LIMIT 100").fetchall()
        sales=c.execute("SELECT s.*,p.code,p.name patient,u.name cashier FROM pharmacy_sales s LEFT JOIN patients p ON p.id=s.patient_id LEFT JOIN users u ON u.id=s.sold_by ORDER BY s.created_at DESC LIMIT 100").fetchall()
    report=''.join(f'<tr><td>{e(r["created_at"])}</td><td>{e(r["patient"] or "—")}</td><td>{e(r["service"])}</td><td>{r["amount"]:,.0f} IQD</td><td>{e(r["collector"] or "—")}</td><td>{"Handed over" if r["handover_id"] else "Unsettled"}</td></tr>' for r in rows)
    turnovers=''.join(f'<tr><td>{e(h["created_at"])}</td><td>{e(h["sender"])}</td><td>{e(h["recipient"])}</td><td>{h["total"]:,.0f} IQD</td><td>{e(h["note"])}</td></tr>' for h in hand)
    staff_opts=''.join(f'<option value="{s["id"]}">{e(s["name"])} · {e(s["role"])}</option>' for s in staff)
    invoice_rows=''.join(f'<tr><td>{e(i["created_at"])}</td><td>{e(i["invoice_no"] or "—")}</td><td>{e(i["vendor"] or "—")}</td><td>{i["total"]:,.0f} IQD</td><td>{e(i["receiver"] or "—")}</td></tr>' for i in invoices)
    sale_rows=''.join(f'<tr><td>{e(s["created_at"])}</td><td>{e(s["patient"] or "Walk-in")}</td><td>{e(s["medicine"])}</td><td>{s["quantity"]}</td><td>{s["amount"]:,.0f} IQD</td><td>{e(s["cashier"] or "—")}</td></tr>' for s in sales)
    return f'''<section class="page-title"><p class="kicker">Accounting</p><h1>Collections and settlements</h1></section><section class="metric-grid"><article class="metric"><small>All recorded collections</small><strong>{total['amount']:,.0f} IQD</strong><span>{total['n']} entries</span></article><article class="metric"><small>Collected today</small><strong>{day['amount']:,.0f} IQD</strong><span>{day['n']} entries</span></article></section><section class="panel"><h2>Cash handover</h2><form method="post" action="/accounting/handover" class="form-grid">{form_csrf(u)}<label class="field"><span>From staff member</span><select name="from_user">{staff_opts}</select></label><label class="field"><span>To accountant</span><select name="to_user">{staff_opts}</select></label>{field('total','Amount received (IQD)','0','number',min='0',step='0.01')}{field('note','Handover note')}<div class="full">{btn('Record end-of-day handover','gold')}</div></form></section><section class="panel"><h2>Collection ledger</h2><div class="table-scroll"><table><thead><tr><th>Date</th><th>Patient</th><th>Service</th><th>Amount</th><th>Collected by</th><th>Settlement</th></tr></thead><tbody>{report or '<tr><td colspan="6">No payments recorded.</td></tr>'}</tbody></table></div></section><section class="panel"><h2>Handover history</h2><div class="table-scroll"><table><thead><tr><th>Date</th><th>From</th><th>To</th><th>Total</th><th>Note</th></tr></thead><tbody>{turnovers or '<tr><td colspan="5">No handovers recorded.</td></tr>'}</tbody></table></div></section><section class="panel"><h2>Pharmacy sales report</h2><div class="table-scroll"><table><thead><tr><th>Date</th><th>Patient</th><th>Medicine</th><th>Qty</th><th>Amount</th><th>Cashier</th></tr></thead><tbody>{sale_rows or '<tr><td colspan="6">No sales yet.</td></tr>'}</tbody></table></div></section><section class="panel"><h2>Supplier invoices</h2><div class="table-scroll"><table><thead><tr><th>Date</th><th>Invoice</th><th>Supplier</th><th>Total</th><th>Received by</th></tr></thead><tbody>{invoice_rows or '<tr><td colspan="5">No purchase invoices.</td></tr>'}</tbody></table></div></section>'''


def admin_page(u: sqlite3.Row) -> str:
    with connect() as c:
        users=c.execute("SELECT u.*,d.name department FROM users u LEFT JOIN departments d ON d.id=u.department_id ORDER BY u.name").fetchall()
        depts=c.execute("SELECT * FROM departments ORDER BY name").fetchall()
    rows=''.join(f'<tr><td>{e(x["name"])}</td><td>{e(x["role"])}</td><td>{e(x["department"] or "—")}</td><td>{"Active" if x["active"] else "Disabled"}</td></tr>' for x in users)
    drows=''.join(f'<tr><td>{e(d["name"])}</td><td>{e(d["kind"])}</td><td>{"Active" if d["active"] else "Disabled"}</td></tr>' for d in depts)
    opts=''.join(f'<option>{e(d["name"])}</option>' for d in depts if d["active"])
    roles=['doctor','resident','nurse','secretary','head_secretary','lab','pharmacy','accountant','hr','admin','staff']
    return f'''<section class="page-title"><p class="kicker">IT administration</p><h1>Users and departments</h1><p>Changes are recorded in the audit log. Default PINs should be changed before live clinical use.</p></section><div class="split"><section class="panel"><h2>Create user</h2><form method="post" action="/admin/user" class="form-grid">{form_csrf(u)}{field('name','Full name',required=True)}<label class="field"><span>Role</span><select name="role">{''.join(f'<option value="{r}">{e(r.replace("_"," ").title())}</option>' for r in roles)}</select></label><label class="field"><span>Department</span><select name="department">{opts}</select></label>{field('pin','Initial four-digit PIN',DEFAULT_PIN,required=True,pattern='[0-9]{4}',maxlength='4')}<div class="full">{btn('Create user','gold')}</div></form></section><section class="panel"><h2>Create department</h2><form method="post" action="/admin/department" class="form-grid">{form_csrf(u)}{field('name','Department name',required=True)}<label class="field"><span>Department type</span><select name="kind">{''.join(f'<option value="{r}">{r.title()}</option>' for r in roles)}</select></label><div class="full">{btn('Create department','gold')}</div></form></section></div><section class="panel"><h2>Accounts</h2><div class="table-scroll"><table><thead><tr><th>Name</th><th>Role</th><th>Department</th><th>State</th></tr></thead><tbody>{rows}</tbody></table></div></section><section class="panel"><h2>Departments</h2><div class="table-scroll"><table><thead><tr><th>Name</th><th>Type</th><th>State</th></tr></thead><tbody>{drows}</tbody></table></div></section>'''


def hr_page(u: sqlite3.Row) -> str:
    with connect() as c:
        users=c.execute("SELECT id,name,role FROM users WHERE active=1 ORDER BY name").fetchall()
        records=c.execute("SELECT h.*,u.name employee,a.name author FROM hr_records h LEFT JOIN users u ON u.id=h.user_id LEFT JOIN users a ON a.id=h.created_by ORDER BY h.created_at DESC LIMIT 200").fetchall()
    items=''.join(f'<tr><td>{e(r["created_at"])}</td><td>{e(r["employee"] or "—")}</td><td>{e(r["record_type"])}</td><td>{e(r["note"])}</td><td>{e(r["author"] or "—")}</td></tr>' for r in records)
    opts=''.join(f'<option value="{x["id"]}">{e(x["name"])} · {e(x["role"])}</option>' for x in users)
    return f'''<section class="page-title"><p class="kicker">Human resources</p><h1>Staff records</h1></section><section class="panel"><h2>Add HR note</h2><form method="post" action="/hr/record" class="form-grid">{form_csrf(u)}<label class="field"><span>Staff member</span><select name="user_id">{opts}</select></label>{field('record_type','Record type','General')}{area('note','Note',rows=3)}<div class="full">{btn('Save HR record','gold')}</div></form></section><section class="panel"><h2>Recent staff records</h2><div class="table-scroll"><table><thead><tr><th>Date</th><th>Staff</th><th>Type</th><th>Note</th><th>Recorded by</th></tr></thead><tbody>{items or '<tr><td colspan="5">No HR records.</td></tr>'}</tbody></table></div></section>'''


def video_page(u: sqlite3.Row) -> str:
    return '''<section class="page-title"><p class="kicker">Clinic communications</p><h1>Video call</h1><p class="muted">Users online in the last 2 minutes. Allow camera and microphone access when your browser prompts.</p></section><section class="panel"><div id="video-roster" class="user-grid"><p>Loading team…</p></div><p id="call-status" class="muted"></p><div class="video-stage" id="video-stage" hidden><video id="remote-video" autoplay playsinline></video><video id="local-video" autoplay muted playsinline></video><div class="hero-actions"><button id="mute" class="btn outline">Mute microphone</button><button id="camera" class="btn outline">Turn camera off</button><button id="hangup" class="btn gold">End call</button></div></div></section>'''


def chat_page(u: sqlite3.Row) -> str:
    with connect() as c:
        peers=c.execute("SELECT id,name,role FROM users WHERE active=1 AND id<>? ORDER BY name",(u["id"],)).fetchall()
    options=''.join(f'<option value="{x["id"]}">{e(x["name"])} · {e(x["role"].replace("_"," "))}</option>' for x in peers)
    return f'''<section class="page-title"><p class="kicker">Clinic communications</p><h1>Team chat</h1><p class="muted">Direct messages between clinic staff.</p></section><section class="panel chat-panel" id="chat-panel"><label class="field"><span>Colleague</span><select id="chat-peer">{options}</select></label><div class="chat-messages" id="chat-messages" aria-live="polite"></div><form id="chat-form" class="chat-compose"><input id="chat-text" maxlength="4000" placeholder="Write a message" required><button class="btn gold">Send</button></form></section>'''


def notifications_page(u: sqlite3.Row) -> str:
    with connect() as c:
        rows=c.execute("SELECT n.*,p.code,p.name FROM notifications n LEFT JOIN patients p ON p.id=n.patient_id WHERE n.user_id=? ORDER BY n.created_at DESC LIMIT 100",(u["id"],)).fetchall()
        c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL",(stamp(),u["id"]))
    pieces=[]
    for r in rows:
        extra=f' · {e(r["code"])} {e(r["name"])}' if r["patient_id"] else ""
        link=f'/patient?id={r["patient_id"]}' if r["patient_id"] else '#'
        pieces.append(f'<article class="notice-row"><a href="{link}">{e(r["message"])}{extra}</a><small>{e(r["created_at"])}</small></article>')
    items=''.join(pieces)
    return '<section class="page-title"><p class="kicker">Clinic updates</p><h1>Notifications</h1></section><section class="panel">'+(items or '<p class="muted">No notifications.</p>')+'</section>'


def page_for(u: sqlite3.Row, path: str, qs: dict[str, list[str]]) -> tuple[str, str]:
    lang = qs.get("lang", ["en"])[0]
    if path == "/": return "Clinic workspace", dashboard(u)
    if path == "/patients": return "Patients", f'<section class="page-title"><p class="kicker">Shared record</p><h1>Today’s patients</h1><p><a href="/patients?all=1">View all patients</a></p></section><section class="panel">{patient_rows(u, qs.get("all")==["1"])}</section>'
    if path == "/patient/new" and has_role(u,"secretary","head_secretary"): return "Register patient", new_patient_form(u)
    if path == "/patient": return "Patient profile", patient_profile(u, int(qs.get("id",["0"])[0] or 0))
    if path in ("/queue","/lab"): return "Queues", queue_page(u)
    if path == "/pharmacy" and has_role(u,"pharmacy"): return "Pharmacy", pharmacy_page(u)
    if path == "/accounting" and has_role(u,"accountant","secretary","head_secretary"): return "Accounting", accounting_page(u)
    if path == "/admin" and has_role(u,"admin"): return "Administration", admin_page(u)
    if path == "/hr" and has_role(u,"hr"): return "Human resources", hr_page(u)
    if path == "/video": return "Video call", video_page(u)
    if path == "/chat": return "Team chat", chat_page(u)
    if path == "/notifications": return "Notifications", notifications_page(u)
    return "Not found", '<section class="panel"><h1>Page unavailable</h1><p>Your account may not have access to this section.</p></section>'


def parse_form(handler: BaseHTTPRequestHandler) -> dict[str, str | bytes]:
    length=int(handler.headers.get("Content-Length","0"))
    if length > MAX_UPLOAD: raise ValueError("Request is larger than the upload limit.")
    body=handler.rfile.read(length)
    ctype=handler.headers.get("Content-Type","")
    if ctype.startswith("application/json"):
        value=json.loads(body.decode("utf-8"))
        if not isinstance(value,dict): raise ValueError("Invalid request body.")
        return value
    if ctype.startswith("multipart/form-data"):
        message=BytesParser(policy=policy.default).parsebytes(b"Content-Type: "+ctype.encode()+b"\r\nMIME-Version: 1.0\r\n\r\n"+body)
        out={}
        for part in message.iter_parts():
            name=part.get_param("name",header="content-disposition")
            if not name: continue
            payload=part.get_payload(decode=True) or b""
            filename=part.get_filename()
            out[name+"__filename"] = filename or ""
            out[name+"__type"] = part.get_content_type()
            out[name]=payload if filename else payload.decode(part.get_content_charset() or "utf-8", "replace")
        return out
    parsed=parse_qs(body.decode("utf-8","replace"),keep_blank_values=True)
    return {k:v[-1] for k,v in parsed.items()}


class Handler(BaseHTTPRequestHandler):
    server_version="MMCOffline/1.0"
    def log_message(self, fmt: str, *args: object) -> None:
        DATA_DIR.mkdir(parents=True,exist_ok=True)
        with (DATA_DIR/"server.log").open("a",encoding="utf-8") as f: f.write(f"{stamp()} {self.client_address[0]} {fmt % args}\n")

    def cookie_value(self, key: str) -> str:
        jar=SimpleCookie(); jar.load(self.headers.get("Cookie","")); return jar[key].value if key in jar else ""

    def send_bytes(self, status: int, body: bytes, ctype: str="text/html; charset=utf-8", headers: list[tuple[str,str]]|None=None) -> None:
        self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store"); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("X-Frame-Options","DENY"); self.send_header("Referrer-Policy","same-origin")
        for k,v in headers or []: self.send_header(k,v)
        self.end_headers()
        if self.command!="HEAD": self.wfile.write(body)

    def redirect(self, to: str) -> None:
        self.send_bytes(303,b"",headers=[("Location",to)])

    def do_GET(self) -> None:
        url=urlparse(self.path); path=url.path; qs=parse_qs(url.query)
        if path=="/style.css":
            try: self.send_bytes(200,(APP_DIR/"style.css").read_bytes(),"text/css; charset=utf-8")
            except OSError: self.send_bytes(404,b"/* style.css missing */","text/css")
            return
        if path=="/app.js":
            try: self.send_bytes(200,(APP_DIR/"app.js").read_bytes(),"text/javascript; charset=utf-8")
            except OSError: self.send_bytes(404,b"", "text/javascript")
            return
        if path=="/logout":
            token=self.cookie_value("mmc_session")
            with connect() as c: c.execute("DELETE FROM sessions WHERE token=?",(token,))
            self.send_bytes(303,b"",headers=[("Location","/"),("Set-Cookie","mmc_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")]); return
        user=login_user(self.cookie_value("mmc_session"))
        if not user:
            self.send_bytes(200,login_page()); return
        if path=="/file":
            rid=int(qs.get("id",["0"])[0] or 0)
            with connect() as c:
                r=c.execute("SELECT r.*,o.patient_id,o.department_id FROM results r JOIN lab_orders o ON o.id=r.order_id WHERE r.id=?",(rid,)).fetchone()
            if not r: self.send_bytes(404,b"Not found"); return
            allowed = user["role"] in ("doctor","resident","nurse","admin") or (user["role"]=="lab" and user["department_id"]==r["department_id"])
            if not allowed: self.send_bytes(404,b"Not found"); return
            f=(UPLOAD_DIR/r["relative_path"]).resolve()
            if UPLOAD_DIR.resolve() not in f.parents or not f.is_file(): self.send_bytes(404,b"File missing"); return
            self.send_bytes(200,f.read_bytes(),r["content_type"],[("Content-Disposition",f'inline; filename="{e(Path(r["file_name"]).name)}"')]); return
        if path=="/api/online":
            with connect() as c: users=c.execute("SELECT id,name,role FROM users WHERE active=1 AND id<>? AND last_seen>=? ORDER BY name",(user["id"],(datetime.now()-timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
            body=json.dumps([dict(x) for x in users]).encode(); self.send_bytes(200,body,"application/json"); return
        if path=="/api/messages":
            peer=int(qs.get("peer",["0"])[0] or 0)
            with connect() as c:
                rows=c.execute("SELECT m.id,m.sender_id,m.receiver_id,m.body,m.created_at,u.name sender FROM messages m JOIN users u ON u.id=m.sender_id WHERE (m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?) ORDER BY m.id DESC LIMIT 100",(user["id"],peer,peer,user["id"])).fetchall()
                c.execute("UPDATE messages SET read_at=? WHERE sender_id=? AND receiver_id=? AND read_at IS NULL",(stamp(),peer,user["id"]))
                c.execute("UPDATE users SET last_seen=? WHERE id=?",(stamp(),user["id"]))
            self.send_bytes(200,json.dumps([dict(x) for x in reversed(rows)]).encode(),"application/json"); return
        if path=="/api/presence":
            with connect() as c: c.execute("UPDATE users SET last_seen=? WHERE id=?",(stamp(),user["id"]))
            self.send_bytes(204,b""); return
        if path=="/api/calls":
            with connect() as c: calls=c.execute("SELECT c.*,a.name caller,b.name recipient FROM calls c JOIN users a ON a.id=c.caller_id JOIN users b ON b.id=c.recipient_id WHERE (c.caller_id=? OR c.recipient_id=?) AND c.updated_at>=? AND c.state IN ('ringing','active','declined','ended') ORDER BY c.created_at DESC",(user["id"],user["id"],(datetime.now()-timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
            self.send_bytes(200,json.dumps([dict(x) for x in calls]).encode(),"application/json"); return
        if path=="/api/signals":
            call_id=qs.get("call_id",[""])[0]
            with connect() as c:
                signals=c.execute("SELECT id,call_id,sender_id,payload FROM call_signals WHERE call_id=? AND recipient_id=? AND received=0 ORDER BY id",(call_id,user["id"])).fetchall()
                if signals: c.executemany("UPDATE call_signals SET received=1 WHERE id=?",[(s["id"],) for s in signals])
            self.send_bytes(200,json.dumps([dict(x) for x in signals]).encode(),"application/json"); return
        title,body=page_for(user,path,qs)
        jar=SimpleCookie(); jar.load(self.headers.get("Cookie","")); saved=jar["mmc_lang"].value if "mmc_lang" in jar else "en"
        lang=qs.get("lang",[saved])[0]
        self.send_bytes(200,page(user,title,body,qs.get("notice",[""])[0],lang))

    def do_POST(self) -> None:
        path=urlparse(self.path).path
        try: data=parse_form(self)
        except Exception as ex: self.send_bytes(400,page(None,"Request error",f'<section class="panel"><h1>Upload failed</h1><p>{e(ex)}</p></section>')); return
        if path=="/login":
            try: uid=int(str(data.get("user_id","0"))); pin=str(data.get("pin",""))
            except ValueError: self.redirect("/?notice=Invalid+credentials"); return
            with connect() as c:
                u=c.execute("SELECT * FROM users WHERE id=? AND active=1",(uid,)).fetchone()
                if not u or not secrets.compare_digest(pin_digest(pin,u["pin_salt"]),u["pin_hash"]): self.redirect("/?notice=PIN+not+accepted"); return
                token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
                c.execute("INSERT INTO sessions(token,user_id,csrf,created_at) VALUES(?,?,?,?)",(token,uid,csrf,stamp())); c.execute("UPDATE users SET last_seen=? WHERE id=?",(stamp(),uid)); audit(c,uid,"sign_in","user",uid)
            self.send_bytes(303,b"",headers=[("Location","/"),("Set-Cookie",f"mmc_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_HOURS*3600}")]); return
        user=login_user(self.cookie_value("mmc_session"))
        if not user: self.redirect("/"); return
        csrf=str(data.get("_csrf",self.headers.get("X-CSRF-Token","")))
        if not secrets.compare_digest(csrf,user["csrf"]): self.send_bytes(403,page(user,"Security check",'<section class="panel"><h1>Security check failed</h1><p>Refresh and try again.</p></section>')); return
        if path=="/language":
            lang=str(data.get("lang","en"))
            if lang not in LANG: lang="en"
            self.send_bytes(303,b"",headers=[("Location","/"),("Set-Cookie",f"mmc_lang={lang}; SameSite=Lax; Path=/; Max-Age=31536000")]); return
        if path.startswith("/api/"):
            try: self.api_action(user,path,data)
            except (ValueError,sqlite3.Error) as ex: self.send_bytes(400,json.dumps({"error":str(ex)}).encode(),"application/json")
            return
        try:
            target=self.handle_action(user,path,data)
            self.redirect(target)
        except (ValueError,sqlite3.Error,OSError) as ex:
            self.send_bytes(400,page(user,"Action failed",f'<section class="panel"><h1>Action could not be completed</h1><p>{e(ex)}</p><p><a href="javascript:history.back()">Go back</a></p></section>'))

    def handle_action(self,u: sqlite3.Row,path: str,d: dict[str,str|bytes]) -> str:
        role=u["role"]
        if path=="/patient/create" and has_role(u,"secretary","head_secretary"):
            name=str(d.get("name","")).strip(); phone=str(d.get("phone","")).strip(); dob=str(d.get("dob","")).strip(); sex=str(d.get("sex","")).strip()
            if not name: raise ValueError("Patient name is required.")
            try: age=int(str(d.get("age","") or "")) if d.get("age") else None
            except ValueError: raise ValueError("Age must be a number.")
            doc=int(str(d.get("doctor_id","0") or 0)); today=stamp(); code=""
            with connect() as c:
                c.execute("INSERT INTO patients(code,name,dob,age,phone,sex,doctor_id,registered_by,status,created_at,updated_at) VALUES(NULL,?,?,?,?,?,?,?,'waiting',?,?)",(name,dob,age,phone,sex,doc,u["id"],today,today))
                pid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; code=f"MMC-{pid:06d}"; c.execute("UPDATE patients SET code=? WHERE id=?",(code,pid)); audit(c,u["id"],"register_patient","patient",pid)
            return f"/patient?id={pid}&notice=Patient+registered"
        if path=="/patient/intake" and has_role(u,"nurse","resident"):
            pid=int(str(d.get("patient_id","0"))); questions=str(d.get("questions", ""))[:10000]
            parsed={}
            for line in questions.splitlines():
                if ":" in line:
                    k,v=line.split(":",1); parsed[k.strip()[:80]]=v.strip()[:1000]
            with connect() as c:
                c.execute("INSERT INTO intake(patient_id,recorded_by,bp,pulse,temperature,spo2,weight,questions,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(pid,u["id"],str(d.get("bp",""))[:80],str(d.get("pulse",""))[:30],str(d.get("temperature",""))[:30],str(d.get("spo2",""))[:30],str(d.get("weight",""))[:30],json.dumps(parsed,ensure_ascii=False),str(d.get("notes",""))[:10000],stamp()))
                c.execute("UPDATE patients SET status='doctor',updated_at=? WHERE id=?",(stamp(),pid)); audit(c,u["id"],"save_intake","patient",pid)
            return f"/patient?id={pid}&notice=Intake+saved+for+doctor"
        if path=="/doctor/visit" and has_role(u,"doctor"):
            pid=int(str(d.get("patient_id","0"))); diagnosis=str(d.get("diagnosis",""))[:5000]; notes=str(d.get("clinical_notes",""))[:10000]; plan=str(d.get("plan",""))[:5000]
            with connect() as c:
                c.execute("INSERT INTO encounters(patient_id,doctor_id,diagnosis,clinical_notes,plan,created_by,created_at) VALUES(?,?,?,?,?,?,?)",(pid,u["id"],diagnosis,notes,plan,u["id"],stamp())); enc=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                code=str(d.get("test_code", "")); details=str(d.get("test_details", ""))[:1000]
                if code:
                    if code not in TESTS: raise ValueError("Unknown test type.")
                    lab_names={"echo":["Echo lab 1"],"pft":["Echo lab 1"],"ecg":["Echo lab 1"],"holter":["Echo lab 1"],"pressure":["Echo lab 1"],"blood":["Blood test lab 1"],"tmt":["TMT lab 1"]}.get(code,[TESTS[code][1]])
                    marks=','.join('?' for _ in lab_names)
                    dept=c.execute(f"SELECT d.id FROM departments d LEFT JOIN lab_orders o ON o.department_id=d.id AND o.status IN ('ordered','in_progress') WHERE d.name IN ({marks}) AND d.active=1 GROUP BY d.id ORDER BY COUNT(o.id),d.name LIMIT 1",lab_names).fetchone()
                    if not dept: raise ValueError("The target lab department does not exist. Add it in IT administration.")
                    c.execute("INSERT INTO lab_orders(patient_id,encounter_id,test_code,department_id,details,ordered_by,created_at) VALUES(?,?,?,?,?,?,?)",(pid,enc,code,dept["id"],details,u["id"],stamp()))
                    oid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                    targets=c.execute("SELECT id FROM users WHERE active=1 AND department_id=?",(dept["id"],)).fetchall()
                    patient=c.execute("SELECT code,name FROM patients WHERE id=?",(pid,)).fetchone()
                    for target in targets: notify(c,target["id"],pid,f"New {TESTS[code][0]} test requested for {patient['code']} · {patient['name']}",oid)
                med_id=int(str(d.get("medicine_id","0") or 0)); med=str(d.get("medicine","")).strip(); qty=max(1,int(str(d.get("quantity","1") or 1)))
                if med_id:
                    stock=c.execute("SELECT * FROM medicines WHERE id=?",(med_id,)).fetchone()
                    if stock: med=stock["name"]
                if med:
                    c.execute("INSERT INTO prescriptions(patient_id,encounter_id,medicine_id,medicine,dose,quantity,instructions,prescribed_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(pid,enc,med_id or None,med,str(d.get("dose",""))[:200],qty,str(d.get("instructions",""))[:3000],u["id"],stamp()))
                    patient=c.execute("SELECT code,name FROM patients WHERE id=?",(pid,)).fetchone()
                    for target in c.execute("SELECT id FROM users WHERE active=1 AND role='pharmacy'").fetchall(): notify(c,target["id"],pid,f"Prescription for {patient['code']} · {patient['name']}")
                c.execute("UPDATE patients SET status='after_doctor',updated_at=? WHERE id=?",(stamp(),pid)); audit(c,u["id"],"save_doctor_visit","patient",pid)
            return f"/patient?id={pid}&notice=Visit+saved"
        if path=="/lab/complete" and has_role(u,"lab"):
            oid=int(str(d.get("order_id","0"))); payload=d.get("report",b""); filename=str(d.get("report__filename", "")); ctype=str(d.get("report__type","application/octet-stream"))
            if not filename or not isinstance(payload,bytes): raise ValueError("Choose a report file.")
            ext=Path(filename).suffix.lower()
            if ext not in (".pdf",".doc",".docx"): raise ValueError("Only PDF or Word documents are allowed.")
            archive_error=""
            with connect() as c:
                order=c.execute("SELECT o.*,p.name patient_name,p.code patient_code,p.doctor_id FROM lab_orders o JOIN patients p ON p.id=o.patient_id WHERE o.id=? AND o.department_id=?",(oid,u["department_id"])).fetchone()
                if not order: raise ValueError("This test is not assigned to your lab.")
                def normalized(s: str) -> str: return ''.join(ch.casefold() for ch in s if ch.isalnum())
                file_key=normalized(Path(filename).stem)
                code_key=normalized(order["patient_code"] or "")
                name_key=normalized(order["patient_name"] or "")
                if not ((code_key and code_key in file_key) or (name_key and name_key in file_key)):
                    raise ValueError("تکایە دڵنیابەوە لەناوی نەخۆش، ئنجا ئەپلۆدی بکە")
                safe=secrets.token_hex(8)+ext; rel=f"{order['patient_id']}/{safe}"; dst=UPLOAD_DIR/str(order["patient_id"])/safe; dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(payload)
                if ARCHIVE_DIR:
                    folders={"echo":"echo","pft":"pft","ecg":"ecg","holter":"holter","tmt":"tmt","sleep":"sleep","blood":"blood tests","pressure":"Pressure","sonar":"sonar","radiology":"radiology"}
                    copy_name=f"{order['patient_code']}_{order['patient_name']}_{order['test_code']}{ext}"
                    try:
                        archive=ARCHIVE_DIR/folders.get(order["test_code"],"other"); archive.mkdir(parents=True,exist_ok=True); (archive/copy_name).write_bytes(payload)
                    except OSError as ex: archive_error=str(ex)
                c.execute("INSERT INTO results(order_id,file_name,relative_path,content_type,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?)",(oid,Path(filename).name,rel,ctype,u["id"],stamp()))
                c.execute("UPDATE lab_orders SET status='completed',completed_at=? WHERE id=?",(stamp(),oid)); c.execute("UPDATE patients SET status='doctor_review',updated_at=? WHERE id=?",(stamp(),order["patient_id"])); c.execute("UPDATE notifications SET read_at=? WHERE order_id=? AND read_at IS NULL",(stamp(),oid)); notify(c,order["doctor_id"],order["patient_id"],f"{TESTS.get(order['test_code'],(order['test_code'],''))[0]} result is ready for {order['patient_code']} · {order['patient_name']}"); audit(c,u["id"],"upload_test_result","lab_order",oid)
            notice="Report attached to patient"
            if archive_error: notice+="; F: backup failed: "+archive_error
            return f"/patient?id={order['patient_id']}&notice="+urlencode({"n":notice})[2:]
        if path=="/payment" and has_role(u,"secretary","head_secretary","accountant"):
            pid=int(str(d.get("patient_id","0"))); service=str(d.get("service","")); amount=float(str(d.get("amount","0") or 0));
            if amount<0 or amount>100000000: raise ValueError("Enter a valid payment amount.")
            with connect() as c:
                c.execute("INSERT INTO payments(patient_id,service,amount,note,collected_by,created_at) VALUES(?,?,?,?,?,?)",(pid,service,amount,str(d.get("note",""))[:500],u["id"],stamp())); audit(c,u["id"],"record_payment","patient",pid)
            return f"/patient?id={pid}&notice=Payment+recorded"
        if path=="/pharmacy/vendor" and has_role(u,"pharmacy"):
            with connect() as c: c.execute("INSERT INTO vendors(name,phone,address) VALUES(?,?,?)",(str(d.get("name",""))[:200],str(d.get("phone",""))[:100],str(d.get("address",""))[:300])); audit(c,u["id"],"add_vendor")
            return "/pharmacy?notice=Supplier+saved"
        if path=="/pharmacy/stock" and has_role(u,"pharmacy"):
            name=str(d.get("name","" )).strip(); barcode=str(d.get("barcode","" )).strip(); batch=str(d.get("batch_no","" )).strip(); qty=int(str(d.get("quantity","1") or 1)); vendor=int(str(d.get("vendor_id","0") or 0)) or None
            if not name or qty<1: raise ValueError("Enter a medicine name and positive quantity.")
            with connect() as c:
                row=c.execute("SELECT id,quantity FROM medicines WHERE barcode=? AND batch_no=? AND name=?",(barcode,batch,name)).fetchone()
                if row: c.execute("UPDATE medicines SET quantity=quantity+?,expiry_date=?,buy_price=?,sell_price=?,vendor_id=?,updated_at=? WHERE id=?",(qty,str(d.get("expiry_date","")),float(d.get("buy_price","0") or 0),float(d.get("sell_price","0") or 0),vendor,stamp(),row["id"]))
                else: c.execute("INSERT INTO medicines(barcode,name,batch_no,expiry_date,quantity,buy_price,sell_price,vendor_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(barcode,name,batch,str(d.get("expiry_date","")),qty,float(d.get("buy_price","0") or 0),float(d.get("sell_price","0") or 0),vendor,stamp()))
                audit(c,u["id"],"receive_stock", "medicine")
            return "/pharmacy?notice=Stock+received"
        if path=="/pharmacy/invoice" and has_role(u,"pharmacy"):
            name=str(d.get("name","" )).strip(); vendor=int(str(d.get("vendor_id","0") or 0)) or None; qty=int(str(d.get("quantity","1") or 1)); buy=float(str(d.get("buy_price","0") or 0)); sell=float(str(d.get("sell_price","0") or 0)); barcode=str(d.get("barcode","" )).strip(); batch=str(d.get("batch_no","" )).strip()
            if not name or qty<1: raise ValueError("Medicine name and positive quantity are required.")
            with connect() as c:
                row=c.execute("SELECT id FROM medicines WHERE barcode=? AND batch_no=? AND name=?",(barcode,batch,name)).fetchone()
                if row:
                    mid=row["id"]; c.execute("UPDATE medicines SET quantity=quantity+?,buy_price=?,sell_price=?,expiry_date=?,vendor_id=?,updated_at=? WHERE id=?",(qty,buy,sell,str(d.get("expiry_date","")),vendor,stamp(),mid))
                else:
                    c.execute("INSERT INTO medicines(barcode,name,batch_no,expiry_date,quantity,buy_price,sell_price,vendor_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(barcode,name,batch,str(d.get("expiry_date","")),qty,buy,sell,vendor,stamp())); mid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                invoice_no=str(d.get("invoice_no",""))[:100]; total=buy*qty
                c.execute("INSERT INTO purchase_invoices(vendor_id,invoice_no,total,received_by,created_at) VALUES(?,?,?,?,?)",(vendor,invoice_no,total,u["id"],stamp())); iid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.execute("INSERT INTO purchase_lines(invoice_id,medicine_id,quantity,unit_price) VALUES(?,?,?,?)",(iid,mid,qty,buy)); audit(c,u["id"],"receive_purchase_invoice","purchase_invoice",iid)
            return "/pharmacy?notice=Purchase+invoice+and+stock+saved"
        if path=="/pharmacy/dispense" and has_role(u,"pharmacy"):
            rid=int(str(d.get("prescription_id","0"))); amount=float(str(d.get("amount","0") or 0))
            with connect() as c:
                rx=c.execute("SELECT * FROM prescriptions WHERE id=? AND status='ordered'",(rid,)).fetchone()
                if not rx: raise ValueError("Prescription is no longer awaiting dispensing.")
                if rx["medicine_id"]:
                    med=c.execute("SELECT * FROM medicines WHERE id=?",(rx["medicine_id"],)).fetchone()
                    if med and med["quantity"]<rx["quantity"]: raise ValueError("Not enough medicine in stock.")
                    if med: c.execute("UPDATE medicines SET quantity=quantity-?,updated_at=? WHERE id=?",(rx["quantity"],stamp(),med["id"]))
                c.execute("UPDATE prescriptions SET status='sold',sold_at=? WHERE id=?",(stamp(),rid)); c.execute("INSERT INTO pharmacy_sales(prescription_id,patient_id,medicine_id,medicine,quantity,amount,sold_by,created_at) VALUES(?,?,?,?,?,?,?,?)",(rid,rx["patient_id"],rx["medicine_id"],rx["medicine"],rx["quantity"],amount,u["id"],stamp())); c.execute("INSERT INTO payments(patient_id,service,amount,note,collected_by,created_at) VALUES(?,?,?,?,?,?)",(rx["patient_id"],"pharmacy",amount,rx["medicine"],u["id"],stamp())); audit(c,u["id"],"dispense_prescription","prescription",rid)
            return "/pharmacy?notice=Sale+recorded"
        if path=="/accounting/handover" and has_role(u,"accountant","secretary","head_secretary"):
            source=int(str(d.get("from_user","0"))); dest=int(str(d.get("to_user","0"))); total=float(str(d.get("total","0") or 0));
            with connect() as c:
                pending=c.execute("SELECT id,amount FROM payments WHERE collected_by=? AND handover_id IS NULL ORDER BY created_at,id",(source,)).fetchall()
                selected=[]; subtotal=0.0
                for item in pending:
                    if subtotal+float(item["amount"])<=total+0.005:
                        selected.append(item["id"]); subtotal+=float(item["amount"])
                if abs(subtotal-total)>0.005: raise ValueError(f"Unsettled recorded receipts total {subtotal:,.0f} IQD. Enter that exact amount to reconcile.")
                c.execute("INSERT INTO cash_handovers(from_user,to_user,total,note,created_at) VALUES(?,?,?,?,?)",(source,dest,total,str(d.get("note",""))[:500],stamp())); hid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
                if selected: c.executemany("UPDATE payments SET handover_id=?,handed_to=? WHERE id=?",[(hid,dest,x) for x in selected])
                audit(c,u["id"],"cash_handover","cash_handovers",hid)
            return "/accounting?notice=Handover+recorded"
        if path=="/hr/record" and has_role(u,"hr"):
            with connect() as c: c.execute("INSERT INTO hr_records(user_id,record_type,note,created_by,created_at) VALUES(?,?,?,?,?)",(int(str(d.get("user_id","0"))),str(d.get("record_type","General"))[:100],str(d.get("note",""))[:5000],u["id"],stamp())); audit(c,u["id"],"add_hr_record")
            return "/hr?notice=HR+record+saved"
        if path=="/admin/user" and has_role(u,"admin"):
            name=str(d.get("name","" )).strip(); role=str(d.get("role","staff")); pin=str(d.get("pin",DEFAULT_PIN)); dept=str(d.get("department",""))
            if len(pin)!=4 or not pin.isdigit(): raise ValueError("PIN must be four digits.")
            with connect() as c:
                dep=c.execute("SELECT id FROM departments WHERE name=?",(dept,)).fetchone(); salt=secrets.token_bytes(16); c.execute("INSERT INTO users(name,role,department_id,pin_salt,pin_hash,created_at) VALUES(?,?,?,?,?,?)",(name,role,dep["id"] if dep else None,salt,pin_digest(pin,salt),stamp())); audit(c,u["id"],"create_user","user")
            return "/admin?notice=Account+created"
        if path=="/admin/department" and has_role(u,"admin"):
            with connect() as c: c.execute("INSERT INTO departments(name,kind) VALUES(?,?)",(str(d.get("name","" )).strip(),str(d.get("kind","lab")))); audit(c,u["id"],"create_department","department")
            return "/admin?notice=Department+created"
        if path=="/queue/next" and has_role(u,"doctor"):
            with connect() as c:
                p=c.execute("SELECT id FROM patients WHERE doctor_id=? AND status IN ('waiting','nurse','doctor','after_doctor','doctor_review') ORDER BY queue_position,created_at LIMIT 1",(u["id"],)).fetchone()
                if not p: raise ValueError("No patient is waiting in your queue.")
                c.execute("UPDATE patients SET status='with_doctor',updated_at=? WHERE id=?",(stamp(),p["id"]))
            return f"/patient?id={p['id']}&notice=Next+patient"
        raise ValueError("You do not have permission for this action.")

    def api_action(self,u: sqlite3.Row,path: str,d: dict[str,str|bytes]) -> None:
        if path=="/api/message":
            peer=int(str(d.get("to","0"))); body=str(d.get("body","")).strip()
            if not body or len(body)>4000: raise ValueError("Message must contain 1–4000 characters.")
            with connect() as c:
                if peer==u["id"] or not c.execute("SELECT 1 FROM users WHERE id=? AND active=1",(peer,)).fetchone(): raise ValueError("Choose an active colleague.")
                c.execute("INSERT INTO messages(sender_id,receiver_id,body,created_at) VALUES(?,?,?,?)",(u["id"],peer,body,stamp()))
                c.execute("UPDATE users SET last_seen=? WHERE id=?",(stamp(),u["id"]))
            self.send_bytes(200,json.dumps({"ok":True}).encode(),"application/json"); return
        if path!="/api/call": raise ValueError("Unknown call action.")
        action=str(d.get("action","")); call_id=str(d.get("call_id","")); now=stamp()
        with connect() as c:
            if action=="start":
                target=int(str(d.get("to","0")))
                if target==u["id"] or not c.execute("SELECT 1 FROM users WHERE id=? AND active=1",(target,)).fetchone(): raise ValueError("Choose an active colleague.")
                call_id=uuid.uuid4().hex
                c.execute("INSERT INTO calls(id,caller_id,recipient_id,state,created_at,updated_at) VALUES(?,?,?,'ringing',?,?)",(call_id,u["id"],target,now,now))
            call=c.execute("SELECT * FROM calls WHERE id=? AND (caller_id=? OR recipient_id=?)",(call_id,u["id"],u["id"])).fetchone()
            if not call: raise ValueError("Call was not found.")
            peer=call["recipient_id"] if call["caller_id"]==u["id"] else call["caller_id"]
            if action=="accept": c.execute("UPDATE calls SET state='active',updated_at=? WHERE id=?",(now,call_id))
            elif action in ("decline","end"): c.execute("UPDATE calls SET state=?,updated_at=? WHERE id=?",(action+"ed" if action=="decline" else "ended",now,call_id))
            elif action=="signal":
                payload=d.get("payload","")
                if isinstance(payload,dict): payload=json.dumps(payload)
                if len(str(payload))>200000: raise ValueError("Call signal is too large.")
                c.execute("INSERT INTO call_signals(call_id,sender_id,recipient_id,payload,created_at) VALUES(?,?,?,?,?)",(call_id,u["id"],peer,str(payload),now))
            else: raise ValueError("Unsupported call action.")
        self.send_bytes(200,json.dumps({"ok":True,"call_id":call_id,"peer_id":peer}).encode(),"application/json")


def serve() -> None:
    init_db()
    class Server(ThreadingHTTPServer):
        daemon_threads=True
        allow_reuse_address=True
    server=Server((HOST,PORT),Handler)
    if TLS_CERT and TLS_KEY:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(TLS_CERT,TLS_KEY)
        server.socket=context.wrap_socket(server.socket,server_side=True)
        print("HTTPS is enabled; install the issuing certificate on client PCs for trusted camera/microphone access.",flush=True)
    print(f"MMC Offline System listening at http://{HOST}:{PORT}/; database={DB_PATH}",flush=True)
    try: server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=="__main__": serve()
