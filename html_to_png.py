"""Render the "Entrega de turno ASRS" report as a PNG without a browser.

PyMuPDF (fitz) insert_htmlbox -> PDF page -> pixmap -> PNG.
No external CSS/fonts/JS. MuPDF's HTML engine only supports a small CSS
subset, so all horizontal layout uses tables (no flex/grid/inline-block/float).

CLI:
    python html_to_png.py [--fecha YYYY-MM-DD] [--turno T2] [--json FILE]
                          [--output PATH] [--zoom 1.0] [--api URL] [--check]
"""

import argparse
import datetime as _dt
import json
import os
import sys

import fitz  # PyMuPDF

# ----------------------------- layout constants ----------------------------
PAGE_W = 1180            # points; insert_htmlbox maps 1 CSS px == 1 pt
PAGE_H = 2600
BODY_PAD_X = 20
INNER_W = PAGE_W - 2 * BODY_PAD_X       # 1140
COL_W = (428, 335, 353)                 # widths of the 3 metric cards
GAP = 12

NAVY = '#0B1D45'
GOLD = '#FBBD00'
BORDER = '#E2E8F0'
BG_SOFT = '#F8FAFC'
BG_PAGE = '#FAFAFA'
SLATE = '#334155'
DARK = '#231F20'
GRAY = '#707379'
SLATE_LIGHT = '#94A3B8'

BADGE_T1_BG = '#1E2F53'     # rgba(255,255,255,0.08) premixed over navy
BADGE_T1_BD = '#6B5D29'     # rgba(251,189,0,0.4)  premixed over navy

SEG_SPACES = [('despachando', 'Despacho'), ('idle', 'IDLE'),
              ('cortinas', 'Cortinas'), ('prensa', 'Prensa'), ('estop', 'E-Stop')]
SEG_COLORS = [('despachando', '#22C55E'), ('idle', '#EAB308'),
              ('cortinas', '#38BDF8'), ('prensa', '#C2884D'), ('estop', '#EF4444')]

ST_CARD = ('background:#FFFFFF; border:1px solid #E2E8F0;'
           ' border-top:3px solid #64748B; border-radius:4px; padding:10px 12px;')


# ------------------------------- helpers ------------------------------------
def _esc(v):
    if v is None:
        return ''
    s = str(v)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _mi(x):
    """Thousands separator with dot (es locale): 2723 -> 2.723"""
    if x is None:
        return '0'
    s = str(x).strip()
    try:
        n = int(float(s))
    except ValueError:
        return s
    return f'{n:,}'.replace(',', '.')


def _pct(v, dec=1):
    try:
        return f'{float(v):.{dec}f}'
    except (TypeError, ValueError):
        return str(v or 0)


def _comp_color(pct):
    try:
        p = float(pct)
    except (TypeError, ValueError):
        p = 0.0
    if p >= 98.0:
        return '#15803D'
    if p >= 95.0:
        return '#B45309'
    return '#B91C1C'


def _seg_widths(times, barw):
    denom = sum(times.get(k, 0) for k, _ in SEG_COLORS) or 1
    out = []
    for i, (key, _c) in enumerate(SEG_COLORS):
        w = int(round(times.get(key, 0) / denom * barw))
        if i == len(SEG_COLORS) - 1:
            w = barw - sum(w for _, w in out)
        if w > 0:
            out.append((key, w))
    if not out:
        out.append((None, barw))
    return out


def _seg_legend(times):
    denom = sum(times.get(k, 0) for k, _ in SEG_COLORS) or 1
    items = []
    for key, label in SEG_SPACES:
        m = times.get(key, 0)
        if m > 0:
            items.append('%s %dm (%.1f%%)' % (label, round(m), m / denom * 100))
    return '  |  '.join(items) if items else 'Sin datos de tiempos'


def _cell(w, styles, text=''):
    return '<td style="width:%spx; %s">%s</td>' % (w, styles, text)


def _td(w, styles, text=''):
    return _cell(w, styles, text)


def _spacer(w):
    return '<td style="width:%spx;">&nbsp;</td>' % w


def _spacer_row(cols, h=6):
    return '<tr><td height="%s" colspan="%s">&nbsp;</td></tr>' % (h, cols)


