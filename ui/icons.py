"""Zamonaviy vektor ikonkalar — QPainter bilan chizilgan.
Hech qanday tashqi kutubxona kerak emas.
"""

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QPainterPath
from PyQt6.QtCore import Qt, QRectF, QPointF
from ui.scale import s


def _make_icon(draw_func, size=20, color="#ffffff", padding=2) -> QIcon:
    """QPainter callback asosida QIcon yaratish."""
    px = s(size)
    pixmap = QPixmap(px, px)
    pixmap.fill(QColor(0, 0, 0, 0))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(s(2))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    pad = s(padding)
    area = QRectF(pad, pad, px - 2 * pad, px - 2 * pad)
    draw_func(p, area, QColor(color))
    p.end()
    return QIcon(pixmap)


# ── Ikonkalar ────────────────────────────────────────────

def icon_plus(color="#ffffff"):
    """➕ Plus — Yangi sotuv"""
    def draw(p, r, c):
        cx, cy = r.center().x(), r.center().y()
        p.drawLine(QPointF(cx, r.top()), QPointF(cx, r.bottom()))
        p.drawLine(QPointF(r.left(), cy), QPointF(r.right(), cy))
    return _make_icon(draw, color=color)


def icon_sync(color="#ffffff"):
    """🔄 Sinxronlash — ikkita aylanma strelka"""
    def draw(p, r, c):
        path = QPainterPath()
        # Yuqori yay (soat yo'nalishida)
        cx, cy = r.center().x(), r.center().y()
        radius = r.width() * 0.38
        # Yay
        arc_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        p.drawArc(arc_rect, 30 * 16, 160 * 16)
        p.drawArc(arc_rect, 210 * 16, 160 * 16)
        # Strelka uchi — yuqori (o'ng)
        import math
        angle1 = math.radians(30)
        ax1 = cx + radius * math.cos(angle1)
        ay1 = cy - radius * math.sin(angle1)
        arr = s(5)
        p.drawLine(QPointF(ax1, ay1), QPointF(ax1 + arr, ay1 + arr * 0.3))
        p.drawLine(QPointF(ax1, ay1), QPointF(ax1 - arr * 0.1, ay1 + arr))
        # Strelka uchi — pastki (chap)
        angle2 = math.radians(210)
        ax2 = cx + radius * math.cos(angle2)
        ay2 = cy - radius * math.sin(angle2)
        p.drawLine(QPointF(ax2, ay2), QPointF(ax2 - arr, ay2 - arr * 0.3))
        p.drawLine(QPointF(ax2, ay2), QPointF(ax2 + arr * 0.1, ay2 - arr))
    return _make_icon(draw, color=color)


def icon_history(color="#ffffff"):
    """📋 Tarix — clipboard"""
    def draw(p, r, c):
        # Clipboard ramka
        inset = r.width() * 0.12
        body = QRectF(r.left() + inset, r.top() + r.height() * 0.15,
                       r.width() - 2 * inset, r.height() * 0.85)
        path = QPainterPath()
        rad = s(3)
        path.addRoundedRect(body, rad, rad)
        p.drawPath(path)
        # Clipboard clip (yuqoridagi)
        clip_w = r.width() * 0.3
        clip_h = r.height() * 0.12
        clip_x = r.center().x() - clip_w / 2
        clip_y = r.top() + r.height() * 0.08
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(clip_x, clip_y, clip_w, clip_h), s(2), s(2))
        p.drawPath(clip_path)
        # 3 ta chiziq (kontent)
        line_x1 = body.left() + body.width() * 0.2
        line_x2 = body.right() - body.width() * 0.2
        for i in range(3):
            ly = body.top() + body.height() * (0.3 + i * 0.22)
            p.drawLine(QPointF(line_x1, ly), QPointF(line_x2, ly))
    return _make_icon(draw, color=color)


def icon_clock(color="#ffffff"):
    """🕐 Soat — kassa tarixi"""
    def draw(p, r, c):
        # Doira
        cx, cy = r.center().x(), r.center().y()
        radius = r.width() * 0.42
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        # Soat mili
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy - radius * 0.6))
        # Minut mili
        p.drawLine(QPointF(cx, cy), QPointF(cx + radius * 0.45, cy + radius * 0.1))
    return _make_icon(draw, color=color)


