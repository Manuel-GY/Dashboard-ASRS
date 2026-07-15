import os
import re
import time
import sqlite3
import concurrent.futures
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests
from pylogix import PLC
from bs4 import BeautifulSoup

_session = requests.Session()
_session.trust_env = False

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
    """Retorna la última timestamp registrada en shift_summaries."""
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
    """Determina fecha y turno (T1/T2/T3) según la hora del sistema."""
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


def get_shift_times(date_str, shift):
    """Retorna (start_dt, end_dt) para un turno dado."""
    if shift == 'T1':
        start_dt = datetime.strptime(date_str + ' 22:00', '%Y-%m-%d %H:%M')
    elif shift == 'T2':
        start_dt = datetime.strptime(date_str + ' 06:00', '%Y-%m-%d %H:%M')
    else:
        start_dt = datetime.strptime(date_str + ' 14:00', '%Y-%m-%d %H:%M')
    end_dt = start_dt + timedelta(hours=8)
    return start_dt, end_dt


def upsert_shift_data(cursor, fecha, turno, maquina, estado, minutos):
    """Inserta o actualiza registros de turnos en shift_summaries."""
    cursor.execute('''SELECT id FROM shift_summaries
                      WHERE fecha = ? AND turno = ? AND maquina = ? AND estado = ?''',
                   (fecha, turno, maquina, estado))
    row = cursor.fetchone()
    if row:
        cursor.execute('''UPDATE shift_summaries
                          SET minutos = ?, timestamp = CURRENT_TIMESTAMP
                          WHERE id = ?''', (minutos, row[0]))
    else:
        cursor.execute('''INSERT INTO shift_summaries (fecha, turno, maquina, estado, minutos)
                          VALUES (?, ?, ?, ?, ?)''', (fecha, turno, maquina, estado, minutos))


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
# DATA COLLECTION - PLCs & IO (EXISTING)
# ============================================================================

