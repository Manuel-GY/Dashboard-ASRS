"""
image_builder.py — Renderiza el reporte de entrega de turno como PNG usando Pillow.
"""
import io
import math
import os
from PIL import Image, ImageDraw, ImageFont

# ─── Goodyear Brand Palette ────────────────────────────────────────────────────
NAVY        = "#0B1D45"
DARK_NAVY   = "#06122D"
GOLD        = "#FBBD00"
GOLD_DARK   = "#E5AA00"
WHITE       = "#FFFFFF"
PAGE_BG     = "#FAFAFA"
CARD_BG     = "#FFFFFF"
BORDER      = "#E2E8F0"
TEXT_DARK   = "#231F20"
TEXT_MUTED  = "#525A66"
ON_NAVY_BRIGHT = "#E6EEFF"
ON_NAVY_MUTED  = "#AFC2E8"
FIELD       = "#F6F8FB"
LINE        = "#EEF2F7"
GRID        = "#E2E8F0"
ACCENT      = "#334155"

# Status tones (legible sobre blanco)
OK_COLOR   = "#16A34A"
WARN_COLOR = "#B45309"
BAD_COLOR  = "#B91C1C"

# Segmentos de las barras por prensa (mismos colores que el dashboard)
SEG_DESPACHO = "#22C55E"
SEG_IDLE     = "#EAB308"
SEG_CORTINAS = "#38BDF8"
SEG_PRENSA   = "#C2884D"
SEG_ESTOP    = "#EF4444"

SEG_COLORS = [
    (SEG_DESPACHO, "Despacho"),
    (SEG_IDLE,     "IDLE"),
    (SEG_CORTINAS, "Cortinas"),
    (SEG_PRENSA,   "Prensa"),
    (SEG_ESTOP,    "E-Stop"),
]
SEG_MAP = {
    "despachando": SEG_DESPACHO,
    "idle":        SEG_IDLE,
    "cortinas":    SEG_CORTINAS,
    "prensa":      SEG_PRENSA,
    "estop":       SEG_ESTOP,
}
SEG_ORDER = ("despachando", "idle", "cortinas", "prensa", "estop")

# ─── Font Loader ───────────────────────────────────────────────────────────────
import threading
import time as _time

_FONT_CACHE = {}
_FONTS_DIR  = os.path.join(os.path.dirname(__file__), "_render_fonts")
_FONT_DL_FAILED = set()

_FONT_URLS = {
    "Jost-Regular.ttf":   "https://cdn.jsdelivr.net/fontsource/fonts/jost@latest/latin-400-normal.ttf",
    "Jost-Medium.ttf":    "https://cdn.jsdelivr.net/fontsource/fonts/jost@latest/latin-500-normal.ttf",
    "Jost-SemiBold.ttf":  "https://cdn.jsdelivr.net/fontsource/fonts/jost@latest/latin-600-normal.ttf",
    "Jost-Bold.ttf":      "https://cdn.jsdelivr.net/fontsource/fonts/jost@latest/latin-700-normal.ttf",
    "Jost-ExtraBold.ttf": "https://cdn.jsdelivr.net/fontsource/fonts/jost@latest/latin-800-normal.ttf",
    "Anton-Regular.ttf":  "https://cdn.jsdelivr.net/fontsource/fonts/anton@latest/latin-400-normal.ttf",
    "RobotoMono-Regular.ttf": "https://cdn.jsdelivr.net/fontsource/fonts/roboto-mono@latest/latin-400-normal.ttf",
    "RobotoMono-Bold.ttf":    "https://cdn.jsdelivr.net/fontsource/fonts/roboto-mono@latest/latin-700-normal.ttf",
}

def _download_font(name, url):
    import requests as _req
    r = _req.get(url, timeout=8)
    r.raise_for_status()
    with open(os.path.join(_FONTS_DIR, name), "wb") as f:
        f.write(r.content)

def _ensure_fonts():
    """Descarga fuentes Goodyear (Jost, Anton, Roboto Mono) si no existen.
    La descarga esta acotada (no bloquea el render si no hay red) y los
    fallos se cachean para no reintentarlo en cada renderizado."""
    missing = [n for n in _FONT_URLS
               if n not in _FONT_DL_FAILED
               and not os.path.exists(os.path.join(_FONTS_DIR, n))]
    if not missing:
        return
    os.makedirs(_FONTS_DIR, exist_ok=True)
    deadline = _time.monotonic() + 15
    for name in missing:
        url = _FONT_URLS[name]
        if _time.monotonic() >= deadline:
            _FONT_DL_FAILED.update(missing)
            break
        t = threading.Thread(target=_download_font, args=(name, url), daemon=True)
        t.start()
        t.join(5)
        if t.is_alive() or not os.path.exists(os.path.join(_FONTS_DIR, name)):
            _FONT_DL_FAILED.add(name)