def icon_lock(color="#ffffff"):
    """🔒 Qulf — kassa yopish"""
    def draw(p, r, c):
        # Qulf tanasi (pastki to'rtburchak)
        body_h = r.height() * 0.52
        body_y = r.bottom() - body_h
        body_x = r.left() + r.width() * 0.15
        body_w = r.width() * 0.7
        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(body_x, body_y, body_w, body_h), s(3), s(3))
        p.setBrush(c)
        p.drawPath(body_path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Yay (yuqoridagi halqa)
        arc_w = body_w * 0.6
        arc_h = r.height() * 0.38
        arc_x = r.center().x() - arc_w / 2
        arc_y = body_y - arc_h
        p.drawArc(QRectF(arc_x, arc_y, arc_w, arc_h * 2), 0, 180 * 16)
    return _make_icon(draw, color=color)


def icon_signal(color="#ffffff"):
    """📡 Signal — offline"""
    def draw(p, r, c):
        cx = r.center().x()
        by = r.bottom()
        # 3 ta bar (signal kuchi)
        bar_w = r.width() * 0.18
        gap = r.width() * 0.08
        total_w = 3 * bar_w + 2 * gap
        start_x = cx - total_w / 2
        heights = [r.height() * 0.35, r.height() * 0.6, r.height() * 0.9]
        for i, h in enumerate(heights):
            bx = start_x + i * (bar_w + gap)
            bar_rect = QRectF(bx, by - h, bar_w, h)
            path = QPainterPath()
            path.addRoundedRect(bar_rect, s(2), s(2))
            p.setBrush(c)
            p.drawPath(path)
    return _make_icon(draw, color=color)


def icon_loading(color="#ffffff"):
    """⏳ Loading"""
    def draw(p, r, c):
        cx, cy = r.center().x(), r.center().y()
        radius = r.width() * 0.42
        # Faqat yarim doira
        arc_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        p.drawArc(arc_rect, 45 * 16, 270 * 16)
        # Strelka
        import math
        angle = math.radians(45)
        ax = cx + radius * math.cos(angle)
        ay = cy - radius * math.sin(angle)
        arr = s(4)
        p.drawLine(QPointF(ax, ay), QPointF(ax + arr, ay))
        p.drawLine(QPointF(ax, ay), QPointF(ax, ay + arr))
    return _make_icon(draw, color=color)


def icon_wifi(color="#10b981"):
    """WiFi — connection status"""
    def draw(p, r, c):
        import math
        cx, cy = r.center().x(), r.bottom() - r.height() * 0.15
        # 3 ta yay
        for i, factor in enumerate([0.85, 0.55, 0.28]):
            radius = r.width() * factor
            arc_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            p.drawArc(arc_rect, 45 * 16, 90 * 16)
        # Markaziy nuqta
        dot_r = r.width() * 0.08
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy), dot_r, dot_r)
    return _make_icon(draw, size=18, color=color, padding=2)


def icon_building(color="#475569"):
    """Bino — kompaniya"""
    def draw(p, r, c):
        # Bino tanasi
        bw = r.width() * 0.65
        bh = r.height() * 0.85
        bx = r.center().x() - bw / 2
        by = r.bottom() - bh
        path = QPainterPath()
        path.addRoundedRect(QRectF(bx, by, bw, bh), s(2), s(2))
        p.drawPath(path)
        # Oynalar (2x3 grid)
        win_w = bw * 0.22
        win_h = bh * 0.14
        for row in range(3):
            for col in range(2):
                wx = bx + bw * 0.18 + col * (bw * 0.38)
                wy = by + bh * 0.12 + row * (bh * 0.25)
                p.setBrush(c)
                p.drawRect(QRectF(wx, wy, win_w, win_h))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Eshik
        dw = bw * 0.22
        dh = bh * 0.2
        dx = r.center().x() - dw / 2
        dy = r.bottom() - dh
        p.setBrush(c)
        p.drawRect(QRectF(dx, dy, dw, dh))
    return _make_icon(draw, size=18, color=color, padding=2)


def icon_user(color="#0369a1"):
    """Foydalanuvchi — kassir"""
    def draw(p, r, c):
        cx = r.center().x()
        # Bosh (doira)
        head_r = r.width() * 0.22
        head_cy = r.top() + r.height() * 0.32
        p.drawEllipse(QPointF(cx, head_cy), head_r, head_r)
        # Tana (pastki yoy)
        body_top = head_cy + head_r + r.height() * 0.08
        body_w = r.width() * 0.65
        body_h = r.height() * 0.35
        body_rect = QRectF(cx - body_w / 2, body_top, body_w, body_h * 2)
        p.drawArc(body_rect, 0, 180 * 16)
    return _make_icon(draw, size=18, color=color, padding=2)
