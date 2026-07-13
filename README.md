# Dashboard ASRS

Sistema de monitoreo para las grúas ASRS y producción de Planta Goodyear, diseñado para visualizar el desempeño, tiempos de parada (downtime), eficiencias de entrada/salida y tasas de producción de Construcción y Vulcanización.

## Requisitos Previos

- Python 3.10 o superior
- `pip` (gestor de paquetes)

Instalar dependencias:

```bash
pip install -r requirements.txt
```

Dependencias principales:
- **Flask**: Servidor web local
- **Waitress**: Servidor WSGI para producción en Windows
- **pylogix**: Conexión a PLCs y lectura de tags (tiempos de grúas)
- **requests**: Consultas a API internas Goodyear
- **beautifulsoup4**: Parseo de HTML en extracciones de datos

## Ejecución

```bash
python serve.py
```

Escucha en el **puerto 5000** por defecto. Accesible en:

```
http://<IP_DEL_SERVIDOR>:5000/
```

## Estructura del Proyecto

```
├── serve.py                  # Backend Flask + background tasks
├── requirements.txt          # Dependencias Python
├── shift_history.db          # Base de datos SQLite (se crea automáticamente)
└── static/
    ├── index.html            # Vista principal (Grid Layout)
    ├── style.css             # Estilos (tema light, glassmorphism)
    ├── script.js             # Lógica cliente (fetch + actualización DOM)
    └── logo-goodyear.png     # Logo
```

## Tarjetas del Dashboard

| Tarjeta | Descripción |
|---|---|
| **CONVEYOR FULL** | Tiempo total de downtime del conveyor (objetivo: 15 min) |
| **PLUMMERS** | Estado RUN/IDLE/STOP de las 3 lubricadoras |
| **ROBOTS** | Estado RUN/IDLE/STOP de LR1, LR2, ULR1, ULR2 (valores en min) |
| **DOWNTIME CONVEYOR** | Estado RUN/IDLE/STOP de CC01, CC02, CC03 (valores en min) |
| **NO TIRE** | Tiempo perdido por falta de neumático por grupo (100A-600B) |
| **INPUT / OUTPUT** | Producción (Construido, Vulcanizado, Total Salida ASRS) + Almacenamiento (Entrada ASRS, Manual, Automático) con eficiencia de entrada |
| **CRANE PERFORMANCE** | Disponibilidad de grúas + Top 3 Downtime y Top 3 Parada Menor |
| **PRESS DELIVERY** | Eficiencia de despacho por prensa (400B, 500A, 500B, 600A, 600B) con barras de progreso animadas |

## APIs del Backend

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/conveyor-full` | GET | Tiempo total downtime conveyor |
| `/api/plc-conveyor` | GET | Estado RUN/IDLE/STOP de conveyors (CC01-CC03) |
| `/api/robots-turnos` | GET | Estado de robots por turno |
| `/api/io-data` | GET | Datos de producción (Construido, Vulcanizado, Entrada/Salida ASRS) |
| `/api/crane-performance` | GET | Performance de grúas por pasillo |
| `/api/downtime` | GET | Tiempo perdido por motivo y grupo |
| `/api/press-delivery` | GET | Eficiencia de despacho por prensa |
| `/api/asrs-engineering-data` | GET | Datos de lubricadoras (Plummers) |
| `/api/daily-ticket` | GET | Ticket diario de producción |

Parámetros comunes: `?start=YYYY-MM-DDTHH:MM&end=YYYY-MM-DDTHH:MM` (rango de turno).

## Base de Datos (SQLite)

Archivo: `shift_history.db` (se crea automáticamente).

- **io_history**: Datos de producción de Construcción y Vulcanizado, entradas/salidas de turnos.
- **shift_summaries**: Tiempos de funcionamiento y error de cada máquina (run, fault, auto).
- **api_cache**: Cache de respuestas API (TTL: 5 minutos).

**Mantenimiento**: Para reiniciar la BD, eliminar `shift_history.db` y reiniciar `serve.py`.

## Funcionalidades

- Selector de turno (Actual, Anterior, Hace 2/3 Turnos)
- Auto-actualización sincronizada con cron del backend (cada 2 horas)
- Tooltips de ayuda explicativos en tarjetas IO y última actualización
- Indicadores de estado con animación de pulsación (verde/roje)
- Barras de progreso animadas en Press Delivery con tooltips por segmento
- Flash animation en datos al actualizarse
- Tabular nums para alineación de números
- Tema light con glassmorphism y backdrop-filter

## Notas IT

- Los archivos `.bat` y `.exe` están en `.gitignore`
- Las variables CSS están en `:root` al inicio de `static/style.css`
- El servidor usa `waitress` en producción (no el servidor de desarrollo de Flask)
- Los `.exe` y `.bat` no se incluyen en el repositorio
