import os
import re
import time
import sqlite3
from datetime import datetime, timedelta

import requests
from pylogix import PLC

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
    """Retorna la última timestamp registrada en shift_summaries."""
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
# DATA COLLECTION
# ============================================================================

def fetch_and_save_shift_data():
    """Tarea principal: lee PLCs, APIs Goodyear/OEE y guarda todo en SQLite."""
    dt_eval = datetime.now() - timedelta(minutes=10)
    date_str, current_shift = get_current_shift_info(dt_eval)

    if current_shift == 'T1':
        start_dt = datetime.strptime(date_str + ' 22:00', '%Y-%m-%d %H:%M')
    elif current_shift == 'T2':
        start_dt = datetime.strptime(date_str + ' 06:00', '%Y-%m-%d %H:%M')
    else:
        start_dt = datetime.strptime(date_str + ' 14:00', '%Y-%m-%d %H:%M')
    end_dt = start_dt + timedelta(hours=8)

    conn = get_db()
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

                    cursor.execute("UPDATE io_history SET construido=?, vulcanizado=? WHERE fecha=? AND turno=?",
                                   (construido, vulcanizado, date_str, current_shift))
                    break
            else:
                print(f"[WARN] Goodyear API status {res_gy.status_code} (attempt {attempt+1}/{max_retries})")
        except Exception as e:
            print(f"[WARN] Error fetching Goodyear tires (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)

    conn.commit()
    conn.close()
    print(f"[{datetime.now()}] Shift data saved successfully for {date_str} {current_shift}")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_db()
    fetch_and_save_shift_data()
