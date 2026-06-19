import http.server
import socketserver
import urllib.request
import urllib.parse
import re
import json
import datetime
import xml.etree.ElementTree as ET
import random
import sys
import threading
import time
import os
import sqlite3
from bs4 import BeautifulSoup
from pylogix import PLC

PLC_TAGS_CONFIG = {
    'conveyors': {
        'CC01': {'ip': '10.107.210.231', 'slot': 0, 'tags': {'RUN': 'CC01_RUN_MINS', 'STOP': 'CC01_STOP_MINS', 'IDLE': 'CC01_IDLE_MINS'}},
        'CC02': {'ip': '10.107.210.232', 'slot': 0, 'tags': {'RUN': 'CC02_RUN_MINS', 'STOP': 'CC02_STOP_MINS', 'IDLE': 'CC02_IDLE_MINS'}},
        'CC03': {'ip': '10.107.210.233', 'slot': 0, 'tags': {'RUN': 'CC03_RUN_MINS', 'STOP': 'CC03_STOP_MINS', 'IDLE': 'CC03_IDLE_MINS'}},
    },
    'robots': {
        'LR1': {'ip': '10.107.210.141', 'slot': 0, 'tags': {'RUN': 'LR1_RUN_MINS', 'STOP': 'LR1_STOP_MINS'}},
        'LR2': {'ip': '10.107.210.140', 'slot': 0, 'tags': {'RUN': 'LR2_RUN_MINS', 'STOP': 'LR2_STOP_MINS'}},
        'ULR1': {'ip': '10.107.210.142', 'slot': 0, 'tags': {'RUN': 'ULR1_RUN_MINS', 'STOP': 'ULR1_STOP_MINS'}},
        'ULR2': {'ip': '10.107.210.143', 'slot': 0, 'tags': {'RUN': 'ULR2_RUN_MINS', 'STOP': 'ULR2_STOP_MINS'}},
        'RL1': {'ip': '10.107.210.160', 'slot': 0, 'tags': {'working': 'RL1_WORK_MINS', 'idle': 'RL1_IDLE_MINS', 'waiting': 'RL1_WAIT_MINS', 'failure': 'RL1_FAIL_MINS'}},
        'RL2': {'ip': '10.107.210.160', 'slot': 0, 'tags': {'working': 'RL2_WORK_MINS', 'idle': 'RL2_IDLE_MINS', 'waiting': 'RL2_WAIT_MINS', 'failure': 'RL2_FAIL_MINS'}},
    },
    'plummers': {
        'L1': {'ip': '10.107.210.160', 'slot': 0, 'tags': {'run': 'L1_RUN_MINS', 'idle': 'L1_IDLE_MINS', 'stop': 'L1_STOP_MINS'}},
        'L2': {'ip': '10.107.210.160', 'slot': 0, 'tags': {'run': 'L2_RUN_MINS', 'idle': 'L2_IDLE_MINS', 'stop': 'L2_STOP_MINS'}},
        'L3': {'ip': '10.107.210.160', 'slot': 0, 'tags': {'run': 'L3_RUN_MINS', 'idle': 'L3_IDLE_MINS', 'stop': 'L3_STOP_MINS'}},
    }
}

def init_shift_db():
    db_path = 'shift_history.db'
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE IF NOT EXISTS shift_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        turno TEXT,
        maquina TEXT,
        estado TEXT,
        minutos REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    cutoff_dt = datetime.datetime.now() - datetime.timedelta(days=3)
    con.execute('DELETE FROM shift_summaries WHERE timestamp < ?', (cutoff_dt.strftime('%Y-%m-%d %H:%M:%S'),))
    con.commit()
    con.close()

init_shift_db()

