# Dashboard ASRS - Resumen del Proyecto

Este documento resume la arquitectura, desarrollo y estado actual del proyecto del Dashboard ASRS.

## 1. Interfaz de Usuario (Frontend)
- **Tecnologías:** HTML5, CSS3 (Vanilla), JavaScript.
- **Diseño:** Interfaz moderna, responsiva y con modo Oscuro/Claro dinámico.
- **Características:** 
  - Reloj en vivo con detección automática de turno (Día, Tarde, Noche).
  - Botones de "Consultas Rápidas" para filtrar la información histórica.
  - Tarjetas (Cards) de KPIs para: Conveyor Full, Desempeño de Grúas (Cranes), Plummers (Lubricadoras), Downtime de Conveyors, Robots y Entrega de Prensas.

## 2. Servidor Backend (Python)
- **Archivo Principal:** `serve.py` (ejecutado a través de `run.bat`).
- **Arquitectura:** Se migró de un modelo de "monitoreo continuo" (scripts agresivos en segundo plano que saturaban la red) a un modelo de lectura directa optimizada usando la librería `pylogix`.
- **Rutas API:** El servidor levanta endpoints (`/api/...`) que el frontend consulta para obtener datos en formato JSON, integrando lecturas de PLCs, bases de datos SQL Server remotas y archivos XML.

## 3. Base de Datos Histórica (Shift Logger)
- **Base de Datos:** `shift_history.db` (SQLite).
- **Lógica de Almacenamiento:** Para evitar el consumo innecesario de recursos de red, se implementó un "Reloj Interno" (Cron) en `serve.py` que despierta exactamente 10 segundos antes de terminar cada turno (`05:59:50`, `13:59:50`, `21:59:50`).
- **Función:** Lee los valores finales (minutos acumulados) de los PLCs y guarda el resumen del turno (Ej. `Turno de 06:00 a 14:00 - Máquina CC01 - Estado RUN: 400 mins`).
- **Retención:** El código limpia automáticamente la base de datos para no guardar registros con más de 3 días de antigüedad.

---

## ⚠️ PUNTOS PENDIENTES (Bloqueados)

Se ha dejado **suspendida** la integración de tiempos en vivo para las tarjetas de:
1. **Plummers (Lubricadoras)**
2. **Downtime Conveyor**
3. **Robots**

**Motivo de la suspensión:**
Se determinó que la computadora no debe realizar el cálculo de tiempos en Python mediante "polling" (lecturas cada segundo) para no saturar la red industrial. La directiva actual es delegar el conteo de tiempos (lógica de timers) directamente a los PLCs.

**Acciones requeridas por el Ingeniero de Software / PLC:**
1. El ingeniero del área debe crear lógica de Timers Retentivos (RTO) en los PLCs para acumular los tiempos de RUN, IDLE y STOP de los equipos.
2. Esos acumulados deben ser divididos entre 60,000 para obtener **Minutos Reales** y ser guardados en nuevos Tags (ej. `CC02_RUN_MINS`).
3. El ingeniero debe resetear esos Timers a cero (RES) al inicio de cada turno.

**Para reactivar el Dashboard:**
Una vez que el ingeniero entregue los nombres de esos nuevos Tags, se deben actualizar en la parte superior del archivo `serve.py` dentro del diccionario `PLC_TAGS_CONFIG`. Finalmente, en `script.js`, se deben descomentar las líneas que ocultan las tablas para que el Dashboard vuelva a mostrar la información en pantalla.
