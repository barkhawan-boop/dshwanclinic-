#!/usr/bin/env python3
"""Copy core records from the former MMC Clinic Desk SQLite schema.

Usage: python migrate_legacy_db.py OLD_DB OUTPUT_DB
Run while the old server is stopped, after taking a backup. The app source does
not include or package either database.
"""
from __future__ import annotations
import importlib.util, json, os, sqlite3, sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if len(sys.argv) != 3:
    raise SystemExit("Usage: python migrate_legacy_db.py OLD_DB OUTPUT_DB")
old_path, new_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
if old_path == new_path or not old_path.is_file():
    raise SystemExit("Provide an existing legacy database and a different output path.")
os.environ["MMC_DB_PATH"] = str(new_path)
spec = importlib.util.spec_from_file_location("mmc_app", APP_DIR / "app.py")
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)
app.init_db()
old = sqlite3.connect(f"file:{old_path.as_posix()}?mode=ro", uri=True)
old.row_factory = sqlite3.Row
new = sqlite3.connect(new_path)
new.row_factory = sqlite3.Row
new.execute("PRAGMA foreign_keys=ON")

def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
legacy_tables = tables(old)
if not {"users", "patients"}.issubset(legacy_tables):
    raise SystemExit("This does not look like the former MMC Clinic Desk database.")
users = old.execute("SELECT * FROM users").fetchall()
user_map = {}
for u in users:
    current = new.execute("SELECT id FROM users WHERE name=?", (u["name"],)).fetchone()
    if current:
        nid = current["id"]
        if "pin_salt" in u.keys() and "pin_hash" in u.keys() and u["pin_salt"] and u["pin_hash"]:
            new.execute("UPDATE users SET pin_salt=?,pin_hash=? WHERE id=?", (u["pin_salt"],u["pin_hash"],nid))
    else:
        # Keep an unrecognized legacy account but disable it until IT assigns its role/department.
        role = u["role"] if u["role"] in {"doctor","resident","nurse","secretary","head_secretary","lab","pharmacy","accountant","hr","admin","staff"} else "staff"
        salt = u["pin_salt"] if "pin_salt" in u.keys() else None
        digest = u["pin_hash"] if "pin_hash" in u.keys() else None
        if not salt or not digest:
            continue
        new.execute("INSERT INTO users(name,role,pin_salt,pin_hash,active,created_at) VALUES(?,?,?,?,0,?)", (u["name"],role,salt,digest,app.stamp()))
        nid = new.execute("SELECT last_insert_rowid()").fetchone()[0]
    user_map[u["id"]] = nid

patients = old.execute("SELECT * FROM patients ORDER BY id").fetchall()
for p in patients:
    keys = set(p.keys())
    name = p["name"]
    dob = p["birth_date"] if "birth_date" in keys else (p["dob"] if "dob" in keys else "")
    doctor_id = new.execute("SELECT id FROM users WHERE name='D.Shwan'").fetchone()
    created_by = user_map.get(p["created_by"]) if "created_by" in keys else None
    created_at = p["created_at"] if "created_at" in keys else app.stamp()
    status = "doctor" if ("resident_confirmed" in keys and p["resident_confirmed"]) else "waiting"
    new.execute("INSERT OR IGNORE INTO patients(id,code,name,dob,age,phone,doctor_id,registered_by,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (p["id"],p["code"],name,dob or "",p["age"],p["phone"] or "",doctor_id["id"] if doctor_id else None,created_by,status,created_at,created_at))
    history = {}
    for source, label in [("previous_drugs","Previous drugs"),("surgeries","Surgeries"),("medical_history","Medical history"),("other_information","Other information")]:
        if source in keys and p[source]: history[label] = p[source]
    if "resident_form_data" in keys and p["resident_form_data"]:
        try:
            saved = json.loads(p["resident_form_data"])
            if isinstance(saved, dict): history.update({str(k):v for k,v in saved.items()})
            else: history["Previous resident form"] = saved
        except (ValueError, TypeError): history["Previous resident form"] = p["resident_form_data"]
    if history or ("blood_pressure" in keys and p["blood_pressure"]):
        resident = new.execute("SELECT id FROM users WHERE name='Resident doctor'").fetchone()
        new.execute("INSERT INTO intake(patient_id,recorded_by,bp,questions,notes,created_at) VALUES(?,?,?,?,?,?)",
                    (p["id"],resident["id"] if resident else None,p["blood_pressure"] if "blood_pressure" in keys else "",json.dumps(history,ensure_ascii=False),"Imported from the prior MMC system.",created_at))

if "notifications" in legacy_tables:
    cols = {r[1] for r in old.execute("PRAGMA table_info(notifications)")}
    for n in old.execute("SELECT * FROM notifications"):
        uid = user_map.get(n["user_id"])
        if uid:
            patient_id = n["patient_id"] if "patient_id" in cols else None
            new.execute("INSERT INTO notifications(user_id,patient_id,message,created_at,read_at) VALUES(?,?,?,?,?)",(uid,patient_id,n["message"],n["created_at"],n["read_at"] if "read_at" in cols else None))
new.commit()
print(f"Migrated {len(patients)} patient record(s), {len(user_map)} account(s), and legacy notifications. Sessions were intentionally reset.")
old.close(); new.close()
