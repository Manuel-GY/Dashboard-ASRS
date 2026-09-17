import os
import json
import base64
import logging
import requests

log = logging.getLogger("teams_sender")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "schedule_config.json")

def get_webhook_url():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                url = data.get("webhook_url", "").strip()
                if url:
                    return url
        except Exception as e:
            log.warning(f"Error al leer {CONFIG_PATH}: {e}")
    return os.getenv("TEAMS_WEBHOOK_URL", "")

def enviar_imagen_a_teams(img_bytes, titulo="Entrega de Turno - ASRS", webhook_url=None):
    """
    Envía la imagen PNG de la entrega de turno a Microsoft Teams / Power Automate.
    """
    url = webhook_url or get_webhook_url()
    if not url:
        log.warning("No se ha configurado la URL del Webhook de Teams en schedule_config.json.")
        return False, "URL del Webhook de Teams no configurada"

    try:
        b64_img = base64.b64encode(img_bytes).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64_img}"

        # Payload compatible con Power Automate y Webhooks estándar de Teams
        payload = {
            "type": "message",
            "title": f"📋 {titulo}",
            "imageB64": b64_img,
            "imageUrl": data_uri,
            "text": f"📋 {titulo}",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": f"📋 **{titulo}**",
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": "Dark"
                            },
                            {
                                "type": "Image",
                                "url": data_uri,
                                "altText": "Reporte Consolidado Entrega de Turno ASRS",
                                "size": "Stretch",
                                "bleed": True
                            }
                        ]
                    }
                }
            ]
        }

        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code in [200, 201, 202]:
            log.info("Reporte enviado exitosamente a Microsoft Teams.")
            return True, "Enviado exitosamente a Teams"
        else:
            log.error(f"Error al enviar a Teams. Código HTTP: {resp.status_code} - {resp.text}")
            return False, f"Error HTTP {resp.status_code}: {resp.text}"

    except Exception as e:
        log.error(f"Excepción al enviar reporte a Teams: {e}")
        return False, str(e)
