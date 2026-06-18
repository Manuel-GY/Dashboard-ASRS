import time
import datetime
import sqlite3
import os
import sys
import threading
from pylogix import PLC

# Configuración de los PLCs a monitorear
PLC_CONFIG = [
    {
        "label": "CC01",
        "ip": "10.107.210.111",
        "slot": 0,
        "tag_estop": "CC01_EStop_Active",
        "tag_run": ["P0100_OK"]
    },
    {
        "label": "CC02",
        "ip": "10.107.210.121",
        "slot": 0,
        "tag_estop": "CC02_Stop",
        "tag_run": ["P1300_OK"]
    },
    {
        "label": "CC03",
        "ip": "10.107.210.131",
        "slot": 0,
        "tag_estop": "CC03_Stop",
        "tag_run": ["CC03_P2900_OK", "CC03_P2975_OK"]
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
    tag_run = config["tag_run"]
    
    current_state = None
    start_time = None
    
    print(f"[{label}] Iniciando monitoreo en {ip}...")
    
    while True:
        try:
            with PLC() as comm:
                comm.IPAddress = ip
                comm.ProcessorSlot = slot
                
                # Leer múltiples tags de una sola vez
                tags_to_read = [tag_estop] + tag_run
                ret = comm.Read(tags_to_read)
                
                if len(ret) == len(tags_to_read) and all(r.Status == "Success" for r in ret):
                    is_estop = bool(ret[0].Value)
                    # Para que esté en RUN, exigimos que todos los tags definidos en tag_run sean True
                    is_run = all(bool(r.Value) for r in ret[1:])
                    
                    # Lógica de la máquina de estados
                    new_state = "IDLE"
                    if is_estop:
                        new_state = "STOP"
                    elif is_run:
                        new_state = "RUN"
                    else:
                        new_state = "IDLE"
                    
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
    print("Iniciando monitor de Estados (RUN, IDLE, STOP) para Conveyors...")
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
