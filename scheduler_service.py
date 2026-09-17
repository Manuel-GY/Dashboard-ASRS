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

def consultar_ticket_programado(port=8006):
    """
    Consulta el ticket requerido de producción de neumáticos en /api/daily-ticket.
    Retorna (ticket_total, ticket_formatted, success)
    """
    url = f"http://127.0.0.1:{port}/api/daily-ticket"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("total", 0)
            formatted = data.get("formatted", str(total))
            return int(total) if str(total).isdigit() else 0, formatted, True
    except Exception as e:
        log.error(f"Error al consultar Ticket Requerido en {url}: {e}")
    return 0, "0", False

def ejecutar_proceso_envio_turno(turno, fecha=None, port=8006, force=False, renderer="pillow"):
    """
    Verifica si el ticket requerido > 0 (o si es envío forzado manual).
    Si es positivo, genera la captura y despacha a Teams.
    renderer: "pillow" (sin navegador, servidores con IT restrictivo) o "playwright".
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

    # 2. Generar imagen del reporte (Pillow primero, sin navegador)
    log.info(f"📸 Generando captura del reporte para {turno} ({fecha}) con renderer={renderer}...")
    img_bytes = None
    try:
        if renderer == "playwright":
            from capture_service import capturar_reporte_png
            img_bytes = capturar_reporte_png(fecha=fecha, turno=turno, port=port)
        else:
            img_bytes = capturar_reporte_png_pillow(turno=turno, fecha=fecha, port=port)
            if not img_bytes:
                log.warning("Render Pillow falló, intentando fallback a Playwright...")
                from capture_service import capturar_reporte_png
                img_bytes = capturar_reporte_png(fecha=fecha, turno=turno, port=port)
        if not img_bytes:
            return False, "Error al generar imagen PNG del reporte"
    except Exception as e:
        log.error(f"Error en captura del reporte: {e}")
        return False, str(e)

    # 3. Enviar a Microsoft Teams
    titulo = f"Entrega de Turno - ASRS | {turno} ({fecha}) • Ticket: {formatted_ticket} tires"
    log.info(f"🚀 Despachando reporte a Microsoft Teams...")
    exito, msg = enviar_imagen_a_teams(img_bytes, titulo=titulo)
    return exito, msg

def capturar_reporte_png_pillow(turno, fecha=None, port=8006):
    """
    Genera el PNG del reporte sin navegador usando el render Pillow (image_builder).
    Retorna bytes PNG o None si falla.
    """
    try:
        import requests
        from image_builder import render_entrega_turno
    except Exception as e:
        log.error(f"image_builder no disponible: {e}")
        return None

    if fecha is None:
        fecha = datetime.now().strftime("%Y-%m-%d")

    url = f"http://127.0.0.1:{port}/api/consolidado-turno?fecha={fecha}&turno={turno}"
    try:
        resp = requests.get(url, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error(f"Error obteniendo consolidado-turno para captura Pillow: {e}")
        return None

    try:
        img_bytes = render_entrega_turno(data)
        if img_bytes:
            log.info(f"Captura Pillow generada: {len(img_bytes)} bytes")
        return img_bytes
    except Exception as e:
        log.error(f"Error en render Pillow: {e}")
        return None

def iniciar_scheduler_loop(port=8006):
    """
    Bucle en segundo plano: calcula el próximo horario de envío configurado
    y duerme hasta ese momento. Solo despierta 1 vez por turno (3 veces al día).
    """
    log.info("Iniciando Planificador Automático de Entrega de Turno ASRS...")
    ultimo_disparo = None

    while True:
        try:
            cfg = load_schedule_config()
            auto_enabled = cfg.get("auto_send_enabled", True)

            if not auto_enabled:
                log.info("Envío automático deshabilitado. Esperando...")
                time.sleep(60)
                continue

            ahora = datetime.now()

            horarios = []
            for time_key, turno in (("t1_time", "T1"), ("t2_time", "T2"), ("t3_time", "T3")):
                t_str = cfg.get(time_key, "").strip()
                if t_str:
                    try:
                        horarios.append((datetime.strptime(t_str, "%H:%M"), turno))
                    except ValueError:
                        log.warning(f"Horario inválido '{t_str}' para {turno}")

            if not horarios:
                log.warning("Sin horarios configurados. Esperando 60s...")
                time.sleep(60)
                continue

            # Encontrar el próximo horario de envío (hoy si aún no pasó, si no mañana)
            next_target = None
            for t, turno in sorted(horarios):
                candidate = ahora.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                if candidate > ahora:
                    next_target = (candidate, turno)
                    break
            if next_target is None:
                t, turno = sorted(horarios)[0]
                next_target = (ahora.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0) + timedelta(days=1), turno)

            target_dt, turno = next_target
            fecha_str = target_dt.strftime("%Y-%m-%d")

            delta = (target_dt - datetime.now()).total_seconds()
            log.info(f"Próximo envío: {turno} a las {target_dt.strftime('%Y-%m-%d %H:%M')} (en {delta/3600:.1f} h)")

            # Dormir hasta 1 minuto antes del horario
            if delta > 60:
                time.sleep(delta - 60)

            # Ajuste fino para disparar exactamente en el minuto configurado
            while datetime.now() < target_dt:
                time.sleep(5)

            disparo_key = f"{fecha_str}_{turno}"
            if ultimo_disparo != disparo_key:
                ultimo_disparo = disparo_key
                log.info(f"⏰ Horario alcanzado: {target_dt.strftime('%H:%M')} -> Ejecutando envío de {turno}...")
                exito, msg = ejecutar_proceso_envio_turno(turno, fecha_str, port=port)
                log.info(f"Resultado de envío automático: {msg}")
        except Exception as e:
            log.error(f"Error en bucle de scheduler: {e}")
            time.sleep(30)
