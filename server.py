#!/usr/bin/env python3
"""Escala da Farmácia — servidor local.

Aplicação web com base de dados SQLite, sem dependências externas:
apenas a biblioteca padrão do Python.

    python server.py            # http://localhost:8765
    python server.py --port 9000 --no-browser
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_VERSION = "1.6.11"

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DB_PATH = Path(os.environ.get("ESCALA_DB") or ROOT / "escala.db")

# Atualizações: o código novo é guardado no volume de dados, ao lado da base de
# dados, para sobreviver à recriação do contentor.
APP_DIR = Path(os.environ.get("ESCALA_APP_DIR") or DB_PATH.parent / "app")
UPDATE_REPO = os.environ.get("ESCALA_UPDATE_REPO", "Xeon3D/escala-farmacia")
UPDATE_REF = os.environ.get("ESCALA_UPDATE_REF", "main")
UPDATES_ENABLED = os.environ.get("ESCALA_UPDATES", "1") not in ("0", "false", "off")
MAX_DOWNLOAD = 20 * 1024 * 1024

ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,60}$")
WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_SHIFTS = [
    {"id": "s9",  "name": "Abertura",         "short": "9h",  "start": "09:00", "end": "18:00", "lunch": True,  "night": False, "onlyDuty": False, "weekday": 1, "weekend": 2, "saturday": 2},
    {"id": "s10", "name": "Intermédio",       "short": "10h", "start": "10:00", "end": "19:00", "lunch": True,  "night": False, "onlyDuty": False, "weekday": 1, "weekend": 0, "saturday": 0},
    {"id": "s11", "name": "Fecho",            "short": "11h", "start": "10:30", "end": "19:30", "lunch": True,  "night": False, "onlyDuty": False, "weekday": 2, "weekend": 1, "saturday": 1},
    {"id": "N",   "name": "Noite de serviço", "short": "N",   "start": "19:00", "end": "09:00", "lunch": False, "night": True,  "onlyDuty": True,  "weekday": 1, "weekend": 1, "saturday": 1},
    {"id": "BO",  "name": "Backoffice",        "short": "BO",  "start": "09:00", "end": "18:00", "lunch": True,  "night": False, "onlyDuty": False, "weekday": 0, "weekend": 0, "saturday": 0, "back": True},
]

DEFAULT_SETTINGS = {
    "lunchFrom": "12:00",
    "lunchTo": "16:00",
    "lunchMin": 60,
    "lunchMax": 120,
    # Quem está em backoffice almoça sempre a esta hora, com a duração mínima.
    "backLunchAt": "12:00",
    # Mostrar as linhas de contagem no fundo da escala.
    "showCounts": True,
    # Feriados: nacionais, o municipal da localidade e os acrescentados à mão.
    "holidays": True,
    "town": "",
    "townHoliday": "",
    "extraHolidays": [],
    "minPresent": 3,
    "minRest": 11,
    "doubleFrom": "22:00",
    "doubleTo": "09:00",
    "doubleFactor": 2,
    "weeklyHours": 40,
    "dayHours": 8,
    "backofficePerDay": 1,
    "dutyAnchorWeek": "2026-09-21",
    "dutyAnchorDay": 0,
    "dutyStep": -1,
    # Horário de abertura, de segunda (índice 0) a domingo; "closed" marca o encerramento semanal.
    "opening": [{"open": "09:00", "close": "19:30", "closed": False} for _ in range(5)]
               + [{"open": "09:00", "close": "13:00", "closed": False}, {"open": "09:00", "close": "20:00", "closed": True}],
    # Períodos com outro mínimo ao balcão: [{"from": "12:00", "to": "16:00", "min": 2}]
    "presenceBands": [{"from": "12:00", "to": "16:00", "min": 2}, {"from": "19:00", "to": "19:30", "min": 2}],
    # Aparência: título, subtítulo e logótipo (data URL de imagem, até ~200 KB).
    "siteTitle": "Escala da Farmácia",
    "siteTagline": "",
    "siteLogo": "",
    # Verificação automática de novas versões: off, 6h, 12h, 24h, week, month.
    "updateCheck": "week",
    # Pessoas escaladas ao sábado (a farmácia só abre de manhã).
    "saturdayPeople": 2,
    # A noite de serviço ao fim de semana começa a esta hora (nos dias úteis vale a hora do turno).
    "nightWeekendStart": "18:00",
}
UPDATE_INTERVALS = {"off": 0, "6h": 6 * 3600, "12h": 12 * 3600, "24h": 86400, "week": 7 * 86400, "month": 30 * 86400}
LOGO_RE = re.compile(r"^data:image/(png|jpeg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=]+$")

# Equipa de exemplo, criada só quando a base de dados está vazia, para a aplicação
# abrir com alguma coisa. Apaga-a e mete a tua equipa real.
# (id, nome, função, cor, aceita noites, aceita fins de semana, preferidos, dias indisponíveis, máx. (sem uso), fixos, notas, backoffice)
SEED_EMPLOYEES = [
    ("ex1", "Carla",     "Técnico(a) de farmácia", "#0A7A5A", 0, 1, [], [], 5, {}, "Exemplo", 0),
    ("ex2", "Liliana",   "Técnico(a) de farmácia", "#2F7FC1", 1, 0, [], [], 5, {}, "Exemplo", 0),
    ("ex3", "Bruno",     "Técnico(a) de farmácia", "#B4458C", 1, 0, [], [], 5, {}, "Exemplo", 0),
    ("ex4", "Alexandra", "Técnico(a) de farmácia", "#5552C2", 1, 1, [], [], 5, {}, "Exemplo", 0),
    ("ex5", "Fernanda",  "Técnico(a) de farmácia", "#C0622B", 0, 1, [], [], 5, {}, "Exemplo", 0),
    ("ex6", "Filipa",    "Técnico(a) de farmácia", "#3E7F8C", 0, 1, [], [], 5, {}, "Exemplo", 0),
    ("ex7", "Cátia",     "Administrativo(a)",      "#6B5B95", 0, 0, [], [], 5, {"0": "BO", "1": "BO", "2": "BO", "3": "BO", "4": "BO"}, "Exemplo · backoffice", 1),
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
  notes         TEXT NOT NULL DEFAULT '',
  weekly_hours  REAL,
  bank_initial  REAL NOT NULL DEFAULT 0,
  backoffice    INTEGER NOT NULL DEFAULT 0,
  extra         INTEGER NOT NULL DEFAULT 0
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
  saturday  INTEGER,
  back      INTEGER NOT NULL DEFAULT 0,
  no_clip   INTEGER NOT NULL DEFAULT 0,
  position  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS assignments (
  week     TEXT NOT NULL,
  day      INTEGER NOT NULL,
  emp_id   TEXT NOT NULL,
  shift_id TEXT NOT NULL DEFAULT '',
  lunch    TEXT NOT NULL DEFAULT '',
  pay      TEXT NOT NULL DEFAULT '',
  bank_hours REAL NOT NULL DEFAULT 0,
  post     TEXT NOT NULL DEFAULT '',
  kind     TEXT NOT NULL DEFAULT '',
  hrs      REAL NOT NULL DEFAULT 0,
  start    TEXT NOT NULL DEFAULT '',
  less     REAL NOT NULL DEFAULT 0,
  locked   INTEGER NOT NULL DEFAULT 0,
  lunch_dur INTEGER NOT NULL DEFAULT 0,
  c_from   TEXT NOT NULL DEFAULT '',
  c_to     TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (week, day, emp_id),
  FOREIGN KEY (emp_id) REFERENCES employees(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_assignments_week ON assignments(week);
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id         TEXT PRIMARY KEY,
  username   TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name       TEXT NOT NULL DEFAULT '',
  role       TEXT NOT NULL DEFAULT 'viewer',
  pw_salt    TEXT NOT NULL,
  pw_hash    TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  avatar     TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at REAL NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

COOKIE = "escala_session"
SESSION_DAYS = 30
PBKDF_ROUNDS = 240_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")

lock = threading.Lock()
conn: sqlite3.Connection


def connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA)
    return c


def migrate() -> None:
    """Acrescenta colunas novas a bases de dados criadas por versões anteriores."""
    additions = {
        "employees": {"weekly_hours": "REAL", "bank_initial": "REAL NOT NULL DEFAULT 0",
                      "backoffice": "INTEGER NOT NULL DEFAULT 0", "extra": "INTEGER NOT NULL DEFAULT 0"},
        "assignments": {"pay": "TEXT NOT NULL DEFAULT ''", "bank_hours": "REAL NOT NULL DEFAULT 0",
                        "post": "TEXT NOT NULL DEFAULT ''", "kind": "TEXT NOT NULL DEFAULT ''",
                        "hrs": "REAL NOT NULL DEFAULT 0", "start": "TEXT NOT NULL DEFAULT ''",
                        "less": "REAL NOT NULL DEFAULT 0", "locked": "INTEGER NOT NULL DEFAULT 0",
                        "lunch_dur": "INTEGER NOT NULL DEFAULT 0",
                        "c_from": "TEXT NOT NULL DEFAULT ''", "c_to": "TEXT NOT NULL DEFAULT ''"},
        "users": {"avatar": "TEXT NOT NULL DEFAULT ''"},
        "shifts": {"saturday": "INTEGER", "back": "INTEGER NOT NULL DEFAULT 0",
                   "no_clip": "INTEGER NOT NULL DEFAULT 0"},
    }
    with lock:
        for table, columns in additions.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                    print(f"Base de dados: coluna {table}.{name} acrescentada.")
        conn.commit()


def migrate_night_end() -> None:
    """Uma só vez: a noite de serviço passa a terminar às 09:00 (era 07:00) — a farmácia de
    plantão fica aberta até às 09:00 do dia seguinte. Só mexe em turnos que ainda estejam a 07:00."""
    if read_setting("_nightEnd09"):
        return
    with lock:
        rows = conn.execute("SELECT id,name FROM shifts WHERE night=1 AND end='07:00'").fetchall()
        for r in rows:
            conn.execute("UPDATE shifts SET end='09:00' WHERE id=?", (r["id"],))
            print(f"Base de dados: turno «{r['name']}» passa a terminar às 09:00.")
        conn.commit()
    write_setting("_nightEnd09", True)


def migrate_back_lunch() -> None:
    """Uma só vez: o almoço de quem está em backoffice passa a ser às 12:00 (era 13:00)."""
    if read_setting("_backLunch12"):
        return
    if str(read_setting("backLunchAt", "")) == "13:00":
        write_setting("backLunchAt", "12:00")
        print("Base de dados: o almoço do backoffice passa a ser às 12:00.")
    write_setting("_backLunch12", True)


def init_data() -> None:
    migrate()
    with lock:
        if not conn.execute("SELECT 1 FROM shifts LIMIT 1").fetchone():
            for i, s in enumerate(DEFAULT_SHIFTS):
                conn.execute(
                    "INSERT INTO shifts (id,name,short,start,end,lunch,night,only_duty,weekday,weekend,saturday,back,no_clip,position)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (s["id"], s["name"], s["short"], s["start"], s["end"], int(s["lunch"]),
                     int(s["night"]), int(s["onlyDuty"]), s["weekday"], s["weekend"], s["saturday"],
                     int(s.get("back", False)), int(s.get("noClip", False)), i),
                )
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, json.dumps(v)))
        conn.commit()
    migrate_night_end()
    migrate_back_lunch()
    with lock:
        if not conn.execute("SELECT 1 FROM employees LIMIT 1").fetchone():
            for (eid, name, role, color, night, weekend, pref, off, mx, fixed, notes, back) in SEED_EMPLOYEES:
                conn.execute(
                    "INSERT INTO employees (id,name,role,color,accepts_night,accepts_weekend,preferred,days_off,max_per_week,fixed,notes,backoffice)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, name, role, color, night, weekend, json.dumps(pref), json.dumps(off), mx, json.dumps(fixed), notes, back),
                )
        conn.commit()


# ---------------------------------------------------------- atualizações

def pointer_path() -> Path:
    return APP_DIR / "current.json"


def read_pointer() -> dict:
    try:
        return json.loads(pointer_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_pointer(data: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = pointer_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, pointer_path())


def version_of(server_file: Path) -> str:
    """Lê APP_VERSION de um ficheiro server.py sem o importar."""
    try:
        text = server_file.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return ""
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]{1,32})"', text, re.M)
    return m.group(1) if m else ""


def installed_dir() -> Path | None:
    """Pasta da versão instalada no volume, se existir e estiver completa."""
    name = read_pointer().get("dir")
    if not name:
        return None
    d = APP_DIR / "versions" / name
    return d if (d / "server.py").is_file() and (d / "public" / "app.html").is_file() else None


def fetch(url: str, timeout: int = 30) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": f"escala-farmacia/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("ficheiro demasiado grande")
    return data


def version_key(v: str) -> tuple:
    """Ordena versões como 1.6.1 > 1.6.0 > 1.5.10."""
    return tuple(int(p) if p.isdigit() else -1 for p in re.split(r"[.\-]", v or ""))


def parse_changelog(text: str) -> list[dict]:
    """Lê o CHANGELOG.md: cabeçalhos '## 1.6.1 — 2026-09-20' seguidos de linhas '- item'."""
    out: list[dict] = []
    for line in text.splitlines():
        m = re.match(r"^##\s+v?([0-9][0-9A-Za-z.\-_]*)\s*(?:[—–-]\s*(.+))?$", line.strip())
        if m:
            out.append({"version": m.group(1), "date": (m.group(2) or "").strip()[:40], "items": []})
        elif out and re.match(r"^\s*[-*]\s+", line):
            item = re.sub(r"^\s*[-*]\s+", "", line).strip()
            if item:
                out[-1]["items"].append(item[:400])
        if len(out) > 50:
            break
    return [e for e in out if e["items"]]


def changes_since(entries: list[dict], current: str, until: str | None = None) -> list[dict]:
    """Entradas mais recentes do que a versão atual (e até à versão indicada)."""
    cur = version_key(current)
    top = version_key(until) if until else None
    return [e for e in entries if version_key(e["version"]) > cur and (top is None or version_key(e["version"]) <= top)]


def local_changelog() -> list[dict]:
    try:
        return parse_changelog((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    except OSError:
        return []


def latest_version() -> dict:
    """Versão publicada no repositório, lida do ficheiro VERSION, e as novidades do CHANGELOG.md."""
    base = f"https://raw.githubusercontent.com/{UPDATE_REPO}/{UPDATE_REF}"
    version = fetch(f"{base}/VERSION", timeout=15).decode("utf-8", "replace").strip()[:32]
    if not re.fullmatch(r"[0-9A-Za-z.\-_]{1,32}", version or ""):
        raise ValueError("o repositório não devolveu uma versão válida")
    changes: list[dict] = []
    try:
        changes = changes_since(parse_changelog(fetch(f"{base}/CHANGELOG.md", timeout=15).decode("utf-8", "replace")), APP_VERSION, version)
    except Exception:  # noqa: BLE001 - sem changelog não há drama
        pass
    return {"version": version, "repo": UPDATE_REPO, "ref": UPDATE_REF, "changes": changes}


# Estado da verificação automática, guardado nas settings com chave "_" (não vai para o cliente como regra).
def read_setting(key: str, default=None):
    with lock:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    try:
        return json.loads(row["value"]) if row else default
    except ValueError:
        return default


def write_setting(key: str, value) -> None:
    with lock:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, json.dumps(value)))
        conn.commit()


def auto_check_state() -> dict:
    st = read_setting("_updateCheck", {}) or {}
    interval = str(read_setting("updateCheck", DEFAULT_SETTINGS["updateCheck"]) or "off")
    st["interval"] = interval if interval in UPDATE_INTERVALS else "off"
    # Uma versão encontrada só é "nova" enquanto for mais recente do que a que está a correr.
    found = st.get("found")
    if found and version_key(found.get("version", "")) <= version_key(APP_VERSION):
        st["found"] = None
    return st


def run_auto_check() -> None:
    """Procura uma versão nova e guarda o resultado para a interface mostrar."""
    st = read_setting("_updateCheck", {}) or {}
    st["lastAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    st["lastTs"] = time.time()
    try:
        info = latest_version()
        st["error"] = None
        st["found"] = info if version_key(info["version"]) > version_key(APP_VERSION) else None
        if st["found"]:
            print(f"Verificação automática: há a versão {info['version']} disponível.")
    except Exception as e:  # noqa: BLE001 - rede ou GitHub em baixo
        st["error"] = str(e)[:200]
    write_setting("_updateCheck", st)


def auto_check_loop() -> None:
    while True:
        try:
            interval = UPDATE_INTERVALS.get(str(read_setting("updateCheck", "week")), 0)
            last = float((read_setting("_updateCheck", {}) or {}).get("lastTs") or 0)
            if interval and time.time() - last >= interval:
                run_auto_check()
        except Exception as e:  # noqa: BLE001 - nunca deixar a thread morrer
            print(f"Verificação automática falhou: {e}")
        time.sleep(60)


def install_update(ref: str | None = None) -> dict:
    """Descarrega o código do repositório e instala-o no volume de dados."""
    import io
    import tarfile

    ref = ref or UPDATE_REF
    raw = fetch(f"https://codeload.github.com/{UPDATE_REPO}/tar.gz/{ref}", timeout=60)
    staging = APP_DIR / "staging"
    if staging.exists():
        _rmtree(staging)
    staging.mkdir(parents=True)

    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        members = []
        for m in tar.getmembers():
            if m.issym() or m.islnk() or not (m.isfile() or m.isdir()):
                continue
            parts = Path(m.name).parts[1:]  # o tar do GitHub tem uma pasta à cabeça
            if not parts or ".." in parts:
                continue
            rel = "/".join(parts)
            # Só o servidor e a interface: nada de workflows, Dockerfile ou testes.
            if not (rel in ("server.py", "VERSION", "CHANGELOG.md") or rel.startswith("public/")):
                continue
            if m.size > 5 * 1024 * 1024:
                continue
            m.name = rel
            members.append(m)
        tar.extractall(staging, members=members, filter="data")

    new_server = staging / "server.py"
    if not new_server.is_file() or not (staging / "public" / "app.html").is_file():
        _rmtree(staging)
        raise ValueError("o pacote não traz o server.py e o public/app.html")
    version = version_of(new_server)
    if not version:
        _rmtree(staging)
        raise ValueError("o server.py descarregado não declara a versão")
    try:
        compile(new_server.read_text(encoding="utf-8"), "server.py", "exec")
    except SyntaxError as e:
        _rmtree(staging)
        raise ValueError(f"o server.py descarregado tem um erro de sintaxe: {e}") from e

    name = f"{version}-{int(time.time())}"
    dest = APP_DIR / "versions" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _rmtree(dest)
    os.replace(staging, dest)

    previous = read_pointer()
    write_pointer({
        "dir": name,
        "version": version,
        "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "previous": previous.get("dir"),
        "previousVersion": previous.get("version") or APP_VERSION,
    })
    prune_versions()
    clear_boot_failed()
    try:
        (APP_DIR / "boot_attempts").write_text("0")
    except OSError:
        pass
    return {"version": version, "dir": name}


def rollback_update() -> dict:
    """Volta à versão anterior; sem versão anterior, volta à que vem na imagem."""
    clear_boot_failed()
    p = read_pointer()
    prev = p.get("previous")
    if prev and (APP_DIR / "versions" / prev / "server.py").is_file():
        write_pointer({
            "dir": prev,
            "version": version_of(APP_DIR / "versions" / prev / "server.py") or p.get("previousVersion", "?"),
            "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "previous": None, "previousVersion": None,
        })
        return {"version": read_pointer().get("version")}
    try:
        pointer_path().unlink()
    except OSError:
        pass
    return {"version": BASE_VERSION}


def prune_versions(keep: int = 3) -> None:
    root = APP_DIR / "versions"
    if not root.is_dir():
        return
    keep_names = {read_pointer().get("dir"), read_pointer().get("previous")}
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        if d.name not in keep_names:
            _rmtree(d)


def _rmtree(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def restart_process(delay: float = 0.8) -> None:
    """Reinicia o processo (sem recriar o contentor) para correr a versão apontada.

    Lança diretamente o server.py da versão instalada no volume (ou o da imagem, se o
    ponteiro foi apagado), sem depender do arranque da imagem — e com o ambiente certo:
    o ESCALA_BOOT_SCRIPT herdado de um processo que já corria do volume fazia o arranque
    da imagem pensar que já estava na versão do volume e nunca trocar.
    Se o exec falhar, termina o processo: em Docker o restart policy volta a arrancá-lo.
    """
    def go():
        time.sleep(delay)
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        exe = sys.executable or "python3"
        env = {k: v for k, v in os.environ.items() if k not in ("ESCALA_BOOT_SCRIPT", "ESCALA_BASE_VERSION")}
        target = installed_dir()
        if target is not None:
            script = str(target / "server.py")
            env.update(ESCALA_BOOT_SCRIPT=BOOT_SCRIPT, ESCALA_BASE_VERSION=BASE_VERSION)
        else:
            script = BOOT_SCRIPT
        print(f"A reiniciar: {exe} {script} {' '.join(BOOT_ARGS)}", flush=True)
        try:
            os.execve(exe, [exe, script, *BOOT_ARGS], env)
        except OSError as e:
            print(f"Não foi possível substituir o processo ({e}); a terminar para o Docker reiniciar.", flush=True)
            os._exit(1)
    threading.Thread(target=go, daemon=True).start()


# Guarda o ponto de partida para o reinício apontar sempre ao carregador da imagem.
BOOT_SCRIPT = os.environ.get("ESCALA_BOOT_SCRIPT") or str(Path(__file__).resolve())
BOOT_ARGS = sys.argv[1:]
BASE_VERSION = os.environ.get("ESCALA_BASE_VERSION") or APP_VERSION


def boot_overlay() -> bool:
    """Arranca a versão instalada no volume, se houver uma diferente desta."""
    if not UPDATES_ENABLED:
        return False
    # Só estamos "a correr do volume" se este ficheiro não for o carregador da imagem;
    # a variável de ambiente pode vir herdada de um reinício e não chega para decidir.
    if os.environ.get("ESCALA_BOOT_SCRIPT") and Path(__file__).resolve() != Path(BOOT_SCRIPT).resolve():
        return False
    d = installed_dir()
    if d is None:
        return False
    target = d / "server.py"
    if target.resolve() == Path(__file__).resolve():
        return False
    attempts_file = APP_DIR / "boot_attempts"
    try:
        attempts = int(attempts_file.read_text().strip() or 0)
    except (OSError, ValueError):
        attempts = 0
    if attempts >= 3:
        print(f"A versão instalada ({version_of(target)}) falhou a arrancar {attempts} vezes."
              f" A usar a versão da imagem ({APP_VERSION}). Usa a reversão na aplicação.", flush=True)
        # Fica registado para a interface explicar porque é que continua a correr a versão da imagem.
        try:
            (APP_DIR / "boot_failed.json").write_text(json.dumps({
                "version": version_of(target), "dir": d.name, "attempts": attempts,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }), encoding="utf-8")
        except OSError:
            pass
        return False
    try:
        attempts_file.write_text(str(attempts + 1))
    except OSError:
        pass
    env = dict(os.environ, ESCALA_BOOT_SCRIPT=BOOT_SCRIPT, ESCALA_BASE_VERSION=APP_VERSION)
    print(f"A arrancar a versão instalada {version_of(target)} a partir de {target} (tentativa {attempts + 1})", flush=True)
    try:
        os.execve(sys.executable or "python3", [sys.executable or "python3", str(target), *sys.argv[1:]], env)
    except OSError as e:
        print(f"Não foi possível arrancar a versão instalada ({e}); a usar a versão da imagem.", flush=True)
        return False
    return True  # inalcançável


def running_from_volume() -> bool:
    return bool(os.environ.get("ESCALA_BOOT_SCRIPT")) and Path(__file__).resolve() != Path(BOOT_SCRIPT).resolve()


def boot_ok() -> None:
    """Chamado quando o servidor está de pé: limpa o contador de tentativas."""
    try:
        (APP_DIR / "boot_attempts").write_text("0")
    except OSError:
        pass
    # Se é a versão do volume que está a correr, a falha anterior já não interessa.
    if running_from_volume():
        clear_boot_failed()


def clear_boot_failed() -> None:
    try:
        (APP_DIR / "boot_failed.json").unlink()
    except OSError:
        pass


def boot_failed() -> dict | None:
    try:
        return json.loads((APP_DIR / "boot_failed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------- autenticação

def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ROUNDS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF_ROUNDS)
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def user_count() -> int:
    with lock:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def public_user(row) -> dict:
    keys = row.keys()
    return {"id": row["id"], "username": row["username"], "name": row["name"],
            "role": row["role"], "createdAt": row["created_at"],
            "avatar": row["avatar"] if "avatar" in keys else ""}


def create_user(username: str, password: str, name: str, role: str) -> dict:
    salt, digest = hash_password(password)
    uid = "u" + secrets.token_hex(8)
    with lock:
        conn.execute(
            "INSERT INTO users (id,username,name,role,pw_salt,pw_hash) VALUES (?,?,?,?,?,?)",
            (uid, username, name[:80], role, salt, digest),
        )
        conn.commit()
        return public_user(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def set_password(uid: str, password: str) -> None:
    salt, digest = hash_password(password)
    with lock:
        conn.execute("UPDATE users SET pw_salt=?, pw_hash=? WHERE id=?", (salt, digest, uid))
        # Sessões antigas deixam de valer quando a palavra-passe muda.
        conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        conn.commit()


def open_session(uid: str) -> str:
    token = secrets.token_urlsafe(32)
    with lock:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        conn.execute(
            "INSERT INTO sessions (token_hash,user_id,expires_at) VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), uid, time.time() + SESSION_DAYS * 86400),
        )
        conn.commit()
    return token


def session_user(token: str):
    if not token:
        return None
    with lock:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ? AND s.expires_at > ?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ).fetchone()
    return row


def close_session(token: str) -> None:
    if not token:
        return
    with lock:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        conn.commit()


# Travão simples a tentativas de adivinhar palavras-passe.
_attempts: dict[str, list] = {}
_attempts_lock = threading.Lock()


def login_blocked(key: str) -> int:
    with _attempts_lock:
        count, until = _attempts.get(key, (0, 0.0))
        return max(0, int(until - time.time())) if count >= 8 else 0


def login_failed(key: str) -> None:
    with _attempts_lock:
        count, _ = _attempts.get(key, (0, 0.0))
        count += 1
        _attempts[key] = (count, time.time() + (60 if count >= 8 else 0))


def login_ok(key: str) -> None:
    with _attempts_lock:
        _attempts.pop(key, None)


def password_problem(password: str) -> str | None:
    if not isinstance(password, str) or len(password) < 8:
        return "A palavra-passe tem de ter pelo menos 8 caracteres."
    if len(password) > 200:
        return "A palavra-passe é demasiado longa."
    return None


# ---------------------------------------------------------------- leitura

def read_state() -> dict:
    with lock:
        shifts = [
            {
                "id": r["id"], "name": r["name"], "short": r["short"], "start": r["start"], "end": r["end"],
                "lunch": bool(r["lunch"]), "night": bool(r["night"]), "onlyDuty": bool(r["only_duty"]), "back": bool(r["back"]),
                "noClip": bool(r["no_clip"]),
                "weekday": r["weekday"], "weekend": r["weekend"], "saturday": r["saturday"],
            }
            for r in conn.execute("SELECT * FROM shifts ORDER BY position, start")
        ]
        settings = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM settings") if not r["key"].startswith("_")}
        employees = {
            r["id"]: {
                "name": r["name"], "role": r["role"], "color": r["color"],
                "acceptsNight": bool(r["accepts_night"]), "acceptsWeekend": bool(r["accepts_weekend"]),
                "preferred": json.loads(r["preferred"]), "daysOff": json.loads(r["days_off"]),
                "maxPerWeek": r["max_per_week"], "fixed": json.loads(r["fixed"]), "notes": r["notes"],
                "weeklyHours": r["weekly_hours"], "bankInitial": r["bank_initial"] or 0,
                "backoffice": bool(r["backoffice"]), "extra": bool(r["extra"]),
            }
            for r in conn.execute("SELECT * FROM employees")
        }
        schedules: dict[str, dict] = {}
        for r in conn.execute("SELECT * FROM assignments"):
            week = schedules.setdefault(r["week"], {"cells": {}})
            cell = {}
            if r["shift_id"]:
                cell["s"] = r["shift_id"]
            if r["lunch"]:
                cell["l"] = r["lunch"]
            if r["pay"]:
                cell["pay"] = r["pay"]
            if r["bank_hours"]:
                cell["bank"] = r["bank_hours"]
            if r["post"]:
                cell["post"] = r["post"]
            if r["kind"] == "vac":
                cell["vac"] = True
            elif r["kind"] == "sick":
                cell["sick"] = True
            elif r["kind"] == "xoff":
                cell["xoff"] = True
            if r["hrs"]:
                cell["hrs"] = r["hrs"]
            if r["start"]:
                cell["from"] = r["start"]
            if r["less"]:
                cell["less"] = r["less"]
            if r["locked"]:
                cell["lock"] = True
            if r["lunch_dur"]:
                cell["ld"] = r["lunch_dur"]
            if r["c_from"] and r["c_to"]:
                cell["cf"] = r["c_from"]
                cell["ct"] = r["c_to"]
            if cell:
                week["cells"].setdefault(r["emp_id"], {})[str(r["day"])] = cell
    config = dict(settings)
    config["shifts"] = shifts
    return {"config": config, "employees": employees, "schedules": schedules}


# ---------------------------------------------------------------- escrita

def save_employee(eid: str, e: dict) -> None:
    with lock:
        conn.execute(
            "INSERT INTO employees (id,name,role,color,accepts_night,accepts_weekend,preferred,days_off,max_per_week,fixed,notes,weekly_hours,bank_initial,backoffice,extra)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role, color=excluded.color,"
            " accepts_night=excluded.accepts_night, accepts_weekend=excluded.accepts_weekend,"
            " preferred=excluded.preferred, days_off=excluded.days_off, max_per_week=excluded.max_per_week,"
            " fixed=excluded.fixed, notes=excluded.notes, weekly_hours=excluded.weekly_hours,"
            " bank_initial=excluded.bank_initial, backoffice=excluded.backoffice, extra=excluded.extra",
            (
                eid, str(e.get("name", ""))[:80], str(e.get("role", ""))[:80], str(e.get("color", "#0A7A5A"))[:20],
                int(bool(e.get("acceptsNight"))), int(bool(e.get("acceptsWeekend"))),
                json.dumps(e.get("preferred") or []), json.dumps(e.get("daysOff") or []),
                max(1, min(7, int(e.get("maxPerWeek") or 5))), json.dumps(e.get("fixed") or {}),
                str(e.get("notes", ""))[:500],
                None if e.get("weeklyHours") in (None, "") else max(0.0, min(80.0, float(e["weeklyHours"]))),
                max(-2000.0, min(2000.0, float(e.get("bankInitial") or 0))),
                int(bool(e.get("backoffice"))), int(bool(e.get("extra"))),
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
            hrs, start, less, locked, ldur = 0.0, "", 0.0, 0, 0
            cfrom, cto = "", ""
            if isinstance(cell, str):
                sid, lunch, pay, bank, post, kind = cell, "", "", 0.0, "", ""
            else:
                sid = str(cell.get("s") or "")[:60]
                lunch = str(cell.get("l") or "")[:5]
                pay = "bank" if cell.get("pay") == "bank" else ""
                post = "back" if cell.get("post") == "back" else ""
                kind = "vac" if cell.get("vac") else "sick" if cell.get("sick") else "xoff" if cell.get("xoff") else ""
                try:
                    bank = max(0.0, min(24.0, float(cell.get("bank") or 0)))
                except (TypeError, ValueError):
                    bank = 0.0
                # Extras: horas avulsas e hora de entrada. Turnos: horas a menos.
                try:
                    hrs = 0.0 if sid else max(0.0, min(24.0, float(cell.get("hrs") or 0)))
                    # Ajuste do dia: positivo = horas a menos, negativo = horas a mais.
                    less = max(-12.0, min(24.0, float(cell.get("less") or 0))) if sid else 0.0
                except (TypeError, ValueError):
                    hrs, less = 0.0, 0.0
                start = str(cell.get("from") or "")[:5] if hrs else ""
                locked = int(bool(cell.get("lock")))
                try:
                    ldur = max(0, min(480, int(cell.get("ld") or 0)))
                except (TypeError, ValueError):
                    ldur = 0
                if post == "back":
                    cfrom = str(cell.get("cf") or "")[:5]
                    cto = str(cell.get("ct") or "")[:5]
            if not sid and not bank and not kind and not hrs and not locked:
                continue
            rows.append((week, d, str(emp_id), sid, lunch, pay, bank, post, kind, hrs, start, less, locked, ldur, cfrom, cto))
    with lock:
        conn.execute("DELETE FROM assignments WHERE week=?", (week,))
        conn.executemany(
            "INSERT OR REPLACE INTO assignments (week,day,emp_id,shift_id,lunch,pay,bank_hours,post,kind,hrs,start,less,locked,lunch_dur,c_from,c_to)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
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
                "INSERT OR REPLACE INTO shifts (id,name,short,start,end,lunch,night,only_duty,weekday,weekend,saturday,back,no_clip,position)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, str(s.get("name", ""))[:60], str(s.get("short", ""))[:8],
                 str(s.get("start", "09:00"))[:5], str(s.get("end", "18:00"))[:5],
                 int(bool(s.get("lunch"))), int(bool(s.get("night"))), int(bool(s.get("onlyDuty"))),
                 max(0, int(s.get("weekday") or 0)), max(0, int(s.get("weekend") or 0)),
                 None if s.get("saturday") in (None, "") else max(0, int(s.get("saturday") or 0)),
                 int(bool(s.get("back"))), int(bool(s.get("noClip"))), i),
            )
        for k in DEFAULT_SETTINGS:
            if k not in cfg:
                continue
            v = cfg[k]
            if k == "siteLogo":
                v = v if isinstance(v, str) and len(v) <= 300_000 and LOGO_RE.match(v) else ""
            elif k in ("siteTitle", "siteTagline"):
                v = str(v or "")[:100]
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, json.dumps(v)))
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
<title>{title}</title>
<style>
:root{color-scheme:light dark;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
body{margin:0;font:14px system-ui,sans-serif;background:#fafaf9}
img{max-width:100%}
[hidden]{display:none!important}
</style>
{body}
</html>
"""


