# Dashboard ASRS - Documentación del Proyecto

Este documento resume la arquitectura de grado industrial, desarrollo y estado actual del proyecto del Dashboard ASRS (v2.0).

## 1. Arquitectura del Backend (Python + Flask)
- **Framework:** `Flask` (API Web) para servir las rutas HTTP, expuesto a producción mediante `Waitress`.
- **Ejecución y Entorno Virtual:** El proyecto arranca mediante `run.bat`. Este script crea automáticamente un entorno virtual aislado (`venv`) e instala las dependencias desde `requirements.txt` para garantizar la estabilidad del sistema frente a actualizaciones globales de Python.
- **Arquitectura de Sincronización y Agregación de Datos:** 
  El Dashboard actúa como un agregador central de múltiples sistemas de la planta:
  - **Métricas de Rendimiento (Cranes, Presses, Daily Ticket):** El servidor hace *web scraping* y consume XML/JSONs de los sistemas internos existentes de la planta (ej. *SBS Reports*, *ProductionWebEditServerRS*).
  - **Estado de Máquinas (Plummers, Robots, Downtime Conveyor):** Para estas tarjetas, el servidor utiliza una **Sincronización Híbrida (En Tiempo Real / Histórica)**:
    - *Turno Activo:* Consulta directamente a los PLCs Allen-Bradley en vivo a través de la librería `pylogix`. Esto garantiza que los usuarios siempre vean los minutos exactos al momento de abrir la pantalla.
    - *Turnos Pasados:* Extrae la información de una base de datos local SQLite (`shift_history.db`). Esto reduce la carga innecesaria a la red industrial al no sobreconsultar datos estáticos.
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
