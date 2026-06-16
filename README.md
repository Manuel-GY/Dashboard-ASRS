# Dashboard ASRS

Dashboard interactivo para el monitoreo de paradas de prensas y grúas ASRS, desarrollado en Python y Javascript para ejecutarse en entornos locales con conexión en tiempo real a los servidores de reportes y PLCs internos.

---

## 🚀 Características Principales

*   **Monitoreo En Vivo 🟢**: Consulta de manera automática cada 30 segundos una ventana deslizante de las últimas horas.
*   **Filtro Histórico por Turno o Rango 📅**: Permite seleccionar rangos de fecha y hora libres para consultar el histórico de producción y paradas, evitando datos puramente acumulados.
*   **Módulos de Monitoreo**:
    1.  **NO TIRE** (Razón de parada: `160000`): Filtra paradas mayores a 0 minutos. Muestra un mensaje amigable en caso de que todas estén en cero.
    2.  **MANTENCIÓN PREVENTIVA ROBOT** (Razón de parada: `210002`): Muestra solo grupos con paradas mayores a 1 minuto.
    3.  **MANTENCIÓN PREVENTIVA GENERAL** (Razón de parada: `40000`): Muestra solo grupos con paradas mayores a 1 minuto.
    4.  **CONVEYORS (Downtime CV)**: Lee en tiempo real el tiempo de STOP (`faulted` y `runtime`) de los conveyors CC01, CC02 y CC03 conectándose directo a los PLCs de control.
    5.  **CRANE PERFORMANCE**: Extrae de forma dinámica el rendimiento y paradas por pasillo (Aisle 1 al 11) a partir de los reportes del sistema.
*   **Historiador Incorporado 💾**: Base de datos SQLite local integrada en el backend que guarda capturas de datos cada 60 segundos con una política de auto-sobreescritura para retener exactamente 7 días de información.
*   **Diseño Premium**: Interfaz moderna en modo oscuro, responsiva, con micro-animaciones, gráficos mejorados y paleta de colores HSL.

---

## 🛠️ Requisitos de Instalación y Uso

### 1. Requisitos Previos
*   **Python 3.x** instalado en el sistema.
*   Librerías de python necesarias (instalables mediante pip):
    ```bash
    pip install pylogix
    ```

### 2. Ejecutar el Proyecto
Para iniciar el backend que actúa como servidor web y API proxy:
1. Abre una consola en el directorio del proyecto.
2. Ejecuta:
   ```bash
   python serve.py
   ```
3. El servidor iniciará en el puerto local `8080`.
4. Accede desde tu navegador a:
   ```
   http://127.0.0.1:8080/index.html
   ```

---

## 📂 Estructura del Proyecto

*   **`index.html`**: Estructura base del Dashboard, optimizada con semántica HTML5 y contenedores dinámicos.
*   **`style.css`**: Hoja de estilos con variables CSS para el tema visual premium y layouts flexibles.
*   **`script.js`**: Controlador de lógica frontend (peticiones asíncronas a la API, renderizado y cálculos).
*   **`serve.py`**: Backend en Python que expone las API REST de datos, realiza polling a los PLCs, escribe en SQLite y actúa como proxy robusto hacia los servidores locales.
*   **`conveyor_history.db`**: Base de datos SQLite (generada automáticamente) para almacenar el historial de conveyors por 7 días.

---

## 🌐 Conexión de Red Interna
El backend realiza solicitudes a los servidores locales internos:
*   Prensas / Reportes: `http://10.107.194.85:8080/`
*   Pasillos (Crane Performance): `http://10.107.194.62/`
*   PLCs Conveyors: `10.107.210.111`, `10.107.210.121`, `10.107.210.131`

Asegúrate de ejecutar la aplicación en un equipo que cuente con acceso físico o VPN a este segmento de red.