def phrases() -> list[str]:
    """Piadas de public/frases.txt: separadas por uma linha «--»; podem ter várias linhas. Linhas com # ignoram-se."""
    try:
        text = (PUBLIC / "frases.txt").read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[str] = []
    for bloco in text.split("\n--"):
        linhas = [ln.strip() for ln in bloco.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if linhas:
            out.append("\n".join(linhas)[:400])
    return out


def daily_phrase() -> str:
    """Frase do dia, lida de public/frases.txt: a mesma durante todo o dia, muda à meia-noite."""
    frases = phrases()
    if not frases:
        return ""
    day = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)) // 86400)
    # Baralha de forma estável para não seguir a ordem do ficheiro.
    idx = int(hashlib.sha256(str(day).encode()).hexdigest(), 16) % len(frases)
    return frases[idx]


def random_phrase(not_this: str = "") -> str:
    """Outra frase ao acaso (diferente da atual, quando há mais do que uma)."""
    frases = phrases()
    pool = [f for f in frases if f != not_this] or frases
    return secrets.choice(pool) if pool else ""


def site_title() -> str:
    try:
        with lock:
            row = conn.execute("SELECT value FROM settings WHERE key='siteTitle'").fetchone()
        title = json.loads(row["value"]) if row else ""
    except (sqlite3.Error, ValueError):
        title = ""
    return str(title or "").strip() or DEFAULT_SETTINGS["siteTitle"]


