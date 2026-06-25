# Dashboard ASRS - Documentación del Proyecto

Este documento resume la arquitectura de grado industrial, desarrollo y estado actual del proyecto del Dashboard ASRS (v2.0).

## 1. Arquitectura del Backend (Python + Flask)
- **Framework:** `Flask` (API Web) servido a través de `Waitress` para manejo concurrente de múltiples usuarios y alta disponibilidad en la planta.
- **Archivo Principal:** `serve.py` (ejecutado a través de `run.bat` que instala las dependencias automáticamente).
- **Sincronización en Tiempo Real con PLCs:** Para mantener la red de automatización industrial limpia y sin sobrecargas de peticiones en segundo plano, el servidor **no mantiene cachés ni bases de datos históricas**. Toda consulta de tiempos perdidos o estado de máquinas viaja directamente a los PLCs Allen-Bradley vía `pylogix` en el momento exacto en el que el navegador del cliente (Frontend) lo solicita.
- **Seguridad:** El servidor bloquea automáticamente cualquier intento web de descargar código fuente (`.py`, `.bat`) o bases de datos (`.db`).

## 2. Interfaz de Usuario (Frontend)
- **Tecnologías:** HTML5, CSS3 (Vanilla), JavaScript.
- **Resiliencia de Red:** El motor JavaScript incorpora un sistema de **Reintentos Automáticos (`fetchWithRetry`)**. Si la red de la planta sufre un micro-corte durante una consulta, el sistema reintentará silenciosamente hasta 2 veces antes de mostrar un error al usuario.
- **Diseño:** Interfaz limpia sin estilos "en línea", utilizando clases modulares en `style.css`.
- **Enfoque de Entrega de Turno:** La interfaz fue rediseñada para eliminar calendarios manuales. Usa botones de acceso rápido ("Turno Actual", "Turno Anterior", etc.) que inyectan los horarios automáticamente basados en la hora del sistema.
- **Actualizador Inteligente:** Para garantizar datos perfectos durante la reunión de cambio de turno, el frontend agenda recargas automáticas exactamente 5 minutos después del cambio de turno oficial (06:05, 14:05, 22:05), permitiendo que la base de datos guarde todo correctamente. Adicionalmente tiene un respaldo de actualización cada 2 horas.

---

## ⚠️ NOTAS DE INTEGRACIÓN CON PLCS

La integración de tiempos en vivo para las tarjetas de Plummers, Downtime Conveyor y Robots **depende 100% de la lógica del PLC**:

1. El PLC debe tener Timers Retentivos (RTO) que acumulen los tiempos de RUN, IDLE y STOP.
2. Esos acumulados deben ser divididos entre 60,000 para obtener **Minutos Reales** y guardarlos en los Tags configurados en la parte superior del archivo `serve.py` (diccionario `PLC_TAGS_CONFIG`).
3. El PLC debe resetear esos Timers a cero (RES) al inicio de cada turno.

**NOTA ESPECÍFICA PARA CC02 (IP 10.107.210.121):**
El Dashboard se conecta **en tiempo real** al PLC de esta máquina vía la ruta `/api/cc02-turnos`. Existe un error conocido en el bloque de automatización `Downtime2` de este equipo: reinicia sus contadores a las 00:00 hrs (medianoche) en lugar de a las 06:00 AM. Se debe modificar la lógica del PLC para solucionar este error y evitar que el Turno Noche (T1) aparezca incompleto.
