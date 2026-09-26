import os
import sys
import re
import json
import secrets
import sqlite3
import threading
import concurrent.futures
from datetime import datetime, timedelta
import time
import math
import logging
import requests
import urllib3
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from flask import Flask, request, jsonify, session
from bs4 import BeautifulSoup

DB_PATH = 'shift_history.db'
INDICADORES_BASE = os.environ.get("INDICADORES_BASE", "http://cl01sv34a:8050/reporte")
INSPECCIONES_BASE = os.environ.get("INSPECCIONES_BASE", "http://10.107.194.70/ASRS/inspecciones")
SAP_USERNAME = os.environ.get("SAP_USERNAME")
SAP_PASSWORD = os.environ.get("SAP_PASSWORD")

# server_config.json viaja con el repo (no tiene secretos, solo la URL del portal) para no
# depender de que alguien configure variables de entorno a mano en el servidor de producción.
SERVER_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "server_config.json")


def _load_server_config():
    try:
        with open(SERVER_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] No se pudo leer server_config.json: {e}")
        return {}


_server_config = _load_server_config()
SAP_LOGIN_URL = os.environ.get("SAP_LOGIN_URL") or _server_config.get("SAP_LOGIN_URL")
SAP_TARGET_DEFAULT = os.environ.get("SAP_TARGET") or _server_config.get("SAP_TARGET") or "L1P"
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "schedule_config.json")

# Árbol de equipos ASRS en SAP: todo lo que cuelga de L504-5200 (grúas, conveyors, horseshoes, robots, etc.)
ASRS_TREE_ROOT_FL = "L504-5200"
ASRS_TREE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "asrs_tree_cache.json")
ASRS_TREE_TTL_SECONDS = 24 * 3600
# Fallback si el portal no responde y no hay cache previo del árbol
ASRS_KEYWORDS_FALLBACK = ("L504-ASRS", "L504-PLMT", "PLMT")
_asrs_tree_cache = {"ids": None, "loaded_at": 0}

# Login por usuario (LDAP) para Entrega de Turno: cada persona usa su propia cuenta,
# la sesión autenticada contra el portal SAP se guarda en memoria del servidor (nunca la contraseña).
AUTH_SESSION_TTL_SECONDS = 9 * 3600
_user_portal_sessions = {}
_user_sessions_lock = threading.Lock()

TURNOS_ENTREGA = {
    "T1": {"nombre": "Turno Noche (T1)", "inicio": "22:00:00", "fin": "06:00:00", "cruza_medianoche": True},
    "T2": {"nombre": "Turno Mañana (T2)", "inicio": "06:00:00", "fin": "14:00:00", "cruza_medianoche": False},
    "T3": {"nombre": "Turno Tarde (T3)", "inicio": "14:00:00", "fin": "22:00:00", "cruza_medianoche": False},
}