def _load_font(name, size):
    key = (name, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    try:
        path = os.path.join(_FONTS_DIR, name)
        if not os.path.exists(path):
            _ensure_fonts()
        fnt = ImageFont.truetype(path, size)
    except Exception:
        fnt = ImageFont.load_default()
    _FONT_CACHE[key] = fnt
    return fnt

def font_jost(size, weight="Bold"):
    mapping = {
        "Bold":      "Jost-Bold.ttf",
        "ExtraBold": "Jost-ExtraBold.ttf",
        "SemiBold":  "Jost-SemiBold.ttf",
        "Medium":    "Jost-Medium.ttf",
        "Regular":   "Jost-Regular.ttf",
    }
    return _load_font(mapping.get(weight, "Jost-Bold.ttf"), size)

def font_anton(size):
    return _load_font("Anton-Regular.ttf", size)

def font_mono(size, bold=True):
    name = "RobotoMono-Bold.ttf" if bold else "RobotoMono-Regular.ttf"
    return _load_font(name, size)

# ─── Drawing Helpers ───────────────────────────────────────────────────────────
SCALE = 2

def _hex(c):
    return tuple(int(c[i:i+2], 16) for i in (1, 3, 5))

class _Scaled:
    """Dibuja en coordenadas lógicas sobre un lienzo a SCALE para render 2x."""

    def __init__(self, raw, scale):
        self._raw = raw
        self._s = scale

    def _xy(self, xy):
        s = self._s
        return (int(round(xy[0] * s)), int(round(xy[1] * s)))

    def _box(self, box):
        s = self._s
        return tuple(int(round(v * s)) for v in box)

    def _w(self, kw):
        if "width" in kw:
            kw["width"] = max(1, int(round(kw["width"] * self._s)))
        return kw

    def rect(self, box, **kw):
        self._raw.rectangle(self._box(box), **self._w(kw))

    def rounded_rectangle(self, box, radius=6, **kw):
        self._raw.rounded_rectangle(
            self._box(box), radius=int(round(radius * self._s)), **self._w(kw))

    def ellipse(self, box, **kw):
        self._raw.ellipse(self._box(box), **self._w(kw))

    def line(self, box, **kw):
        self._raw.line(self._box(box), **self._w(kw))

    def text(self, xy, text, font=None, **kw):
        self._raw.text(self._xy(xy), text, font=font, **kw)

    def measure(self, text, font):
        bb = self._raw.textbbox((0, 0), text, font=font)
        return (bb[2] - bb[0]) / self._s, (bb[3] - bb[1]) / self._s

def _clip_text(d, text, font, max_w, ell="..."):
    """Trunca text para que quepa en max_w px lógicos (sin cortar a mitad por glyph)."""
    text = (text or "").strip()
    if not text or d.measure(text, font)[0] <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if d.measure(text[:mid], font)[0] <= max_w - d.measure(ell, font)[0]:
            lo = mid
        else:
            hi = mid - 1
    clipped = text[:lo].rstrip()
    return (clipped + ell) if clipped else ell

def _wrap_lines(d, text, font, max_w, max_lines=2):
    """Envuelve text a max_w px lógicos y limita a max_lines; marca la continuacion."""
    text = (text or "").strip().replace("\r", " ").replace("\n", " ")
    if not text:
        return []
    if d.measure(text, font)[0] <= max_w:
        return [text]
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if d.measure(trial, font)[0] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            while word and d.measure(word, font)[0] > max_w:
                word = word[:-1]
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    lines[-1] = _clip_text(d, lines[-1], font, max_w)
    return lines

def _status_color(pct):
    return OK_COLOR if pct >= 98 else (WARN_COLOR if pct >= 95 else BAD_COLOR)

def _draw_bar(img, x, y, w, h, segments, radius=3):
    """Barra segmentada: los segmentos suman el 100% del ancho y los extremos
    respetan el radio sin dejar huecos blancos entre segmentos."""
    s = SCALE
    total = sum(p for p, _ in segments) or 1.0
    if total <= 0:
        return
    wd = max(2, int(round(w * s)))
    hd = max(2, int(round(h * s)))
    layer = Image.new("RGBA", (wd, hd), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    start = 0.0
    for pct, color in segments:
        pct = float(pct)
        if pct <= 0:
            continue
        end = start + (pct / total) * wd
        left = int(start)
        right = min(wd, max(int(math.ceil(end)), left + 1))
        ld.rectangle((left, 0, right, hd), fill=_hex(color))
        start = end
    mask = Image.new("L", (wd, hd), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, wd - 1, hd - 1), radius=int(round(radius * s)), fill=255)
    layer.putalpha(mask)
    img.alpha_composite(layer, (int(round(x * s)), int(round(y * s))))

# ─── Main Renderer ─────────────────────────────────────────────────────────────

# Layout (unidades logicas; se renderiza a SCALE)
PAGE_W      = 1180
MARGIN      = 24
HEADER_H    = 84
GOLD_BORDER_H = 5
BODY_PAD    = 22
COL_GAP     = 16
SEC_GAP     = 20
COL_HEADER_H = 40
MAX_ORDER_ROWS = 8

def render_entrega_turno(data, output_path=None):
    """
    Renderiza el reporte de entrega de turno como imagen PNG.

    data: dict con la misma estructura que devuelve /api/consolidado-turno
    output_path: ruta del archivo PNG (opcional, retorna bytes si es None)

    Returns: bytes de la imagen PNG
    """
    _ensure_fonts()
    s = SCALE

    def fj(size, weight="Bold"):
        return font_jost(int(round(size * s)), weight)

    def fm(size, bold=True):
        return font_mono(int(round(size * s)), bold)

    def fa(size):
        return font_anton(int(round(size * s)))

    consult     = data.get("consulta", {})
    io_data     = data.get("input_output", {})
    crane_data  = data.get("crane_performance", {})
    press_data  = data.get("press_delivery", {})
    orders      = data.get("ordenes", []) or []

    shift_code  = consult.get("turno") or "T2"
    shift_name  = consult.get("turno_nombre", "") or shift_code
    fecha       = consult.get("fecha", "")
    rango       = consult.get("rango_horas", "")

    presses     = press_data.get("resumen_prensas", []) or _default_presses()
    top_cranes  = crane_data.get("top_downtime", [])[:3]
    n_crane     = max(1, min(3, len(top_cranes)))

    # ── ALTURAS DERIVADAS ──────────────────────────────────────────────────────
    sub_h = 60
    sub_gap = 10
    panel_h = 66
    efi_h = 96
    c1_h = 12 + 2 * sub_h + sub_gap + panel_h + 12 + efi_h + 10

    avail_h = 52
    title_h = 14
    row_dt_h = 40
    row_dt_gap = 10
    pasillos = crane_data.get("pasillos", []) or []
    minors = [p for p in pasillos if 0 < (p.get("downtime_minutes") or 0) <= 10]
    minors = sorted(minors, key=lambda p: p.get("downtime_minutes", 0), reverse=True)[:3]
    c2_h = (12 + avail_h + 12 + title_h + 10
            + n_crane * row_dt_h + (n_crane - 1) * row_dt_gap
            + 12 + title_h + 10
            + max(1, len(minors)) * row_dt_h
            + max(0, min(3, len(minors)) - 1) * row_dt_gap)

    legend_h = 16
    press_card_h = 74
    press_card_gap = 12
    n_press = len(presses)
    c3_h = (12 + legend_h + 12 + n_press * press_card_h
            + (n_press - 1) * press_card_gap)

    col_cards = [COL_HEADER_H + c1_h, COL_HEADER_H + c2_h, COL_HEADER_H + c3_h]
    max_col_card = max(col_cards)

    rows_shown = min(len(orders), MAX_ORDER_ROWS)
    hdr_orders = 36
    tbl_hdr = 26
    order_row_h = 48
    foot_h = 26 if len(orders) > rows_shown else 0
    empty_row_h = order_row_h if not orders else 0
    orders_h = hdr_orders + 8 + tbl_hdr + rows_shown * order_row_h + foot_h + empty_row_h + 8

    body_y = HEADER_H + GOLD_BORDER_H + 12
    body_h = BODY_PAD + max_col_card + SEC_GAP + orders_h + BODY_PAD
    page_h = body_y + body_h + 14

    img = Image.new("RGBA", (int(PAGE_W * s), int(page_h * s)), (0, 0, 0, 0))
    raw = ImageDraw.Draw(img)
    d = _Scaled(raw, s)
    d.rect((0, 0, PAGE_W, page_h), fill=_hex(PAGE_BG))

    # ── HEADER BANNER ──────────────────────────────────────────────────────────
    d.rect((0, 0, PAGE_W, HEADER_H), fill=_hex(NAVY))
    d.rect((0, HEADER_H, PAGE_W, HEADER_H + GOLD_BORDER_H), fill=_hex(GOLD))

    hcx = HEADER_H / 2
    logo_r = 23
    lx = MARGIN
    ly = hcx - logo_r
    d.ellipse((lx, ly, lx + 2 * logo_r, ly + 2 * logo_r), fill=_hex(GOLD))
    d.text((lx + logo_r, hcx), "GY", fill=_hex(NAVY), font=fa(20), anchor="mm")

    tx0 = lx + 2 * logo_r + 16
    title_font = fa(30)
    if "Anton" not in getattr(title_font, "path", ""):
        title_font = fj(26, "ExtraBold")
    d.text((tx0, hcx - 12), "ENTREGA DE TURNO - ASRS", fill=_hex(WHITE),
           font=title_font, anchor="lm")
    sub_text = "  |  ".join(x for x in (shift_name, fecha, rango) if x)
    d.text((tx0, hcx + 15), sub_text, fill=_hex(ON_NAVY_MUTED),
           font=fj(11.5, "Medium"), anchor="lm")

    chip_h = 34
    date_text = f"{fecha} ({rango})".strip()
    df = fm(11.5)
    sf = fm(14)
    tf = fm(11.5)
    dw = d.measure(date_text, df)[0] + 24
    sw = d.measure(shift_code, sf)[0] + 24
    
    date_x1 = PAGE_W - MARGIN
    date_x0 = date_x1 - dw
    d.rounded_rectangle((date_x0, hcx - chip_h / 2, date_x1, hcx + chip_h / 2),
                        radius=6, fill=_hex(ACCENT), width=1)
    d.text((date_x0 + dw / 2, hcx), date_text, fill=_hex(ON_NAVY_BRIGHT),
           font=df, anchor="mm")
           
    gold_x1 = date_x0 - 8
    gold_x0 = gold_x1 - sw
    d.rounded_rectangle((gold_x0, hcx - chip_h / 2, gold_x1, hcx + chip_h / 2),
                        radius=6, fill=_hex(GOLD))
    d.text((gold_x0 + sw / 2, hcx), shift_code, fill=_hex(DARK_NAVY),
           font=sf, anchor="mm")

    ticket_val = str(consulta.get("ticket") or data.get("ticket") or "").strip()
    if ticket_val:
        ticket_text = f"Ticket: {ticket_val}" if "tires" in ticket_val.lower() else f"Ticket: {ticket_val} tires"
        tw = d.measure(ticket_text, tf)[0] + 22
        tkt_x1 = gold_x0 - 8
        tkt_x0 = tkt_x1 - tw
        d.rounded_rectangle((tkt_x0, hcx - chip_h / 2, tkt_x1, hcx + chip_h / 2),
                            radius=6, fill=_hex(ACCENT), width=1)
        d.text((tkt_x0 + tw / 2, hcx), ticket_text, fill=_hex(GOLD),
               font=tf, anchor="mm")

    # ── BODY ───────────────────────────────────────────────────────────────────
    d.rounded_rectangle((MARGIN, body_y, PAGE_W - MARGIN, body_y + body_h),
                        radius=12, fill=_hex(CARD_BG), outline=_hex(BORDER), width=1)

    inner_x = MARGIN + BODY_PAD
    inner_w = PAGE_W - 2 * (MARGIN + BODY_PAD)
    base_w = (inner_w - 2 * COL_GAP) // 3
    col_ws = [base_w, base_w, base_w + (inner_w - 2 * COL_GAP) % 3]
    col_xs = []
    acc = inner_x
    for cw in col_ws:
        col_xs.append(acc)
        acc += cw + COL_GAP

    cols_top = body_y + BODY_PAD

    def section_header(x, y, w, icon, title, badge=None, badge_fill=ACCENT,
                       badge_fill_text=WHITE, card_h=None):
        if card_h is not None:
            d.rounded_rectangle((x, y, x + w, y + card_h), radius=10,
                                fill=_hex(CARD_BG), outline=_hex(BORDER), width=1)
        hdr = COL_HEADER_H
        d.rounded_rectangle((x, y, x + w, y + hdr), radius=10, fill=_hex(NAVY))
        d.rect((x, y + hdr - 10, x + 10, y + hdr), fill=_hex(NAVY))
        d.rect((x + w - 10, y + hdr - 10, x + w, y + hdr), fill=_hex(NAVY))
        d.line((x + 12, y + hdr - 3, x + w - 12, y + hdr - 3), fill=_hex(GOLD), width=3)
        ic_r = 13
        ic_cx = x + 10 + ic_r
        ic_cy = y + hdr / 2
        d.ellipse((ic_cx - ic_r, ic_cy - ic_r, ic_cx + ic_r, ic_cy + ic_r), fill=_hex(GOLD))
        d.text((ic_cx, ic_cy), icon, fill=_hex(DARK_NAVY), font=fj(12, "Bold"), anchor="mm")
        tf = fj(13, "ExtraBold")
        title = title.upper()
        if badge:
            bf = fm(11)
            bw = d.measure(badge, bf)[0] + 22
            bx = x + w - bw - 10
            by = y + (hdr - 24) / 2
            d.rounded_rectangle((bx, by, bx + bw, by + 24), radius=5, fill=_hex(badge_fill))
            d.text((bx + bw / 2, by + 12), badge, fill=_hex(badge_fill_text), font=bf, anchor="mm")
            title_max = bx - ic_cx - ic_r - 18
        else:
            title_max = x + w - ic_cx - ic_r - 22
        d.text((ic_cx + ic_r + 8, y + hdr / 2),
               _clip_text(d, title, tf, title_max), fill=_hex(WHITE), font=tf, anchor="lm")
        return y + hdr + 12

    # ── COL 1: FLUJO / INPUT & OUTPUT ─────────────────────────────────────────
    cx = col_xs[0]
    cw = col_ws[0]
    cy = section_header(cx, cols_top, cw, "IO", "Flujo / Input & Output",
                        badge=f"EFIC {io_data.get('eficiencia_entrada', '-')}%",
                        card_h=col_cards[0])
    sub_w = (cw - sub_gap) / 2

    def subcard(sx, sy, sw, sh, label, value, note, accent):
        d.rounded_rectangle((sx, sy, sx + sw, sy + sh), radius=8,
                            fill=_hex(FIELD), outline=_hex(BORDER), width=1)
        d.rect((sx + 3, sy + 10, sx + 6, sy + sh - 10), fill=_hex(accent))
        d.text((sx + 14, sy + 8), label.upper(), fill=_hex(TEXT_MUTED), font=fj(9.5, "Bold"))
        d.text((sx + 14, sy + 24), str(value), fill=_hex(DARK_NAVY), font=fm(19))
        if note:
            d.text((sx + 14, sy + 46), note, fill=_hex(TEXT_MUTED), font=fj(9.5, "Medium"))

    subcard(cx, cy, sub_w, sub_h, "Construido", io_data.get("construido", "-"), "tires", NAVY)
    subcard(cx + sub_w + sub_gap, cy, sub_w, sub_h, "Vulcanizado",
            io_data.get("vulcanizado", "-"), "tires", GOLD_DARK)
    cy += sub_h + sub_gap
    subcard(cx, cy, sub_w, sub_h, "Entrada ASRS", io_data.get("entrada_asrs", "-"),
            f"Rate: {io_data.get('rate_entrada', '-')} t/m", SEG_DESPACHO)
    subcard(cx + sub_w + sub_gap, cy, sub_w, sub_h, "Total Salida",
            io_data.get("total_salida", "-"),
            f"Rate: {io_data.get('rate_salida', '-')} t/m", WARN_COLOR)
    cy += sub_h + sub_gap

    d.rounded_rectangle((cx, cy, cx + cw, cy + panel_h), radius=8,
                        fill=_hex(FIELD), outline=_hex(BORDER), width=1)
    half = cw / 2
    d.line((cx + half, cy + 10, cx + half, cy + panel_h - 10), fill=_hex(LINE), width=1)
    d.text((cx + 14, cy + 8), "MANUAL", fill=_hex(TEXT_MUTED), font=fj(9.5, "Bold"))
    d.text((cx + 14, cy + 26), f"{io_data.get('salida_manual', '-')} tires",
           fill=_hex(WARN_COLOR), font=fm(16))
    d.text((cx + 14, cy + 48), f"Rate: {io_data.get('rate_manual', '-')}",
           fill=_hex(TEXT_MUTED), font=fj(9.5, "Medium"))
    d.text((cx + half + 12, cy + 8), "AUTOMATICO", fill=_hex(TEXT_MUTED), font=fj(9.5, "Bold"))
    d.text((cx + half + 12, cy + 26), f"{io_data.get('salida_auto', '-')} tires",
           fill=_hex(OK_COLOR), font=fm(16))
    d.text((cx + half + 12, cy + 48), f"Rate: {io_data.get('rate_auto', '-')}",
           fill=_hex(TEXT_MUTED), font=fj(9.5, "Medium"))
    cy += panel_h + 12

    # ── medidor: EFICIENCIA DE ENTRADA ────────────────────────────────────────
    eff = io_data.get("eficiencia_entrada", 0)
    try:
        eff = float(str(eff).replace(",", ".").replace("%", ""))
    except (TypeError, ValueError):
        eff = 0
    eff_obj = 95.0
    frac = min(1.0, max(0.0, eff / 100.0))
    eff_col = OK_COLOR if eff >= eff_obj else (WARN_COLOR if eff >= 90 else BAD_COLOR)

    d.rounded_rectangle((cx, cy, cx + cw, cy + efi_h), radius=8,
                        fill=_hex(NAVY))
    d.text((cx + 14, cy + 9), "EFICIENCIA DE ENTRADA", fill=_hex(ON_NAVY_MUTED),
           font=fj(9.5, "Bold"))
    d.text((cx + cw - 14, cy + 6), f"OBJ {eff_obj:.0f}%", fill=_hex(ON_NAVY_MUTED),
           font=fj(9.5, "Bold"), anchor="ra")
    d.text((cx + cw - 14, cy + 18), f"{eff:.1f}%", fill=_hex(eff_col),
           font=fm(24), anchor="ra")
    bar_x, bar_y = cx + 14, cy + 56
    bar_w = cw - 28
    d.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 8),
                        radius=4, fill=_hex("#1E3A6E"))
    mark_x = bar_x + bar_w * (eff_obj / 100.0)
    d.line((mark_x, bar_y - 3, mark_x, bar_y + 11), fill=_hex(WHITE), width=2)
    if frac > 0:
        d.rounded_rectangle((bar_x, bar_y, bar_x + bar_w * frac, bar_y + 8),
                            radius=4, fill=_hex(eff_col))
    cy += efi_h + 10

    # ── COL 2: CRANE PERFORMANCE ──────────────────────────────────────────────
    cx = col_xs[1]
    cw = col_ws[1]
    disp = crane_data.get("disponibilidad_pct", 100.0)
    cy = section_header(cx, cols_top, cw, "C", "Crane Performance",
                        badge=f"DISP {disp}%", card_h=col_cards[1])

    d.rounded_rectangle((cx, cy, cx + cw, cy + avail_h), radius=8, fill=_hex(NAVY))
    d.text((cx + 14, cy + 9), "DISPONIBILIDAD GLOBAL", fill=_hex(ON_NAVY_MUTED),
           font=fj(9.5, "Bold"))
    d.text((cx + 14, cy + 26), "11 Pasillos ASRS", fill=_hex(ON_NAVY_MUTED),
           font=fj(9.5, "Medium"))
    disp_txt = f"{disp}%"
    d.text((cx + cw - 14, cy + 26), disp_txt, fill=_hex(GOLD), font=fm(22), anchor="rm")
    cy += avail_h + 12

    d.text((cx + 10, cy), "TOP 3 PASILLOS CON DOWNTIME", fill=_hex(TEXT_MUTED),
           font=fj(9.5, "Bold"), anchor="lm")
    cy += title_h + 10

    if not top_cranes:
        d.rounded_rectangle((cx, cy, cx + cw, cy + row_dt_h), radius=6,
                            fill=_hex(FIELD), outline=_hex(BORDER), width=1)
        d.text((cx + cw / 2, cy + row_dt_h / 2), "Sin paradas registradas",
               fill=_hex(TEXT_MUTED), font=fj(11, "Medium"), anchor="mm")
        cy += row_dt_h + 12
    else:
        max_dt = max(c.get("downtime_minutes", 1) for c in top_cranes) or 1
        for ci, c in enumerate(top_cranes):
            ry = cy + ci * (row_dt_h + row_dt_gap)
            aisle = c.get("aisle", "?")
            dt_m = c.get("downtime_minutes", 0)
            dt_p = c.get("downtime_percent", 0)
            frac = min(1.0, (dt_m / max_dt)) if max_dt else 0.0
            d.rounded_rectangle((cx, ry, cx + cw, ry + row_dt_h), radius=6,
                                fill=_hex(FIELD), outline=_hex(BORDER), width=1)
            d.text((cx + 12, ry + 7), f"Pasillo {aisle}", fill=_hex(TEXT_DARK),
                   font=fj(12, "Bold"), anchor="lm")
            d.text((cx + cw - 12, ry + 8), f"{dt_m} min ({dt_p}%)", fill=_hex(BAD_COLOR),
                   font=fm(10.5), anchor="rm")
            bar_w = cw - 24
            d.rounded_rectangle((cx + 12, ry + 31, cx + 12 + bar_w, ry + 36),
                                radius=2.5, fill=_hex(GRID))
            if frac > 0:
                d.rounded_rectangle((cx + 12, ry + 31, cx + 12 + bar_w * frac, ry + 36),
                                    radius=2.5, fill=_hex(BAD_COLOR))
        cy = cy + len(top_cranes) * row_dt_h + (len(top_cranes) - 1) * row_dt_gap + 12

    # ── Paradas menors (≤ 10 min) ────────────────────────────────────────────
    pasillos = crane_data.get("pasillos", []) or []
    minors = [p for p in pasillos if 0 < (p.get("downtime_minutes") or 0) <= 10]
    minors = sorted(minors, key=lambda p: p.get("downtime_minutes", 0), reverse=True)[:3]

    d.text((cx + 10, cy), "PARADAS MENORES (≤ 10 MIN)", fill=_hex(TEXT_MUTED),
           font=fj(9.5, "Bold"), anchor="lm")
    cy += title_h + 10
    if minors:
        for ci in range(min(3, len(minors))):
            m = minors[ci]
            my = cy + ci * (row_dt_h + row_dt_gap)
            d.rounded_rectangle((cx, my, cx + cw, my + row_dt_h), radius=6,
                                fill=_hex(FIELD), outline=_hex(BORDER), width=1)
            d.text((cx + 12, my + 7), f"Pasillo {m.get('aisle', '?')}", fill=_hex(TEXT_DARK),
                   font=fj(12, "Bold"), anchor="lm")
            d.text((cx + cw - 12, my + 8),
                   f"{m.get('downtime_minutes', 0)} min ({m.get('downtime_percent', 0)}%)",
                   fill=_hex(WARN_COLOR), font=fm(10.5), anchor="rm")
            dw = cw - 24
            d.rounded_rectangle((cx + 12, my + 31, cx + 12 + dw, my + 36),
                                radius=2.5, fill=_hex(GRID))
        cy += len(minors) * row_dt_h + (len(minors) - 1) * row_dt_gap
    else:
        d.rounded_rectangle((cx, cy, cx + cw, cy + row_dt_h), radius=6,
                            fill=_hex(FIELD), outline=_hex(BORDER), width=1)
        d.text((cx + cw / 2, cy + row_dt_h / 2),
               "Sin paradas menores", fill=_hex(TEXT_MUTED), font=fj(11, "Medium"),
               anchor="mm")
        cy += row_dt_h

    # ── COL 3: PRESS DELIVERY ─────────────────────────────────────────────────
    cx = col_xs[2]
    cw = col_ws[2]
    cumple = press_data.get("cumplimiento_global_pct", 0)
    cy = section_header(cx, cols_top, cw, "P", "Press Delivery",
                        badge=f"CUMPL {cumple}%", card_h=col_cards[2])

    lx = cx + 2
    ly = cy + 2
    lf0 = fj(9, "Medium")
    for color, label in SEG_COLORS:
        d.rounded_rectangle((lx, ly, lx + 10, ly + 10), radius=3, fill=_hex(color))
        d.text((lx + 14, ly + 5), label, fill=_hex(TEXT_DARK), font=lf0, anchor="lm")
        lx += 14 + d.measure(label, lf0)[0] + 14
    cy += legend_h + 12

    for pi, p in enumerate(presses):
        py = cy + pi * (press_card_h + press_card_gap)
        t = p.get("times", {}) or {}
        total_t = sum(t.get(k, 0) for k in SEG_ORDER) or 1
        p_pct = p.get("pct", 0)
        segs = [(t.get(k, 0) / total_t * 100.0, SEG_MAP[k]) for k in SEG_ORDER]

        d.rounded_rectangle((cx, py, cx + cw, py + press_card_h), radius=8,
                            fill=_hex(FIELD), outline=_hex(BORDER), width=1)
        d.text((cx + 12, py + 10), str(p.get("press", "?")), fill=_hex(TEXT_DARK),
               font=fj(12.5, "Bold"), anchor="lm")
        d.text((cx + cw - 12, py + 10), f"{p_pct}%", fill=_hex(_status_color(p_pct)),
               font=fm(12), anchor="rm")
        _draw_bar(img, cx + 12, py + 28, cw - 24, 9, segs, radius=3)
        my = py + 48
        third = cw / 3
        for cx3, label, val in [
            (cx + third * 0.5, "Robot", p.get("delivered_robot", 0)),
            (cx + third * 1.5, "Manual", p.get("manual", 0)),
            (cx + third * 2.5, "Total", p.get("vulcanized", 0)),
        ]:
            d.text((cx3, my), f"{label} {val}", fill=_hex(TEXT_MUTED),
                   font=fj(9.5, "Medium"), anchor="mm")

    # ── ORDERS TABLE ──────────────────────────────────────────────────────────
    ox = inner_x
    ow = inner_w
    oy = cols_top + max_col_card + SEC_GAP

    d.rounded_rectangle((ox, oy, ox + ow, oy + hdr_orders), radius=8, fill=_hex(NAVY))
    d.line((ox + 12, oy + hdr_orders - 3, ox + ow - 12, oy + hdr_orders - 3),
           fill=_hex(GOLD), width=3)
    d.text((ox + 14, oy + hdr_orders / 2), "NOVEDADES Y ORDENES CORRECTIVAS DEL TURNO",
           fill=_hex(WHITE), font=fj(13, "ExtraBold"), anchor="lm")
    if len(orders) == 1:
        count_text = "1 ORDEN"
    elif orders:
        count_text = f"{len(orders)} ORDENES"
    else:
        count_text = "SIN ORDENES"
    cbf = fm(10.5)
    cbw = d.measure(count_text, cbf)[0] + 22
    cbx = ox + ow - cbw - 10
    d.rounded_rectangle((cbx, oy + 7, cbx + cbw, oy + 27), radius=5, fill=_hex(ACCENT))
    d.text((cbx + cbw / 2, oy + 17), count_text, fill=_hex(WHITE), font=cbf, anchor="mm")

    ty = oy + hdr_orders + 8
    d.rect((ox, ty, ox + ow, ty + tbl_hdr), fill=_hex(FIELD))
    d.line((ox, ty + tbl_hdr, ox + ow, ty + tbl_hdr), fill=_hex(GRID), width=1)

    col_defs = [
        ("N° OT", 64),
        ("HORA", 62),
        ("EQUIPO", 150),
        ("TITULO", 170),
        ("TP", 58),
        ("DETALLE", ow - (64 + 62 + 150 + 170 + 58) - 24),
    ]
    hf0 = fj(9.5, "Bold")
    hx = ox + 12
    for label, width in col_defs:
        d.text((hx, ty + tbl_hdr / 2), label, fill=_hex(TEXT_MUTED), font=hf0, anchor="lm")
        hx += width

    if not orders:
        d.text((ox + ow / 2, ty + tbl_hdr + empty_row_h / 2),
               "Sin eventos correctivos reportados en este turno",
               fill=_hex(TEXT_MUTED), font=fj(11, "Medium"), anchor="mm")
    else:
        ry = ty + tbl_hdr + 2
        for oi in range(rows_shown):
            o = orders[oi]
            d.rect((ox, ry, ox + ow, ry + order_row_h),
                   fill=_hex(WHITE if oi % 2 == 0 else FIELD))
            cxr = ox + 12
            ot_txt = str(o.get("ot", ""))
            chip_h2 = 26
            d.rounded_rectangle((cxr, ry + (order_row_h - chip_h2) / 2,
                                 cxr + 58, ry + (order_row_h + chip_h2) / 2),
                                radius=5, fill=_hex(ACCENT))
            d.text((cxr + 29, ry + order_row_h / 2),
                   _clip_text(d, ot_txt, fm(10.5), 52), fill=_hex(WHITE),
                   font=fm(10.5), anchor="mm")
            cxr += col_defs[0][1]
            d.text((cxr, ry + order_row_h / 2), str(o.get("hora", "")),
                   fill=_hex(TEXT_DARK), font=fm(11), anchor="lm")
            cxr += col_defs[1][1]
            maquina = str(o.get("maquina", "") or o.get("equipo", "")).strip()
            equipo = str(o.get("equipo", "")).strip()
            d.text((cxr, ry + 7), _clip_text(d, maquina, fj(11, "Bold"), col_defs[2][1]),
                   fill=_hex(TEXT_DARK), font=fj(11, "Bold"), anchor="lm")
            if equipo and equipo != maquina:
                d.text((cxr, ry + 25),
                       _clip_text(d, equipo, fj(9.5, "Medium"), col_defs[2][1]),
                       fill=_hex(TEXT_MUTED), font=fj(9.5, "Medium"), anchor="lm")
            cxr += col_defs[2][1]
            d.text((cxr, ry + order_row_h / 2),
                   _clip_text(d, str(o.get("titulo", "")), fj(11, "Bold"), col_defs[3][1]),
                   fill=_hex(TEXT_DARK), font=fj(11, "Bold"), anchor="lm")
            cxr += col_defs[3][1]
            tp_txt = f"{o.get('tp_min', '0')} min"
            d.text((cxr + col_defs[4][1] / 2, ry + order_row_h / 2), tp_txt,
                   fill=_hex(TEXT_DARK), font=fm(10.5), anchor="mm")
            cxr += col_defs[4][1]
            det = str(o.get("detalle", "") or o.get("titulo", ""))
            det_lines = _wrap_lines(d, det, fj(9.5, "Medium"), col_defs[5][1], 2)
            if det_lines:
                if len(det_lines) == 1:
                    d.text((cxr, ry + order_row_h / 2), det_lines[0],
                           fill=_hex(TEXT_MUTED), font=fj(9.5, "Medium"), anchor="lm")
                else:
                    d.text((cxr, ry + 6), det_lines[0], fill=_hex(TEXT_MUTED),
                           font=fj(9.5, "Medium"), anchor="lm")
                    d.text((cxr, ry + 24), det_lines[1], fill=_hex(TEXT_MUTED),
                           font=fj(9.5, "Medium"), anchor="lm")
            d.line((ox, ry + order_row_h - 1, ox + ow, ry + order_row_h - 1),
                   fill=_hex(LINE), width=1)
            ry += order_row_h
        if len(orders) > rows_shown:
            d.rect((ox, ry, ox + ow, ry + foot_h), fill=_hex(FIELD))
            d.text((ox + ow / 2, ry + foot_h / 2),
                   f"+{len(orders) - rows_shown} ordenes adicionales no mostradas",
                   fill=_hex(TEXT_MUTED), font=fj(9.5, "Medium"), anchor="mm")

    # ── OUTPUT ──────────────────────────────────────────────────────────────────
    out = img.convert("RGB")
    if output_path:
        out.save(output_path, "PNG", optimize=True)
        return None
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _default_presses():
    return [
        {"press": "400B", "pct": 0, "delivered_robot": 0, "manual": 0, "vulcanized": 0, "times": {}},
        {"press": "500A", "pct": 0, "delivered_robot": 0, "manual": 0, "vulcanized": 0, "times": {}},
        {"press": "500B", "pct": 0, "delivered_robot": 0, "manual": 0, "vulcanized": 0, "times": {}},
        {"press": "600A", "pct": 0, "delivered_robot": 0, "manual": 0, "vulcanized": 0, "times": {}},
        {"press": "600B", "pct": 0, "delivered_robot": 0, "manual": 0, "vulcanized": 0, "times": {}},
    ]


# ─── CLI Test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    import sys
    import requests
    from datetime import datetime, timedelta

    PORT = 8006
    now = datetime.now()
    hour = now.hour
    if 6 <= hour < 14:
        turno, fecha = "T2", now.strftime("%Y-%m-%d")
    elif 14 <= hour < 22:
        turno, fecha = "T3", now.strftime("%Y-%m-%d")
    else:
        turno = "T1"
        fecha = (now - timedelta(days=1)).strftime("%Y-%m-%d") if hour < 6 else now.strftime("%Y-%m-%d")

    url = f"http://127.0.0.1:{PORT}/api/consolidado-turno?fecha={fecha}&turno={turno}"
    print(f"Obteniendo datos: {url}")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error obteniendo datos: {e}")
        sys.exit(1)

    out = r"C:\Users\ac17157\Dashboard-ASRS\captura_pillow_test.png"
    print("Renderizando reporte Pillow...")
    render_entrega_turno(data, output_path=out)
    with Image.open(out) as im:
        print(f"Captura Pillow guardada: {out}  ({im.width}x{im.height}px, {os.path.getsize(out)} bytes)")