def _kpi_badge(badge):
    return ('<span style="font-family:monospace; font-size:11px; font-weight:700;'
            ' color:#1E293B; background:#F1F5F9; border:1px solid #CBD5E1;'
            ' border-radius:3px; padding:2px 8px;">%s</span>' % _esc(badge))


def _card_header(title, badge, cw):
    left = _td(cw - 100, 'font-size:13px; font-weight:800;'
                          ' text-transform:uppercase; color:#231F20;'
                          ' padding:0 0 8px 0;', _esc(title))
    right = _td(100, 'text-align:right; white-space:nowrap;',
                _kpi_badge(badge))
    return _tbl([left, right], cw)


def _open(cells, w):
    return '<tr>' + ''.join(cells) + '</tr>'


def _tbl(cells, w):
    return ('<table style="width:%spx;" cellspacing="0" cellpadding="0">' % w
            + '<tr>' + ''.join(cells) + '</tr></table>')


def _tbl_rows(rows, w):
    return ('<table style="width:%spx;" cellspacing="0" cellpadding="0">' % w
            + ''.join(rows) + '</table>')


# ---------------------------- report builders -------------------------------
def build_header(c, ts):
    turno_nombre = _esc(c.get('turno_nombre', 'Turno'))
    fecha = _esc(c.get('fecha', ''))
    rango = _esc(c.get('rango_horas', ''))
    time_txt = '%s (%s)' % (fecha, rango) if fecha else rango

    badge1 = 'background:%s; color:%s; border:1px solid %s; border-radius:4px;' \
             ' font-size:13.5px; font-weight:800; padding:9px 16px;' \
             ' white-space:nowrap;' % (BADGE_T1_BG, GOLD, BADGE_T1_BD)
    badge2 = 'background:#FFFFFF; color:#0B1D45; border:1px solid #CBD5E1;' \
             ' border-radius:4px; font-family:monospace; font-size:13.5px;' \
             ' font-weight:700; padding:9px 16px; white-space:nowrap;'

    left = _td(PAGE_W - 520, '',
               '<div style="padding:12px 24px;">'
               '<div style="font-size:24px; font-weight:800; line-height:26px;">'
               'ENTREGA DE TURNO - ASRS</div>'
               '<div style="font-size:11px; color:%s; margin-top:3px;">'
               'Consolidado autom&aacute;tico de turno &middot; Generado %s</div>'
               '</div>'
               % (SLATE_LIGHT, ts))
    right = _td(520, 'text-align:right;',
                '<div style="padding:12px 24px;">%s</div>'
                % _tbl([_td(250, badge1, turno_nombre), _spacer(6),
                        _td(0, badge2, time_txt)], 470))

    return ('<div style="width:%spx; background:%s; color:#FFFFFF;'
            ' border-bottom:8px solid %s;">' % (PAGE_W, NAVY, GOLD)
            + _tbl([left, right], PAGE_W) + '</div>')


def _subcard(label, val, sub, color_left, cw):
    st_box = ('background:%s; border:1px solid #E2E8F0;'
              ' border-left:3px solid %s; border-radius:4px;'
              ' padding:6px 10px;' % (BG_SOFT, color_left))
    body = ('<div style="%s">'
            '<div style="font-size:10.5px; font-weight:800; color:#64748B;'
            ' text-transform:uppercase;">%s</div>'
            '<div style="font-family:monospace; font-size:22px; font-weight:800;'
            ' color:%s; line-height:24px;">%s</div>'
            '<div style="font-size:11px; color:#707379; font-weight:600;">%s</div>'
            '</div>'
            % (st_box, _esc(label), NAVY, _esc(val), _esc(sub)))
    return _td(cw, '', body)


