# Dashboard ASRS - Documentación del Proyecto

Este documento resume la arquitectura de grado industrial, desarrollo y estado actual del proyecto del Dashboard ASRS (v2.0).

## 1. Arquitectura del Backend (Python + Flask)
- **Framework:** `Flask` (API Web) servido a través de `Waitress` para manejo concurrente de múltiples usuarios y alta disponibilidad en la planta.
- **Archivo Principal:** `serve.py` (ejecutado a través de `run.bat` que instala las dependencias automáticamente).
- **Caché Inteligente de PLCs:** Para proteger la red de hardware industrial, el servidor ya no consulta los PLCs en tiempo real con cada clic. En su lugar, un Hilo (Thread) en segundo plano consulta los equipos Allen-Bradley vía `pylogix` cada 10 segundos y almacena los datos en memoria RAM (`plc_cache`). Cuando el usuario presiona "Consultar", el servidor responde en 1 ms con el último dato cacheado.
- **Seguridad:** El servidor bloquea automáticamente cualquier intento web de descargar código fuente (`.py`, `.bat`) o bases de datos (`.db`).

## 2. Base de Datos Histórica (Shift Logger)
- **Base de Datos:** `shift_history.db` (SQLite).
- **Programador (Scheduler):** Se utiliza la librería profesional `APScheduler` para ejecutar una tarea (CronJob) exactamente a las `05:59:50`, `13:59:50` y `21:59:50`.
- **Función:** Lee los valores acumulados de los PLCs y guarda el resumen del turno.
- **Retención:** Limpia automáticamente la base de datos para no guardar registros con más de 3 días de antigüedad.

## 3. Interfaz de Usuario (Frontend)
- **Tecnologías:** HTML5, CSS3 (Vanilla), JavaScript.
- **Resiliencia de Red:** El motor JavaScript incorpora un sistema de **Reintentos Automáticos (`fetchWithRetry`)**. Si la red de la planta sufre un micro-corte durante una consulta, el sistema reintentará silenciosamente hasta 2 veces antes de mostrar un error al usuario.
- **Diseño:** Interfaz limpia sin estilos "en línea", utilizando clases modulares en `style.css`.
- **Características:** Reloj en vivo, botones de turnos rápidos y restricción de calendario (solo permite consultar datos de las últimas 24 horas).

---

## ⚠️ NOTAS DE INTEGRACIÓN CON PLCS

La integración de tiempos en vivo para las tarjetas de Plummers, Downtime Conveyor y Robots **depende 100% de la lógica del PLC**:

1. El PLC debe tener Timers Retentivos (RTO) que acumulen los tiempos de RUN, IDLE y STOP.
2. Esos acumulados deben ser divididos entre 60,000 para obtener **Minutos Reales** y guardarlos en los Tags configurados en la parte superior del archivo `serve.py` (diccionario `PLC_TAGS_CONFIG`).
3. El PLC debe resetear esos Timers a cero (RES) al inicio de cada turno.

El Dashboard actual simplemente leerá esos Tags listos y los mostrará en pantalla.