def log_shift_data():
    now = datetime.datetime.now()
    _, shift_name = get_shift_info(now)
    fecha_str = now.strftime('%d/%m/%Y')
    
    if shift_name == 'Day': shift_text = '06:00 a 14:00'
    elif shift_name == 'Afternoon': shift_text = '14:00 a 22:00'
    else: shift_text = '22:00 a 06:00'
    
    db_path = 'shift_history.db'
    con = sqlite3.connect(db_path)
    
    for category, machines in PLC_TAGS_CONFIG.items():
        for maq, conf in machines.items():
            ip = conf['ip']
            tags_dict = conf['tags']
            comm = PLC()
            comm.IPAddress = ip
            comm.ProcessorSlot = conf['slot']
            try:
                ret = comm.Read(list(tags_dict.values()))
                for r in ret:
                    if r.Status == 'Success':
                        val = float(r.Value)
                        estado = [k for k,v in tags_dict.items() if v == r.TagName][0]
                        con.execute("""INSERT INTO shift_summaries (fecha, turno, maquina, estado, minutos) 
                                       VALUES (?, ?, ?, ?, ?)""", 
                                    (fecha_str, shift_text, maq, estado, val))
            except Exception as e:
                print(f'[ShiftLogger] Error PLC {maq}: {e}')
            comm.Close()
            
    con.commit()
    con.close()
    print(f'[{now.strftime("%H:%M:%S")}] Shift History Saved!')

def shift_logger_thread():
    while True:
        now = datetime.datetime.now()
        if now.minute == 59 and now.second == 50 and now.hour in [5, 13, 21]:
            log_shift_data()
            time.sleep(2)
        time.sleep(1)

threading.Thread(target=shift_logger_thread, daemon=True).start()

# Helper para determinar el turno actual
def get_shift_info(dt):
    hour = dt.hour
    if 6 <= hour < 14:
        shift_name = "Day"
        shift_date = dt.date()
    elif 14 <= hour < 22:
        shift_name = "Afternoon"
        shift_date = dt.date()
    elif hour >= 22:
        shift_name = "Night"
        shift_date = dt.date()
    else:
        shift_name = "Night"
        shift_date = (dt - datetime.timedelta(days=1)).date()
    return shift_date.isoformat(), shift_name


PORT = 8080



