# Dashboard ASRS

Dashboard interactivo para el monitoreo de paradas de prensas ASRS, desarrollado para ejecutarse en entornos locales con servidores web como **XAMPP (Apache)** y conectarse en tiempo real al servidor de reportes interno.

---

## 🚀 Características Principales

*   **Monitoreo En Vivo 🟢**: Modo que consulta de manera automática cada 30 segundos una ventana deslizante de las últimas 24 horas.
*   **Filtro Histórico 📅**: Permite deshabilitar el tiempo real y seleccionar rangos de fecha y hora libres para consultar el histórico.
*   **Secciones de Monitoreo**:
    1.  **NO TIRE** (Razón de parada: `160000`)
    2.  **MANTENCIÓN PREVENTIVA ROBOT** (Razón de parada: `210002`)
    3.  **MANTENCIÓN PREVENTIVA GENERAL** (Razón de parada: `40000`)
*   **Diseño Premium y Oscuro**: Interfaz moderna, limpia, responsiva y con colores armónicos adaptados para pantallas de salas de control.
*   **Precisión Exacta**: Tiempos de parada reportados en minutos y centésimas de minuto directo del servidor sin redondeos aproximados.
*   **Visualización de 0**: Muestra explícitamente un `0` cuando no se registran paradas durante el periodo consultado.

---

## 🛠️ Requisitos de Instalación y Uso

### 1. Servidor Local (XAMPP)
El proyecto requiere un servidor web con soporte de PHP.
1. Instala [XAMPP](https://www.apachefriends.org/).
2. Clona o copia esta carpeta dentro del directorio raíz de XAMPP (`C:\xampp\htdocs\Dashboard ASRS`).
3. Asegúrate de iniciar **Apache** desde el Panel de Control de XAMPP.
   * *Nota: Si el puerto default de Apache (80) está en conflicto (por ejemplo con IIS), puedes cambiarlo a otro puerto como el `8082` en el archivo de configuración `httpd.conf` de Apache.*

### 2. URL de Acceso
Una vez levantado el servidor de Apache, accede desde tu navegador:
```
http://localhost:8082/Dashboard ASRS/
```
*(Cambia `8082` por el puerto correspondiente si usas el puerto por defecto u otro puerto).*

---

## 📂 Estructura del Proyecto

*   **`index.php`**: El punto de entrada principal del Dashboard, estructurado semánticamente con las tarjetas y layouts.
*   **`style.css`**: Hoja de estilos moderna con variables de CSS, scrollbars personalizados y tablas alineadas con bordes estilizados.
*   **`script.js`**: Controlador de lógica frontend encargado de alternar modos (Live/Histórico), auto-refrescar y realizar peticiones HTTP.
*   **`api_no_tire.php`**: Proxy para consultar y agrupar datos de paradas por falta de neumáticos (`160000`).
*   **`api_preventiva.php`**: Proxy para consultar y agrupar datos de mantenimiento preventivo del robot (`210002`).
*   **`api_preventiva_general.php`**: Proxy para consultar y agrupar datos de mantenimiento preventivo general (`40000`).

---

## 🌐 Proxies PHP y Red Interna
Debido a políticas de CORS, el frontend realiza solicitudes asíncronas (`fetch`) a los archivos `.php` locales, y estos actúan como intermediarios (proxies) consultando al servidor de reportes interno:
```
http://10.107.194.85:8080/ProductionWebEditServerRS/
```
Para que el Dashboard muestre datos correctos, tu equipo debe estar conectado a la red local que tenga acceso a la IP anterior.