def page_html() -> bytes:
    import html
    fragment = (PUBLIC / "app.html").read_text(encoding="utf-8")
    return PAGE_TEMPLATE.replace("{title}", html.escape(site_title())).replace("{body}", fragment).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "EscalaFarmacia/1.1"

    def log_message(self, fmt, *args):  # menos ruído na consola
        if self.path.startswith("/api/") and self.command != "GET":
            print(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    # -- utilitários
    def send_json(self, data, status=200, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    # -- sessão
    @property
    def token(self) -> str:
        raw = self.headers.get("Cookie")
        if not raw:
            return ""
        try:
            morsel = SimpleCookie(raw).get(COOKIE)
        except Exception:  # noqa: BLE001 - cookie malformado
            return ""
        return morsel.value if morsel else ""

    def cookie_header(self, token: str | None) -> str:
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        if token is None:
            return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{secure}"
        return (f"{COOKIE}={token}; Path=/; Max-Age={SESSION_DAYS * 86400};"
                f" HttpOnly; SameSite=Lax{secure}")

    def current_user(self):
        return session_user(self.token)

    def require(self, admin: bool):
        """Devolve o utilizador ou responde 401/403 e devolve None."""
        user = self.current_user()
        if user is None:
            self.send_json({"error": "unauthenticated", "setup": user_count() == 0}, 401)
            return None
        if admin and user["role"] != "admin":
            self.send_json({"error": "forbidden"}, 403)
            return None
        return user

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
            return self.send_json({"ok": True, "version": APP_VERSION})
        if path == "/api/frase":
            import urllib.parse
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            if q.get("random"):
                return self.send_json({"text": random_phrase((q.get("not") or [""])[0][:400])})
            return self.send_json({"text": daily_phrase()})
        if path == "/api/app":
            if not self.require(admin=False):
                return None
            p = read_pointer()
            return self.send_json({
                "version": APP_VERSION,
                "baseVersion": BASE_VERSION,
                "running": "volume" if running_from_volume() else "imagem",
                "installedAt": p.get("installedAt"),
                "previousVersion": p.get("previousVersion") if p.get("previous") else None,
                "canRollback": bool(p.get("previous")) or bool(p.get("dir")),
                "updatesEnabled": UPDATES_ENABLED,
                "repo": UPDATE_REPO, "ref": UPDATE_REF,
                "changes": [e for e in local_changelog() if e["version"] == APP_VERSION],
                "autoCheck": auto_check_state(),
                "bootFailed": boot_failed(),
            })
        if path == "/api/app/check":
            if not self.require(admin=True):
                return None
            if not UPDATES_ENABLED:
                return self.send_json({"error": "updates_disabled"}, 409)
            try:
                info = latest_version()
            except Exception as e:  # noqa: BLE001 - rede, DNS, GitHub em baixo
                return self.send_json({"error": "check_failed", "message": str(e)}, 502)
            info["current"] = APP_VERSION
            info["upToDate"] = version_key(info["version"]) <= version_key(APP_VERSION)
            st = read_setting("_updateCheck", {}) or {}
            st.update({"lastAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "lastTs": time.time(), "error": None,
                       "found": None if info["upToDate"] else info})
            write_setting("_updateCheck", st)
            return self.send_json(info)
        if path == "/api/me":
            user = self.current_user()
            if user is None:
                return self.send_json({"user": None, "setup": user_count() == 0})
            return self.send_json({"user": public_user(user), "setup": False})
        if path == "/api/users":
            if not self.require(admin=True):
                return None
            with lock:
                rows = conn.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE").fetchall()
            return self.send_json({"users": [public_user(r) for r in rows]})
        if path == "/api/state":
            if not self.require(admin=False):
                return None
            return self.send_json(read_state())
        if path == "/api/export":
            if not self.require(admin=False):
                return None
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
        if len(parts) == 3 and parts[:2] == ["api", "users"]:
            return self.update_user(parts[2], data)
        if not self.require(admin=True):
            return None
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
        path = self.path.split("?", 1)[0]
        data = self.read_json()
        if data is None and path not in ("/api/logout",):
            return self.send_json({"error": "invalid_json"}, 400)

        if path == "/api/setup":
            return self.do_setup(data)
        if path == "/api/login":
            return self.do_login(data)
        if path == "/api/logout":
            close_session(self.token)
            return self.send_json({"ok": True}, cookie=self.cookie_header(None))
        if path == "/api/password":
            return self.change_own_password(data)
        if path == "/api/avatar":
            return self.set_avatar(data)
        if path == "/api/avatar/fetch":
            return self.fetch_avatar(data)
        if path == "/api/users":
            return self.add_user(data)

        if not self.require(admin=True):
            return None
        if path == "/api/app/update":
            if not UPDATES_ENABLED:
                return self.send_json({"error": "updates_disabled"}, 409)
            ref = str((data or {}).get("ref") or UPDATE_REF)
            if not re.fullmatch(r"[0-9A-Za-z./\-_]{1,64}", ref):
                return self.send_json({"error": "invalid_ref"}, 400)
            try:
                result = install_update(ref)
            except Exception as e:  # noqa: BLE001 - rede ou pacote inválido
                return self.send_json({"error": "update_failed", "message": str(e)}, 502)
            print(f"Atualização instalada: {result['version']}. A reiniciar…")
            restart_process()
            return self.send_json({"ok": True, **result, "restarting": True})
        if path == "/api/app/rollback":
            result = rollback_update()
            print(f"Reversão para {result['version']}. A reiniciar…")
            restart_process()
            return self.send_json({"ok": True, **result, "restarting": True})
        if path == "/api/import":
            if not isinstance(data, dict):
                return self.send_json({"error": "invalid_json"}, 400)
            import_state(data)
            return self.send_json({"ok": True})
        return self.send_json({"error": "not_found"}, 404)

    def do_DELETE(self):
        parts = [p for p in self.path.split("?", 1)[0].split("/") if p]
        if len(parts) == 3 and parts[:2] == ["api", "users"]:
            return self.delete_user(parts[2])
        if not self.require(admin=True):
            return None
        if len(parts) == 3 and parts[:2] == ["api", "employees"] and ID_RE.match(parts[2]):
            delete_employee(parts[2])
            return self.send_json({"ok": True})
        return self.send_json({"error": "not_found"}, 404)

    # ------------------------------------------------------ contas

    def do_setup(self, data):
        """Cria o primeiro administrador. Só funciona com a base de dados sem contas."""
        if user_count() > 0:
            return self.send_json({"error": "already_set_up"}, 409)
        username = str((data or {}).get("username", "")).strip()
        password = (data or {}).get("password", "")
        if not USERNAME_RE.match(username):
            return self.send_json({"error": "invalid_username"}, 400)
        problem = password_problem(password)
        if problem:
            return self.send_json({"error": "weak_password", "message": problem}, 400)
        user = create_user(username, password, str((data or {}).get("name", "")).strip() or username, "admin")
        token = open_session(user["id"])
        return self.send_json({"user": user}, cookie=self.cookie_header(token))

    def do_login(self, data):
        username = str((data or {}).get("username", "")).strip()
        password = (data or {}).get("password", "")
        key = username.lower() or "?"
        wait = login_blocked(key)
        if wait:
            return self.send_json({"error": "too_many_attempts", "retryAfter": wait}, 429)
        with lock:
            row = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if row is None or not verify_password(str(password), row["pw_salt"], row["pw_hash"]):
            login_failed(key)
            time.sleep(0.4)
            return self.send_json({"error": "invalid_credentials"}, 401)
        login_ok(key)
        token = open_session(row["id"])
        return self.send_json({"user": public_user(row)}, cookie=self.cookie_header(token))

    def change_own_password(self, data):
        user = self.require(admin=False)
        if not user:
            return None
        if not verify_password(str((data or {}).get("current", "")), user["pw_salt"], user["pw_hash"]):
            return self.send_json({"error": "invalid_credentials"}, 403)
        problem = password_problem((data or {}).get("password"))
        if problem:
            return self.send_json({"error": "weak_password", "message": problem}, 400)
        set_password(user["id"], (data or {})["password"])
        token = open_session(user["id"])  # a sessão atual é renovada
        return self.send_json({"ok": True}, cookie=self.cookie_header(token))

    def set_avatar(self, data):
        """Guarda (ou remove, com string vazia) a imagem de perfil do próprio utilizador."""
        user = self.require(admin=False)
        if not user:
            return None
        avatar = (data or {}).get("avatar", "")
        if not isinstance(avatar, str) or len(avatar) > 300_000 or (avatar and not LOGO_RE.match(avatar)):
            return self.send_json({"error": "invalid_image", "message": "A imagem não é válida ou é demasiado grande."}, 400)
        with lock:
            conn.execute("UPDATE users SET avatar=? WHERE id=?", (avatar, user["id"]))
            conn.commit()
            fresh = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        return self.send_json({"user": public_user(fresh)})

    def fetch_avatar(self, data):
        """Vai buscar uma imagem a um endereço e devolve-a como data URL, para o navegador a recortar."""
        import base64
        import urllib.parse
        if not self.require(admin=False):
            return None
        url = str((data or {}).get("url", "")).strip()[:2000]
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return self.send_json({"error": "invalid_url", "message": "Indica um endereço http:// ou https://."}, 400)
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": f"escala-farmacia/{APP_VERSION}", "Accept": "image/*"})
            with urllib.request.urlopen(req, timeout=15) as r:
                ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                raw = r.read(6 * 1024 * 1024 + 1)
        except Exception as e:  # noqa: BLE001 - rede, DNS, 404…
            return self.send_json({"error": "fetch_failed", "message": f"Não foi possível ir buscar a imagem ({e})."}, 502)
        if len(raw) > 6 * 1024 * 1024:
            return self.send_json({"error": "too_large", "message": "A imagem é demasiado grande (máximo 6 MB)."}, 400)
        if ctype not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            return self.send_json({"error": "not_image", "message": "O endereço não devolveu uma imagem PNG, JPG, WebP ou GIF."}, 400)
        return self.send_json({"data": f"data:{ctype};base64,{base64.b64encode(raw).decode()}"})

    def add_user(self, data):
        if not self.require(admin=True):
            return None
        username = str((data or {}).get("username", "")).strip()
        if not USERNAME_RE.match(username):
            return self.send_json({"error": "invalid_username"}, 400)
        problem = password_problem((data or {}).get("password"))
        if problem:
            return self.send_json({"error": "weak_password", "message": problem}, 400)
        role = "admin" if (data or {}).get("role") == "admin" else "viewer"
        try:
            user = create_user(username, (data or {})["password"], str((data or {}).get("name", "")).strip() or username, role)
        except sqlite3.IntegrityError:
            return self.send_json({"error": "username_taken"}, 409)
        return self.send_json({"user": user})

    def update_user(self, uid: str, data):
        """Um administrador muda nome, papel ou palavra-passe de qualquer conta."""
        me = self.require(admin=True)
        if not me:
            return None
        with lock:
            row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if row is None:
            return self.send_json({"error": "not_found"}, 404)
        role = data.get("role")
        if role in ("admin", "viewer") and role != row["role"]:
            if row["role"] == "admin" and role == "viewer" and self.last_admin(uid):
                return self.send_json({"error": "last_admin"}, 409)
            with lock:
                conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
                conn.commit()
        if "name" in data:
            with lock:
                conn.execute("UPDATE users SET name=? WHERE id=?", (str(data["name"]).strip()[:80], uid))
                conn.commit()
        if data.get("password"):
            problem = password_problem(data["password"])
            if problem:
                return self.send_json({"error": "weak_password", "message": problem}, 400)
            set_password(uid, data["password"])
            if uid == me["id"]:  # não fiques à porta depois de mudares a tua
                token = open_session(uid)
                with lock:
                    fresh = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                return self.send_json({"user": public_user(fresh)}, cookie=self.cookie_header(token))
        with lock:
            fresh = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return self.send_json({"user": public_user(fresh)})

    def delete_user(self, uid: str):
        me = self.require(admin=True)
        if not me:
            return None
        if uid == me["id"]:
            return self.send_json({"error": "self_delete"}, 409)
        if self.last_admin(uid):
            return self.send_json({"error": "last_admin"}, 409)
        with lock:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            conn.execute("DELETE FROM users WHERE id=?", (uid,))
            conn.commit()
        return self.send_json({"ok": True})

    @staticmethod
    def last_admin(uid: str) -> bool:
        with lock:
            row = conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND id<>?", (uid,)).fetchone()
        return row["n"] == 0


def reset_admin(username: str) -> int:
    """Recuperação: cria ou repõe uma conta de administrador a partir da consola."""
    import getpass

    if not USERNAME_RE.match(username):
        print("Nome de utilizador inválido (3 a 32 caracteres: letras, números, . - _).")
        return 2
    password = getpass.getpass("Nova palavra-passe: ")
    if password != getpass.getpass("Repete a palavra-passe: "):
        print("As palavras-passe não coincidem.")
        return 2
    problem = password_problem(password)
    if problem:
        print(problem)
        return 2
    with lock:
        row = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    if row:
        with lock:
            conn.execute("UPDATE users SET role='admin' WHERE id=?", (row["id"],))
            conn.commit()
        set_password(row["id"], password)
        print(f"Conta '{row['username']}' reposta como administrador. As sessões abertas foram fechadas.")
    else:
        create_user(username, password, username, "admin")
        print(f"Conta de administrador '{username}' criada.")
    return 0


def main():
    global conn
    ap = argparse.ArgumentParser(description="Servidor da Escala da Farmácia")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ESCALA_PORT") or 8765))
    ap.add_argument("--host", default=os.environ.get("ESCALA_HOST") or "127.0.0.1")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reset-admin", metavar="UTILIZADOR",
                    help="cria ou repõe esta conta como administrador e sai (pede a palavra-passe)")
    args = ap.parse_args()
    if os.environ.get("ESCALA_NO_BROWSER"):
        args.no_browser = True

    # Consolas antigas em Windows usam cp1252 e rebentam com acentos.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    # Se houver uma versão mais recente instalada no volume, é essa que corre.
    if not args.reset_admin:
        boot_overlay()

    conn = connect(Path(args.db))
    init_data()

    if args.reset_admin:
        return reset_admin(args.reset_admin)

    url = f"http://{args.host}:{args.port}/"
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    boot_ok()
    if UPDATES_ENABLED:
        threading.Thread(target=auto_check_loop, daemon=True, name="auto-check").start()
    origem = "volume de dados" if running_from_volume() else "imagem"
    print(f"Escala da Farmácia {APP_VERSION} ({origem})  ->  {url}")
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
    sys.exit(main() or 0)