# Margen de tolerancia: órdenes cargadas poco después del cierre nominal siguen contando para el turno que termina
SHIFT_GRACE_MINUTES = 59


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_db():
    """Retorna una conexión SQLite con WAL mode y busy timeout."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_capped_now():
    """Retorna la última timestamp registrada en shift_summaries (para sincronizar reloj del dashboard)."""
    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT datetime(MAX(timestamp), 'localtime') FROM shift_summaries")
            row = cursor.fetchone()
            if row and row[0]:
                return datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        finally:
            conn.close()
    except Exception:
        pass
    return datetime.now()


def get_current_shift_info(dt=None):
    """Determina fecha y turno (T1/T2/T3) según la hora del sistema. T1: 22:00-06:00, T2: 06:00-14:00, T3: 14:00-22:00."""
    if dt is None:
        dt = get_capped_now()
    hour = dt.hour
    if 6 <= hour < 14:
        shift = 'T2'
        date_str = dt.strftime('%Y-%m-%d')
    elif 14 <= hour < 22:
        shift = 'T3'
        date_str = dt.strftime('%Y-%m-%d')
    else:
        shift = 'T1'
        if hour < 6:
            date_str = (dt - timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            date_str = dt.strftime('%Y-%m-%d')
    return date_str, shift


def get_shift_from_start(start_str):
    """Parsea parámetro start del request y retorna (fecha, turno). Fallback al turno actual."""
    if start_str:
        try:
            start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            return get_current_shift_info(start_dt)
        except Exception as e:
            print(f'[WARN] Error parsing start date: {e}')
    return get_current_shift_info()


def calc_idle(auto, run, fault):
    """Calcula tiempo idle: auto - run - fault (mínimo 0)."""
    return max(0, auto - run - fault)


# ============================================================================
# DATABASE INIT
# ============================================================================

def init_db():
    """Crea tablas si no existen. Ejecuta migraciones de columnas."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute('''CREATE TABLE IF NOT EXISTS io_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT, turno TEXT, entrada TEXT, manual TEXT, auto TEXT,
                        rate_entrada TEXT, rate_manual TEXT, rate_auto TEXT,
                        construido TEXT, vulcanizado TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    try:
        conn.execute("ALTER TABLE io_history ADD COLUMN construido TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE io_history ADD COLUMN vulcanizado TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute('''CREATE TABLE IF NOT EXISTS api_cache (
                        cache_key TEXT PRIMARY KEY,
                        response_json TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS shift_summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT, turno TEXT, maquina TEXT, estado TEXT, minutos REAL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS crane_aisle_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT NOT NULL,
                        turno TEXT,
                        aisle INTEGER NOT NULL,
                        downtime_percent REAL,
                        downtime_minutes REAL,
                        query_start TEXT,
                        query_end TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS conveyor_full_downtime (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT NOT NULL,
                        turno TEXT,
                        total_downtime_minutes REAL,
                        frequency INTEGER,
                        objective_minutes REAL DEFAULT 15.0,
                        query_start TEXT,
                        query_end TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS press_downtime_by_reason (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT NOT NULL,
                        turno TEXT,
                        reason_code TEXT NOT NULL,
                        press_group TEXT NOT NULL,
                        downtime_minutes REAL,
                        query_start TEXT,
                        query_end TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS press_delivery_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT NOT NULL,
                        turno TEXT,
                        press_group TEXT NOT NULL,
                        delivered INTEGER DEFAULT 0,
                        cancelled INTEGER DEFAULT 0,
                        total_orders INTEGER DEFAULT 0,
                        vulcanized INTEGER DEFAULT 0,
                        t_idle REAL DEFAULT 0,
                        t_estop REAL DEFAULT 0,
                        t_cortinas REAL DEFAULT 0,
                        t_prensa REAL DEFAULT 0,
                        query_start TEXT,
                        query_end TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS daily_ticket_target (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT NOT NULL UNIQUE,
                        target INTEGER,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.commit()
    conn.close()


# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__, static_folder='static', static_url_path='')
# Necesario para la sesión de login (cookie firmada); no persiste entre reinicios del server.
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


def _get_authenticated_portal_session():
    """
    Retorna (requests.Session, portal_base, username) de la sesión LDAP del usuario logueado
    en el navegador actual, o (None, None, None) si no hay sesión válida/vigente.
    """
    entry = _get_auth_entry()
    if not entry:
        return None, None, None
    return entry["session"], entry["portal_base"], entry["username"]


def _get_auth_entry():
    """Retorna el dict completo de la sesión autenticada (incluye display_name/photo_url) o None."""
    token = session.get("auth_token")
    if not token:
        return None
    with _user_sessions_lock:
        entry = _user_portal_sessions.get(token)
        if not entry:
            return None
        if (time.time() - entry["created_at"]) >= AUTH_SESSION_TTL_SECONDS:
            _user_portal_sessions.pop(token, None)
            return None
        return entry


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Login LDAP contra el portal SAP; cada usuario usa su propia cuenta."""
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    if not username or not password:
        return jsonify({"success": False, "error": "Usuario y contraseña son requeridos"}), 400

    portal_url = (SAP_LOGIN_URL or "").strip()
    if not portal_url:
        return jsonify({"success": False, "error": "El servidor no tiene configurado SAP_LOGIN_URL"}), 500

    portal_session = requests.Session()
    portal_session.trust_env = False
    portal_session.verify = False
    portal_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    try:
        login_resp = portal_session.post(
            portal_url,
            json={"username": username, "password": password, "sap_target": SAP_TARGET_DEFAULT},
            timeout=15,
        )
        login_payload = login_resp.json() if login_resp.content else {}
    except Exception as e:
        return jsonify({"success": False, "error": f"Error de conexión con el portal SAP: {e}"}), 502

    if login_resp.status_code not in (200, 201) or not login_payload.get("success"):
        return jsonify({"success": False, "error": login_payload.get("error") or "Credenciales inválidas"}), 401

    portal_base = portal_url.rsplit("/api/auth/login", 1)[0] if "/api/auth/login" in portal_url else ""
    if not portal_base:
        return jsonify({"success": False, "error": "SAP_LOGIN_URL mal configurado en el servidor"}), 500

    display_name, photo_url = username, ""
    try:
        status_resp = portal_session.get(f"{portal_base}/api/auth/status", timeout=10)
        status_payload = status_resp.json() if status_resp.content else {}
        user_info = status_payload.get("data", {}).get("user", {})
        display_name = user_info.get("display_name") or username
        photo_url = user_info.get("photo_url") or ""
    except Exception as e:
        print(f"[WARN] No se pudo obtener el nombre del usuario desde el portal: {e}")

    token = secrets.token_urlsafe(32)
    with _user_sessions_lock:
        _user_portal_sessions[token] = {
            "session": portal_session,
            "portal_base": portal_base,
            "username": username,
            "display_name": display_name,
            "photo_url": photo_url,
            "created_at": time.time(),
        }

    session.clear()
    session["auth_token"] = token
    session["username"] = username
    session.permanent = False
    return jsonify({"success": True, "username": username, "display_name": display_name, "photo_url": photo_url})


@app.route("/api/auth/status")
def api_auth_status():
    entry = _get_auth_entry()
    if not entry:
        return jsonify({"success": True, "authenticated": False, "username": None})
    return jsonify({
        "success": True,
        "authenticated": True,
        "username": entry["username"],
        "display_name": entry.get("display_name") or entry["username"],
        "photo_url": entry.get("photo_url") or "",
    })


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    token = session.pop("auth_token", None)
    session.pop("username", None)
    if token:
        with _user_sessions_lock:
            _user_portal_sessions.pop(token, None)
    return jsonify({"success": True})


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/io-data')
def api_io_data():
    """Retorna datos de producción (Construido, Vulcanizado, Entrada/Salida ASRS) desde io_history."""
    start_str = request.args.get('start', '')
    target_date, target_shift = get_current_shift_info()
    if start_str:
        try:
            start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            target_date, target_shift = get_current_shift_info(start_dt)
        except Exception as e:
            print(f'[WARN] Error parsing date params: {e}')

    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT entrada, manual, auto, rate_entrada, rate_manual, rate_auto, construido, vulcanizado FROM io_history WHERE fecha = ? AND turno = ?", (target_date, target_shift))
            row = cursor.fetchone()

            if row:
                return jsonify({
                    "entrada": row[0], "manual": row[1], "auto": row[2],
                    "rate_entrada": row[3], "rate_manual": row[4], "rate_auto": row[5],
                    "construido": row[6] if row[6] is not None else "-",
                    "vulcanizado": row[7] if row[7] is not None else "-",
                    "mock": False
                })
            else:
                return jsonify({
                    "entrada": "-", "manual": "-", "auto": "-",
                    "rate_entrada": "-", "rate_manual": "-", "rate_auto": "-",
                    "construido": "-", "vulcanizado": "-",
                    "mock": False, "message": "Sin información guardada para este turno"
                })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/robots-turnos')
def api_robots_turnos():
    """Retorna estados RUN/FAULT/AUTO de robots (ULR1, ULR2, LR1, LR2) por turno desde shift_summaries."""
    start_str = request.args.get('start', '')
    target_date, _ = get_shift_from_start(start_str)

    machines = ['ULR1', 'ULR2', 'LR1', 'LR2']
    data = {m: {
        "T1": {"run": 0, "fault": 0, "auto": 0, "idle": 0},
        "T2": {"run": 0, "fault": 0, "auto": 0, "idle": 0},
        "T3": {"run": 0, "fault": 0, "auto": 0, "idle": 0}
    } for m in machines}

    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(f'SELECT maquina, turno, estado, minutos FROM shift_summaries WHERE fecha = ? AND maquina IN ({",".join(["?"]*len(machines))})', [target_date] + machines)
            rows = cursor.fetchall()

            for r in rows:
                maq, t, est, mins = r
                if est == 'idle': est = 'auto'
                if maq in data and t in data[maq] and est in data[maq][t]:
                    data[maq][t][est] = mins

            for maq in machines:
                for t in ['T1', 'T2', 'T3']:
                    data[maq][t]['idle'] = calc_idle(data[maq][t]['auto'], data[maq][t]['run'], data[maq][t]['fault'])

            return jsonify({"success": True, "data": data, "source": "db"})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/plc-conveyor')
def api_plc_conveyor():
    """Retorna estados RUN/IDLE/STOP de conveyors (CC01, CC02, CC03) por turno desde shift_summaries."""
    start_str = request.args.get('start', '')
    target_date, target_shift = get_shift_from_start(start_str)
    machines = ['CC01', 'CC02', 'CC03']

    data = {m: {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0, 'AUTO': 0.0} for m in machines}

    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT maquina, estado, minutos FROM shift_summaries WHERE fecha = ? AND turno = ? AND maquina IN ({seq})'.format(seq=','.join(['?']*len(machines))), [target_date, target_shift] + machines)
            rows = cursor.fetchall()

            for maq, est, mins in rows:
                if maq in data:
                    if est == 'idle': est = 'auto'
                    if est == 'run': data[maq]['RUN'] = mins
                    elif est == 'fault': data[maq]['STOP'] = mins
                    elif est == 'auto': data[maq]['AUTO'] = mins

            for maq in machines:
                data[maq]['IDLE'] = calc_idle(data[maq]['AUTO'], data[maq]['RUN'], data[maq]['STOP'])
                del data[maq]['AUTO']

            return jsonify({"success": True, "data": data, "source": "db"})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/asrs-engineering-data')
def api_asrs_engineering():
    """Retorna estados de lubricadoras Plummers (L1, L2, L3) + timestamp de última actualización."""
    start_str = request.args.get('start', '')
    target_date, target_shift = get_shift_from_start(start_str)

    plummers_list = ['L1', 'L2', 'L3']
    plummers = {m: {'run': 0.0, 'idle': 0.0, 'stop': 0.0, 'auto': 0.0} for m in plummers_list}

    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT maquina, estado, minutos FROM shift_summaries WHERE fecha = ? AND turno = ? AND maquina IN ({seq})'.format(seq=','.join(['?']*len(plummers_list))), [target_date, target_shift] + plummers_list)
            rows = cursor.fetchall()

            for maq, est, mins in rows:
                if est == 'idle': est = 'auto'
                if maq in plummers:
                    if est == 'run': plummers[maq]['run'] = mins
                    elif est == 'fault': plummers[maq]['stop'] = mins
                    elif est == 'auto': plummers[maq]['auto'] = mins

            for maq in plummers_list:
                plummers[maq]['idle'] = calc_idle(plummers[maq]['auto'], plummers[maq]['run'], plummers[maq]['stop'])
                del plummers[maq]['auto']

            cursor.execute("SELECT datetime(MAX(timestamp), 'localtime') FROM shift_summaries")
            max_ts_row = cursor.fetchone()
            last_updated_db = max_ts_row[0] if max_ts_row and max_ts_row[0] else None

            return jsonify({"success": True, "plummers": plummers, "source": "db", "last_updated": last_updated_db})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/crane-performance')
def api_crane_performance():
    """Retorna performance de grúas por pasillo desde crane_aisle_history."""
    start_str = request.args.get('start', '')
    target_date, target_shift = get_shift_from_start(start_str)

    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute('''SELECT aisle, downtime_percent, downtime_minutes
                              FROM crane_aisle_history
                              WHERE fecha = ? AND turno = ?
                              ORDER BY aisle''', (target_date, target_shift))
            rows = cursor.fetchall()

            aisle_data = [{"aisle": r[0], "downtime_percent": r[1], "downtime_minutes": r[2]} for r in rows]
            return jsonify({"success": True, "data": aisle_data, "source": "db"})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/conveyor-full')
def api_conveyor_full():
    """Retorna tiempo total de downtime del conveyor (reason 10315) desde conveyor_full_downtime."""
    start_str = request.args.get('start', '')
    target_date, target_shift = get_shift_from_start(start_str)

    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute('''SELECT total_downtime_minutes, frequency, objective_minutes, query_start, query_end
                              FROM conveyor_full_downtime
                              WHERE fecha = ? AND turno = ?
                              LIMIT 1''', (target_date, target_shift))
            row = cursor.fetchone()

            if row:
                total_downtime = row[0] or 0.0
                frequency = row[1] or 0
                objective = row[2] or 15.0
                return jsonify({
                    "success": True, "query_start": row[3], "query_end": row[4],
                    "total_downtime": round(total_downtime, 2), "frequency": frequency,
                    "objective_minutes": objective, "is_ok": round(total_downtime, 2) <= objective, "mock": False, "source": "db"
                })
            else:
                return jsonify({
                    "success": True, "total_downtime": 0.0, "frequency": 0,
                    "objective_minutes": 15.0, "is_ok": True, "mock": False, "source": "db"
                })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/downtime')
def api_downtime():
    """Retorna downtime por reason code agrupado por prensa (100A-600B) desde press_downtime_by_reason."""
    reason = request.args.get('reason', '')
    if not all(r.strip().isdigit() for r in reason.split(',') if r.strip()):
        return jsonify({"error": "Parámetro inválido"}), 400

    start_str = request.args.get('start', '')
    target_date, target_shift = get_shift_from_start(start_str)
    reasons = [r.strip() for r in reason.split(",") if r.strip()]

    try:
        conn = get_db()
        try:
            cursor = conn.cursor()

            downtime_by_group = {f"{r}00{s}": 0.0 for r in range(1,7) for s in ["A","B"]}

            placeholders = ','.join(['?'] * len(reasons))
            cursor.execute(f'''SELECT press_group, SUM(downtime_minutes)
                               FROM press_downtime_by_reason
                               WHERE fecha = ? AND turno = ? AND reason_code IN ({placeholders})
                               GROUP BY press_group''',
                           [target_date, target_shift] + reasons)
            rows = cursor.fetchall()

            for press_group, total_mins in rows:
                if press_group in downtime_by_group:
                    downtime_by_group[press_group] = round(total_mins, 2)
        finally:
            conn.close()

        start_dt = datetime.strptime(target_date + ' 06:00', '%Y-%m-%d %H:%M') if target_shift == 'T2' else \
                   (datetime.strptime(target_date + ' 14:00', '%Y-%m-%d %H:%M') if target_shift == 'T3' else \
                    datetime.strptime(target_date + ' 22:00', '%Y-%m-%d %H:%M'))
        end_dt = start_dt + timedelta(hours=8)
        duration_minutes = max(1, round((end_dt - start_dt).total_seconds() / 60))
        total_downtime = sum(downtime_by_group.values())
        downtime_percent = (total_downtime / (duration_minutes * 48)) * 100

        return jsonify({
            "success": True, "duration_minutes": duration_minutes,
            "downtime_by_group": downtime_by_group, "total_downtime": round(total_downtime, 2),
            "downtime_percent": round(downtime_percent, 2), "mock": False, "source": "db"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/press-delivery')
def api_press_delivery():
    """Retorna eficiencia de despacho por prensa (400B-600B) desde press_delivery_data."""
    start_str = request.args.get('start', '')
    target_date, target_shift = get_shift_from_start(start_str)

    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute('''SELECT press_group, delivered, cancelled, total_orders, vulcanized,
                                     t_idle, t_estop, t_cortinas, t_prensa, query_start, query_end
                              FROM press_delivery_data
                              WHERE fecha = ? AND turno = ?
                              ORDER BY press_group''', (target_date, target_shift))
            rows = cursor.fetchall()
        finally:
            conn.close()

        groups = {}
        global_delivered = 0
        global_vulcanized = 0

        for r in rows:
            press_group = r[0]
            delivered = r[1] or 0
            cancelled = r[2] or 0
            total_orders = r[3] or 0
            vulcanized = r[4] or 0
            t_idle = r[5] or 0.0
            t_estop = r[6] or 0.0
            t_cortinas = r[7] or 0.0
            t_prensa = r[8] or 0.0

            try:
                start_dt = datetime.strptime(r[9], '%Y/%m/%d %H:%M:%S') if r[9] else get_capped_now() - timedelta(hours=8)
                end_dt = datetime.strptime(r[10], '%Y/%m/%d %H:%M:%S') if r[10] else get_capped_now()
            except (ValueError, TypeError):
                start_dt = get_capped_now() - timedelta(hours=8)
                end_dt = get_capped_now()
            total_minutes = max(0, (end_dt - start_dt).total_seconds() / 60.0)
            despachando = max(0, total_minutes - (t_idle + t_estop + t_cortinas + t_prensa))

            groups[press_group] = {
                "delivered": delivered,
                "cancelled": cancelled,
                "total": total_orders,
                "vulcanized": vulcanized,
                "times": {
                    "idle": round(t_idle, 2),
                    "estop": round(t_estop, 2),
                    "cortinas": round(t_cortinas, 2),
                    "prensa": round(t_prensa, 2),
                    "despachando": round(despachando, 2)
                }
            }

            global_delivered += delivered
            global_vulcanized += vulcanized

        return jsonify({"success": True, "presses": groups, "uptime": 99.40, "source": "db"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/daily-ticket')
def api_daily_ticket():
    """Retorna target diario de producción desde daily_ticket_target."""
    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT fecha, target FROM daily_ticket_target ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()

            if row and row[1] and row[1] > 0:
                return jsonify({"success": True, "total": row[1], "formatted": f"{row[1]:,}", "source": "db"})
        finally:
            conn.close()
    except Exception:
        pass

    plant_ip = os.environ.get("PLANT_SERVER_IP", "10.107.194.110:8006")
    remote_ticket = fetch_json(f"http://{plant_ip}/api/daily-ticket", timeout=2)
    if remote_ticket and remote_ticket.get("success"):
        return jsonify(remote_ticket)

    return jsonify({"success": True, "total": 13500, "formatted": "13,500", "source": "default"})


@app.route('/entrega-turno')
def serve_entrega_turno():
    return app.send_static_file('entrega-turno.html')

_http_session = requests.Session()
_http_session.trust_env = False


def build_sap_session():
    """Crea una sesión autenticada para el sitio de Indicadores Planta que exige LDAP/SSO."""
    session = requests.Session()
    session.trust_env = False
    session.verify = False
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Accept-Language": "es-CL,es;q=0.9",
    })

    if not SAP_USERNAME or not SAP_PASSWORD:
        print("[WARN] SAP_USERNAME / SAP_PASSWORD no configurados. Se usará sesión anónima para Indicadores Planta.")
        return session, False

    login_endpoint = SAP_LOGIN_URL or f"{INDICADORES_BASE.rstrip('/')}/login"
    base_url = INDICADORES_BASE.rstrip('/') + "/"

    try:
        probe = session.get(base_url, timeout=12, allow_redirects=True)
        if probe.status_code == 200 and "login" not in probe.url.lower() and "auth" not in probe.url.lower():
            return session, True

        soup = BeautifulSoup(probe.text, "html.parser")
        form = soup.find("form")
        payload = {}
        if form:
            action = form.get("action") or login_endpoint
            action_url = urljoin(base_url, action) if not action.startswith("http") else action
            for field in form.select("input"):
                name = field.get("name")
                if not name:
                    continue
                key = name.lower()
                field_type = (field.get("type") or "text").lower()
                if field_type == "hidden":
                    payload[name] = field.get("value", "")
                elif key in {"username", "user", "userid", "j_username", "login", "usuario", "email"}:
                    payload[name] = SAP_USERNAME
                elif key in {"password", "passwd", "pass", "pwd", "j_password", "contrasena"}:
                    payload[name] = SAP_PASSWORD
                elif key in {"submit", "button"}:
                    continue

            if not payload:
                payload = {
                    "username": SAP_USERNAME,
                    "password": SAP_PASSWORD,
                    "j_username": SAP_USERNAME,
                    "j_password": SAP_PASSWORD,
                    "login": SAP_USERNAME,
                    "passwd": SAP_PASSWORD,
                }

            if action_url:
                login_resp = session.post(action_url, data=payload, timeout=12, allow_redirects=True)
                if login_resp.status_code in (200, 302) and "login" not in login_resp.url.lower() and "auth" not in login_resp.url.lower():
                    return session, True

        login_resp = session.post(login_endpoint, data={
            "username": SAP_USERNAME,
            "password": SAP_PASSWORD,
            "j_username": SAP_USERNAME,
            "j_password": SAP_PASSWORD,
            "login": SAP_USERNAME,
            "passwd": SAP_PASSWORD,
        }, timeout=12, allow_redirects=True)
        if login_resp.status_code in (200, 302) and "login" not in login_resp.url.lower() and "auth" not in login_resp.url.lower():
            return session, True
    except Exception as e:
        print(f"[WARN] Error autenticando sesión SAP/LDAP: {e}")

    return session, False


def fetch_json(url, timeout=6):
    try:
        r = _http_session.get(url, timeout=timeout, verify=False)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[WARN] Error consultando {url}: {e}")
    return None

def get_shift_range_entrega(fecha_str, turno_key):
    t_info = TURNOS_ENTREGA.get(turno_key, TURNOS_ENTREGA["T2"])
    base_date = datetime.strptime(fecha_str, "%Y-%m-%d")
    
    if turno_key == "T1":
        dt_start = (base_date - timedelta(days=1)).replace(hour=22, minute=0, second=0)
        dt_end = base_date.replace(hour=6, minute=0, second=0)
    elif turno_key == "T2":
        dt_start = base_date.replace(hour=6, minute=0, second=0)
        dt_end = base_date.replace(hour=14, minute=0, second=0)
    else: # T3
        dt_start = base_date.replace(hour=14, minute=0, second=0)
        dt_end = base_date.replace(hour=22, minute=0, second=0)
        
    return dt_start, dt_end


def _portal_login_session():
    """Crea una sesión autenticada (LDAP) contra el portal SAP configurado en SAP_LOGIN_URL."""
    portal_url = (SAP_LOGIN_URL or "").strip()
    if not portal_url or not SAP_USERNAME or not SAP_PASSWORD:
        return None, None

    session = requests.Session()
    session.trust_env = False
    session.verify = False
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        login_resp = session.post(
            portal_url,
            json={"username": SAP_USERNAME, "password": SAP_PASSWORD, "sap_target": SAP_TARGET_DEFAULT},
            timeout=15,
        )
        login_payload = login_resp.json() if login_resp.content else {}
        if login_resp.status_code not in (200, 201) or not login_payload.get("success"):
            print(f"[WARN] Login portal SAP falló: {login_resp.status_code} {login_payload}")
            return None, None
    except Exception as e:
        print(f"[WARN] Error autenticando portal SAP: {e}")
        return None, None

    portal_base = portal_url.rsplit("/api/auth/login", 1)[0] if "/api/auth/login" in portal_url else ""
    if not portal_base:
        return None, None
    return session, portal_base


def _fetch_asset_tree_children(session, portal_base, parent_id):
    try:
        resp = session.get(f"{portal_base}/api/asset-tree/children", params={"parent_id": parent_id}, timeout=20)
        payload = resp.json() if resp.content else {}
        if resp.status_code == 200 and payload.get("success"):
            return payload.get("data", [])
    except Exception as e:
        print(f"[WARN] Error consultando asset-tree/children({parent_id}): {e}")
    return []


def _walk_asset_tree(session, portal_base, root_id, collected, max_workers=4):
    """
    Recorre el árbol en anchura (BFS), pidiendo los hijos de cada nivel en paralelo,
    para no hacer ~70 llamadas HTTP secuenciales (que tardaban 1-2 min en frío).
    """
    frontier = [root_id]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        while frontier:
            results = executor.map(lambda node: _fetch_asset_tree_children(session, portal_base, node), frontier)
            next_frontier = []
            for children in results:
                for child in children:
                    cid = child.get("id")
                    if not cid or cid in collected:
                        continue
                    collected.add(cid)
                    if child.get("has_children"):
                        next_frontier.append(cid)
            frontier = next_frontier


ASRS_TREE_SEED_FILE = os.path.join(os.path.dirname(__file__), "asrs_tree_seed.json")
# Umbral mínimo de nodos para considerar "buena" una respuesta en vivo del portal (el árbol real tiene ~525)
ASRS_TREE_MIN_GOOD_SIZE = 400


def _load_asrs_tree_seed():
    """Lista fija de respaldo (capturada manualmente una vez) por si el portal falla/está lento."""
    try:
        with open(ASRS_TREE_SEED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f).get("ids", []))
    except Exception as e:
        print(f"[WARN] Error leyendo semilla del árbol ASRS: {e}")
        return set()


_asrs_tree_refresh_lock = threading.Lock()
_asrs_tree_refreshing = False


def _refresh_asrs_tree_background(auth_session, portal_base):
    """Recorre el árbol real del portal en un hilo aparte y actualiza el cache si sale bien."""
    global _asrs_tree_refreshing
    try:
        collected = {ASRS_TREE_ROOT_FL}
        _walk_asset_tree(auth_session, portal_base, ASRS_TREE_ROOT_FL, collected)
        if len(collected) >= ASRS_TREE_MIN_GOOD_SIZE:
            now = time.time()
            _asrs_tree_cache["ids"] = collected
            _asrs_tree_cache["loaded_at"] = now
            try:
                with open(ASRS_TREE_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"ids": sorted(collected), "loaded_at": now}, f)
            except Exception as e:
                print(f"[WARN] Error guardando cache de árbol ASRS: {e}")
            print(f"[INFO] Árbol ASRS actualizado en segundo plano desde el portal: {len(collected)} FL/EQ.")
        else:
            print(f"[WARN] Actualización en segundo plano del árbol ASRS incompleta ({len(collected)} nodos); se mantiene la semilla.")
    except Exception as e:
        print(f"[WARN] Error actualizando árbol ASRS en segundo plano: {e}")
    finally:
        with _asrs_tree_refresh_lock:
            _asrs_tree_refreshing = False


def get_asrs_functional_locations(auth_session=None, portal_base_override=None):
    """
    Retorna el set de FL/EQ que cuelgan de L504-5200 (ASRS) en el árbol de equipos SAP.
    Responde al instante con cache (memoria/disco, TTL 24h) o con la semilla fija (asrs_tree_seed.json)
    si no hay cache vigente, y dispara una actualización real contra el portal en segundo plano
    (sin bloquear la respuesta) para refrescar el cache de cara a la próxima consulta.
    """
    now = time.time()
    if _asrs_tree_cache["ids"] is not None and (now - _asrs_tree_cache["loaded_at"]) < ASRS_TREE_TTL_SECONDS:
        return _asrs_tree_cache["ids"]

    if os.path.exists(ASRS_TREE_CACHE_FILE):
        try:
            with open(ASRS_TREE_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if (now - cached.get("loaded_at", 0)) < ASRS_TREE_TTL_SECONDS and cached.get("ids"):
                ids = set(cached["ids"])
                _asrs_tree_cache["ids"] = ids
                _asrs_tree_cache["loaded_at"] = cached.get("loaded_at", now)
                return ids
        except Exception as e:
            print(f"[WARN] Error leyendo cache de árbol ASRS: {e}")

    # Sin cache vigente: responder al instante con la semilla fija y refrescar en segundo plano.
    seed_ids = _load_asrs_tree_seed()
    _asrs_tree_cache["ids"] = seed_ids
    # Marca el cache como "viejo" (expira pronto) para reintentar el refresco real en la próxima consulta.
    _asrs_tree_cache["loaded_at"] = now - ASRS_TREE_TTL_SECONDS + 300

    if auth_session is not None and portal_base_override:
        session_obj, portal_base = auth_session, portal_base_override
    else:
        session_obj, portal_base = _portal_login_session()

    if session_obj:
        global _asrs_tree_refreshing
        with _asrs_tree_refresh_lock:
            already_running = _asrs_tree_refreshing
            _asrs_tree_refreshing = True
        if not already_running:
            print(f"[INFO] Usando semilla del árbol ASRS ({len(seed_ids)} nodos) mientras se actualiza en segundo plano...")
            threading.Thread(
                target=_refresh_asrs_tree_background, args=(session_obj, portal_base), daemon=True
            ).start()
    else:
        print("[WARN] No se pudo autenticar contra el portal para refrescar el árbol ASRS; se usa la semilla fija.")

    return seed_ids


def _is_asrs_location(value, ids_set):
    """Determina si un FL/EQ de una orden pertenece al árbol ASRS (match exacto o por prefijo jerárquico)."""
    if not value or not ids_set:
        return False
    if value in ids_set:
        return True
    parts = value.split("-")
    for i in range(len(parts) - 1, 0, -1):
        if "-".join(parts[:i]) in ids_set:
            return True
    return False


def _fetch_order_time_and_detail(get_json_fn, base_url, order_id, notification_id):
    """
    Trae hora real (malf_start_time), autor y repuestos usados desde /api/orders/{id}, y el
    texto largo del trabajo realizado desde /api/notifications/{id}.
    Retorna (order_dt|None, detalle|None, reportado_por|None, repuestos: list[str]).
    """
    order_dt = None
    detail_text = None
    reported_by = None
    components = []

    detail_payload = get_json_fn(f"{base_url}/api/orders/{order_id}")
    if detail_payload and detail_payload.get("success"):
        d = detail_payload.get("data", {}) or {}
        malf_date = str(d.get("malf_start_date") or d.get("start_date") or "").strip()
        malf_time = str(d.get("malf_start_time") or "").strip()
        if malf_date:
            for fmt in (("%d/%m/%Y %H:%M" if malf_time else "%d/%m/%Y"),):
                try:
                    order_dt = datetime.strptime(f"{malf_date} {malf_time}".strip() if malf_time else malf_date, fmt)
                except ValueError:
                    order_dt = None

        reported_by = str(d.get("created_by_name") or d.get("created_by") or "").strip() or None
        for comp in d.get("components", []) or []:
            desc = str(comp.get("description") or "").strip()
            qty = str(comp.get("quantity") or "").strip().rstrip("0").rstrip(".")
            unit = str(comp.get("unit") or "").strip()
            if desc:
                components.append(f"{desc} ({qty} {unit})".strip() if qty else desc)

    if notification_id:
        notif_payload = get_json_fn(f"{base_url}/api/notifications/{notification_id}")
        if notif_payload and notif_payload.get("success"):
            detail_text = str(notif_payload.get("data", {}).get("long_text") or "").strip() or None

    return order_dt, detail_text, reported_by, components


@app.route("/api/consolidado-turno")
def api_consolidado_turno():
    now_date, now_shift = get_current_shift_info()
    fecha_req = request.args.get("fecha", now_date)
    turno_req = request.args.get("turno", now_shift)
    
    dt_start, dt_end = get_shift_range_entrega(fecha_req, turno_req)
    start_param = dt_start.strftime("%Y-%m-%dT%H:%M")
    plant_ip = os.environ.get("PLANT_SERVER_IP", "10.107.194.110:8006")
    
    # 1. Fetch Dashboard metrics from local port 8006, fallback to plant server if local has empty metrics
    io_data = fetch_json(f"http://127.0.0.1:8006/api/io-data?start={start_param}") or {}
    if not io_data or io_data.get("entrada") == "-" or io_data.get("entrada") is None:
        remote_io = fetch_json(f"http://{plant_ip}/api/io-data?start={start_param}")
        if remote_io and remote_io.get("entrada") != "-":
            io_data = remote_io

    crane_data = fetch_json(f"http://127.0.0.1:8006/api/crane-performance?start={start_param}") or {}
    if not crane_data.get("data") or all(c.get("downtime_minutes", 0) == 0 for c in crane_data.get("data", [])):
        remote_crane = fetch_json(f"http://{plant_ip}/api/crane-performance?start={start_param}")
        if remote_crane and remote_crane.get("data"):
            crane_data = remote_crane

    press_data = fetch_json(f"http://127.0.0.1:8006/api/press-delivery?start={start_param}") or {}
    if not press_data.get("presses"):
        remote_press = fetch_json(f"http://{plant_ip}/api/press-delivery?start={start_param}")
        if remote_press and remote_press.get("presses"):
            press_data = remote_press

    conveyor_data = fetch_json(f"http://127.0.0.1:8006/api/conveyor-full?start={start_param}") or {}
    if not conveyor_data.get("success") or conveyor_data.get("total_downtime", 0) == 0:
        remote_conveyor = fetch_json(f"http://{plant_ip}/api/conveyor-full?start={start_param}")
        if remote_conveyor and remote_conveyor.get("success"):
            conveyor_data = remote_conveyor
    
    # Entrada / Salida Calculations
    entrada_val = io_data.get("entrada", "-")
    manual_val = io_data.get("manual", "-")
    auto_val = io_data.get("auto", "-")
    construido_val = io_data.get("construido", "-")
    vulcanizado_val = io_data.get("vulcanizado", "-")
    rate_entrada_val = io_data.get("rate_entrada", "-")
    rate_manual_val = io_data.get("rate_manual", "-")
    rate_auto_val = io_data.get("rate_auto", "-")

    try:
        m_num = int(str(manual_val).replace(",", "").strip())
    except (ValueError, TypeError):
        m_num = 0

    try:
        a_num = int(str(auto_val).replace(",", "").strip())
    except (ValueError, TypeError):
        a_num = 0

    if manual_val != "-" or auto_val != "-":
        total_salida = m_num + a_num
    else:
        total_salida = "-"

    try:
        rm_num = float(str(rate_manual_val).replace(",", ".").strip())
        ra_num = float(str(rate_auto_val).replace(",", ".").strip())
        rate_salida = round(rm_num + ra_num, 2)
    except (ValueError, TypeError):
        rate_salida = "-"

    try:
        e_num = int(str(entrada_val).replace(",", "").strip())
        c_num = int(str(construido_val).replace(",", "").strip())
        if c_num > 0:
            eficiencia_entrada = round((e_num / c_num) * 100.0, 1)
        else:
            eficiencia_entrada = "-"
    except (ValueError, TypeError):
        eficiencia_entrada = "-"

    # Crane Global Availability
    crane_list = crane_data.get("data", [])
    if crane_list:
        total_dt_crane = sum(c.get("downtime_minutes", 0) for c in crane_list)
        total_available = len(crane_list) * 480.0
        crane_avail_pct = round(max(0.0, 100.0 - (total_dt_crane / total_available * 100.0)), 2)
        top_cranes = [c for c in sorted(crane_list, key=lambda x: x.get("downtime_minutes", 0), reverse=True) if c.get("downtime_minutes", 0) > 0][:3]
    else:
        crane_avail_pct = "-"
        top_cranes = []

    # Press Global Delivery
    press_dict = press_data.get("presses", {})
    press_summary = []
    total_robot_delivered = 0
    total_vulcanized = 0
    for p_name in ["400B", "500A", "500B", "600A", "600B"]:
        p_val = press_dict.get(p_name, {})
        deliv = p_val.get("delivered", 0)
        vulc = p_val.get("vulcanized", 0)
        manual = max(0, vulc - deliv)
        pct = round((deliv / vulc * 100.0), 1) if vulc > 0 else 0.0
        total_robot_delivered += deliv
        total_vulcanized += vulc
        press_summary.append({
            "press": p_name,
            "delivered_robot": deliv,
            "manual": manual,
            "vulcanized": vulc,
            "pct": pct,
            "times": p_val.get("times", {})
        })
    global_press_pct = round((total_robot_delivered / total_vulcanized * 100.0), 2) if total_vulcanized > 0 else 0.0

    def _extraer_titulo_limpio(titulo_raw, detalle_raw):
        t = str(titulo_raw or "").strip()
        d = str(detalle_raw or "").strip()
        # Si el título ya es corto y diferente del detalle (ej. "Ajuste sensor en estructura"), usarlo
        if t and t != d and len(t) <= 65:
            return t
        base = t or d
        if not base:
            return "Aviso correctivo"
        s = base.strip()
        for sep in [". ", "; ", "\n"]:
            if sep in s:
                part = s.split(sep)[0].strip()
                if len(part) >= 8:
                    s = part
                    break
        if len(s) > 50 and ", " in s:
            comma_part = s.split(", ")[0].strip()
            if len(comma_part) >= 15:
                s = comma_part
        if len(s) > 50:
            s = s[:48].rsplit(" ", 1)[0].strip() + "..."
        if s:
            s = s[0].upper() + s[1:]
        return s

    def fetch_orders_indicadores_planta():
        """
        Fuente de órdenes del turno: portal SAP PM interno, usando la sesión LDAP del usuario
        logueado en el navegador. Retorna (orders_list, auth_required).
        """
        def parse_order_date(value):
            if not value:
                return None
            value = str(value).strip()
            for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    pass
            return None

        portal_session, portal_base, _username = _get_authenticated_portal_session()
        if not portal_session:
            return [], True

        try:
            from_date = min(dt_start, dt_end).strftime("%Y%m%d")
            to_date = max(dt_start, dt_end).strftime("%Y%m%d")
            params = {
                "plant": "L504",
                "page": 1,
                "per_page": 500,
                "date_from": from_date,
                "date_to": to_date,
            }
            api_resp = portal_session.get(f"{portal_base}/api/orders", params=params, timeout=20)
            api_payload = api_resp.json() if api_resp.content else {}
            if api_resp.status_code != 200 or not api_payload.get("data"):
                return [], False

            asrs_ids = get_asrs_functional_locations(portal_session, portal_base)
            orders_list = []
            seen = set()

            def _get_json_portal(url):
                try:
                    r = portal_session.get(url, timeout=15)
                    return r.json() if r.status_code == 200 and r.content else None
                except Exception as e:
                    print(f"[WARN] Error consultando {url}: {e}")
                    return None

            for order in api_payload.get("data", []):
                order_number = str(order.get("number") or order.get("id") or "").strip()
                if not order_number or order_number in seen:
                    continue

                order_type = str(order.get("type") or "").strip().upper()
                if order_type != "ZM01":
                    continue

                functional_location = str(order.get("functional_location") or "").strip().upper()
                equipment = str(order.get("equipment") or "").strip().upper()
                is_asrs = _is_asrs_location(functional_location, asrs_ids) or _is_asrs_location(equipment, asrs_ids)
                if not asrs_ids and not is_asrs:
                    is_asrs = any(kw in functional_location or kw in equipment for kw in ASRS_KEYWORDS_FALLBACK)
                if not is_asrs:
                    continue

                order_dt = None
                for key in ("actual_start", "start_date", "created_date", "actual_end", "end_date"):
                    candidate = parse_order_date(order.get(key))
                    if candidate is not None:
                        order_dt = candidate
                        break

                if order_dt is None:
                    continue

                order_date = order_dt.date()
                allowed_dates = {dt_start.date(), dt_end.date()}
                if order_date not in allowed_dates:
                    continue

                order_number_digits = order_number.lstrip("0") or order_number
                real_dt, detail_text, reported_by, repuestos = _fetch_order_time_and_detail(
                    _get_json_portal, portal_base, order.get("id") or order_number_digits, order.get("notification")
                )
                if real_dt is not None:
                    # Ventana de conteo de órdenes corrida +margen: una orden cargada poco después
                    # del cierre nominal cuenta para el turno que termina, sin duplicarse en el siguiente.
                    order_win_start = dt_start + timedelta(minutes=SHIFT_GRACE_MINUTES)
                    order_win_end = dt_end + timedelta(minutes=SHIFT_GRACE_MINUTES)
                    if not (order_win_start <= real_dt <= order_win_end):
                        continue
                    order_dt = real_dt

                seen.add(order_number)
                description = str(order.get("description") or "").strip() or "Sin descripción"
                equipment_code = str(order.get("equipment") or "").strip()
                functional_location_display = str(order.get("functional_location") or "").strip()

                orders_list.append({
                    "ot": order_number_digits,
                    "hora": order_dt.strftime("%H:%M:%S") if order_dt.hour or order_dt.minute or order_dt.second else "00:00:00",
                    "equipo": equipment_code or "-",
                    "maquina": functional_location_display or equipment_code or "-",
                    "titulo": description,
                    "detalle": detail_text or description,
                    "reportado_por": reported_by or str(order.get("created_by") or "").strip() or "-",
                    "repuestos": repuestos,
                })
            return orders_list, False
        except Exception as e:
            print(f"[WARN] Error consultando /api/orders del portal SAP: {e}")
            return [], False

    # 2. Obtener órdenes de mantenimiento
    filtered_orders = []
    orders_auth_required = False
    try:
        filtered_orders, orders_auth_required = fetch_orders_indicadores_planta()
    except Exception as e:
        print(f"[WARN] Error en fetch_orders_indicadores_planta: {e}")

    # Fallback a Inspecciones ASRS (10.107.194.70) si no se obtuvieron datos de Indicadores Planta
    if not filtered_orders:
        n1_orders = fetch_json(f"{INSPECCIONES_BASE}/avisos_correctivos_ASRS_table.php", timeout=4) or {}
        n1_recent = fetch_json(f"{INSPECCIONES_BASE}/index_n1asrs_table.php", timeout=4) or {}
        
        n1_map = {}
        for row in n1_recent.get("data", []):
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                ot_k = str(row[2] or "").strip()
                if ot_k:
                    n1_map[ot_k] = {
                        "tag": str(row[0] or "").strip(),
                        "titulo": str(row[1] or "").strip(),
                        "fecha": str(row[3] or "").strip(),
                        "hora": str(row[4] or "").strip(),
                        "tp_min": str(row[5] or "0").strip(),
                        "detalle": str(row[6] or "").strip() if len(row) > 6 else "",
                        "maquina": str(row[7] or "").strip() if len(row) > 7 else ""
                    }
        
        all_raw_rows = list(n1_orders.get("data", []))
        for row in n1_recent.get("data", []):
            all_raw_rows.append(row)

        seen_ots = set()
        for row in all_raw_rows:
            if not isinstance(row, (list, tuple)) or len(row) < 7:
                continue

            if len(row) >= 9 and str(row[0] or "").isdigit() and len(str(row[0] or "")) >= 6:
                ot = str(row[0] or "").strip()
                titulo_raw = str(row[1] or "").strip()
                fecha_str = str(row[2] or "").strip()
                maquina = str(row[4] or "").strip()
                tag_equipo = str(row[5] or "").strip()
                tp_min = str(row[7] or "0").strip()
                detalle_raw = str(row[8] or "").strip()
                if len(row) >= 10 and row[9]:
                    maquina = str(row[9]).strip() or maquina
                hora_str = "00:00:00"
                if " " in fecha_str:
                    parts = fecha_str.split(" ")
                    fecha_str, hora_str = parts[0], parts[1]
                elif ot in n1_map and n1_map[ot].get("hora"):
                    hora_str = n1_map[ot]["hora"]
                    if not tag_equipo and n1_map[ot].get("tag"):
                        tag_equipo = n1_map[ot]["tag"]
            elif len(row) >= 8:
                tag_equipo = str(row[0] or "").strip()
                titulo_raw = str(row[1] or "").strip()
                ot = str(row[2] or "").strip()
                fecha_str = str(row[3] or "").strip()
                hora_str = str(row[4] or "").strip()
                tp_min = str(row[5] or "0").strip()
                detalle_raw = str(row[6] or "").strip()
                maquina = str(row[7] or "").strip() or tag_equipo
            else:
                continue

            if not ot or not fecha_str or not hora_str or ot in seen_ots:
                continue

            try:
                if len(hora_str.split(":")) == 2:
                    order_dt = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M")
                else:
                    order_dt = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue

            if dt_start <= order_dt < dt_end:
                seen_ots.add(ot)
                titulo_final = _extraer_titulo_limpio(titulo_raw, detalle_raw)
                detalle_final = detalle_raw or titulo_raw or "Sin observaciones adicionales registradas."
                filtered_orders.append({
                    "ot": ot,
                    "hora": hora_str,
                    "equipo": tag_equipo or maquina,
                    "maquina": maquina or tag_equipo,
                    "titulo": titulo_final,
                    "tp_min": tp_min,
                    "detalle": detalle_final
                })

    turno_info = TURNOS_ENTREGA.get(turno_req, TURNOS_ENTREGA["T2"])
    
    from scheduler_service import consultar_ticket_programado
    _, formatted_ticket, _ = consultar_ticket_programado(port=8006)
    
    payload = {
        "consulta": {
            "fecha": fecha_req,
            "turno": turno_req,
            "turno_nombre": turno_info["nombre"],
            "rango_horas": f"{turno_info['inicio'][:5]} a {turno_info['fin'][:5]}",
            "start_dt": dt_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_dt": dt_end.strftime("%Y-%m-%d %H:%M:%S"),
            "ticket": formatted_ticket
        },
        "input_output": {
            "construido": construido_val,
            "vulcanizado": vulcanizado_val,
            "entrada_asrs": entrada_val,
            "total_salida": total_salida,
            "salida_manual": manual_val,
            "salida_auto": auto_val,
            "rate_entrada": rate_entrada_val,
            "rate_salida": rate_salida,
            "rate_manual": rate_manual_val,
            "rate_auto": rate_auto_val,
            "eficiencia_entrada": eficiencia_entrada
        },
        "crane_performance": {
            "disponibilidad_pct": crane_avail_pct,
            "top_downtime": top_cranes,
            "pasillos": crane_list
        },
        "conveyor": {
            "downtime_min": conveyor_data.get("total_downtime", 0.0),
            "frecuencia": conveyor_data.get("frequency", 0),
            "objetivo_min": conveyor_data.get("objective_minutes", 15.0),
            "is_ok": conveyor_data.get("is_ok", True)
        },
        "press_delivery": {
            "cumplimiento_global_pct": global_press_pct,
            "resumen_prensas": press_summary
        },
        "ordenes": filtered_orders,
        "ordenes_auth_required": orders_auth_required
    }

    return jsonify(payload)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_db()

    try:
        print("Servidor Web corriendo en el puerto 8006...")
        from waitress import serve
        serve(app, host='0.0.0.0', port=8006, threads=24)
    except Exception as e:
        print("Error iniciando Waitress, usando app.run()")
        app.run(host='0.0.0.0', port=8006, threaded=True)
