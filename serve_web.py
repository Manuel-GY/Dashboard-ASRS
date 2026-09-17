import os
import sys
import re
import json
import sqlite3
import threading
from datetime import datetime, timedelta
import requests
import urllib3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from flask import Flask, request, jsonify

DB_PATH = 'shift_history.db'
INSPECCIONES_BASE = "http://10.107.194.70/ASRS/inspecciones"
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "schedule_config.json")

TURNOS_ENTREGA = {
    "T1": {"nombre": "Turno Noche (T1)", "inicio": "22:00:00", "fin": "06:00:00", "cruza_medianoche": True},
    "T2": {"nombre": "Turno Mañana (T2)", "inicio": "06:00:00", "fin": "14:00:00", "cruza_medianoche": False},
    "T3": {"nombre": "Turno Tarde (T3)", "inicio": "14:00:00", "fin": "22:00:00", "cruza_medianoche": False},
}


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

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


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
        crane_avail_pct = 100.0
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

    # 2. Fetch Orders from Inspecciones (con timeout corto y caché)
    n1_orders = fetch_json(f"{INSPECCIONES_BASE}/index_n1asrs_table.php", timeout=4) or {}
    
    ORDERS_CACHE_FILE = os.path.join(os.path.dirname(__file__), "orders_cache.json")
    if n1_orders.get("data"):
        try:
            with open(ORDERS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(n1_orders, f, ensure_ascii=False)
        except Exception:
            pass
    elif os.path.exists(ORDERS_CACHE_FILE):
        try:
            with open(ORDERS_CACHE_FILE, "r", encoding="utf-8") as f:
                n1_orders = json.load(f)
        except Exception:
            pass

    filtered_orders = []
    seen_ots = set()

    for row in n1_orders.get("data", []):
        if len(row) >= 8:
            tag_equipo = str(row[0] or "").strip()
            titulo = str(row[1] or "").strip()
            ot = str(row[2] or "").strip()
            fecha_str = str(row[3] or "").strip()
            hora_str = str(row[4] or "").strip()
            tp_min = str(row[5] or "0").strip()
            detalle = str(row[6] or "").strip()
            maquina = str(row[7] or "").strip() or tag_equipo

            if not ot or not fecha_str or not hora_str:
                continue

            try:
                if len(hora_str.split(":")) == 2:
                    order_dt = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M")
                else:
                    order_dt = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue

            if dt_start <= order_dt < dt_end and ot not in seen_ots:
                seen_ots.add(ot)
                filtered_orders.append({
                    "ot": ot,
                    "hora": hora_str,
                    "equipo": tag_equipo or maquina,
                    "maquina": maquina or tag_equipo,
                    "titulo": titulo or "Aviso correctivo",
                    "tp_min": tp_min,
                    "detalle": detalle or titulo
                })

    turno_info = TURNOS_ENTREGA.get(turno_req, TURNOS_ENTREGA["T2"])
    
    payload = {
        "consulta": {
            "fecha": fecha_req,
            "turno": turno_req,
            "turno_nombre": turno_info["nombre"],
            "rango_horas": f"{turno_info['inicio'][:5]} a {turno_info['fin'][:5]}",
            "start_dt": dt_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_dt": dt_end.strftime("%Y-%m-%d %H:%M:%S")
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
        "ordenes": filtered_orders
    }

    return jsonify(payload)

@app.route('/api/schedule-config', methods=['GET', 'POST'])
def api_schedule_config():
    """Lee y actualiza la configuración dinámica de horarios de Teams."""
    from scheduler_service import load_schedule_config, CONFIG_PATH
    
    if request.method == 'GET':
        return jsonify(load_schedule_config())
        
    try:
        data = request.get_json() or {}
        current_cfg = load_schedule_config()
        current_cfg.update({
            "auto_send_enabled": bool(data.get("auto_send_enabled", True)),
            "t1_time": str(data.get("t1_time", "06:45")).strip(),
            "t2_time": str(data.get("t2_time", "14:45")).strip(),
            "t3_time": str(data.get("t3_time", "22:45")).strip(),
            "webhook_url": str(data.get("webhook_url", current_cfg.get("webhook_url", ""))).strip()
        })
        
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(current_cfg, f, indent=2, ensure_ascii=False)
            
        return jsonify({"success": True, "config": current_cfg})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/send-teams", methods=["GET", "POST"])
def api_send_teams():
    now_date, now_shift = get_current_shift_info()
    fecha_req = request.args.get("fecha", now_date)
    turno_req = request.args.get("turno", now_shift)
    force = request.args.get("force", "false").lower() == "true"
    renderer = request.args.get("renderer", "pillow").lower()
    
    from scheduler_service import consultar_ticket_programado, ejecutar_proceso_envio_turno
    
    total_ticket, formatted_ticket, ok = consultar_ticket_programado(port=8006)
    if total_ticket <= 0 and not force:
        return jsonify({
            "success": False,
            "skipped": True,
            "message": f"Envío omitido: Ticket Requerido en 0 tires ({formatted_ticket}). Use force=true para forzar.",
            "ticket": formatted_ticket
        }), 200
        
    exito, msg = ejecutar_proceso_envio_turno(turno_req, fecha_req, port=8006, force=force, renderer=renderer)
    return jsonify({
        "success": exito,
        "message": msg,
        "turno": turno_req,
        "fecha": fecha_req,
        "ticket": formatted_ticket
    }), (200 if exito else 500)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_db()

    # Iniciar scheduler en segundo plano
    try:
        from scheduler_service import iniciar_scheduler_loop
        t_sched = threading.Thread(target=iniciar_scheduler_loop, kwargs={"port": 8006}, daemon=True)
        t_sched.start()
        print("Scheduler automático de Teams iniciado en segundo plano.")
    except Exception as e:
        print(f"Error iniciando scheduler: {e}")

    try:
        print("Servidor Web corriendo en el puerto 8006...")
        from waitress import serve
        serve(app, host='0.0.0.0', port=8006, threads=24)
    except Exception as e:
        print("Error iniciando Waitress, usando app.run()")
        app.run(host='0.0.0.0', port=8006, threaded=True)

