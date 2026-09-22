import os
import json
import time
import logging
from datetime import datetime, timedelta
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger("scheduler_service")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "schedule_config.json")

def load_schedule_config():
    """Carga los horarios de configuración dinámicos."""
    config = {
        "auto_send_enabled": True,
        "t1_time": "06:45",
        "t2_time": "14:45",
        "t3_time": "22:45",
        "webhook_url": ""
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                config.update(data)
        except Exception as e:
            log.warning(f"Error al leer {CONFIG_PATH}: {e}")
    return config

def _parse_ticket_number(val):
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val or "").replace(",", "").replace(".", "").strip()
    return int(s) if s.isdigit() else 0

def consultar_ticket_programado(port=8006):
    """
    Consulta el ticket requerido de producción de neumáticos en /api/daily-ticket.
    Retorna (ticket_total, ticket_formatted, success)
    """
    port = int(os.environ.get("PORT", port))
    url = f"http://127.0.0.1:{port}/api/daily-ticket"
    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(url, timeout=8, proxies={"http": None, "https": None})
        if resp.status_code == 200:
            data = resp.json()
            raw_total = data.get("total", 0)
            formatted = str(data.get("formatted", raw_total) or raw_total)
            total_num = _parse_ticket_number(raw_total)
            if total_num == 0 and formatted:
                total_num = _parse_ticket_number(formatted)
            return total_num, formatted, True
    except Exception as e:
        log.error(f"Error al consultar Ticket Requerido en {url}: {e}")
    return 0, "0", False

def ejecutar_proceso_envio_turno(turno, fecha=None, port=8006, force=False):
    """
    Verifica si el ticket requerido > 0 (o si es envío forzado manual).
    Si es positivo, genera la captura con Pillow y despacha a Teams.
    """
    from teams_sender import enviar_imagen_a_teams

    if fecha is None:
        fecha = datetime.now().strftime("%Y-%m-%d")

    log.info(f"=== EVALUANDO ENVÍO AUTOMÁTICO: {turno} ({fecha}) ===")
    
    # 1. Validar condición: Ticket Requerido > 0
    total_ticket, formatted_ticket, ok = consultar_ticket_programado(port=port)
    log.info(f"Ticket Requerido: {formatted_ticket} tires (total: {total_ticket})")

    if total_ticket <= 0 and not force:
        log.info(f"🚫 [ENVÍO OMITIDO] Ticket Requerido en 0 tires. El reporte de {turno} no se despacha.")
        return False, f"Omitido: Ticket Requerido en 0 tires ({formatted_ticket})"

    # 2. Generar imagen del reporte (Pillow nativo)
    log.info(f"📸 Generando captura del reporte para {turno} ({fecha}) con Pillow...")
    img_bytes, err = capturar_reporte_png_pillow(turno=turno, fecha=fecha, port=port)
    if not img_bytes:
        log.error(f"Error en render Pillow: {err}")
        return False, f"Error en render Pillow: {err}"

    # 3. Enviar a Microsoft Teams
    titulo = f"Entrega de Turno - ASRS | {turno} ({fecha}) • Ticket: {formatted_ticket} tires"
    log.info(f"🚀 Despachando reporte a Microsoft Teams...")
    exito, msg = enviar_imagen_a_teams(img_bytes, titulo=titulo)
    return exito, msg

def capturar_reporte_png_pillow(turno, fecha=None, port=8006):
    """
    Genera el PNG del reporte sin navegador usando el render Pillow (image_builder).
    Retorna (bytes PNG, error_message).
    """
    port = int(os.environ.get("PORT", port))
    try:
        from image_builder import render_entrega_turno
    except Exception as e:
        err = f"image_builder no disponible: {e}"
        log.error(err)
        return None, err

    if fecha is None:
        fecha = datetime.now().strftime("%Y-%m-%d")

    url = f"http://127.0.0.1:{port}/api/consolidado-turno?fecha={fecha}&turno={turno}"
    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(url, timeout=25, proxies={"http": None, "https": None})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        err = f"Error obteniendo consolidado-turno en {url}: {e}"
        log.error(err)
        return None, err

    try:
        img_bytes = render_entrega_turno(data)
        if img_bytes:
            log.info(f"Captura Pillow generada: {len(img_bytes)} bytes")
            return img_bytes, None
        return None, "render_entrega_turno retornó datos vacíos"
    except Exception as e:
        err = f"Error en render Pillow: {e}"
        log.error(err)
        return None, err

def iniciar_scheduler_loop(port=8006):
    """
    Bucle en segundo plano: revisa 1 vez por minuto si la hora actual (HH:MM)
    coincide con los horarios programados de envío automático (T1, T2, T3).
    """
    log.info("Iniciando Planificador Automático de Entrega de Turno ASRS (1 chequeo/min)...")
    ultimo_disparo = None
    ultimo_mtime = 0
    cached_cfg = None

    while True:
        try:
            # Recargar configuración si el archivo cambió en disco
            if os.path.exists(CONFIG_PATH):
                try:
                    mtime = os.path.getmtime(CONFIG_PATH)
                    if mtime != ultimo_mtime or cached_cfg is None:
                        cached_cfg = load_schedule_config()
                        ultimo_mtime = mtime
                except Exception:
                    cached_cfg = load_schedule_config()
            else:
                cached_cfg = load_schedule_config()

            cfg = cached_cfg or {}
            auto_enabled = cfg.get("auto_send_enabled", True)
            ahora = datetime.now()
            hora_actual_str = ahora.strftime("%H:%M")
            fecha_hoy_str = ahora.strftime("%Y-%m-%d")

            if auto_enabled:
                horarios = {
                    "T1": cfg.get("t1_time", "06:45").strip(),
                    "T2": cfg.get("t2_time", "14:45").strip(),
                    "T3": cfg.get("t3_time", "22:45").strip()
                }

                for turno, hora_prog in horarios.items():
                    if hora_prog and hora_actual_str == hora_prog:
                        disparo_key = f"{fecha_hoy_str}_{turno}"
                        if ultimo_disparo != disparo_key:
                            ultimo_disparo = disparo_key
                            log.info(f"⏰ [DISPARO AUTOMÁTICO] Horario alcanzado: {hora_actual_str} ({turno}) -> Despachando reporte...")
                            exito, msg = ejecutar_proceso_envio_turno(turno, fecha_hoy_str, port=port)
                            log.info(f"Resultado del envío de {turno}: {msg}")

            # Dormir hasta el inicio del próximo minuto (exactamente 1 vez por minuto)
            now_sec = datetime.now().second
            sleep_sec = max(1, 60 - now_sec)
            time.sleep(sleep_sec)

        except Exception as e:
            log.error(f"Error en bucle de scheduler: {e}")
            time.sleep(30)