def build_flow_card(io, cw):
    icw = cw - 24
    half = (icw - 6) // 2
    grid = _tbl_rows(
        [_open([_subcard('Construido', _mi(io.get('construido')), 'tires',
                         '#64748B', half), _spacer(6),
                _subcard('Vulcanizado', _mi(io.get('vulcanizado')), 'tires',
                         '#64748B', half)], icw),
         _spacer_row(3, 6),
         _open([_subcard('Entrada ASRS', _mi(io.get('entrada_asrs')),
                         'Rate: %s t/m' % io.get('rate_entrada', '-'),
                         '#15803D', half), _spacer(6),
                _subcard('Total Salida', _mi(io.get('total_salida')),
                         'Rate: %s t/m' % io.get('rate_salida', '-'),
                         '#B45309', half)], icw)], icw)

    st_split = 'background:%s; border:1px solid #E2E8F0;' \
               ' border-radius:4px; padding:6px 10px;' % BG_SOFT
    man = ('<div style="%s"><div style="font-size:10.5px; font-weight:800;'
           ' color:#64748B; text-transform:uppercase;">Manual</div>'
           '<div style="font-family:monospace; font-size:14px; font-weight:800;'
           ' color:#B45309;">%s</div>'
           '<div style="font-size:10.5px; color:#707379;">Rate: <b>%s</b></div></div>'
           % (st_split, _mi(io.get('salida_manual')), io.get('rate_manual', '-')))
    auto = ('<div style="%s"><div style="font-size:10.5px; font-weight:800;'
            ' color:#64748B; text-transform:uppercase;">Autom&aacute;tico</div>'
            '<div style="font-family:monospace; font-size:14px; font-weight:800;'
            ' color:#15803D;">%s</div>'
            '<div style="font-size:10.5px; color:#707379;">Rate: <b>%s</b></div></div>'
            % (st_split, _mi(io.get('salida_auto')), io.get('rate_auto', '-')))
    split = _tbl([_td(half, '', man), _spacer(6), _td(half, '', auto)], icw)

    efic = 'Efic: %s%%' % io.get('eficiencia_entrada', 0)
    return ('<div style="%s">%s<div style="height:6px;"></div>%s'
            '<div style="height:6px;"></div>%s</div>'
            % (ST_CARD, _card_header('Flujo / Input &amp; Output', efic, icw),
               grid, split))


def build_crane_card(cr, cw):
    icw = cw - 24
    disp = cr.get('disponibilidad_pct', '0')
    npas = len(cr.get('pasillos') or []) or '-'

    avail = ('<div style="background:%s; border-radius:4px; padding:8px 12px;">'
             % NAVY
             + _tbl([_td(0, 'font-size:10px; color:#D2D2D2; font-weight:800;'
                           ' text-transform:uppercase;',
                         'Disponibilidad Global<br/>'
                         '<span style="font-size:11px; color:#CBD5E1;">'
                         '%s Pasillos ASRS</span>' % npas),
                     _td(0, 'text-align:right; font-family:monospace;'
                            ' font-size:22px; font-weight:800; color:%s;' % GOLD,
                         '%s%%' % _esc(disp))], icw - 24)
             + '</div>')

    rows = []
    items = (cr.get('top_downtime') or [])[:3]
    st_row = ('background:%s; border:1px solid #E2E8F0; border-radius:4px;'
              ' padding:7px 12px;' % BG_SOFT)
    inner = icw - 26
    for i, it in enumerate(items):
        dtxt = '%s min (%s%%)' % (it.get('downtime_minutes'),
                                  it.get('downtime_percent'))
        dt_w = inner - 114
        rowdiv = ('<div style="%s">'
                  '<table style="width:%spx;" cellspacing="0" cellpadding="0"><tr>'
                  '<td style="width:110px; font-size:13.5px; font-weight:700;'
                  ' color:#334155;">Pasillo %s</td>'
                  '<td style="width:4px;">&nbsp;</td>'
                  '<td style="width:%spx; text-align:right; font-family:monospace;'
                  ' font-size:12.5px; font-weight:700; color:#B91C1C;">%s</td>'
                  '</tr></table></div>'
                  % (st_row, inner, _esc(it.get('aisle')), dt_w, _esc(dtxt)))
        rows.append(rowdiv)
        if i < len(items) - 1:
            rows.append('<div style="height:6px;"></div>')
    if not rows:
        rows.append('<div style="padding:10px; text-align:center;'
                    ' font-size:12px; color:#707379;">Sin paradas registradas</div>')

    lst = ''.join(rows)
    label = ('<div style="font-size:11px; font-weight:800; color:#64748B;'
             ' text-transform:uppercase;">Top pasillos con downtime</div>')
    bd = 'Disp: %s%%' % disp
    return ('<div style="%s">%s<div style="height:6px;"></div>%s'
            '<div style="height:8px;"></div>%s<div style="height:4px;"></div>%s</div>'
            % (ST_CARD, _card_header('Crane Performance', bd, icw),
               avail, label, lst))


