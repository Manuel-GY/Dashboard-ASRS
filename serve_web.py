import os
import re
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, request, jsonify

DB_PATH = 'shift_history.db'


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
            else:
                return jsonify({"success": False, "error": "Target no encontrado"}), 503
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503


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
