# Dashboard ASRS — Goodyear Chile

Sistema de monitoreo en tiempo real para las grúas ASRS y producción de Planta. Visualiza desempeño, tiempos de parada (downtime), eficiencias de entrada/salida y tasas de producción de Construcción y Vulcanización.

---

## Arquitectura

El sistema se compone de **2 servicios independientes** que comparten una base de datos SQLite:

```
┌─────────────────────┐         ┌─────────────────────┐
│   serve_web.py      │         │  serve_worker.py    │
│   (Flask/Waitress)  │◄────────│  (Background Task)  │
│   Puerto 8006       │  DB     │  Sin puerto         │
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
| `serve_web.py` | Sirve el dashboard y endpoints JSON (solo lee de BD) | Se pierde acceso al dashboard |
| `serve_worker.py` | Lee PLCs, consulta APIs, guarda todo en BD | El dashboard muestra últimos datos guardados |

**Diseño:** Todos los datos pasan por SQLite. El web server **nunca** consulta APIs externas directamente.

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
| `requests` | Consultas a APIs internas Goodyear (solo worker) |
| `beautifulsoup4` | Parseo de HTML (solo worker) |

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

> El dashboard funcionará con los últimos datos guardados en `shift_history.db`.

### Solo worker (recolección sin dashboard)

```bash
python serve_worker.py
```

---

## Despliegue con Crontab (Linux)

### Servidor Web (daemon permanente)

```cron
@reboot cd /ruta/al/proyecto && /usr/bin/python3 serve_web.py >> logs/web.log 2>&1 &
```

### Worker de recolección (one-shot, cada 2 horas)

```cron
0 */2 * * * cd /ruta/al/proyecto && /usr/bin/python3 serve_worker.py >> logs/worker.log 2>&1
```

> El worker corre una vez, recolecta **todos** los datos (PLCs + APIs), guarda en SQLite, y se cierra. Crontab lo ejecuta cada 2 horas.

### Frequency de ejecución

| Servicio | Tipo | Frecuencia |
|---|---|---|
| `serve_web.py` | Daemon (permanente) | Todo el tiempo, puerto 8006 |
| `serve_worker.py` | One-shot (cron) | Cada 2 horas |

### Antes de aplicar

```bash
mkdir -p /ruta/al/proyecto/logs
```

### Verificar crontab

```bash
crontab -l
```

### Reinicio manual

```bash
# Matar web server
pkill -f serve_web.py

# Ejecutar worker una vez
python3 serve_worker.py

# Reiniciar web server
nohup python3 serve_web.py >> logs/web.log 2>&1 &
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
├── serve_web.py              # Servidor Flask (solo endpoints + frontend, lee de BD)
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
| **CONVEYOR FULL** | SQLite (worker → OEE) | Tiempo total de downtime del conveyor (objetivo: 15 min) |
| **PLUMMERS** | SQLite (worker → PLC) | Estado RUN/IDLE/STOP de L1, L2, L3 |
| **ROBOTS** | SQLite (worker → PLC) | Estado de ULR1, ULR2, LR1, LR2 (valores en min) |
| **DOWNTIME CONVEYOR** | SQLite (worker → PLC) | Estado de CC01, CC02, CC03 (valores en min) |
| **NO TIRE** | SQLite (worker → OEE) | Tiempo perdido por falta de neumático por grupo |
| **INPUT / OUTPUT** | SQLite (worker → Goodyear) | Producción (Construido, Vulcanizado, Salida ASRS) + Almacenamiento |
| **CRANE PERFORMANCE** | SQLite (worker → Goodyear) | Disponibilidad de grúas + Top 3 Downtime y Parada Menor |
| **PRESS DELIVERY** | SQLite (worker → compliance + OEE) | Eficiencia de despacho por prensa con barras animadas |

---

## APIs del Backend

| Endpoint | Método | Descripción | Fuente |
|---|---|---|---|
| `/api/conveyor-full` | GET | Tiempo total downtime conveyor | `conveyor_full_downtime` |
| `/api/plc-conveyor` | GET | Estado conveyors (CC01-CC03) | `shift_summaries` |
| `/api/robots-turnos` | GET | Estado de robots por turno | `shift_summaries` |
| `/api/io-data` | GET | Datos de producción | `io_history` |
| `/api/crane-performance` | GET | Performance de grúas por pasillo | `crane_aisle_history` |
| `/api/downtime` | GET | Tiempo perdido por motivo y grupo | `press_downtime_by_reason` |
| `/api/press-delivery` | GET | Eficiencia de despacho por prensa | `press_delivery_data` |
| `/api/asrs-engineering-data` | GET | Datos de lubricadoras (Plummers) | `shift_summaries` |
| `/api/daily-ticket` | GET | Ticket diario de producción | `daily_ticket_target` |

**Parámetros comunes:** `?start=YYYY-MM-DDTHH:MM&end=YYYY-MM-DDTHH:MM`

**Fuente de datos:** Todos los endpoints leen directamente de SQLite. No hay consultas HTTP en vivo.

---

## Base de Datos (SQLite)

Archivo: `shift_history.db` (se crea automáticamente, modo WAL).

| Tabla | Propósito |
|---|---|
| `io_history` | Producción Construcción/Vulcanizado + Entrada/Salida ASRS |
| `shift_summaries` | Tiempos de run/fault/auto por máquina y turno |
| `crane_aisle_history` | Performance de grúas por pasillo (downtime %, minutos) |
| `conveyor_full_downtime` | Downtime total del conveyor (reason 10315) |
| `press_downtime_by_reason` | Downtime por reason code agrupado por prensa |
| `press_delivery_data` | Eficiencia de despacho por prensa (compliance + KPIs) |
| `daily_ticket_target` | Target diario de producción (AOP Chile FCST) |

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
- SQLite WAL permite concurrencia lectura/escritura entre ambos servicios
- Los PLCs están en la red interna Goodyear (10.107.210.x)
- El web server **no** hace consultas HTTP externas, solo lee de la BD
- El worker es el único que se comunica con PLCs y APIs externas