def build_press_card(pr, cw):
    presses = pr.get('resumen_prensas') or []
    cumpl = pr.get('cumplimiento_global_pct') or 0
    barw = cw - 44
    hw = barw // 2

    items = []
    for p in presses:
        times = p.get('times') or {}
        segs = _seg_widths(times, barw)
        seg_td = []
        for key, w in segs:
            col = (next((c for k, c in SEG_COLORS if k == key), '#E2E8F0')
                   if key else '#E2E8F0')
            seg_td.append('<td style="width:%spx; background:%s; height:8px;">'
                          '&nbsp;</td>' % (w, col))
        rem = barw - sum(w for _, w in segs)
        if rem > 0:
            seg_td.append('<td style="width:%spx; background:#E2E8F0;'
                          ' height:8px;">&nbsp;</td>' % rem)
        meta = ('Robot: <b>%s</b> &nbsp;Manual: <b>%s</b>'
                ' &nbsp;Total: <b>%s</b>'
                % (_mi(p.get('delivered_robot')), _mi(p.get('manual')),
                   _mi(p.get('vulcanized'))))
        item = ('<div style="background:%s; border:1px solid #E2E8F0;'
                ' border-radius:4px; padding:6px 10px;">' % BG_SOFT
                + _tbl([_td(hw, 'font-size:13.5px; font-weight:800;'
                               ' color:%s;' % SLATE, _esc(p.get('press'))),
                        _td(hw, 'text-align:right; font-family:monospace;'
                                ' font-size:13.5px; font-weight:800;'
                                ' color:%s;' % _comp_color(p.get('pct')),
                            '%s%%' % _pct(p.get('pct')))], barw)
                + '<div style="height:4px;"></div>'
                + _tbl(seg_td, barw)
                + '<div style="height:4px;"></div>'
                + ('<div style="font-size:10.5px; color:#707379;'
                   ' font-weight:600;">%s</div>' % meta)
                + ('<div style="font-size:9.5px; color:#94A3B8;'
                   ' margin-top:2px;">%s</div>' % _seg_legend(times))
                + '</div><div style="height:6px;"></div>')
        items.append(item)
    if not items:
        items.append('<div style="font-size:12px; color:#707379;'
                     ' text-align:center;">Sin datos de prensas</div>')

    bd = 'Cumpl: %s%%' % _pct(cumpl)
    return ('<div style="%s">%s<div style="height:6px;"></div>%s</div>'
            % (ST_CARD, _card_header('Press Delivery', bd, cw - 24),
               ''.join(items)))


