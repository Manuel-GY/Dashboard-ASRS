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
import sqlite3
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor
from pylogix import PLC as LogixPLC


# ── Historiador SQLite ──────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conveyor_history.db")

PLC_CONFIG = [
    {
        "label": "CC01",
        "ip": "10.107.210.111",
        "slot": 0,
        "tag_faulted": "Program:Main.cc01_faulted_minutes",
        "tag_runtime": "Program:Main.cc01_runtime_minutes",
    },
    {
        "label": "CC02",
        "ip": "10.107.210.121",
        "slot": 0,
        "tag_faulted": "Program:MainProgram.cc02_faulted_minutes",
        "tag_runtime": "Program:MainProgram.sortercc02runtime_minutes",
    },
    {
        "label": "CC03",
        "ip": "10.107.210.131",
        "slot": 0,
        "tag_faulted": "Program:MainProgram.cc03_faulted_minutes",
        "tag_runtime": "Program:MainProgram.cc03_runtime_minutes",
    },
]

def db_init():
    """Crea la tabla de snapshots si no existe."""
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("""
        CREATE TABLE IF NOT EXISTS plc_snapshots (
            ts           TEXT PRIMARY KEY,
            cc01_faulted INTEGER,
            cc01_runtime INTEGER,
            cc02_faulted INTEGER,
            cc02_runtime INTEGER,
            cc03_faulted INTEGER,
            cc03_runtime INTEGER
        )
    """)
    con.commit()
    con.close()

def db_insert_snapshot(values: dict):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("""
        INSERT OR REPLACE INTO plc_snapshots
            (ts, cc01_faulted, cc01_runtime, cc02_faulted, cc02_runtime, cc03_faulted, cc03_runtime)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        ts,
        values.get('CC01', {}).get('faulted'), values.get('CC01', {}).get('runtime'),
        values.get('CC02', {}).get('faulted'), values.get('CC02', {}).get('runtime'),
        values.get('CC03', {}).get('faulted'), values.get('CC03', {}).get('runtime'),
    ))
    # Eliminar registros de más de 7 días
    con.execute("DELETE FROM plc_snapshots WHERE ts < ?", (cutoff,))
    con.commit()
    con.close()

def poll_single_plc(cfg):
    label = cfg["label"]
    try:
        with LogixPLC() as comm:
            comm.IPAddress = cfg["ip"]
            comm.ProcessorSlot = cfg["slot"]
            r_f = comm.Read(cfg["tag_faulted"])
            r_r = comm.Read(cfg["tag_runtime"])
        return label, {
            "faulted": int(r_f.Value) if r_f.Status == "Success" and r_f.Value is not None else None,
            "runtime": int(r_r.Value) if r_r.Status == "Success" and r_r.Value is not None else None,
        }
    except Exception as e:
        print(f"[Historiador] Error leyendo {label}: {e}", file=sys.stderr)
        return label, {"faulted": None, "runtime": None}

def plc_poll_loop():
    """Hilo daemon: lee los PLCs en paralelo cada 60 s y guarda un snapshot en SQLite."""
    print("[Historiador] Iniciado. Guardando snapshots cada 60 s.", file=sys.stderr)
    while True:
        snapshot = {}
        with ThreadPoolExecutor(max_workers=len(PLC_CONFIG)) as executor:
            results = executor.map(poll_single_plc, PLC_CONFIG)
            for label, data in results:
                snapshot[label] = data
        try:
            db_insert_snapshot(snapshot)
        except Exception as e:
            print(f"[Historiador] Error guardando en DB: {e}", file=sys.stderr)
        time.sleep(60)

# Inicializar DB y arrancar hilo
db_init()
_poll_thread = threading.Thread(target=plc_poll_loop, daemon=True)
_poll_thread.start()

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
        else:
            # Servir como servidor de archivos estáticos
            super().do_GET()

    def handle_io_data(self, start_dt=None, end_dt=None):
        try:
            # Determinar el prefijo del turno (s1, s2, s3, s4, s5) según la hora de consulta
            prefix = "s1"
            if start_dt and end_dt:
                now_dt = datetime.datetime.now()
                current_date = now_dt.date()
                candidates = []
                for d in [current_date - datetime.timedelta(days=1), current_date, current_date + datetime.timedelta(days=1)]:
                    candidates.append(datetime.datetime.combine(d, datetime.time(6, 0)))
                    candidates.append(datetime.datetime.combine(d, datetime.time(14, 0)))
                    candidates.append(datetime.datetime.combine(d, datetime.time(22, 0)))
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
                    s5_start = datetime.datetime.combine(s1_start.date() - datetime.timedelta(days=1), datetime.time(6, 0))
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
        """Calcula el tiempo en STOP de CC01/CC02/CC03 en el rango start_dt..end_dt
        usando la DB histórica (deltas entre snapshots más cercanos al inicio y fin).
        """
        start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
        end_str   = end_dt.strftime('%Y-%m-%d %H:%M:%S')

        try:
            con = sqlite3.connect(DB_PATH, timeout=10.0)
            con.execute("PRAGMA journal_mode=WAL;")
            con.row_factory = sqlite3.Row

            def nearest(ts_target, direction):
                """Devuelve la fila más cercana al timestamp, antes (<=) o después (>=)."""
                if direction == 'before':
                    row = con.execute(
                        "SELECT * FROM plc_snapshots WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
                        (ts_target,)
                    ).fetchone()
                else:
                    row = con.execute(
                        "SELECT * FROM plc_snapshots WHERE ts >= ? ORDER BY ts ASC LIMIT 1",
                        (ts_target,)
                    ).fetchone()
                return dict(row) if row else None

            row_start = nearest(start_str, 'after')   # snapshot más cercano al inicio
            row_end   = nearest(end_str,   'before')  # snapshot más cercano al fin
            con.close()

            if not row_start or not row_end:
                self.send_json_response(200, {
                    "success": True,
                    "data": {},
                    "message": "Sin datos históricos para ese período. El historiador lleva activo desde que se inició el servidor."
                })
                return

            results = {}
            for label in ['CC01', 'CC02', 'CC03']:
                key = label.lower()
                f_start = row_start.get(f"{key}_faulted")
                f_end   = row_end.get(f"{key}_faulted")
                r_start = row_start.get(f"{key}_runtime")
                r_end   = row_end.get(f"{key}_runtime")

                if f_start is not None and f_end is not None:
                    if f_end < f_start:
                        # Se detecta un reinicio del contador del PLC
                        faulted_delta = f_end
                    else:
                        faulted_delta = f_end - f_start
                else:
                    faulted_delta = None

                if r_start is not None and r_end is not None:
                    if r_end < r_start:
                        # Se detecta un reinicio del contador del PLC
                        runtime_delta = r_end
                    else:
                        runtime_delta = r_end - r_start
                else:
                    runtime_delta = None

                results[label] = {
                    "faulted_minutes": faulted_delta,
                    "runtime_minutes": runtime_delta,
                    "status": "ok"
                }

            self.send_json_response(200, {
                "success": True,
                "query_start": row_start['ts'],
                "query_end": row_end['ts'],
                "data": results
            })

        except Exception as e:
            print(f"[Error] handle_plc_conveyor: {e}", file=sys.stderr)
            self.send_json_response(503, {"success": False, "error": str(e)})

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