def fetch_and_save_shift_data():
    """Tarea principal: lee PLCs, APIs Goodyear/OEE y guarda todo en SQLite."""
    dt_eval = datetime.now() - timedelta(minutes=10)
    date_str, current_shift = get_current_shift_info(dt_eval)
    start_dt, end_dt = get_shift_times(date_str, current_shift)

    conn = get_db()
    try:
        cursor = conn.cursor()

        # --- LECTURA DE PLCs: Robots, Conveyors, Lubricadoras ---
        def save_robot_turn_data(robot_id, ip, base_tag, has_idle=False):
            comm = PLC()
            comm.IPAddress = ip
            comm.ProcessorSlot = 0
            try:
                tags_to_read = [f'{base_tag}.{current_shift}_TimerOK', f'{base_tag}.{current_shift}_TimerFault']
                if has_idle:
                    tags_to_read.append(f'{base_tag}.{current_shift}_TimerAuto')

                results = comm.Read(tags_to_read)
                for r in results:
                    if r.Status == 'Success':
                        tag = r.TagName
                        val = round(float(r.Value), 2)
                        estado = 'run' if 'TimerOK' in tag else ('auto' if 'TimerAuto' in tag else 'fault')
                        upsert_shift_data(cursor, date_str, current_shift, robot_id, estado, val)
            except Exception as e:
                print(f'[WARN] Error saving shift data for {robot_id}: {e}')
            finally:
                comm.Close()

        # Robots
        save_robot_turn_data('ULR1', '10.107.210.151', 'PickDownTimeUnload1', has_idle=True)
        save_robot_turn_data('ULR2', '10.107.210.150', 'PickDownTimeUnload2', has_idle=True)
        save_robot_turn_data('LR1', '10.107.210.141', 'PickDownTimeLoad1', has_idle=True)
        save_robot_turn_data('LR2', '10.107.210.140', 'PickDownTimeLoad2', has_idle=True)

        # Conveyors
        save_robot_turn_data('CC01', '10.107.210.111', 'DowntimeCC01', has_idle=True)
        save_robot_turn_data('CC02', '10.107.210.121', 'DowntimeCC02', has_idle=True)
        save_robot_turn_data('CC03', '10.107.210.131', 'DowntimeCC03', has_idle=True)

        # Lubricadoras
        save_robot_turn_data('L1', '10.107.210.51', 'DownTimePlummer1', has_idle=True)
        save_robot_turn_data('L2', '10.107.210.52', 'DownTimePlummer2', has_idle=True)
        save_robot_turn_data('L3', '10.107.210.53', 'DownTimePlummer3', has_idle=True)

        # --- IO DATA: Scraping de dashboard Goodyear ---
        try:
            url = "http://10.107.194.62/sbs/gtasrs_dashboard/gtasrs_dashboard_ctrl.php"
            res = _session.get(url, timeout=5)
            if res.status_code == 200:
                html = res.text
                def extract(id_name):
                    match = re.search(rf"getElementById\('{id_name}'\)\.innerHTML\s*=\s*'([^']+)'", html)
                    return match.group(1) if match else "0"

                entrada = extract("s1_inbound_total")
                manual = extract("s1_outbound_cv31_actual")
                auto = extract("s1_press_total")
                rate_entrada = extract("s1_inbound_avg")
                rate_manual = extract("s1_manual_rate")
                rate_auto = extract("s1_press_rate")

                cursor.execute("SELECT id FROM io_history WHERE fecha = ? AND turno = ?", (date_str, current_shift))
                row = cursor.fetchone()
                if row:
                    cursor.execute('''UPDATE io_history
                                      SET entrada=?, manual=?, auto=?, rate_entrada=?, rate_manual=?, rate_auto=?, timestamp=CURRENT_TIMESTAMP
                                      WHERE id=?''', (entrada, manual, auto, rate_entrada, rate_manual, rate_auto, row[0]))
                else:
                    cursor.execute('''INSERT INTO io_history (fecha, turno, entrada, manual, auto, rate_entrada, rate_manual, rate_auto)
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                                   (date_str, current_shift, entrada, manual, auto, rate_entrada, rate_manual, rate_auto))
        except Exception as e:
            print(f"[WARN] Error saving IO data: {e}")

        # --- GOODYEAR API: Construido (HVA) y Vulcanizado (Cura) ---
        shift_map = {'T1': 'noche', 'T2': 'manana', 'T3': 'tarde'}
        gy_turno = shift_map.get(current_shift, 'noche')
        url_gy = f"http://10.107.194.110/hora/get_tires/?dia={date_str}&turno={gy_turno}"

        max_retries = 3
        for attempt in range(max_retries):
            try:
                res_gy = _session.get(url_gy, timeout=15)
                if res_gy.status_code == 200:
                    data_gy = res_gy.json()
                    if data_gy.get("status") == "success":
                        construido = str(data_gy["data"]["total"]["hva"]["prod"])
                        vulcanizado = str(data_gy["data"]["total"]["cura"]["prod"])

                        cursor.execute("SELECT id FROM io_history WHERE fecha = ? AND turno = ?", (date_str, current_shift))
                        io_row = cursor.fetchone()
                        if io_row:
                            cursor.execute("UPDATE io_history SET construido=?, vulcanizado=? WHERE id=?",
                                           (construido, vulcanizado, io_row[0]))
                        else:
                            cursor.execute("INSERT INTO io_history (fecha, turno, construido, vulcanizado) VALUES (?, ?, ?, ?)",
                                           (date_str, current_shift, construido, vulcanizado))
                        break
                else:
                    print(f"[WARN] Goodyear API status {res_gy.status_code} (attempt {attempt+1}/{max_retries})")
            except Exception as e:
                print(f"[WARN] Error fetching Goodyear tires (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)

        conn.commit()
        print(f"[{datetime.now()}] Shift data saved successfully for {date_str} {current_shift}")
    finally:
        conn.close()


# ============================================================================
# DATA COLLECTION - CRANE PERFORMANCE
# ============================================================================

def fetch_and_save_crane_data():
    """Recolecta performance de grúas por pasillo desde la API de Goodyear."""
    dt_eval = datetime.now() - timedelta(minutes=10)
    date_str, current_shift = get_current_shift_info(dt_eval)
    start_dt, end_dt = get_shift_times(date_str, current_shift)
    start_fmt = start_dt.strftime('%Y/%m/%d %H:%M:%S')
    end_fmt = end_dt.strftime('%Y/%m/%d %H:%M:%S')

    url = f"http://10.107.194.62/sbs/reports/gtasrs_aisle_history.php?run=1&str_ts={requests.utils.quote(start_fmt)}&end_ts={requests.utils.quote(end_fmt)}"

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

        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM crane_aisle_history WHERE fecha = ? AND turno = ?", (date_str, current_shift))
            for item in aisle_data:
                cursor.execute('''INSERT INTO crane_aisle_history
                                  (fecha, turno, aisle, downtime_percent, downtime_minutes, query_start, query_end)
                                  VALUES (?, ?, ?, ?, ?, ?, ?)''',
                               (date_str, current_shift, item['aisle'], item['downtime_percent'],
                                item['downtime_minutes'], start_fmt, end_fmt))
            conn.commit()
        finally:
            conn.close()
        print(f"[{datetime.now()}] Crane data saved: {len(aisle_data)} aisles for {date_str} {current_shift}")
    except Exception as e:
        print(f"[WARN] Error saving crane data: {e}")


# ============================================================================
# DATA COLLECTION - CONVEYOR FULL
# ============================================================================

def fetch_and_save_conveyor_full():
    """Recolecta downtime del conveyor (reason 10315) desde API OEE."""
    dt_eval = datetime.now() - timedelta(minutes=10)
    date_str, current_shift = get_current_shift_info(dt_eval)
    start_dt, end_dt = get_shift_times(date_str, current_shift)
    start_fmt = start_dt.strftime('%Y/%m/%d %H:%M:%S')
    end_fmt = end_dt.strftime('%Y/%m/%d %H:%M:%S')

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

        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conveyor_full_downtime WHERE fecha = ? AND turno = ?", (date_str, current_shift))
            cursor.execute('''INSERT INTO conveyor_full_downtime
                              (fecha, turno, total_downtime_minutes, frequency, objective_minutes, query_start, query_end)
                              VALUES (?, ?, ?, ?, 15.0, ?, ?)''',
                           (date_str, current_shift, round(total_downtime, 2), frequency, start_fmt, end_fmt))
            conn.commit()
        finally:
            conn.close()
        print(f"[{datetime.now()}] Conveyor full data saved: {total_downtime:.2f} min for {date_str} {current_shift}")
    except Exception as e:
        print(f"[WARN] Error saving conveyor full data: {e}")


# ============================================================================
# DATA COLLECTION - PRESS DOWNTIME BY REASON
# ============================================================================

def fetch_and_save_press_downtime():
    """Recolecta downtime por reason code agrupado por prensa desde API OEE."""
    dt_eval = datetime.now() - timedelta(minutes=10)
    date_str, current_shift = get_current_shift_info(dt_eval)
    start_dt, end_dt = get_shift_times(date_str, current_shift)
    start_fmt = start_dt.strftime('%Y/%m/%d %H:%M:%S')
    end_fmt = end_dt.strftime('%Y/%m/%d %H:%M:%S')

    url = "http://10.107.194.85:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/SummaryDataByReason/SingleDowntimeReason.EditGrid/EditGrid/DataSource/loadId"
    reasons = ['160000', '210002']

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
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM press_downtime_by_reason WHERE fecha = ? AND turno = ?", (date_str, current_shift))

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(reasons)) as executor:
                futures = {executor.submit(_fetch_reason_downtime, r): r for r in reasons}
                for f in concurrent.futures.as_completed(futures):
                    reason_code = futures[f]
                    try:
                        for group, val in f.result():
                            cursor.execute('''INSERT INTO press_downtime_by_reason
                                              (fecha, turno, reason_code, press_group, downtime_minutes, query_start, query_end)
                                              VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                           (date_str, current_shift, reason_code, group, round(val, 2), start_fmt, end_fmt))
                    except Exception as e:
                        print(f'[WARN] Error saving downtime reason {reason_code}: {e}')

            conn.commit()
        finally:
            conn.close()
        print(f"[{datetime.now()}] Press downtime data saved for {date_str} {current_shift}")
    except Exception as e:
        print(f"[WARN] Error saving press downtime data: {e}")


