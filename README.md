# Dashboard ASRS - Documentación del Proyecto

Este documento resume la arquitectura de grado industrial, desarrollo y estado actual del proyecto del Dashboard ASRS (v2.0).

## 1. Arquitectura del Backend (Python + Flask)
- **Framework:** `Flask` (API Web) para servir las rutas HTTP, expuesto a producción mediante `Waitress`.
- **Ejecución y Entorno Virtual:** El proyecto arranca mediante `run.bat`. Este script crea automáticamente un entorno virtual aislado (`venv`) e instala las dependencias desde `requirements.txt` para garantizar la estabilidad del sistema frente a actualizaciones globales de Python.
- **Sincronización Híbrida (En Tiempo Real / Histórica):** 
  - Para el turno activo, el servidor consulta directamente a los PLCs Allen-Bradley en vivo a través de la librería `pylogix`. Esto garantiza que los usuarios siempre vean los minutos exactos al momento de abrir la pantalla.
  - Para turnos pasados (históricos), el sistema extrae la información de una base de datos local SQLite (`shift_history.db`). Esto reduce la carga innecesaria a la red industrial al no tener que sobreconsultar datos estáticos.
- **Seguridad:** El servidor bloquea automáticamente cualquier intento web de descargar código fuente (`.py`, `.bat`) o extraer directamente las bases de datos (`.db`).

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
   Para que esta fórmula funcione y los datos en la pantalla sean reales, es imperativo que los acumuladores del PLC (especialmente `TimerAuto` y `TimerOK`) se limpien (`0`) estrictamente al iniciar el turno correspondiente.
   *Actualmente se ha detectado que ciertos robots (ej. `ULR1`, `LR1`, `LR2`) mantienen acumuladores que superan la barrera lógica de los 480 minutos (8 horas) por turno, lo que corrompe el cálculo matemático del IDLE temporalmente hasta que se corrija dicha rutina en el programa de Studio 5000.*
