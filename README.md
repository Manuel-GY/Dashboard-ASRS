# Dashboard ASRS — Goodyear Chile

Sistema de monitoreo en tiempo real para las grúas ASRS y producción de Planta. Visualiza desempeño, tiempos de parada (downtime), eficiencias de entrada/salida y tasas de producción de Construcción y Vulcanización.

---

## Arquitectura

El sistema se compone de **2 servicios independientes** que comparten una base de datos SQLite:

```
┌─────────────────────┐         ┌─────────────────────┐
│   serve_web.py      │         │  serve_worker.py    │
│   (Flask/Waitress)  │◄────────│  (Background Task)  │
│   Puerto 8006       │  cache  │  Sin puerto         │
└─────────┬───────────┘         └─────────┬───────────┘
          │                               │
          ▼                               ▼
    ┌───────────┐                  ┌───────────────┐
    │ Usuarios  │                  │  PLCs / APIs  │
    │ (Browser) │                  │  Goodyear     │
    └───────────┘                  └───────────────┘
          │                               │
          └───────────┬───────────────────┘
                      ▼
              ┌──────────────┐
              │ shift_       │
              │ history.db   │
              │ (SQLite WAL) │
              └──────────────┘
```

| Servicio | Función | Si se detiene... |
|---|---|---|
| `serve_web.py` | Sirve el dashboard y endpoints JSON | Se pierde acceso al dashboard |
| `serve_worker.py` | Lee PLCs, consulta APIs, guarda en BD | El dashboard muestra últimos datos cacheados |

---

## Requisitos

- Python 3.10+
- `pip install -r requirements.txt`

### Dependencias principales

| Paquete | Uso |
|---|---|
| `Flask` | Servidor web |
| `Waitress` | WSGI server para producción |
| `pylogix` | Comunicación con PLCs Allen-Bradley |
| `requests` | Consultas a APIs internas Goodyear |
| `beautifulsoup4` | Parseo de HTML |

---

## Ejecución

### Iniciar ambos servicios

```bash
# Terminal 1 — Servidor Web
python serve_web.py

# Terminal 2 — Worker de recolección
python serve_worker.py
```

### Solo servidor web (modo lectura)

```bash
python serve_web.py
```

> El dashboard funcionará con los últimos datos cacheados en `shift_history.db`.

### Solo worker (recolección sin dashboard)

```bash
python serve_worker.py
```

---

## Despliegue con Crontab (Linux)

Para que ambos servicios se inicien automáticamente al reiniciar el servidor, agregar las siguientes líneas al crontab:

```bash
crontab -e
```

Agregar:

```cron
# Dashboard ASRS — Inicio automático al arrancar el servidor
@reboot cd /ruta/al/proyecto && /usr/bin/python3 serve_web.py >> logs/web.log 2>&1 &
@reboot cd /ruta/al/proyecto && /usr/bin/python3 serve_worker.py >> logs/worker.log 2>&1 &
```

**Antes de aplicar**, crear la carpeta de logs:

```bash
mkdir -p /ruta/al/proyecto/logs
```

**Verificar que el crontab quedó correcto:**

```bash
crontab -l
```

### Frequency de ejecución

| Servicio | Frecuencia | Detalle |
|---|---|---|
| `serve_web.py` | Permanente (daemon) | Escucha en puerto 8006 todo el tiempo |
| `serve_worker.py` | Permanente (daemon) | Ejecuta recolección cada 2 horas (06:05, 08:05, ..., 22:05) |

> Ambos servicios corren como procesos permanentes. El `@reboot` del crontab se encarga de iniciarlos al arrancar el servidor. Si alguno se detiene, se reinicia automáticamente al próximo reboot.

### Si se necesita reinicio manual

```bash
# Matar procesos existentes
pkill -f serve_web.py
pkill -f serve_worker.py

# Reiniciar
@reboot cd /ruta/al/proyecto && /usr/bin/python3 serve_web.py >> logs/web.log 2>&1 &
@reboot cd /ruta/al/proyecto && /usr/bin/python3 serve_worker.py >> logs/worker.log 2>&1 &
```

O ejecutar directamente:

```bash
cd /ruta/al/proyecto
nohup python3 serve_web.py >> logs/web.log 2>&1 &
nohup python3 serve_worker.py >> logs/worker.log 2>&1 &
```

---

## Acceso

```
http://<IP_DEL_SERVIDOR>:8006/
```