def build_orders(ord_list, cw):
    icw = cw - 28
    widths = [95, 85, 170, 255, 95, icw - 700]
    heads = ['N&deg; OT', 'Hora', 'Equipo / M&aacute;quina', 'T&iacute;tulo',
             'Tiempo (TP)', 'Detalle Intervenci&oacute;n']
    aligns = ['left', 'left', 'left', 'left', 'center', 'left']

    th = []
    for w, h, al in zip(widths, heads, aligns):
        th.append(_td(w, 'text-align:%s;' % al,
                      '<div style="background:#F8FAFC; padding:7px 8px;'
                      ' font-size:10.5px; font-weight:800; color:#334155;'
                      ' text-transform:uppercase;">%s</div>' % h))

    rows = []
    if not ord_list:
        rows.append('<tr><td colspan="6" style="text-align:center; padding:18px;'
                    ' color:#707379; font-size:12.5px; font-weight:700;">'
                    'Sin eventos correctivos reportados en este turno.</td></tr>')
    else:
        for o in ord_list:
            maq = o.get('maquina') or o.get('equipo') or ''
            sub_maq = o.get('equipo') or ''
            detalle = o.get('detalle') or o.get('titulo') or 'Sin observaciones.'
            maq_txt = _esc(maq)
            if sub_maq:
                maq_txt += ('<br/><span style="font-size:11px; color:#475569;">%s'
                            '</span>' % _esc(sub_maq))
            cells = (
                '<td style="padding:6px 8px;"><span style="background:#334155;'
                ' color:#fff; font-family:monospace; font-weight:800;'
                ' font-size:11.5px; padding:3px 8px; border-radius:4px;">%s</span></td>'
                % _esc(o.get('ot')),
                '<td style="padding:6px 8px; font-family:monospace;'
                ' font-weight:800; font-size:13px;">%s</td>' % _esc(o.get('hora')),
                '<td style="padding:6px 8px; font-size:13px;">%s</td>' % maq_txt,
                '<td style="padding:6px 8px; font-size:13px; font-weight:800;">%s</td>'
                % _esc(o.get('titulo')),
                '<td style="padding:6px 8px; text-align:center; font-family:monospace;'
                ' font-weight:800; font-size:13px;">%s min</td>' % _esc(o.get('tp_min')),
                '<td style="padding:6px 8px; font-size:12.5px; line-height:1.4;">%s</td>'
                % _esc(detalle))
            rows.append('<tr>' + ''.join(cells) + '</tr>')

    n = len(ord_list)
    if n == 0:
        count = 'Sin &Oacute;rdenes Registradas'
    else:
        count = '%d &Oacute;rdenes Registrar%s' % (n, 'da' if n == 1 else 'das')

    head_bar = _tbl([_td(icw - 140, 'font-size:13px; font-weight:800;'
                                  ' text-transform:uppercase; color:#231F20;'
                                  ' padding:0 0 8px 0;',
                         'Novedades y &Oacute;rdenes Correctivas del Turno'),
                     _td(140, 'text-align:right;', _kpi_badge(count))], icw)
    table = ('<table style="width:%spx; border-collapse:collapse;"'
             ' cellspacing="0" cellpadding="0">%s'
             '<tr><td colspan="6" style="height:2px; background:#E2E8F0;">'
             '&nbsp;</td></tr>%s</table>' % (icw, ''.join(th), ''.join(rows)))

    return ('<div style="background:#FFFFFF; border:1px solid #E2E8F0;'
            ' border-top:3px solid #64748B; border-radius:4px; padding:12px 14px;">'
            '%s<div style="height:6px;"></div>%s</div>' % (head_bar, table))


def _build_html(data, ts):
    c = data.get('consulta') or {}
    io = data.get('input_output') or {}
    cr = data.get('crane_performance') or {}
    pr = data.get('press_delivery') or {}
    ord_list = data.get('ordenes') or []

    c1, c2, c3 = COL_W
    cols = _tbl([_td(c1, 'vertical-align:top;', build_flow_card(io, c1)),
                 _spacer(GAP),
                 _td(c2, 'vertical-align:top;', build_crane_card(cr, c2)),
                 _spacer(GAP),
                 _td(c3, 'vertical-align:top;', build_press_card(pr, c3))], INNER_W)
    orders = build_orders(ord_list, INNER_W)

    body = ('<div style="width:%spx; background:%s;">%s'
            '<div style="padding:14px %spx 16px %spx;">%s'
            '<div style="height:12px;"></div>%s</div>'
            '<div style="padding:0 20px 14px 20px; font-size:10px;'
            ' color:%s; text-align:center;">Dashboard ASRS &middot;'
            ' Reporte de entrega de turno &middot;'
            ' Generado autom&aacute;ticamente %s</div></div>'
            % (PAGE_W, BG_PAGE, build_header(c, ts), BODY_PAD_X, BODY_PAD_X,
               cols, orders, SLATE_LIGHT, ts))

    return ('<html><head><meta charset="utf-8"></head>'
            '<body style="margin:0; font-family:Arial, Verdana, sans-serif;'
            ' color:#231F20;">%s</body></html>' % body)


