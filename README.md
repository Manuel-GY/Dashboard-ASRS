# Dashboard ASRS

Sistema de monitoreo para las grúas ASRS y producción de Planta, diseñado para visualizar el desempeño, los tiempos de parada (downtime), eficiencias de entrada/salida y las tasas de producción de Construcción y Vulcanización.

## Requisitos Previos

Asegúrate de tener instalado Python (preferiblemente 3.10 o superior) y el gestor de paquetes `pip`.

Todas las librerías necesarias con sus versiones "congeladas" se encuentran en `requirements.txt`. Para instalarlas, ejecuta el siguiente comando en la terminal desde la raíz del proyecto:

```bash
pip install -r requirements.txt
```

Las dependencias principales son:
- **Flask**: Para levantar el servidor web local.
- **Waitress**: Servidor WSGI para producción en Windows (recomendado por encima del servidor de desarrollo de Flask).
- **pylogix**: Para la conexión a los PLC y lectura de tags (tiempos de grúas).
- **requests**: Para las consultas a las API internas (Goodyear).
- **beautifulsoup4**: Para el parseo de HTML en algunas extracciones de datos (si es necesario).

## Estructura del Código

- `serve.py`: Es el archivo principal (backend). Se encarga de levantar el servidor web y ejecuta **tareas en segundo plano (background tasks)**. Estas tareas consultan el estado de los PLC y las APIs internas cada ciertos segundos/minutos y guardan la información histórica en una base de datos local SQLite (`shift_history.db`).
  - *Comentarios incluidos:* El código de `serve.py` se ha comentado para distinguir las funciones de inicialización de la BD, las llamadas a PLC, llamadas HTTP a la API de Goodyear (Construcción y Vulcanizado) y la exposición de Endpoints (JSON) para el Frontend.
- `static/`: Contiene todo el Frontend de la aplicación (UI).
  - `index.html`: La vista principal del Dashboard (HTML semántico basado en Grid Layout).
  - `style.css`: La hoja de estilos. Contiene variables globales de CSS (Light/Dark mode) y la distribución visual responsiva.
  - `script.js`: Archivo con la lógica del lado del cliente. Contiene los llamados `fetch()` hacia los Endpoints de `serve.py` (por ejemplo `/api/crane-data`, `/api/io-data`) y actualiza el HTML dinámicamente cada pocos segundos.

## Ejecución del Servidor

En un entorno de Producción en Windows, **se recomienda NO utilizar los archivos `.bat`** que pudieran haberse usado en desarrollo.

Para iniciar el sistema de manera oficial y robusta, ejecuta el siguiente comando por consola:

```bash
python serve.py
```

### Puerto de Alojamiento
Por defecto, el archivo `serve.py` utiliza `waitress` para levantar el servidor y escuchar en el **puerto 5000**.
Una vez ejecutado el comando, el dashboard será accesible localmente y en red mediante:

`http://<IP_DEL_SERVIDOR>:5000/`

(Si por algún motivo el puerto 5000 está ocupado, puedes buscar en `serve.py` al final del archivo la línea `serve(app, host='0.0.0.0', port=5000)` y cambiar el puerto).

## Base de Datos (SQLite)

El sistema genera y utiliza un archivo local llamado `shift_history.db`.
- **io_history**: Guarda los datos de producción de Construcción (HVA) y Vulcanizado (Cura), así como las entradas/salidas de los turnos.
- **shift_summaries**: Guarda un registro de los tiempos de funcionamiento y error (run, fault, auto) de cada máquina consultada vía PLC.

**Mantenimiento**: Si alguna vez la base de datos se corrompe o requiere reiniciarse, simplemente puede renombrarse o eliminarse el archivo `shift_history.db` y `serve.py` lo volverá a crear vacío en la siguiente ejecución.

## Notas para Soporte y Sistemas (IT)
- Los archivos `.bat` y `.exe` locales están incluidos en el `.gitignore` para no entorpecer el despliegue del código limpio.
- El archivo de estilos está configurado de manera modular. Si deseas ajustar el aspecto, las paletas de colores principales residen en `:root` al inicio de `static/style.css`.
