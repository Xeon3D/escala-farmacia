#!/usr/bin/env python3
"""Escala da Farmácia — servidor local.

Aplicação web com base de dados SQLite, sem dependências externas:
apenas a biblioteca padrão do Python.

    python server.py            # http://localhost:8765
    python server.py --port 9000 --no-browser
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DB_PATH = Path(os.environ.get("ESCALA_DB") or ROOT / "escala.db")

ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,60}$")
WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_SHIFTS = [
    {"id": "s9",  "name": "Abertura",         "short": "9h",  "start": "09:00", "end": "18:00", "lunch": True,  "night": False, "onlyDuty": False, "weekday": 1, "weekend": 1},
    {"id": "s10", "name": "Intermédio",       "short": "10h", "start": "10:00", "end": "19:00", "lunch": True,  "night": False, "onlyDuty": False, "weekday": 1, "weekend": 0},
    {"id": "s11", "name": "Fecho",            "short": "11h", "start": "11:00", "end": "20:00", "lunch": True,  "night": False, "onlyDuty": False, "weekday": 2, "weekend": 1},
    {"id": "N",   "name": "Noite de serviço", "short": "N",   "start": "19:00", "end": "07:00", "lunch": False, "night": True,  "onlyDuty": True,  "weekday": 1, "weekend": 1},
]

DEFAULT_SETTINGS = {
    "lunchFrom": "12:00",
    "lunchTo": "16:00",
    "lunchMin": 60,
    "minPresent": 1,
    "minRest": 11,
    "doubleFrom": "22:00",
    "doubleTo": "09:00",
    "doubleFactor": 2,
    "dutyAnchorWeek": "2026-09-14",
    "dutyAnchorDay": 6,
    "dutyStep": 1,
}

# Equipa de exemplo, criada só quando a base de dados está vazia, para a aplicação
# abrir com alguma coisa. Apaga-a e mete a tua equipa real.
SEED_EMPLOYEES = [
    ("ex1", "Helena Marques", "Farmacêutica diretora técnica", "#0A7A5A", 0, 0, ["s9"], [], 5, {"0": "s9", "1": "s9", "2": "s9", "3": "s9", "4": "s9"}, "Exemplo"),
    ("ex2", "Rui Tavares", "Farmacêutico", "#2F7FC1", 1, 1, ["s11", "N"], [], 5, {}, "Exemplo"),
    ("ex3", "Sofia Almeida", "Técnica de farmácia", "#B4458C", 0, 1, ["s9", "s11"], [2], 5, {}, "Exemplo · às quartas tem formação"),
    ("ex4", "Tiago Fonseca", "Técnico de farmácia", "#5552C2", 1, 1, ["N"], [], 5, {}, "Exemplo"),
    ("ex5", "Marta Pinheiro", "Técnica auxiliar de farmácia", "#C0622B", 0, 1, ["s11"], [], 4, {}, "Exemplo · part-time"),
    ("ex6", "Diogo Ramos", "Farmacêutico", "#3E7F8C", 1, 1, ["s10", "N"], [], 5, {}, "Exemplo"),
    ("ex7", "Inês Carvalho", "Técnica de farmácia", "#6B5B95", 0, 1, ["s9", "s11"], [], 5, {}, "Exemplo"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT '',
  color         TEXT NOT NULL DEFAULT '#0A7A5A',
  accepts_night INTEGER NOT NULL DEFAULT 0,
  accepts_weekend INTEGER NOT NULL DEFAULT 1,
  preferred     TEXT NOT NULL DEFAULT '[]',
  days_off      TEXT NOT NULL DEFAULT '[]',
  max_per_week  INTEGER NOT NULL DEFAULT 5,
  fixed         TEXT NOT NULL DEFAULT '{}',
  notes         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS shifts (
  id        TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  short     TEXT NOT NULL DEFAULT '',
  start     TEXT NOT NULL,
  end       TEXT NOT NULL,
  lunch     INTEGER NOT NULL DEFAULT 1,
  night     INTEGER NOT NULL DEFAULT 0,
  only_duty INTEGER NOT NULL DEFAULT 0,
  weekday   INTEGER NOT NULL DEFAULT 0,
  weekend   INTEGER NOT NULL DEFAULT 0,
  position  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS assignments (
  week     TEXT NOT NULL,
  day      INTEGER NOT NULL,
  emp_id   TEXT NOT NULL,
  shift_id TEXT NOT NULL,
  lunch    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (week, day, emp_id),
  FOREIGN KEY (emp_id) REFERENCES employees(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_assignments_week ON assignments(week);
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

lock = threading.Lock()
conn: sqlite3.Connection


def connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA)
    return c


def init_data() -> None:
    with lock:
        if not conn.execute("SELECT 1 FROM shifts LIMIT 1").fetchone():
            for i, s in enumerate(DEFAULT_SHIFTS):
                conn.execute(
                    "INSERT INTO shifts (id,name,short,start,end,lunch,night,only_duty,weekday,weekend,position)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (s["id"], s["name"], s["short"], s["start"], s["end"], int(s["lunch"]),
                     int(s["night"]), int(s["onlyDuty"]), s["weekday"], s["weekend"], i),
                )
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, json.dumps(v)))
        if not conn.execute("SELECT 1 FROM employees LIMIT 1").fetchone():
            for (eid, name, role, color, night, weekend, pref, off, mx, fixed, notes) in SEED_EMPLOYEES:
                conn.execute(
                    "INSERT INTO employees (id,name,role,color,accepts_night,accepts_weekend,preferred,days_off,max_per_week,fixed,notes)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, name, role, color, night, weekend, json.dumps(pref), json.dumps(off), mx, json.dumps(fixed), notes),
                )
        conn.commit()


# ---------------------------------------------------------------- leitura

def read_state() -> dict:
    with lock:
        shifts = [
            {
                "id": r["id"], "name": r["name"], "short": r["short"], "start": r["start"], "end": r["end"],
                "lunch": bool(r["lunch"]), "night": bool(r["night"]), "onlyDuty": bool(r["only_duty"]),
                "weekday": r["weekday"], "weekend": r["weekend"],
            }
            for r in conn.execute("SELECT * FROM shifts ORDER BY position, start")
        ]
        settings = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM settings")}
        employees = {
            r["id"]: {
                "name": r["name"], "role": r["role"], "color": r["color"],
                "acceptsNight": bool(r["accepts_night"]), "acceptsWeekend": bool(r["accepts_weekend"]),
                "preferred": json.loads(r["preferred"]), "daysOff": json.loads(r["days_off"]),
                "maxPerWeek": r["max_per_week"], "fixed": json.loads(r["fixed"]), "notes": r["notes"],
            }
            for r in conn.execute("SELECT * FROM employees")
        }
        schedules: dict[str, dict] = {}
        for r in conn.execute("SELECT * FROM assignments"):
            week = schedules.setdefault(r["week"], {"cells": {}})
            cell = {"s": r["shift_id"]}
            if r["lunch"]:
                cell["l"] = r["lunch"]
            week["cells"].setdefault(r["emp_id"], {})[str(r["day"])] = cell
    config = dict(settings)
    config["shifts"] = shifts
    return {"config": config, "employees": employees, "schedules": schedules}


# ---------------------------------------------------------------- escrita

def save_employee(eid: str, e: dict) -> None:
    with lock:
        conn.execute(
            "INSERT INTO employees (id,name,role,color,accepts_night,accepts_weekend,preferred,days_off,max_per_week,fixed,notes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role, color=excluded.color,"
            " accepts_night=excluded.accepts_night, accepts_weekend=excluded.accepts_weekend,"
            " preferred=excluded.preferred, days_off=excluded.days_off, max_per_week=excluded.max_per_week,"
            " fixed=excluded.fixed, notes=excluded.notes",
            (
                eid, str(e.get("name", ""))[:80], str(e.get("role", ""))[:80], str(e.get("color", "#0A7A5A"))[:20],
                int(bool(e.get("acceptsNight"))), int(bool(e.get("acceptsWeekend"))),
                json.dumps(e.get("preferred") or []), json.dumps(e.get("daysOff") or []),
                max(1, min(7, int(e.get("maxPerWeek") or 5))), json.dumps(e.get("fixed") or {}),
                str(e.get("notes", ""))[:500],
            ),
        )
        conn.commit()


def delete_employee(eid: str) -> None:
    with lock:
        conn.execute("DELETE FROM assignments WHERE emp_id=?", (eid,))
        conn.execute("DELETE FROM employees WHERE id=?", (eid,))
        conn.commit()


def save_week(week: str, cells: dict) -> None:
    rows = []
    for emp_id, days in (cells or {}).items():
        if not ID_RE.match(str(emp_id)):
            continue
        for day, cell in (days or {}).items():
            try:
                d = int(day)
            except (TypeError, ValueError):
                continue
            if not 0 <= d <= 6 or not cell:
                continue
            sid = cell if isinstance(cell, str) else cell.get("s")
            if not sid:
                continue
            lunch = "" if isinstance(cell, str) else str(cell.get("l") or "")[:5]
            rows.append((week, d, str(emp_id), str(sid)[:60], lunch))
    with lock:
        conn.execute("DELETE FROM assignments WHERE week=?", (week,))
        conn.executemany(
            "INSERT OR REPLACE INTO assignments (week,day,emp_id,shift_id,lunch) VALUES (?,?,?,?,?)", rows
        )
        conn.commit()


def save_config(cfg: dict) -> None:
    shifts = cfg.get("shifts") or []
    with lock:
        conn.execute("DELETE FROM shifts")
        for i, s in enumerate(shifts):
            sid = str(s.get("id") or "")[:60]
            if not ID_RE.match(sid):
                continue
            conn.execute(
                "INSERT OR REPLACE INTO shifts (id,name,short,start,end,lunch,night,only_duty,weekday,weekend,position)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, str(s.get("name", ""))[:60], str(s.get("short", ""))[:8],
                 str(s.get("start", "09:00"))[:5], str(s.get("end", "18:00"))[:5],
                 int(bool(s.get("lunch"))), int(bool(s.get("night"))), int(bool(s.get("onlyDuty"))),
                 max(0, int(s.get("weekday") or 0)), max(0, int(s.get("weekend") or 0)), i),
            )
        for k in DEFAULT_SETTINGS:
            if k in cfg:
                conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, json.dumps(cfg[k])))
        conn.commit()


def import_state(data: dict) -> None:
    if data.get("config"):
        save_config(data["config"])
    if isinstance(data.get("employees"), dict):
        with lock:
            conn.execute("DELETE FROM employees")
            conn.commit()
        for eid, e in data["employees"].items():
            if ID_RE.match(str(eid)):
                save_employee(str(eid), e)
    if isinstance(data.get("schedules"), dict):
        with lock:
            conn.execute("DELETE FROM assignments")
            conn.commit()
        for week, sched in data["schedules"].items():
            if WEEK_RE.match(str(week)):
                save_week(str(week), (sched or {}).get("cells") or {})


# ---------------------------------------------------------------- HTTP

PAGE_TEMPLATE = """<!doctype html>
<html lang="pt-PT">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
:root{color-scheme:light dark;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
body{margin:0;font:14px system-ui,sans-serif;background:#fafaf9}
img{max-width:100%}
[hidden]{display:none!important}
</style>
{body}
</html>
"""


def page_html() -> bytes:
    fragment = (PUBLIC / "app.html").read_text(encoding="utf-8")
    return PAGE_TEMPLATE.replace("{body}", fragment).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "EscalaFarmacia/1.0"

    def log_message(self, fmt, *args):  # menos ruído na consola
        if self.path.startswith("/api/") and self.command != "GET":
            print(f"{self.command} {self.path} → {args[1] if len(args) > 1 else ''}")

    # -- utilitários
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body: bytes, ctype: str, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 8_000_000:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    # -- rotas
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                return self.send_bytes(page_html(), "text/html; charset=utf-8")
            except OSError:
                return self.send_bytes(b"public/app.html not found", "text/plain; charset=utf-8", 500)
        if path == "/api/health":
            return self.send_json({"ok": True})
        if path == "/api/state":
            return self.send_json(read_state())
        if path == "/api/export":
            data = read_state()
            body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="escala.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == "/favicon.ico":
            return self.send_bytes(b"", "image/x-icon", 204)
        return self.send_json({"error": "not_found"}, 404)

    def do_PUT(self):
        path = self.path.split("?", 1)[0]
        data = self.read_json()
        if data is None:
            return self.send_json({"error": "invalid_json"}, 400)
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[:2] == ["api", "employees"]:
            if not ID_RE.match(parts[2]):
                return self.send_json({"error": "invalid_id"}, 400)
            if not str(data.get("name", "")).strip():
                return self.send_json({"error": "name_required"}, 400)
            save_employee(parts[2], data)
            return self.send_json({"ok": True})
        if len(parts) == 3 and parts[:2] == ["api", "weeks"]:
            if not WEEK_RE.match(parts[2]):
                return self.send_json({"error": "invalid_week"}, 400)
            save_week(parts[2], data.get("cells") or {})
            return self.send_json({"ok": True})
        if parts == ["api", "config"]:
            save_config(data)
            return self.send_json({"ok": True})
        return self.send_json({"error": "not_found"}, 404)

    def do_POST(self):
        if self.path.split("?", 1)[0] == "/api/import":
            data = self.read_json()
            if not isinstance(data, dict):
                return self.send_json({"error": "invalid_json"}, 400)
            import_state(data)
            return self.send_json({"ok": True})
        return self.send_json({"error": "not_found"}, 404)

    def do_DELETE(self):
        parts = [p for p in self.path.split("?", 1)[0].split("/") if p]
        if len(parts) == 3 and parts[:2] == ["api", "employees"] and ID_RE.match(parts[2]):
            delete_employee(parts[2])
            return self.send_json({"ok": True})
        return self.send_json({"error": "not_found"}, 404)


def main():
    global conn
    ap = argparse.ArgumentParser(description="Servidor da Escala da Farmácia")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ESCALA_PORT") or 8765))
    ap.add_argument("--host", default=os.environ.get("ESCALA_HOST") or "127.0.0.1")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if os.environ.get("ESCALA_NO_BROWSER"):
        args.no_browser = True

    conn = connect(Path(args.db))
    init_data()

    # Consolas antigas em Windows usam cp1252 e rebentam com acentos.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    url = f"http://{args.host}:{args.port}/"
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Escala da Farmácia  ->  {url}")
    print(f"Base de dados: {Path(args.db).resolve()}")
    print("Ctrl+C para parar.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")
    finally:
        httpd.server_close()
        conn.close()


if __name__ == "__main__":
    main()