# ------------------------------- export API ---------------------------------
def render_html_report(data, output_path=None, zoom=1.0):
    """Render report JSON (same shape as /api/consolidado-turno) to PNG bytes."""
    ts = _dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    html = _build_html(data, ts)
    pdf = fitz.open()
    page = pdf.new_page(width=PAGE_W, height=PAGE_H)
    (spare_h, _scale) = page.insert_htmlbox(
        fitz.Rect(0, 0, PAGE_W, PAGE_H), html, scale_low=1.0)
    if spare_h < 0:
        raise RuntimeError('El HTML no cupo en la pagina (revisar alturas).')
    used_h = max(0.0, PAGE_H - spare_h)
    clip = fitz.Rect(0, 0, PAGE_W, min(used_h + 40, PAGE_H))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, clip=clip)
    out = pix.tobytes('png')
    if output_path:
        with open(output_path, 'wb') as fh:
            fh.write(out)
    pdf.close()
    return out


# ------------------------------- verification -------------------------------
def _near(a, b, tol=10):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def verify(png_path, zoom=1.0):
    from PIL import Image
    im = Image.open(png_path).convert('RGB')
    w, h = im.size
    lines = ['PNG: %dx%d (ancho esperado ~%d a zoom %s)'
             % (w, h, round(PAGE_W * zoom), zoom)]

    px = im.getpixel((10, 10))
    ok = _near(px, (11, 29, 69))
    lines.append('pixel(10,10)=%s navy #0B1D45: %s' % (px, 'OK' if ok else 'FAIL'))

    gold_top = gold_bot = None
    for y in range(h):
        if _near(im.getpixel((10, y)), (251, 189, 0)):
            if gold_top is None:
                gold_top = y
            gold_bot = y
    lines.append('borde gold #FBBD00 (col 10): y=%s..%s %s'
                 % (gold_top, gold_bot,
                    'OK' if gold_top is not None else 'FAIL'))

    names = [('green despacho #22C55E', (34, 197, 94)),
             ('yellow IDLE #EAB308', (234, 179, 8)),
             ('blue cortinas #38BDF8', (56, 189, 248)),
             ('brown prensa #C2884D', (194, 136, 77)),
             ('red E-Stop #EF4444', (239, 68, 68))]
    for label, rgb in names:
        found = []
        for yy in range(0, h):
            row = [xx for xx in range(0, w)
                   if _near(im.getpixel((xx, yy)), rgb)]
            if row:
                found.append((min(row), max(row), yy))
        if found:
            x0 = min(p[0] for p in found)
            x1 = max(p[1] for p in found)
            y0 = min(p[2] for p in found)
            y1 = max(p[2] for p in found)
            lines.append('  %s: x %d..%d y %d..%d' % (label, x0, x1, y0, y1))
        else:
            lines.append('  %s: NO encontrado' % label)
    return '\n'.join(lines)


# ------------------------------- CLI ----------------------------------------
def _load_json(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _load_api(args):
    import requests
    url = args.api.rstrip('/') + '/api/consolidado-turno'
    r = requests.get(url, params={'fecha': args.fecha, 'turno': args.turno},
                     timeout=30)
    r.raise_for_status()
    return r.json()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Entrega de turno ASRS -> PNG sin navegador (PyMuPDF)')
    ap.add_argument('--fecha', default=None, help='Fecha YYYY-MM-DD (defecto: hoy)')
    ap.add_argument('--turno', default='T2', help='Turno T1/T2/T3 (defecto: T2)')
    ap.add_argument('--json', default=None, help='JSON local con la data')
    ap.add_argument('--output', default=None,
                    help='PNG de salida (defecto: captura_html_png_test.png)')
    ap.add_argument('--zoom', type=float, default=1.0, help='Zoom PNG (2 = alta res.)')
    ap.add_argument('--api', default='http://127.0.0.1:8006', help='Base URL API')
    ap.add_argument('--check', action='store_true', help='Verificar el PNG generado')
    args = ap.parse_args(argv)

    if args.json:
        data = _load_json(args.json)
    else:
        args.fecha = args.fecha or _dt.date.today().isoformat()
        data = _load_api(args)

    args.output = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'captura_html_png_test.png')
    print('Fecha: %s  Turno: %s' % (args.fecha, args.turno))
    print('Renderizando PNG (zoom %s) -> %s' % (args.zoom, args.output))
    render_html_report(data, output_path=args.output, zoom=args.zoom)
    print('Generado OK.')
    if args.check:
        print(verify(args.output, args.zoom))
    return 0


if __name__ == '__main__':
    sys.exit(main())