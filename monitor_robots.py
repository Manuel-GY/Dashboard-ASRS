import time
import datetime
import sqlite3
import os
import sys
import threading
from pylogix import PLC

# Configuración de los PLCs a monitorear (Robots)
PLC_CONFIG = [
    {
        "label": "LR1",
        "ip": "10.107.210.141",
        "slot": 0,
        "tag_estop": "ESTOP_OK",
        "tag_manual": "Auto_Manual"
    },
    {
        "label": "LR2",
        "ip": "10.107.210.140",
        "slot": 0,
        "tag_estop": "ESTOP_OK",
        "tag_manual": "Auto_Manual"
    },
    {
        "label": "ULR1",
        "ip": "10.107.210.143", # Placeholder
        "slot": 0,
        "tag_estop": "ESTOP_OK",
        "tag_manual": "Auto_Manual"
    },
    {
        "label": "ULR2",
        "ip": "10.107.210.144", # Placeholder
        "slot": 0,
        "tag_estop": "ESTOP_OK",
        "tag_manual": "Auto_Manual"
    }
]

# Configuración de Base de Datos
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estop_history.db")

def init_db():
    """Inicializa la base de datos y crea la tabla si no existe."""
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("""
        CREATE TABLE IF NOT EXISTS conveyor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            maquina TEXT,
            estado TEXT,
            fecha TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            duracion_segundos REAL
        )
    """)
    # Crear un índice en hora_inicio para optimizar búsquedas y borrados
    con.execute("CREATE INDEX IF NOT EXISTS idx_hora_inicio_conv ON conveyor_events(hora_inicio)")
    
    # Tabla para estados actuales
    con.execute("""
        CREATE TABLE IF NOT EXISTS current_states (
            maquina TEXT PRIMARY KEY,
            estado TEXT,
            hora_inicio TEXT
        )
    """)
    
    con.commit()
    con.close()

def save_event(maquina, estado, start_dt, end_dt):
    """Guarda un evento y elimina los registros de más de 24 horas."""
    duracion = (end_dt - start_dt).total_seconds()
    if duracion <= 0:
        return  # Ignorar si no hubo duración real
        
    fecha = start_dt.strftime('%Y-%m-%d')
    hora_inicio = start_dt.strftime('%Y-%m-%d %H:%M:%S')
    hora_fin = end_dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Calcular el límite de 7 días (168 horas)
    cutoff_dt = datetime.datetime.now() - datetime.timedelta(days=7)
    cutoff_str = cutoff_dt.strftime('%Y-%m-%d %H:%M:%S')

    try:
        con = sqlite3.connect(DB_PATH, timeout=10.0)
        con.execute("PRAGMA journal_mode=WAL;")
        
        # Insertar nuevo registro
        con.execute("""
            INSERT INTO conveyor_events (maquina, estado, fecha, hora_inicio, hora_fin, duracion_segundos)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (maquina, estado, fecha, hora_inicio, hora_fin, duracion))
        
        # Eliminar registros más antiguos de 7 días
        con.execute("DELETE FROM conveyor_events WHERE hora_inicio < ?", (cutoff_str,))
        
        con.commit()
        con.close()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Evento guardado: {maquina} | Estado: {estado} | Inicio: {hora_inicio} | Duración: {duracion:.1f}s")
    except Exception as e:
        print(f"[Error DB] No se pudo guardar el evento de {maquina}: {e}", file=sys.stderr)

def monitor_single_plc(config):
    """Función que monitorea un solo PLC de forma continua."""
    label = config["label"]
    ip = config["ip"]
    slot = config["slot"]
    tag_estop = config["tag_estop"]
    tag_manual = config["tag_manual"]
    
    current_state = None
    start_time = None
    
    # Intentar recuperar el estado anterior para no perder el tiempo acumulado al reiniciar el script
    try:
        con = sqlite3.connect(DB_PATH, timeout=5.0)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT estado, hora_inicio FROM current_states WHERE maquina=?", (label,)).fetchone()
        if row:
            current_state = row["estado"]
            start_time = datetime.datetime.strptime(row["hora_inicio"], '%Y-%m-%d %H:%M:%S')
        con.close()
    except Exception:
        pass
        
    print(f"[{label}] Iniciando monitoreo de Robot en {ip}...")
    
    while True:
        try:
            with PLC() as comm:
                comm.IPAddress = ip
                comm.ProcessorSlot = slot
                
                ret = comm.Read([tag_estop, tag_manual])
                
                if len(ret) == 2 and ret[0].Status == "Success" and ret[1].Status == "Success":
                    estop_ok = bool(ret[0].Value)
                    is_auto = bool(ret[1].Value)
                    
                    # Lógica de la máquina de estados para Robots (STOP y RUN)
                    # Está en STOP si hay E-STOP o si está en MANUAL (is_auto == False)
                    if not estop_ok or not is_auto:
                        new_state = "STOP"
                    else:
                        new_state = "RUN"
                    
                    # Si acabamos de iniciar o cambió de estado
                    if current_state != new_state:
                        now = datetime.datetime.now()
                        
                        # Si venimos de un estado anterior, guardamos su duración en el historial
                        if current_state is not None and start_time is not None:
                            save_event(label, current_state, start_time, now)
                            
                        # Actualizamos al nuevo estado
                        print(f"[{now.strftime('%H:%M:%S')}] {label} cambió a estado: {new_state}")
                        current_state = new_state
                        start_time = now
                        
                        # Guardar el estado activo en SQLite
                        try:
                            con = sqlite3.connect(DB_PATH, timeout=10.0)
                            con.execute("PRAGMA journal_mode=WAL;")
                            con.execute("INSERT OR REPLACE INTO current_states (maquina, estado, hora_inicio) VALUES (?, ?, ?)", 
                                        (label, current_state, start_time.strftime('%Y-%m-%d %H:%M:%S')))
                            con.commit()
                            con.close()
                        except Exception as e:
                            print(f"[Error DB] Guardando estado actual de {label}: {e}", file=sys.stderr)
                        
                else:
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [{label}] Error leyendo los tags.", file=sys.stderr)
                    # En caso de error de red, no hacemos nada con el estado actual, solo esperamos
                    
        except Exception as e:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [{label}] Excepción de red/PLC: {e}", file=sys.stderr)
            
        # Esperar 1 segundo antes de la próxima lectura
        time.sleep(1)

def main():
    print("Iniciando monitor de Estados (RUN, IDLE, STOP) para Robots...")
    init_db()
    
    threads = []
    for cfg in PLC_CONFIG:
        t = threading.Thread(target=monitor_single_plc, args=(cfg,), daemon=True)
        t.start()
        threads.append(t)
        
    # Mantener el hilo principal vivo
    while True:
        time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitor detenido por el usuario.")
        sys.exit(0)
