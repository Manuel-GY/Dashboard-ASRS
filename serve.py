import os
import sys
import re
import time
import json
import sqlite3
import threading
import urllib.parse
import concurrent.futures
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

import requests
from flask import Flask, request, jsonify, send_from_directory, abort
from bs4 import BeautifulSoup
from pylogix import PLC




def get_capped_now():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT datetime(MAX(timestamp), 'localtime') FROM shift_summaries")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
    except:
        pass
    return datetime.now()

app = Flask(__name__, static_folder='static', static_url_path='')

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/io-data')
def api_io_data():
    start_str = request.args.get('start', '')
    
    target_date, target_shift = get_current_shift_info()
    if start_str:
        try:
            start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            target_date, target_shift = get_current_shift_info(start_dt)
        except Exception as e:
            print(f'[WARN] Error parsing date params: {e}')
            
    try:
        conn = sqlite3.connect(DB_PATH)
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

def fetch_robot_turnos_data(machine_name, ip_address, base_tag):
    start_str = request.args.get('start', '')
    target_date = None
    target_shift = 'T1'
    
    if start_str:
        try:
            start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            target_date, target_shift = get_current_shift_info(start_dt)
        except Exception as e: print(f'[WARN] Error parsing start date: {e}')
    
    current_date, _ = get_current_shift_info()
    if not target_date: target_date = current_date
    
    data = {
        "T1": {"run": 0, "fault": 0, "auto": 0, "idle": 0},
        "T2": {"run": 0, "fault": 0, "auto": 0, "idle": 0},
        "T3": {"run": 0, "fault": 0, "auto": 0, "idle": 0}
    }
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT turno, estado, minutos FROM shift_summaries WHERE fecha = ? AND maquina = ?', (target_date, machine_name))
        rows = cursor.fetchall()
        
        for r in rows:
            t, est, mins = r
            if est == 'idle': est = 'auto'
            if t in data and est in data[t]:
                data[t][est] = mins
                
        for t in ['T1', 'T2', 'T3']:
            prev_data = get_previous_odometer(cursor, target_date, t, machine_name)
            for est in ['run', 'fault', 'auto']:
                if data[t][est] > 0 and prev_data[est] > 0:
                    delta = data[t][est] - prev_data[est]
                    if delta >= 0:
                        data[t][est] = delta
                        
        conn.close()
                    
        for t in ['T1', 'T2', 'T3']:
            idle = data[t]['auto'] - data[t]['run'] - data[t]['fault']
            data[t]['idle'] = max(0, idle)
            
        return jsonify({"success": True, "data": data, "source": "db"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/ulr1-turnos')
def api_ulr1_turnos(): return fetch_robot_turnos_data('ULR1', '10.107.210.151', 'PickDownTimeUnload1')

@app.route('/api/ulr2-turnos')
def api_ulr2_turnos(): return fetch_robot_turnos_data('ULR2', '10.107.210.150', 'PickDownTimeUnload2')

@app.route('/api/lr1-turnos')
def api_lr1_turnos(): return fetch_robot_turnos_data('LR1', '10.107.210.141', 'PickDownTimeLoad1')

@app.route('/api/lr2-turnos')
def api_lr2_turnos(): return fetch_robot_turnos_data('LR2', '10.107.210.140', 'PickDownTimeLoad2')

@app.route('/api/plc-conveyor')
def api_plc_conveyor():
    start_str = request.args.get('start', '')
    target_date = None
    target_shift = None
    if start_str:
        try:
            start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            target_date, target_shift = get_current_shift_info(start_dt)
        except Exception as e: print(f'[WARN] Error parsing conveyor start date: {e}')
    
    current_date, current_shift = get_current_shift_info()
    if not target_date: target_date = current_date
    if not target_shift: target_shift = current_shift
    machines = ['CC01', 'CC02', 'CC03']
    
    data = {m: {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0, 'AUTO': 0.0} for m in machines}
    
    try:
        conn = sqlite3.connect(DB_PATH)
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
            prev_data = get_previous_odometer(cursor, target_date, target_shift, maq)
            for k_est, db_est in [('RUN', 'run'), ('STOP', 'fault'), ('AUTO', 'auto')]:
                if data[maq][k_est] > 0 and prev_data[db_est] > 0:
                    delta = data[maq][k_est] - prev_data[db_est]
                    if delta >= 0:
                        data[maq][k_est] = delta
                        
            idle_val = data[maq]['AUTO'] - data[maq]['RUN'] - data[maq]['STOP']
            data[maq]['IDLE'] = max(0, idle_val)
            del data[maq]['AUTO']
            
        conn.close()
        return jsonify({"success": True, "data": data, "source": "db"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/asrs-engineering-data')
def api_asrs_engineering():
    start_str = request.args.get('start', '')
    target_date = None
    target_shift = None
    if start_str:
        try:
            start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            target_date, target_shift = get_current_shift_info(start_dt)
        except Exception as e: print(f'[WARN] Error parsing engineering start date: {e}')
    
    current_date, current_shift = get_current_shift_info()
    if not target_date: target_date = current_date
    if not target_shift: target_shift = current_shift
    
    robots_list = []
    plummers_list = ['L1', 'L2', 'L3']
    all_mach = robots_list + plummers_list
    
    robots = {m: {'idle': 0.0, 'working': 0.0, 'waiting': 0.0, 'failure': 0.0} for m in robots_list}
    plummers = {m: {'run': 0.0, 'idle': 0.0, 'stop': 0.0, 'auto': 0.0} for m in plummers_list}
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT maquina, estado, minutos FROM shift_summaries WHERE fecha = ? AND turno = ? AND maquina IN ({seq})'.format(seq=','.join(['?']*len(all_mach))), [target_date, target_shift] + all_mach)
        rows = cursor.fetchall()
        
        for maq, est, mins in rows:
            if est == 'idle': est = 'auto'
            if maq in robots: robots[maq][est] = mins
            if maq in plummers:
                if est == 'run': plummers[maq]['run'] = mins
                elif est == 'fault': plummers[maq]['stop'] = mins
                elif est == 'auto': plummers[maq]['auto'] = mins
                
        for maq in robots_list:
            prev_data = get_previous_odometer(cursor, target_date, target_shift, maq)
            for est in ['idle', 'working', 'waiting', 'failure']:
                # Note: original code didn't seem to math robots for asrs engineering, but just in case
                if robots[maq][est] > 0 and prev_data.get(est, 0) > 0:
                    delta = robots[maq][est] - prev_data[est]
                    if delta >= 0: robots[maq][est] = delta
                    
        for maq in plummers_list:
            prev_data = get_previous_odometer(cursor, target_date, target_shift, maq)
            for k_est, db_est in [('run', 'run'), ('stop', 'fault'), ('auto', 'auto')]:
                if plummers[maq][k_est] > 0 and prev_data[db_est] > 0:
                    delta = plummers[maq][k_est] - prev_data[db_est]
                    if delta >= 0: plummers[maq][k_est] = delta
                    
            idle_val = plummers[maq]['auto'] - plummers[maq]['run'] - plummers[maq]['stop']
            plummers[maq]['idle'] = max(0, idle_val)
            del plummers[maq]['auto']
            
        cursor.execute("SELECT datetime(MAX(timestamp), 'localtime') FROM shift_summaries")
        max_ts_row = cursor.fetchone()
        last_updated_db = max_ts_row[0] if max_ts_row and max_ts_row[0] else None
            
        conn.close()
        return jsonify({"success": True, "robots": robots, "plummers": plummers, "source": "db", "last_updated": last_updated_db})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/crane-performance')
def api_crane_performance():
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    try:
        if start_str: start_param = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M').strftime('%Y/%m/%d %H:%M:00')
        else: start_param = (get_capped_now() - timedelta(hours=8)).strftime('%Y/%m/%d %H:%M:00')
        if end_str: end_param = datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M').strftime('%Y/%m/%d %H:%M:00')
        else: end_param = get_capped_now().strftime('%Y/%m/%d %H:%M:00')
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    url = f"http://10.107.194.62/sbs/reports/gtasrs_aisle_history.php?run=1&str_ts={urllib.parse.quote(start_param)}&end_ts={urllib.parse.quote(end_param)}"
    
    try:
        res = requests.get(url, timeout=10, proxies={"http": None, "https": None})
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
                        except Exception as e: print(f'[WARN] Error parsing aisle data: {e}')

        return jsonify({"success": True, "url_queried": url, "data": aisle_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/conveyor-full')
def api_conveyor_full():
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    try:
        if start_str: start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
        else: start_dt = get_capped_now() - timedelta(hours=24)
        if end_str: end_dt = datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
        else: end_dt = get_capped_now()
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    start_formatted = start_dt.strftime('%Y/%m/%d %H:%M:%S')
    end_formatted = end_dt.strftime('%Y/%m/%d %H:%M:%S')
    
    url = "http://clsapsweb:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/SummaryDataByReason/SummaryDataByReason.EditGrid/EditGrid/DataSource/loadId"
    params = {
        "ARG_MACH_TYPE": "HFPLT4", "ARG_MACH_PART_NAME": "",
        "ARG_START_DATE": start_formatted, "ARG_END_DATE": end_formatted,
        "ARG_OEE_GROUP_SET_ID": "1", "ARG_MACHINE_GROUP_GUID": "6012295917FD36E2E05373C26B0A2E11",
        "ARG_LANG": "ENG", "ARG_OEE_GROUP_UID": "5826BFF57FA71BBCE05373C26B0A0752"
    }

    try:
        res = requests.get(url, params=params, headers={"Accept-language": "en"}, timeout=10, proxies={"http": None, "https": None})
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
            "success": True, "query_start": start_formatted, "query_end": end_formatted,
            "total_downtime": round(total_downtime, 2), "frequency": frequency,
            "objective_minutes": 15.0, "is_ok": round(total_downtime, 2) <= 15.0, "mock": False
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/downtime')
def api_downtime():
    reason = request.args.get('reason', '')
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    if not all(r.strip().isdigit() for r in reason.split(',') if r.strip()):
        return jsonify({"error": "Parámetro inválido"}), 400
        
    try:
        if start_str: start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
        else: start_dt = get_capped_now() - timedelta(hours=24)
        if end_str: end_dt = datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
        else: end_dt = get_capped_now()
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    start_formatted = start_dt.strftime('%Y/%m/%d %H:%M:%S')
    end_formatted = end_dt.strftime('%Y/%m/%d %H:%M:%S')
    
    url = "http://10.107.194.85:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/SummaryDataByReason/SingleDowntimeReason.EditGrid/EditGrid/DataSource/loadId"
    reasons = [r.strip() for r in reason.split(",") if r.strip()]
    
    try:
        downtime_by_group = {f"{r}00{s}": 0.0 for r in range(1,7) for s in ["A","B"]}
        
        for r in reasons:
            params = {
                "ARG_MACH_TYPE": "PRS", "ARG_MACH_PART_NAME": "", "ARG_DOWNTIME_REASON": r,
                "ARG_START_DATE": start_formatted, "ARG_END_DATE": end_formatted,
                "ARG_LANG": "ENG", "ARG_MACHINE_GROUP_GUID": ""
            }
            res = requests.get(url, params=params, headers={"Accept-language": "en"}, timeout=8, proxies={"http": None, "https": None})
            root = ET.fromstring(res.content)
            for row in root.findall('.//Row'):
                mach_el = row.find('MACH_PART_NAME')
                down_el = row.find('DOWN_TIME')
                if mach_el is not None and down_el is not None:
                    mach = (mach_el.text or "").strip()

                    match = re.match(r'^([1-6])(\d+)$', mach)
                    if match:
                        group = match.group(1) + '00' + ('A' if int(match.group(2)) % 2 != 0 else 'B')
                        if group in downtime_by_group:
                            downtime_by_group[group] += float(down_el.text or "0")

        duration_minutes = max(1, round((end_dt - start_dt).total_seconds() / 60))
        total_downtime = sum(downtime_by_group.values())
        downtime_percent = (total_downtime / (duration_minutes * 48)) * 100
        
        for k in downtime_by_group: downtime_by_group[k] = round(downtime_by_group[k], 2)
        
        return jsonify({
            "success": True, "duration_minutes": duration_minutes,
            "downtime_by_group": downtime_by_group, "total_downtime": round(total_downtime, 2),
            "downtime_percent": round(downtime_percent, 2), "mock": False
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 503

@app.route('/api/press-delivery')
def api_press_delivery():
    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    try:
        if start_str: start_dt = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
        else: start_dt = get_capped_now() - timedelta(hours=8)
        if end_str: end_dt = datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
        else: end_dt = get_capped_now()
    except Exception as e: return jsonify({"error": str(e)}), 400

    start_formatted = start_dt.strftime('%Y/%m/%d %H:%M:%S')
    end_formatted = end_dt.strftime('%Y/%m/%d %H:%M:%S')
    
    url_compliance = f"http://10.107.194.62/sbs/reports/auto_order_compliance.php?byheader=0&sortby=order_num&sortorder=ASC&str_ts={urllib.parse.quote(start_formatted)}&end_ts={urllib.parse.quote(end_formatted)}&prszone=&prsrow=all_rows&prscav=all_cavs"
    groups = {f"{r}00{s}": {"delivered": 0, "cancelled": 0, "total": 0, "vulcanized": 0} for r in range(4,7) for s in ["A","B"] if f"{r}00{s}" != "400A"}
    ignored_cavities = {"440", "520", "540", "620", "640"}

    try:
        res = requests.get(url_compliance, timeout=10, proxies={"http": None, "https": None})
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
    except Exception as e: print(f'[WARN] Error fetching press compliance: {e}')

    # Vulcanization
    url_cross = "http://10.107.194.85:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/Production_Counts_Crosstab/Production_Counts_Crosstab.CrossTab/CrossTab/DataSource/DS1"
    params_cross = {
        "ARG_TRANS_START_DATE": start_formatted, "ARG_TRANS_END_DATE": end_formatted,
        "ARG_MACHINE_GROUP_GUID": "9A98FF823A234EEDE05356C26B0A13F5", "ARG_TIME_SUMMARY": "DD",
        "ARG_MACH_TYPE": "", "ARG_COLUMN": "MACH_PART_NAME;", "ARG_ROW": "PRODUCTION_HOUR;",
        "ARG_DATA": "PRODUCT_CNT;", "ARG_LANG": "ENG", "ARG_LANGUAGE_CD": "en", "ARG_USER": ""
    }
    try:
        res_cross = requests.get(url_cross, params=params_cross, headers={"Accept-language": "en"}, timeout=10, proxies={"http": None, "https": None})
        root = ET.fromstring(res_cross.content)
        for row in root.findall('.//Row'):
            mach_el = row.find('MACH_PART_NAME')
            cnt_el = row.find('PRODUCT_CNT')
            if mach_el is not None and cnt_el is not None:
                dest = (mach_el.text or "").strip()
                try: product_cnt = int(float(cnt_el.text or "0"))
                except Exception as e: product_cnt = 0
                if dest in ignored_cavities: continue
                group = "400B" if dest.startswith("4") else (f"{dest[0]}00A" if int(dest) % 2 != 0 else f"{dest[0]}00B")
                if group in groups:
                    groups[group]["vulcanized"] += product_cnt
    except Exception as e: print(f'[WARN] Error fetching vulcanization: {e}')

    # Fetch Dynamic Hourly KPI

    machines_map = {0: '400B', 1: '500A', 2: '500B', 3: '600A', 4: '600B'}
    variables = ['t_idle', 't_estop', 't_znl', 't_trays']
    target_hours = set()
    current_dt = start_dt.replace(minute=0, second=0, microsecond=0)
    end_floor = end_dt.replace(minute=0, second=0, microsecond=0)
    while current_dt <= end_floor:
        target_hours.add(current_dt.hour)
        current_dt += timedelta(hours=1)
        
    total_minutes = max(0, (end_dt - start_dt).total_seconds() / 60.0)
    
    def fetch_machine_var(m_id, var):
        url = f"http://10.107.194.70/ASRS/press_kpi_data.php?machine={m_id}&variable={var}"
        try:
            res = requests.get(url, timeout=5, proxies={"http": None, "https": None})
            return m_id, var, res.json()
        except Exception as e:
            print(f'[WARN] Error fetching KPI m={m_id} v={var}: {e}')
            return m_id, var, []

    # Initialize times to 0
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
            
            for item in data:
                hour_str = str(item.get('time'))
                if hour_str.isdigit() and int(hour_str) in target_hours:
                    val = item.get(var)
                    if val:
                        try: groups[m_name]['times'][val_key] += float(val)
                        except Exception as e: print(f'[WARN] Error parsing KPI val: {e}')

    for m_name in groups:
        t_data = groups[m_name]['times']
        sum_down = t_data['idle'] + t_data['estop'] + t_data['cortinas'] + t_data['prensa']
        t_data['despachando'] = max(0, total_minutes - sum_down)

    return jsonify({"success": True, "presses": groups, "uptime": 99.40})

@app.route('/api/daily-ticket')
def api_daily_ticket():
    try:
        now = get_capped_now()
        # El formato en la página AOP es MM/DD
        date_str = now.strftime('%m/%d')
        
        url = "http://akrmfgcorp.akr.goodyear.com/mfgcorp/aop/pzkmtsc.jsp?RptView=LA"
        
        res = requests.get(url, timeout=10, proxies={"http": None, "https": None})
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
# DATABASE & BACKGROUND TASK LOGIC
# ============================================================================
DB_PATH = 'shift_history.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS io_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT,
                        turno TEXT,
                        entrada TEXT,
                        manual TEXT,
                        auto TEXT,
                        rate_entrada TEXT,
                        rate_manual TEXT,
                        rate_auto TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS shift_summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fecha TEXT,
                        turno TEXT,
                        maquina TEXT,
                        estado TEXT,
                        minutos REAL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
    conn.commit()
    conn.close()

def upsert_shift_data(fecha, turno, maquina, estado, minutos):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

def get_current_shift_info(dt=None):
    if dt is None:
        dt = get_capped_now()
    hour = dt.hour
    if hour >= 6 and hour < 14:
        shift = 'T2'
        date_str = dt.strftime('%Y-%m-%d')
    elif hour >= 14 and hour < 22:
        shift = 'T3'
        date_str = dt.strftime('%Y-%m-%d')
    else:
        shift = 'T1'
        if hour < 6:
            date_str = (dt - timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            date_str = dt.strftime('%Y-%m-%d')
    return date_str, shift

def get_previous_odometer(cursor, target_date, turno, maquina):
    prev = {'run': 0, 'fault': 0, 'auto': 0}
    for est in ['run', 'fault', 'auto']:
        search_est = 'idle' if est == 'auto' else est
        cursor.execute('''SELECT minutos FROM shift_summaries 
                          WHERE fecha < ? AND turno = ? AND maquina = ? AND estado IN (?, ?)
                          ORDER BY fecha DESC LIMIT 1''', (target_date, turno, maquina, est, search_est))
        row = cursor.fetchone()
        if row: prev[est] = row[0]
    return prev


def fetch_and_save_shift_data():
    date_str, current_shift = get_current_shift_info(datetime.now())
    
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
                    upsert_shift_data(date_str, current_shift, robot_id, estado, val)
        except Exception as e: print(f'[WARN] Error saving shift data for {robot_id}: {e}')
        finally: comm.Close()

    save_robot_turn_data('ULR1', '10.107.210.151', 'PickDownTimeUnload1', has_idle=True)
    save_robot_turn_data('ULR2', '10.107.210.150', 'PickDownTimeUnload2', has_idle=True)
    save_robot_turn_data('LR1', '10.107.210.141', 'PickDownTimeLoad1', has_idle=True)
    save_robot_turn_data('LR2', '10.107.210.140', 'PickDownTimeLoad2', has_idle=True)
    
    save_robot_turn_data('CC01', '10.107.210.111', 'DowntimeCC01', has_idle=True)
    save_robot_turn_data('CC02', '10.107.210.121', 'DowntimeCC02', has_idle=True)
    save_robot_turn_data('CC03', '10.107.210.131', 'DowntimeCC03', has_idle=True)

    save_robot_turn_data('L1', '10.107.210.51', 'DownTimePlummer1', has_idle=True)
    save_robot_turn_data('L2', '10.107.210.52', 'DownTimePlummer2', has_idle=True)
    save_robot_turn_data('L3', '10.107.210.53', 'DownTimePlummer3', has_idle=True)

    # Fetch and save IO data to SQLite
    try:
        url = "http://10.107.194.62/sbs/gtasrs_dashboard/gtasrs_dashboard_ctrl.php"
        res = requests.get(url, timeout=5, proxies={"http": None, "https": None})
        if res.status_code == 200:
            import re
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
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
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
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"[WARN] Error saving IO data: {e}")

    # Fetch Construido and Vulcanizado from Goodyear API
    try:
        shift_map = {'T1': 'noche', 'T2': 'manana', 'T3': 'tarde'}
        gy_turno = shift_map.get(current_shift, 'noche')
        url_gy = f"http://10.107.194.110/hora/get_tires/?dia={date_str}&turno={gy_turno}"
        res_gy = requests.get(url_gy, timeout=5, proxies={"http": None, "https": None})
        if res_gy.status_code == 200:
            data_gy = res_gy.json()
            if data_gy.get("status") == "success":
                construido = str(data_gy["data"]["total"]["hva"]["prod"])
                vulcanizado = str(data_gy["data"]["total"]["cura"]["prod"])
                
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("UPDATE io_history SET construido=?, vulcanizado=? WHERE fecha=? AND turno=?",
                               (construido, vulcanizado, date_str, current_shift))
                conn.commit()
                conn.close()
    except Exception as e:
        print(f"[WARN] Error fetching Goodyear tires data: {e}")

    print(f"[{datetime.now()}] Shift data saved successfully for {date_str} {current_shift}")

def background_polling_task():
    init_db()
    
    # Ejecutar primera lectura al arrancar
    try:
        fetch_and_save_shift_data()
    except Exception as e:
        print(f"Error in background polling init: {e}")
        
    while True:
        now = datetime.now()
        # Escanear cada 2 horas (horas pares) a los 5 minutos (06:05, 08:05, 10:05... 14:05... 22:05)
        if now.hour % 2 == 0 and now.minute == 5:
            try:
                fetch_and_save_shift_data()
            except Exception as e:
                print(f"Error in background polling: {e}")
            time.sleep(60) # Dormir 1 minuto para no volver a lanzar dentro del mismo minuto
        else:
            time.sleep(25) # Despertar cada 25 segundos para mirar el reloj

if __name__ == '__main__':
    # Iniciar la tarea en segundo plano
    threading.Thread(target=background_polling_task, daemon=True).start()
    
    try:
        print("Servidor Flask corriendo en el puerto 8080...")
        from waitress import serve
        serve(app, host='0.0.0.0', port=8080)
    except Exception as e:
        print("Error iniciando Waitress, usando app.run()")
        app.run(host='0.0.0.0', port=8080, threaded=True)