Por defecto escucha en `0.0.0.0:8006`. Para cambiar el puerto, editar la línea `port=8006` al final de `serve_web.py`.

---

## Estructura del Proyecto

```
├── serve_web.py              # Servidor Flask (endpoints + cache + frontend)
├── serve_worker.py           # Background task (PLCs + APIs → SQLite)
├── requirements.txt          # Dependencias Python
├── shift_history.db          # Base de datos SQLite (se crea automáticamente)
└── static/
    ├── index.html            # Vista principal (Grid Layout)
    ├── style.css             # Estilos (tema light, glassmorphism)
    ├── script.js             # Lógica cliente (fetch + actualización DOM)
    └── logo-goodyear.png     # Logo
```

---

## Tarjetas del Dashboard

| Tarjeta | Fuente de datos | Descripción |
|---|---|---|
| **CONVEYOR FULL** | API OEE (HTTP) | Tiempo total de downtime del conveyor (objetivo: 15 min) |
| **PLUMMERS** | PLC (pylogix) | Estado RUN/IDLE/STOP de L1, L2, L3 |
| **ROBOTS** | PLC (pylogix) | Estado de ULR1, ULR2, LR1, LR2 (valores en min) |
| **DOWNTIME CONVEYOR** | PLC (pylogix) | Estado de CC01, CC02, CC03 (valores en min) |
| **NO TIRE** | API OEE (HTTP) | Tiempo perdido por falta de neumático por grupo |
| **INPUT / OUTPUT** | SQLite + API Goodyear | Producción (Construido, Vulcanizado, Salida ASRS) + Almacenamiento |
| **CRANE PERFORMANCE** | API Goodyear (HTTP) | Disponibilidad de grúas + Top 3 Downtime y Parada Menor |
| **PRESS DELIVERY** | API compliance + OEE (HTTP) | Eficiencia de despacho por prensa con barras animadas |

---

## APIs del Backend

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/conveyor-full` | GET | Tiempo total downtime conveyor |
| `/api/plc-conveyor` | GET | Estado conveyors (CC01-CC03) |
| `/api/robots-turnos` | GET | Estado de robots por turno |
| `/api/io-data` | GET | Datos de producción |
| `/api/crane-performance` | GET | Performance de grúas por pasillo |
| `/api/downtime` | GET | Tiempo perdido por motivo y grupo |
| `/api/press-delivery` | GET | Eficiencia de despacho por prensa |
| `/api/asrs-engineering-data` | GET | Datos de lubricadoras (Plummers) |
| `/api/daily-ticket` | GET | Ticket diario de producción |

**Parámetros comunes:** `?start=YYYY-MM-DDTHH:MM&end=YYYY-MM-DDTHH:MM`

**Cache:** Las respuestas se cachean 5 minutos en `api_cache`. Agregar `?live=1` fuerza consulta en vivo.

---

## Base de Datos (SQLite)

Archivo: `shift_history.db` (se crea automáticamente, modo WAL).

| Tabla | Propósito |
|---|---|
| `io_history` | Producción Construcción/Vulcanizado + Entrada/Salida ASRS |
| `shift_summaries` | Tiempos de run/fault/auto por máquina y turno |
| `api_cache` | Cache de respuestas API (TTL: 5 min) |

**Reiniciar BD:** Eliminar `shift_history.db` y reiniciar los servicios.

---

## Turnos

| Turno | Horario | Nombre API Goodyear |
|---|---|---|
| T1 | 22:00 - 06:00 | noche |
| T2 | 06:00 - 14:00 | manana |
| T3 | 14:00 - 22:00 | tarde |

---

## Funcionalidades del Frontend

- Selector de turno (Actual, Anterior, Hace 2/3 Turnos)
- Auto-actualización sincronizada con cron del worker (cada 2 horas)
- Tooltips de ayuda explicativos
- Indicadores de estado con animación de pulsación
- Barras de progreso animadas en Press Delivery
- Flash animation en datos al actualizarse
- Tema light con glassmorphism

---

## Notas IT

- Los archivos `.bat` y `.exe` están en `.gitignore`
- Variables CSS en `:root` al inicio de `static/style.css`
- El worker se comunica con el web vía `http://127.0.0.1:8006` para poblar el cache
- SQLite WAL permite concurrencia lectura/escritura entre ambos servicios
- Los PLCs están en la red interna Goodyear (10.107.210.x)
