# Dashboard ASRS - Documentación del Proyecto

Este documento resume la arquitectura de grado industrial, desarrollo y estado actual del proyecto del Dashboard ASRS (v2.0).

## 1. Arquitectura del Backend (Python + Flask)
- **Framework:** `Flask` (API Web) para servir las rutas HTTP, expuesto a producción mediante `Waitress`.
- **Ejecución y Entorno Virtual:** El proyecto arranca mediante `run.bat`. Este script crea automáticamente un entorno virtual aislado (`venv`) e instala las dependencias desde `requirements.txt` para garantizar la estabilidad del sistema frente a actualizaciones globales de Python.
- **Arquitectura de Sincronización CRON (Fotografías Temporales Ancladas):** 
  El Dashboard actúa como un agregador central de múltiples sistemas de la planta que opera en bloques estáticos de 2 horas para garantizar la congruencia en la entrega de turnos:
  - **Programador Cron Industrial:** El servidor ejecuta un hilo secundario en segundo plano anclado al reloj del sistema que "despierta" y ejecuta extracciones **exactamente a los 5 minutos de las horas pares** (ej. 06:05, 08:05, 10:05... 14:05... 22:05).
  - **Base de Datos Local (SQLite):** Durante la extracción CRON, el sistema guarda en la base de datos local (`shift_history.db`) toda la información recopilada directamente desde los PLCs Allen-Bradley mediante la librería `pylogix` (Robots, Plummers) y mediante web scraping para el Daily Ticket (IO Data).
  - **Limitador de Horizonte Temporal:** Para métricas secundarias que se leen bajo demanda desde servidores externos web (Grúas, Prensas, Conveyor Full), el servidor intercepta la petición HTTP y suplanta el reloj de "Tiempo Real" por el timestamp del último registro de la base de datos (`get_capped_now()`). Esto garantiza que **todos** los indicadores del dashboard muestren una "foto" sincronizada al mismo milisegundo, eliminando discrepancias operativas en los reportes.
- **Seguridad:** Para prevenir vulnerabilidades de "Path Traversal" (evasión de directorios), el proyecto aísla y empaqueta estrictamente los archivos de la interfaz gráfica (`index.html`, `script.js`, `style.css`) dentro del directorio `/static`. El servidor Flask está configurado para servir recursos de manera exclusiva desde esta carpeta, lo que blinda al sistema haciendo matemáticamente imposible la descarga o exposición accidental del código fuente (`.py`, `.bat`) o bases de datos industriales (`.db`).

## 2. Interfaz de Usuario (Frontend)
- **Tecnologías:** HTML5, CSS3 (Vanilla), JavaScript.
- **Resiliencia de Red:** El motor JavaScript incorpora un sistema de **Reintentos Automáticos (`fetchWithRetry`)**. Si la red de la planta sufre un micro-corte o alta latencia, el sistema reintentará las conexiones silenciosamente antes de mostrar un estado de "Fallo" al usuario.
- **Diseño:** Interfaz modular, con colores estandarizados en `style.css` y prevenciones activas de caché usando versionado en las importaciones (`?v=2`).
- **Programador Inteligente de Turnos:** La interfaz evita calendarios manuales usando botones contextuales ("Turno Actual", "Turno Anterior"). Además, el frontend agenda recargas automáticas exactamente 5 minutos después del cambio de turno oficial (ej. 06:05, 14:05, 22:05) para asegurar que la base de datos alcanzó a registrar el cierre del turno anterior correctamente.

---

## ⚠️ NOTAS DE INTEGRACIÓN CON PLCS (CRÍTICO)

La integración de tiempos en vivo para las tarjetas de **Plummers**, **Downtime Conveyor** y **Robots** depende 100% de la lógica programada en las instrucciones AOI (como `Downtime3`) de cada PLC.

1. **Lectura Estructurada por Turno:**
   El dashboard lee los atributos directos del turno que se está solicitando (`T1_`, `T2_`, `T3_`).
   - `TimerOK`: Representa el tiempo (en minutos) que la máquina pasó ejecutando ciclos de trabajo válidos. (Mostrado en columna **RUN**).
   - `TimerFault`: Representa el tiempo que la máquina pasó detenida por falla. (Mostrado en columna **STOP**).
   - `TimerAuto`: Representa el tiempo total que la máquina estuvo encendida y habilitada en modo Automático.

2. **Cálculo del Tiempo IDLE (Espera):**
   El Dashboard calcula automáticamente los minutos de inactividad que no corresponden a fallas usando la siguiente fórmula:
   > **`IDLE = TimerAuto - TimerOK - TimerFault`**

3. **Requisito de Reset en Ladder (Issue Conocido):**
   Para que esta fórmula funcione y los datos en la pantalla sean reales, es imperativo que los acumuladores del PLC (específicamente los bloques de conteo `CTU` que fungen como *Timers*) se limpien a `0` estrictamente al iniciar el turno correspondiente mediante la ejecución de una instrucción **`RES`** (Reset).
   *Se ha documentado que en la lógica actual del PLC, los robots (ej. `ULR1`, `ULR2`, `LR1`, `LR2`) carecen de esta instrucción `RES` en paralelo al cambio de turno, provocando que mantengan acumuladores infinitos que superan ampliamente la barrera física de 480 minutos (8 horas). La anomalía ha sido reportada y delegada al equipo de Ingeniería de Software para su mitigación directa en el código de Studio 5000.*
