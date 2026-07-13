import os
import re
import sqlite3
import urllib.parse
import concurrent.futures
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

import requests
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup

_session = requests.Session()
_session.proxies.update({"http": None, "https": None})

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
        cursor = conn.cursor()
        cursor.execute("SELECT datetime(MAX(timestamp), 'localtime') FROM shift_summaries")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
    except Exception as e:
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


def parse_start_end(default_hours=24):
    """Parsea parámetros start/end del request. Retorna (start_dt, end_dt, start_fmt, end_fmt)."""
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M') if start_str else get_capped_now() - timedelta(hours=default_hours)
    end_dt = datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M') if end_str else get_capped_now()
    return start_dt, end_dt, start_dt.strftime('%Y/%m/%d %H:%M:%S'), end_dt.strftime('%Y/%m/%d %H:%M:%S')


def calc_idle(auto, run, fault):
    """Calcula tiempo idle: auto - run - fault (mínimo 0)."""
    return max(0, auto - run - fault)


def build_cache_key(path, params):
    """Genera cache key excluyendo el parámetro 'live'."""
    filtered = {k: v for k, v in params.items() if k != 'live'}
    sorted_query = urllib.parse.urlencode(sorted(filtered.items()))
    return f"{path}?{sorted_query}" if sorted_query else path


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
    conn.commit()
    conn.close()


# ============================================================================
# FLASK APP + CACHE MIDDLEWARE
# ============================================================================

app = Flask(__name__, static_folder='static', static_url_path='')

from flask import current_app

@app.before_request
def serve_from_cache():
    """Intercepta requests a /api/ y retorna respuesta cacheada si es válida (<5 min)."""
    if request.path.startswith('/api/') and request.path not in ['/api/io-data', '/api/ulr1-turnos', '/api/ulr2-turnos', '/api/lr1-turnos', '/api/lr2-turnos']:
        if request.args.get('live') == '1':
            return

        cache_key = build_cache_key(request.path, dict(request.args))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT response_json, timestamp FROM api_cache WHERE cache_key=?", (cache_key,))
        row = cursor.fetchone()
        conn.close()

        if row:
            try:
                cache_time = datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
                if (datetime.utcnow() - cache_time).total_seconds() < 300:
                    return current_app.response_class(row[0], mimetype='application/json')
            except Exception as e:
                pass

@app.after_request
def cache_response(response):
    """Almacena respuesta exitosa en api_cache para servir desde cache en requests futuros."""
    if request.path.startswith('/api/') and request.args.get('live') != '1' and response.status_code == 200:
        if request.path not in ['/api/io-data', '/api/ulr1-turnos', '/api/ulr2-turnos', '/api/lr1-turnos', '/api/lr2-turnos']:
            cache_key = build_cache_key(request.path, dict(request.args))
            try:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('''INSERT OR REPLACE INTO api_cache (cache_key, response_json, timestamp)
                                  VALUES (?, ?, CURRENT_TIMESTAMP)''', (cache_key, response.get_data(as_text=True)))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[WARN] Cache insert error: {e}")
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
        cursor = conn.cursor()
        cursor.execute("SELECT entrada, manual, auto, rate_entrada, rate_manual, rate_auto, construido, vulcanizado FROM io_history WHERE fecha = ? AND turno = ?", (target_date, target_shift))
        row = cursor.fetchone()
        conn.close()

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

        conn.close()
        return jsonify({"success": True, "data": data, "source": "db"})
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

        conn.close()
        return jsonify({"success": True, "data": data, "source": "db"})
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

        conn.close()
        return jsonify({"success": True, "plummers": plummers, "source": "db", "last_updated": last_updated_db})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/crane-performance')