# ============================================================================
# DATA COLLECTION - PRESS DELIVERY
# ============================================================================

def fetch_and_save_press_delivery():
    """Recolecta eficiencia de despacho por prensa: compliance + vulcanización + KPIs."""
    dt_eval = datetime.now() - timedelta(minutes=10)
    date_str, current_shift = get_current_shift_info(dt_eval)
    start_dt, end_dt = get_shift_times(date_str, current_shift)
    start_fmt = start_dt.strftime('%Y/%m/%d %H:%M:%S')
    end_fmt = end_dt.strftime('%Y/%m/%d %H:%M:%S')

    groups = {f"{r}00{s}": {"delivered": 0, "cancelled": 0, "total": 0, "vulcanized": 0} for r in range(4,7) for s in ["A","B"] if f"{r}00{s}" != "400A"}
    ignored_cavities = {"440", "520", "540", "620", "640"}

    # Call 1: Compliance data
    url_compliance = f"http://10.107.194.62/sbs/reports/auto_order_compliance.php?byheader=0&sortby=order_num&sortorder=ASC&str_ts={requests.utils.quote(start_fmt)}&end_ts={requests.utils.quote(end_fmt)}&prszone=&prsrow=all_rows&prscav=all_cavs"
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
                    try:
                        group = "400B" if dest.startswith("4") else (f"{dest[0]}00A" if int(dest) % 2 != 0 else f"{dest[0]}00B")
                    except ValueError:
                        continue
                    if group in groups:
                        groups[group]["total"] += 1
                        if status == "Fulfilled": groups[group]["delivered"] += 1
                        elif status == "Cancelled": groups[group]["cancelled"] += 1
    except Exception as e:
        print(f'[WARN] Error fetching press compliance: {e}')

    # Call 2: Vulcanization crosstab
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
                except Exception:
                    product_cnt = 0
                if dest in ignored_cavities: continue
                try:
                    group = "400B" if dest.startswith("4") else (f"{dest[0]}00A" if int(dest) % 2 != 0 else f"{dest[0]}00B")
                except ValueError:
                    continue
                if group in groups:
                    groups[group]["vulcanized"] += product_cnt
    except Exception as e:
        print(f'[WARN] Error fetching vulcanization: {e}')

    # Call 3: Press KPI data (hourly time breakdowns)
    machines_map = {0: '400B', 1: '500A', 2: '500B', 3: '600A', 4: '600B'}
    variables = ['t_idle', 't_estop', 't_znl', 't_trays']

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
                if hour_int < 0 or hour_int > 23: continue

                attempts = 0
                while current_date.hour != hour_int and attempts < 24:
                    current_date -= timedelta(hours=1)
                    attempts += 1

                if current_date.hour != hour_int: continue

                if target_start <= current_date <= target_end:
                    val = item.get(var)
                    if val:
                        try:
                            groups[m_name]['times'][val_key] += float(val)
                        except Exception:
                            pass

                current_date -= timedelta(hours=1)

    for m_name in groups:
        t_data = groups[m_name]['times']
        sum_down = t_data['idle'] + t_data['estop'] + t_data['cortinas'] + t_data['prensa']
        t_data['despachando'] = max(0, ((end_dt - start_dt).total_seconds() / 60.0) - sum_down)

    # Save to DB
    try:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM press_delivery_data WHERE fecha = ? AND turno = ?", (date_str, current_shift))

            for m_name, m_data in groups.items():
                t = m_data['times']
                cursor.execute('''INSERT INTO press_delivery_data
                                  (fecha, turno, press_group, delivered, cancelled, total_orders, vulcanized,
                                   t_idle, t_estop, t_cortinas, t_prensa, query_start, query_end)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                               (date_str, current_shift, m_name, m_data['delivered'], m_data['cancelled'],
                                m_data['total'], m_data['vulcanized'],
                                round(t['idle'], 2), round(t['estop'], 2), round(t['cortinas'], 2), round(t['prensa'], 2),
                                start_fmt, end_fmt))

            conn.commit()
        finally:
            conn.close()
        print(f"[{datetime.now()}] Press delivery data saved for {date_str} {current_shift}")
    except Exception as e:
        print(f"[WARN] Error saving press delivery data: {e}")


# ============================================================================
# DATA COLLECTION - DAILY TICKET
# ============================================================================

def fetch_and_save_daily_ticket():
    """Recolecta target diario de producción desde AOP."""
    try:
        now = get_capped_now()
        date_str = now.strftime('%Y-%m-%d')
        date_fmt = now.strftime('%m/%d')

        url = "http://akrmfgcorp.akr.goodyear.com/mfgcorp/aop/pzkmtsc.jsp?RptView=LA"
        res = _session.get(url, timeout=10)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, 'html.parser')
        target = 0
        for tr in soup.find_all('tr'):
            tds = tr.find_all(['td', 'th'])
            if tds and tds[0].get_text(strip=True) == date_fmt:
                if len(tds) > 3:
                    chile_fcst_str = tds[3].get_text(strip=True)
                    try:
                        target = int(float(chile_fcst_str) * 1000)
                        break
                    except ValueError:
                        pass

        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM daily_ticket_target WHERE fecha = ?", (date_str,))
            row = cursor.fetchone()
            if row:
                cursor.execute("UPDATE daily_ticket_target SET target = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?", (target, row[0]))
            else:
                cursor.execute("INSERT INTO daily_ticket_target (fecha, target) VALUES (?, ?)", (date_str, target))
            conn.commit()
        finally:
            conn.close()
        print(f"[{datetime.now()}] Daily ticket saved: {target} for {date_str}")
    except Exception as e:
        print(f"[WARN] Error saving daily ticket: {e}")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_db()
    fetch_and_save_shift_data()
    fetch_and_save_crane_data()
    fetch_and_save_conveyor_full()
    fetch_and_save_press_downtime()
    fetch_and_save_press_delivery()
    fetch_and_save_daily_ticket()