class Handler(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        if path.endswith('.html'):
            return 'text/html'
        return super().guess_type(path)

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        # Redireccionar raíz a index.html
        if path == '/' or path == '':
            self.path = '/index.html'
            return super().do_GET()
            
        # API INPUT / OUTPUT
        elif path == '/api/io-data' or path == '/api_io_data.php':
            start_str = query_params.get('start', [''])[0]
            end_str = query_params.get('end', [''])[0]
            start_dt = None
            end_dt = None
            try:
                if start_str:
                    start_dt = datetime.datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                if end_str:
                    end_dt = datetime.datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            except Exception:
                pass
            self.handle_io_data(start_dt, end_dt)
            
        # API DOWNTIME (NO TIRE / PREVENTIVAS)
        elif path == '/api/downtime' or path in ['/api_no_tire.php', '/api_preventiva.php', '/api_preventiva_general.php']:
            # Resolver la razón (Downtime Reason)
            reason = ""
            if 'reason' in query_params:
                reason = query_params['reason'][0]
            elif 'api_no_tire' in path:
                reason = "160000"
            elif 'api_preventiva_general' in path:
                reason = "40000"
            elif 'api_preventiva' in path:
                reason = "210002"
                
            # Sanitizar parametro reason
            if not reason.isdigit():
                self.send_error_response(400, "Parámetro de razón inválido. Debe ser un valor numérico.")
                return
                
            # Resolver fechas
            start_str = query_params.get('start', [''])[0]
            end_str = query_params.get('end', [''])[0]
            
            try:
                if start_str:
                    # Formato datetime-local: YYYY-MM-DDTHH:mm
                    start_dt = datetime.datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                else:
                    start_dt = datetime.datetime.now() - datetime.timedelta(hours=24)
                    
                if end_str:
                    end_dt = datetime.datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                else:
                    end_dt = datetime.datetime.now()
            except Exception as e:
                self.send_error_response(400, f"Formatos de fecha inválidos. Use YYYY-MM-DDTHH:mm. Error: {str(e)}")
                return
                
            self.handle_downtime(reason, start_dt, end_dt)

        # API CONVEYOR FULL (razón APS 10315)
        elif path == '/api/conveyor-full':
            start_str = query_params.get('start', [''])[0]
            end_str = query_params.get('end', [''])[0]
            try:
                if start_str:
                    start_dt = datetime.datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                else:
                    start_dt = datetime.datetime.now() - datetime.timedelta(hours=24)
                if end_str:
                    end_dt = datetime.datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                else:
                    end_dt = datetime.datetime.now()
            except Exception as e:
                self.send_error_response(400, f"Formatos de fecha inválidos. Use YYYY-MM-DDTHH:mm. Error: {str(e)}")
                return
            self.handle_conveyor_full(start_dt, end_dt)

        # API PLC CONVEYOR STOP (CC01, CC02, CC03 — histórico por rango)
        elif path == '/api/plc-conveyor':
            start_str = query_params.get('start', [''])[0]
            end_str   = query_params.get('end',   [''])[0]
            try:
                if start_str:
                    start_dt = datetime.datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                else:
                    start_dt = datetime.datetime.now() - datetime.timedelta(hours=8)
                if end_str:
                    end_dt = datetime.datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                else:
                    end_dt = datetime.datetime.now()
            except Exception as e:
                self.send_error_response(400, f"Formato inválido: {e}")
                return
            self.handle_plc_conveyor(start_dt, end_dt)

        elif path == '/api/crane-performance':
            start_str = query_params.get('start', [''])[0]
            end_str   = query_params.get('end',   [''])[0]
            self.handle_crane_performance(start_str, end_str)



        elif path == '/api/asrs-engineering-data':
            start_str = query_params.get('start', [''])[0]
            end_str   = query_params.get('end',   [''])[0]
            self.handle_asrs_engineering_data(start_str, end_str)
        elif path == '/api/press-delivery':
            start_str = query_params.get('start', [''])[0]
            end_str   = query_params.get('end',   [''])[0]
            self.handle_press_delivery(start_str, end_str)
        elif path == '/api/daily-ticket':
            self.handle_daily_ticket()
        else:
            # Servir como servidor de archivos estáticos
            super().do_GET()

    def handle_io_data(self, start_dt=None, end_dt=None):
        try:
            # Los turnos del sistema de código de barras ASRS van desfasados +1 hora
            # respecto a los turnos de entrega. Sumamos 1 hora para el mapeo.
            if start_dt:
                start_dt = start_dt + datetime.timedelta(hours=1)
            if end_dt:
                end_dt = end_dt + datetime.timedelta(hours=1)

            # Determinar el prefijo del turno (s1, s2, s3, s4, s5) según la hora de consulta
            prefix = "s1"
            if start_dt and end_dt:
                now_dt = datetime.datetime.now()
                current_date = now_dt.date()
                candidates = []
                for d in [current_date - datetime.timedelta(days=1), current_date, current_date + datetime.timedelta(days=1)]:
                    candidates.append(datetime.datetime.combine(d, datetime.time(7, 0)))
                    candidates.append(datetime.datetime.combine(d, datetime.time(15, 0)))
                    candidates.append(datetime.datetime.combine(d, datetime.time(23, 0)))
                candidates.sort()
                
                s1_start = None
                for c in candidates:
                    if c <= now_dt:
                        s1_start = c
                
                if s1_start:
                    s1_end = s1_start + datetime.timedelta(hours=8)
                    s2_start = s1_start - datetime.timedelta(hours=8)
                    s2_end = s1_start
                    s3_start = s2_start - datetime.timedelta(hours=8)
                    s3_end = s2_start
                    s4_start = s3_start - datetime.timedelta(hours=8)
                    s4_end = s3_start
                    s5_start = datetime.datetime.combine(s1_start.date() - datetime.timedelta(days=1), datetime.time(7, 0))
                    s5_end = s5_start + datetime.timedelta(days=1)
                    
                    shifts = {
                        "s1": (s1_start, s1_end),
                        "s2": (s2_start, s2_end),
                        "s3": (s3_start, s3_end),
                        "s4": (s4_start, s4_end),
                        "s5": (s5_start, s5_end)
                    }
                    
                    # Excluir consultas de más de 1 día atrás (anteriores a s4_start)
                    if start_dt < s4_start:
                        self.send_json_response(200, {
                            "entrada": "-",
                            "manual": "-",
                            "auto": "-",
                            "rate_entrada": "-",
                            "rate_manual": "-",
                            "rate_auto": "-",
                            "mock": False,
                            "message": "Sin información para fechas anteriores a 1 día"
                        })
                        return
                        
                    # Encontrar el que tenga el mayor traslape en segundos
                    max_overlap = -1
                    best_prefix = "s1"
                    for p, (s_start, s_end) in shifts.items():
                        if p == "s5": 
                            continue # s5 es para todo el día anterior, nos enfocamos en s1-s4 para los turnos individuales
                        overlap_start = max(start_dt, s_start)
                        overlap_end = min(end_dt, s_end)
                        if overlap_end > overlap_start:
                            overlap_sec = (overlap_end - overlap_start).total_seconds()
                            if overlap_sec > max_overlap:
                                max_overlap = overlap_sec
                                best_prefix = p
                    prefix = best_prefix


            url = "http://10.107.194.62/sbs/gtasrs_dashboard/gtasrs_dashboard_ctrl.php"
            req = urllib.request.Request(url)
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            
            with opener.open(req, timeout=4) as response:
                html = response.read().decode('utf-8', errors='ignore')
            
            def extract(id_name):
                match = re.search(rf"getElementById\('{id_name}'\)\.innerHTML\s*=\s*'([^']+)'", html)
                return match.group(1) if match else "0"

            data = {
                "entrada": extract(f"{prefix}_inbound_total"),
                "manual": extract(f"{prefix}_outbound_cv31_actual"),
                "auto": extract(f"{prefix}_press_total"),
                "rate_entrada": extract(f"{prefix}_inbound_avg"),
                "rate_manual": extract(f"{prefix}_manual_rate"),
                "rate_auto": extract(f"{prefix}_press_rate"),
                "mock": False
            }
            self.send_json_response(200, data)
        except Exception as e:
            print(f"[Error] Servidor remoto no disponible para IO-Data: {str(e)}", file=sys.stderr)
            self.send_json_response(503, {"success": False, "error": "Servidor remoto no disponible."})

    def handle_plc_conveyor(self, start_dt, end_dt):
        results = {
            'CC01': {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0},
            'CC02': {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0},
            'CC03': {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0},
            'LR1':  {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0},
            'LR2':  {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0},
            'ULR1': {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0},
            'ULR2': {'RUN': 0.0, 'IDLE': 0.0, 'STOP': 0.0}
        }
        for maq, conf in PLC_TAGS_CONFIG['conveyors'].items():
            comm = PLC()
            comm.IPAddress = conf['ip']
            comm.ProcessorSlot = conf['slot']
            try:
                ret = comm.Read(list(conf['tags'].values()))
                for r in ret:
                    if r.Status == 'Success':
                        estado = [k for k,v in conf['tags'].items() if v == r.TagName][0]
                        results[maq][estado] = round(float(r.Value), 2)
            except: pass
            comm.Close()
            
        for maq in ['LR1', 'LR2', 'ULR1', 'ULR2']:
            if maq in PLC_TAGS_CONFIG['robots']:
                conf = PLC_TAGS_CONFIG['robots'][maq]
                comm = PLC()
                comm.IPAddress = conf['ip']
                comm.ProcessorSlot = conf['slot']
                try:
                    ret = comm.Read(list(conf['tags'].values()))
                    for r in ret:
                        if r.Status == 'Success':
                            estado = [k for k,v in conf['tags'].items() if v == r.TagName][0]
                            results[maq][estado] = round(float(r.Value), 2)
                except: pass
                comm.Close()
                
        self.send_json_response(200, {
            'success': True,
            'data': results
        })
    def handle_crane_performance(self, start_str, end_str):
        """Consulta el reporte de Aisle Down Time, parsea el HTML y devuelve los datos."""
        # Convertir 'YYYY-MM-DDTHH:MM' a 'YYYY/MM/DD HH:MM:00'
        try:
            if start_str:
                start_dt = datetime.datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                start_param = start_dt.strftime('%Y/%m/%d %H:%M:00')
            else:
                start_param = (datetime.datetime.now() - datetime.timedelta(hours=8)).strftime('%Y/%m/%d %H:%M:00')
                
            if end_str:
                end_dt = datetime.datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                end_param = end_dt.strftime('%Y/%m/%d %H:%M:00')
            else:
                end_param = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:00')
        except Exception as e:
            self.send_error_response(400, f"Formato de fecha inválido. Error: {e}")
            return

        url = f"http://10.107.194.62/sbs/reports/gtasrs_aisle_history.php?run=1&str_ts={urllib.parse.quote(start_param)}&end_ts={urllib.parse.quote(end_param)}"
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                html_bytes = response.read()
            
            # El servidor suele devolver UTF-8 or CP1252. Usamos UTF-16LE solo si tiene BOM.
            if html_bytes.startswith(b'\xff\xfe'):
                html_text = html_bytes.decode('utf-16le', errors='ignore')
            elif html_bytes.startswith(b'\xfe\xff'):
                html_text = html_bytes.decode('utf-16be', errors='ignore')
            else:
                html_text = html_bytes.decode('utf-8', errors='ignore')
            
            # Extraer botones de Aisle con Regex
            # Formato: VALUE='Aisle 1 \n0.7%\n2 min' o value="Aisle 1 \n 0.1%\n 1 min"
            aisle_data = []
            matches = re.finditer(r'value=[\'"]Aisle\s+(\d+)\s+([\d\.]+)%\s+(\d+)\s+min[\'"]', html_text, re.IGNORECASE)
            for m in matches:
                aisle = int(m.group(1))
                percent = float(m.group(2))
                minutes = int(m.group(3))
                aisle_data.append({
                    "aisle": aisle,
                    "downtime_percent": percent,
                    "downtime_minutes": minutes
                })
            
            # Si no encontró usando ese regex, probamos buscar los inputs más permisivos
            if not aisle_data:
                matches = re.finditer(r'<input[^>]+value=[\'"]([^\'"]+)[\'"]', html_text, re.IGNORECASE)
                for m in matches:
                    val_str = m.group(1)
                    if "Aisle" in val_str and "%" in val_str and "min" in val_str:
                        parts = re.split(r'\s+', val_str.replace('\n', ' ').replace('\r', '').strip())
                        if len(parts) >= 5:
                            try:
                                aisle = int(parts[1])
                                percent = float(parts[2].replace('%', ''))
                                minutes = int(parts[3])
                                aisle_data.append({
                                    "aisle": aisle,
                                    "downtime_percent": percent,
                                    "downtime_minutes": minutes
                                })
                            except:
                                pass


            self.send_json_response(200, {
                "success": True,
                "url_queried": url,
                "data": aisle_data
            })
            
        except Exception as e:
            print(f"[Error] handle_crane_performance: {e}", file=sys.stderr)
            self.send_json_response(503, {"success": False, "error": str(e)})

    def handle_conveyor_full(self, start_dt, end_dt):
        """Consulta el tiempo de Conveyor Full (razón 10315) al servidor APS.
        
        Usa el endpoint SummaryDataByReason con ARG_MACH_TYPE=HFPLT4 y filtra
        la fila con DOWNTIME_REASON=10315. El campo DOWNTIME_MINUTES ya viene en minutos.
        """
        start_formatted = start_dt.strftime('%Y/%m/%d %H:%M:%S')
        end_formatted = end_dt.strftime('%Y/%m/%d %H:%M:%S')
        CONVEYOR_FULL_REASON = "10315"
        OBJECTIVE_MINUTES = 15.0

        baseUrl = "http://clsapsweb:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/SummaryDataByReason/SummaryDataByReason.EditGrid/EditGrid/DataSource/loadId"
        params = {
            "ARG_MACH_TYPE": "HFPLT4",
            "ARG_MACH_PART_NAME": "",
            "ARG_START_DATE": start_formatted,
            "ARG_END_DATE": end_formatted,
            "ARG_OEE_GROUP_SET_ID": "1",
            "ARG_MACHINE_GROUP_GUID": "6012295917FD36E2E05373C26B0A2E11",
            "ARG_LANG": "ENG",
            "ARG_OEE_GROUP_UID": "5826BFF57FA71BBCE05373C26B0A0752"
        }
        url = baseUrl + "?" + urllib.parse.urlencode(params)

        try:
            req = urllib.request.Request(url, headers={"Accept-language": "en"})
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)

            with opener.open(req, timeout=8) as response:
                xml_data = response.read()

            root = ET.fromstring(xml_data)
            total_downtime = 0.0
            frequency = 0

            for row in root.findall('.//Row'):
                reason_el = row.find('DOWNTIME_REASON')
                if reason_el is None or (reason_el.text or '').strip() != CONVEYOR_FULL_REASON:
                    continue
                min_el = row.find('DOWNTIME_MINUTES')
                freq_el = row.find('FREQUENCY')
                if min_el is not None:
                    total_downtime += float(min_el.text or "0")
                if freq_el is not None:
                    frequency += int(float(freq_el.text or "0"))

            total_downtime = round(total_downtime, 2)
            is_ok = total_downtime <= OBJECTIVE_MINUTES

            self.send_json_response(200, {
                "success": True,
                "query_start": start_formatted,
                "query_end": end_formatted,
                "total_downtime": total_downtime,
                "frequency": frequency,
                "objective_minutes": OBJECTIVE_MINUTES,
                "is_ok": is_ok,
                "mock": False
            })
        except Exception as e:
            print(f"[Error] Conveyor Full (10315) no disponible: {str(e)}", file=sys.stderr)
            self.send_json_response(503, {"success": False, "error": "Servidor de reportes no disponible."})

    def handle_downtime(self, reason, start_dt, end_dt):
        start_formatted = start_dt.strftime('%Y/%m/%d %H:%M:%S')
        end_formatted = end_dt.strftime('%Y/%m/%d %H:%M:%S')
        
        baseUrl = "http://10.107.194.85:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/SummaryDataByReason/SingleDowntimeReason.EditGrid/EditGrid/DataSource/loadId"
        params = {
            "ARG_MACH_TYPE": "PRS",
            "ARG_MACH_PART_NAME": "",
            "ARG_DOWNTIME_REASON": reason,
            "ARG_START_DATE": start_formatted,
            "ARG_END_DATE": end_formatted,
            "ARG_LANG": "ENG",
            "ARG_MACHINE_GROUP_GUID": ""
        }
        url = baseUrl + "?" + urllib.parse.urlencode(params)
        
        try:
            req = urllib.request.Request(url, headers={"Accept-language": "en"})
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            
            with opener.open(req, timeout=5) as response:
                xml_data = response.read()
            
            root = ET.fromstring(xml_data)
            
            downtime_by_group = {
                "100A": 0.0, "100B": 0.0,
                "200A": 0.0, "200B": 0.0,
                "300A": 0.0, "300B": 0.0,
                "400A": 0.0, "400B": 0.0,
                "500A": 0.0, "500B": 0.0,
                "600A": 0.0, "600B": 0.0
            }
            
            # Buscar elementos Row en XML
            for row in root.findall('.//Row'):
                mach_el = row.find('MACH_PART_NAME')
                down_el = row.find('DOWN_TIME')
                
                if mach_el is not None and down_el is not None:
                    mach = (mach_el.text or "").strip()
                    down_time = float(down_el.text or "0")
                    
                    # Mapeo a línea y lado (A: impares, B: pares)
                    # Ejemplo: '107' -> 100A, '108' -> 100B
                    match = re.match(r'^([1-6])(\d+)$', mach)
                    if match:
                        line = match.group(1) + '00'
                        num = int(match.group(2))
                        side = 'A' if num % 2 != 0 else 'B'
                        group = line + side
                        
                        if group in downtime_by_group:
                            downtime_by_group[group] += down_time

            duration_seconds = (end_dt - start_dt).total_seconds()
            duration_minutes = max(1, round(duration_seconds / 60))
            total_downtime = sum(downtime_by_group.values())
            
            num_presses = 48
            total_available_minutes = duration_minutes * num_presses
            downtime_percent = (total_downtime / total_available_minutes) * 100
            
            # Redondeos
            for k in downtime_by_group:
                downtime_by_group[k] = round(downtime_by_group[k], 2)
                
            response_data = {
                "success": True,
                "query_start": start_formatted,
                "query_end": end_formatted,
                "duration_minutes": duration_minutes,
                "downtime_by_group": downtime_by_group,
                "total_downtime": round(total_downtime, 2),
                "downtime_percent": round(downtime_percent, 2),
                "mock": False
            }
            self.send_json_response(200, response_data)
            
        except Exception as e:
            print(f"[Error] Servidor de reportes no disponible para razón {reason}: {str(e)}", file=sys.stderr)
            self.send_json_response(503, {"success": False, "error": "Servidor de reportes no disponible."})



    def handle_asrs_engineering_data(self, start_str=None, end_str=None):
        robots = {
            'RL1': {'idle': 0.0, 'working': 0.0, 'waiting': 0.0, 'failure': 0.0},
            'RL2': {'idle': 0.0, 'working': 0.0, 'waiting': 0.0, 'failure': 0.0}
        }
        plummers = {
            'L1': {'run': 0.0, 'idle': 0.0, 'stop': 0.0, 'tires': '-'},
            'L2': {'run': 0.0, 'idle': 0.0, 'stop': 0.0, 'tires': '-'},
            'L3': {'run': 0.0, 'idle': 0.0, 'stop': 0.0, 'tires': '-'}
        }
        for maq in ['RL1', 'RL2']:
            if maq in PLC_TAGS_CONFIG['robots']:
                conf = PLC_TAGS_CONFIG['robots'][maq]
                comm = PLC()
                comm.IPAddress = conf['ip']
                comm.ProcessorSlot = conf['slot']
                try:
                    ret = comm.Read(list(conf['tags'].values()))
                    for r in ret:
                        if r.Status == 'Success':
                            estado = [k for k,v in conf['tags'].items() if v == r.TagName][0]
                            robots[maq][estado] = round(float(r.Value), 2)
                except: pass
                comm.Close()
                
        for maq in ['L1', 'L2', 'L3']:
            if maq in PLC_TAGS_CONFIG['plummers']:
                conf = PLC_TAGS_CONFIG['plummers'][maq]
                comm = PLC()
                comm.IPAddress = conf['ip']
                comm.ProcessorSlot = conf['slot']
                try:
                    ret = comm.Read(list(conf['tags'].values()))
                    for r in ret:
                        if r.Status == 'Success':
                            estado = [k for k,v in conf['tags'].items() if v == r.TagName][0]
                            plummers[maq][estado] = round(float(r.Value), 2)
                except: pass
                comm.Close()
                
        self.send_json_response(200, {
            'success': True,
            'robots': robots,
            'plummers': plummers
        })
    def handle_press_delivery(self, start_str, end_str):
        try:
            if start_str:
                start_dt = datetime.datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            else:
                start_dt = datetime.datetime.now() - datetime.timedelta(hours=8)
            if end_str:
                end_dt = datetime.datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            else:
                end_dt = datetime.datetime.now()
        except Exception as e:
            self.send_error_response(400, f"Fechas inválidas: {e}")
            return

        start_formatted = start_dt.strftime('%Y/%m/%d %H:%M:%S')
        end_formatted = end_dt.strftime('%Y/%m/%d %H:%M:%S')

        # ── 1. Obtener datos de cumplimiento (órdenes despachadas / canceladas) ──
        url_compliance = f"http://10.107.194.62/sbs/reports/auto_order_compliance.php?byheader=0&sortby=order_num&sortorder=ASC&str_ts={urllib.parse.quote(start_formatted)}&end_ts={urllib.parse.quote(end_formatted)}&prszone=&prsrow=all_rows&prscav=all_cavs"
        
        groups = {
            "400B": {"delivered": 0, "cancelled": 0, "total": 0, "vulcanized": 0},
            "500A": {"delivered": 0, "cancelled": 0, "total": 0, "vulcanized": 0},
            "500B": {"delivered": 0, "cancelled": 0, "total": 0, "vulcanized": 0},
            "600A": {"delivered": 0, "cancelled": 0, "total": 0, "vulcanized": 0},
            "600B": {"delivered": 0, "cancelled": 0, "total": 0, "vulcanized": 0}
        }

        ignored_cavities = {"440", "520", "540", "620", "640"}

        try:
            req = urllib.request.Request(url_compliance, headers={"User-Agent": "Mozilla/5.0"})
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')

            soup = BeautifulSoup(html, "html.parser")
            tables = soup.find_all("table")
            
            target_table = None
            for t in tables:
                rows = t.find_all("tr")
                if len(rows) > 10:
                    target_table = t
                    break
            
            if target_table:
                rows = target_table.find_all("tr")
                for r in rows[1:]:
                    cells = [td.get_text(strip=True) for td in r.find_all("td")]
                    if len(cells) > 7:
                        status = cells[1]
                        dest = cells[7]
                        
                        if dest in ignored_cavities:
                            continue

                        group = None
                        if dest.startswith("4"):
                            group = "400B"
                        elif dest.startswith("5"):
                            try:
                                num = int(dest)
                                group = "500A" if num % 2 != 0 else "500B"
                            except ValueError:
                                pass
                        elif dest.startswith("6"):
                            try:
                                num = int(dest)
                                group = "600A" if num % 2 != 0 else "600B"
                            except ValueError:
                                pass
                        
                        if group in groups:
                            groups[group]["total"] += 1
                            if status == "Fulfilled":
                                groups[group]["delivered"] += 1
                            elif status == "Cancelled":
                                groups[group]["cancelled"] += 1
        except Exception as e:
            print(f"[Error] fetch compliance: {e}", file=sys.stderr)

        # ── 2. Obtener datos de vulcanización (crosstab de producción) ──
        crosstab_baseUrl = "http://10.107.194.85:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/Production_Counts_Crosstab/Production_Counts_Crosstab.CrossTab/CrossTab/DataSource/DS1"
        crosstab_params = {
            "ARG_TRANS_START_DATE": start_formatted,
            "ARG_TRANS_END_DATE": end_formatted,
            "ARG_MACHINE_GROUP_GUID": "9A98FF823A234EEDE05356C26B0A13F5",
            "ARG_TIME_SUMMARY": "DD",
            "ARG_MACH_TYPE": "",
            "ARG_COLUMN": "MACH_PART_NAME;",
            "ARG_ROW": "PRODUCTION_HOUR;",
            "ARG_DATA": "PRODUCT_CNT;",
            "ARG_LANG": "ENG",
            "ARG_LANGUAGE_CD": "en",
            "ARG_USER": ""
        }
        crosstab_url = crosstab_baseUrl + "?" + urllib.parse.urlencode(crosstab_params)

        try:
            req_crosstab = urllib.request.Request(crosstab_url, headers={"Accept-language": "en"})
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req_crosstab, timeout=10) as response:
                xml_data = response.read()

            root = ET.fromstring(xml_data)
            for row in root.findall('.//Row'):
                mach_el = row.find('MACH_PART_NAME')
                cnt_el = row.find('PRODUCT_CNT')
                if mach_el is not None and cnt_el is not None:
                    dest = (mach_el.text or "").strip()
                    try:
                        product_cnt = int(float(cnt_el.text or "0"))
                    except ValueError:
                        product_cnt = 0

                    if dest in ignored_cavities:
                        continue

                    group = None
                    if dest.startswith("4"):
                        group = "400B"
                    elif dest.startswith("5"):
                        try:
                            num = int(dest)
                            group = "500A" if num % 2 != 0 else "500B"
                        except ValueError:
                            pass
                    elif dest.startswith("6"):
                        try:
                            num = int(dest)
                            group = "600A" if num % 2 != 0 else "600B"
                        except ValueError:
                            pass

                    if group in groups:
                        groups[group]["vulcanized"] += product_cnt
        except Exception as e:
            print(f"[Error] fetch crosstab vulcanized: {e}", file=sys.stderr)

        total_delivered = sum(g["delivered"] for g in groups.values())
        total_cancelled = sum(g["cancelled"] for g in groups.values())
        total_valid = total_delivered + total_cancelled
        uptime = (total_delivered / total_valid * 100.0) if total_valid > 0 else 100.0

        self.send_json_response(200, {
            "success": True,
            "uptime": round(uptime, 2),
            "presses": groups
        })

    def handle_daily_ticket(self):
        url = "http://akrmfgcorp.akr.goodyear.com/mfgcorp/aop/pzkmtsc.jsp?RptView=LA"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, timeout=8) as response:
                html = response.read().decode('utf-8', errors='ignore')

            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table")
            if not table:
                self.send_json_response(200, {"success": False, "error": "No table found"})
                return

            # Obtener fecha de hoy en formato MM/DD
            today_str = datetime.datetime.now().strftime('%m/%d')
            rows = table.find_all("tr")
            
            ticket_val = None
            for r in rows:
                cells = [c.get_text(strip=True) for c in r.find_all(['td', 'th'])]
                if cells and cells[0] == today_str:
                    if len(cells) > 3:
                        ticket_val = cells[3]
                        break

            if ticket_val is not None:
                try:
                    ticket_float = float(ticket_val)
                    ticket_units = int(ticket_float * 1000)
                    ticket_formatted = f"{ticket_units:,}".replace(',', '.')
                except ValueError:
                    ticket_float = 0.0
                    ticket_units = 0
                    ticket_formatted = ticket_val

                self.send_json_response(200, {
                    "success": True,
                    "date": today_str,
                    "ticket": ticket_float,
                    "units": ticket_units,
                    "formatted": ticket_formatted
                })
            else:
                self.send_json_response(200, {
                    "success": False,
                    "error": f"Date {today_str} not found in AOP table"
                })
        except Exception as e:
            print(f"[Error] handle_daily_ticket: {e}", file=sys.stderr)
            self.send_json_response(503, {"success": False, "error": str(e)})

    def send_json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def send_error_response(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode('utf-8'))

with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"Server ASRS running locally at http://127.0.0.1:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
        sys.exit(0)