def api_crane_performance():
    """Consulta API de Goodyear para performance de grúas por pasillo (disponibilidad, downtime %)."""
    try:
        start_dt, end_dt, start_fmt, end_fmt = parse_start_end(8)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    url = f"http://10.107.194.62/sbs/reports/gtasrs_aisle_history.php?run=1&str_ts={urllib.parse.quote(start_fmt)}&end_ts={urllib.parse.quote(end_fmt)}"

    try:
        res = _session.get(url, timeout=10)
        res.encoding = 'utf-8' if not res.content.startswith(b'\xff\xfe') else 'utf-16le'
        html_text = res.text

        aisle_data = []
        matches = re.finditer(r'value=[\'"]Aisle\s+(\d+)\s+([\d\.]+)%\s+(\d+)\s+min[\'"]', html_text, re.IGNORECASE)
        for m in matches:
            aisle_data.append({"aisle": int(m.group(1)), "downtime_percent": float(m.group(2)), "downtime_minutes": int(m.group(3))})

        if not aisle_data:
            matches = re.finditer(r'<input[^>]+value=[\'"]([^\'"]+)[\'"]', html_text, re.IGNORECASE)
            for m in matches:
                val_str = m.group(1)
                if "Aisle" in val_str and "%" in val_str and "min" in val_str:
                    parts = re.split(r'\s+', val_str.replace('\n', ' ').replace('\r', '').strip())
                    if len(parts) >= 5:
                        try:
                            aisle_data.append({"aisle": int(parts[1]), "downtime_percent": float(parts[2].replace('%', '')), "downtime_minutes": int(parts[3])})
                        except Exception as e:
                            print(f'[WARN] Error parsing aisle data: {e}')

        return jsonify({"success": True, "url_queried": url, "data": aisle_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/conveyor-full')
def api_conveyor_full():
    """Consulta API OEE para tiempo total de downtime del conveyor (reason 10315). Objetivo: 15 min."""
    try:
        start_dt, end_dt, start_fmt, end_fmt = parse_start_end(24)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    url = "http://10.107.194.114:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/SummaryDataByReason/SummaryDataByReason.EditGrid/EditGrid/DataSource/loadId"
    params = {
        "ARG_MACH_TYPE": "HFPLT4", "ARG_MACH_PART_NAME": "",
        "ARG_START_DATE": start_fmt, "ARG_END_DATE": end_fmt,
        "ARG_OEE_GROUP_SET_ID": "1", "ARG_MACHINE_GROUP_GUID": "6012295917FD36E2E05373C26B0A2E11",
        "ARG_LANG": "ENG", "ARG_OEE_GROUP_UID": "5826BFF57FA71BBCE05373C26B0A0752"
    }

    try:
        res = _session.get(url, params=params, headers={"Accept-language": "en"}, timeout=10)
        root = ET.fromstring(res.content)
        total_downtime = 0.0
        frequency = 0
        for row in root.findall('.//Row'):
            reason_el = row.find('DOWNTIME_REASON')
            if reason_el is not None and (reason_el.text or '').strip() == "10315":
                min_el = row.find('DOWNTIME_MINUTES')
                freq_el = row.find('FREQUENCY')
                if min_el is not None: total_downtime += float(min_el.text or "0")
                if freq_el is not None: frequency += int(float(freq_el.text or "0"))

        return jsonify({
            "success": True, "query_start": start_fmt, "query_end": end_fmt,
            "total_downtime": round(total_downtime, 2), "frequency": frequency,
            "objective_minutes": 15.0, "is_ok": round(total_downtime, 2) <= 15.0, "mock": False
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/downtime')
def api_downtime():
    """Consulta API OEE para downtime por reason code, agrupado por prensa (100A-600B). Paraleliza requests."""
    reason = request.args.get('reason', '')
    if not all(r.strip().isdigit() for r in reason.split(',') if r.strip()):
        return jsonify({"error": "Parámetro inválido"}), 400

    try:
        start_dt, end_dt, start_fmt, end_fmt = parse_start_end(24)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    url = "http://10.107.194.85:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/SummaryDataByReason/SingleDowntimeReason.EditGrid/EditGrid/DataSource/loadId"
    reasons = [r.strip() for r in reason.split(",") if r.strip()]

    def _fetch_reason_downtime(reason_code):
        params = {
            "ARG_MACH_TYPE": "PRS", "ARG_MACH_PART_NAME": "", "ARG_DOWNTIME_REASON": reason_code,
            "ARG_START_DATE": start_fmt, "ARG_END_DATE": end_fmt,
            "ARG_LANG": "ENG", "ARG_MACHINE_GROUP_GUID": ""
        }
        res = _session.get(url, params=params, headers={"Accept-language": "en"}, timeout=8)
        root = ET.fromstring(res.content)
        results = []
        for row in root.findall('.//Row'):
            mach_el = row.find('MACH_PART_NAME')
            down_el = row.find('DOWN_TIME')
            if mach_el is not None and down_el is not None:
                mach = (mach_el.text or "").strip()
                match = re.match(r'^([1-6])(\d+)$', mach)
                if match:
                    group = match.group(1) + '00' + ('A' if int(match.group(2)) % 2 != 0 else 'B')
                    results.append((group, float(down_el.text or "0")))
        return results

    try:
        downtime_by_group = {f"{r}00{s}": 0.0 for r in range(1,7) for s in ["A","B"]}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(reasons)) as executor:
            futures = {executor.submit(_fetch_reason_downtime, r): r for r in reasons}
            for f in concurrent.futures.as_completed(futures):
                try:
                    for group, val in f.result():
                        if group in downtime_by_group:
                            downtime_by_group[group] += val
                except Exception as e:
                    print(f'[WARN] Error fetching downtime reason {futures[f]}: {e}')

        duration_minutes = max(1, round((end_dt - start_dt).total_seconds() / 60))
        total_downtime = sum(downtime_by_group.values())
        downtime_percent = (total_downtime / (duration_minutes * 48)) * 100

        for k in downtime_by_group:
            downtime_by_group[k] = round(downtime_by_group[k], 2)

        return jsonify({
            "success": True, "duration_minutes": duration_minutes,
            "downtime_by_group": downtime_by_group, "total_downtime": round(total_downtime, 2),
            "downtime_percent": round(downtime_percent, 2), "mock": False
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/press-delivery')
def api_press_delivery():
    """Eficiencia de despacho por prensa (400B-600B). Combina: compliance API + vulcanización + KPIs horarios."""
    try:
        start_dt, end_dt, start_fmt, end_fmt = parse_start_end(8)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    url_compliance = f"http://10.107.194.62/sbs/reports/auto_order_compliance.php?byheader=0&sortby=order_num&sortorder=ASC&str_ts={urllib.parse.quote(start_fmt)}&end_ts={urllib.parse.quote(end_fmt)}&prszone=&prsrow=all_rows&prscav=all_cavs"
    groups = {f"{r}00{s}": {"delivered": 0, "cancelled": 0, "total": 0, "vulcanized": 0} for r in range(4,7) for s in ["A","B"] if f"{r}00{s}" != "400A"}
    ignored_cavities = {"440", "520", "540", "620", "640"}

    try:
        res = _session.get(url_compliance, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        target_table = next((t for t in soup.find_all("table") if len(t.find_all("tr")) > 10), None)
        if target_table:
            for r in target_table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in r.find_all("td")]
                if len(cells) > 7:
                    status, dest = cells[1], cells[7]
                    if dest in ignored_cavities: continue
                    group = "400B" if dest.startswith("4") else (f"{dest[0]}00A" if int(dest) % 2 != 0 else f"{dest[0]}00B")
                    if group in groups:
                        groups[group]["total"] += 1
                        if status == "Fulfilled": groups[group]["delivered"] += 1
                        elif status == "Cancelled": groups[group]["cancelled"] += 1
    except Exception as e:
        print(f'[WARN] Error fetching press compliance: {e}')

    url_cross = "http://10.107.194.85:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/Production_Counts_Crosstab/Production_Counts_Crosstab.CrossTab/CrossTab/DataSource/DS1"
    params_cross = {
        "ARG_TRANS_START_DATE": start_fmt, "ARG_TRANS_END_DATE": end_fmt,
        "ARG_MACHINE_GROUP_GUID": "9A98FF823A234EEDE05356C26B0A13F5", "ARG_TIME_SUMMARY": "DD",
        "ARG_MACH_TYPE": "", "ARG_COLUMN": "MACH_PART_NAME;", "ARG_ROW": "PRODUCTION_HOUR;",
        "ARG_DATA": "PRODUCT_CNT;", "ARG_LANG": "ENG", "ARG_LANGUAGE_CD": "en", "ARG_USER": ""
    }
    try:
        res_cross = _session.get(url_cross, params=params_cross, headers={"Accept-language": "en"}, timeout=10)
        root = ET.fromstring(res_cross.content)
        for row in root.findall('.//Row'):
            mach_el = row.find('MACH_PART_NAME')
            cnt_el = row.find('PRODUCT_CNT')
            if mach_el is not None and cnt_el is not None:
                dest = (mach_el.text or "").strip()
                try:
                    product_cnt = int(float(cnt_el.text or "0"))
                except Exception as e:
                    product_cnt = 0
                if dest in ignored_cavities: continue
                group = "400B" if dest.startswith("4") else (f"{dest[0]}00A" if int(dest) % 2 != 0 else f"{dest[0]}00B")
                if group in groups:
                    groups[group]["vulcanized"] += product_cnt
    except Exception as e:
        print(f'[WARN] Error fetching vulcanization: {e}')

    machines_map = {0: '400B', 1: '500A', 2: '500B', 3: '600A', 4: '600B'}
    variables = ['t_idle', 't_estop', 't_znl', 't_trays']
    total_minutes = max(0, (end_dt - start_dt).total_seconds() / 60.0)

    def fetch_machine_var(m_id, var):
        url = f"http://10.107.194.70/ASRS/press_kpi_data.php?machine={m_id}&variable={var}"
        try:
            res = _session.get(url, timeout=5)
            return m_id, var, res.json()
        except Exception as e:
            print(f'[WARN] Error fetching KPI m={m_id} v={var}: {e}')
            return m_id, var, []

    for m in groups:
        groups[m]['times'] = {'idle': 0.0, 'estop': 0.0, 'cortinas': 0.0, 'prensa': 0.0, 'despachando': 0.0}

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        for m_id in machines_map:
            for var in variables:
                futures.append(executor.submit(fetch_machine_var, m_id, var))

        for f in concurrent.futures.as_completed(futures):
            m_id, var, data = f.result()
            m_name = machines_map.get(m_id)
            if m_name not in groups: continue

            val_key = var.replace('t_', '')
            if val_key == 'znl': val_key = 'cortinas'
            if val_key == 'trays': val_key = 'prensa'

            current_date = get_capped_now().replace(minute=0, second=0, microsecond=0)
            target_start = start_dt.replace(minute=0, second=0, microsecond=0)
            target_end = end_dt.replace(minute=0, second=0, microsecond=0)

            for item in reversed(data):
                hour_str = str(item.get('time'))
                if not hour_str.isdigit(): continue
                hour_int = int(hour_str)

                while current_date.hour != hour_int:
                    current_date -= timedelta(hours=1)

                if target_start <= current_date <= target_end:
                    val = item.get(var)
                    if val:
                        try:
                            groups[m_name]['times'][val_key] += float(val)
                        except Exception as e:
                            pass

                current_date -= timedelta(hours=1)

    for m_name in groups:
        t_data = groups[m_name]['times']
        sum_down = t_data['idle'] + t_data['estop'] + t_data['cortinas'] + t_data['prensa']
        t_data['despachando'] = max(0, total_minutes - sum_down)

    return jsonify({"success": True, "presses": groups, "uptime": 99.40})

@app.route('/api/daily-ticket')
def api_daily_ticket():
    """Consulta AOP para obtener target diario de producción (Chile FCST)."""
    try:
        now = get_capped_now()
        date_str = now.strftime('%m/%d')

        url = "http://akrmfgcorp.akr.goodyear.com/mfgcorp/aop/pzkmtsc.jsp?RptView=LA"
        res = _session.get(url, timeout=10)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, 'html.parser')
        target = 0
        for tr in soup.find_all('tr'):
            tds = tr.find_all(['td', 'th'])
            if tds and tds[0].get_text(strip=True) == date_str:
                if len(tds) > 3:
                    chile_fcst_str = tds[3].get_text(strip=True)
                    try:
                        target = int(float(chile_fcst_str) * 1000)
                        break
                    except ValueError:
                        pass

        if target > 0:
            return jsonify({"success": True, "total": target, "formatted": f"{target:,}"})
        else:
            return jsonify({"success": False, "error": "Target no encontrado para hoy en AOP"}), 503

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
