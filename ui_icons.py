# -*- coding: utf-8 -*-
"""v2.2.8: 툴바·패널 버튼 아이콘.

외부 이미지나 남의 아이콘 세트를 쓰지 않고 QPainter로 일반 기호(폴더, 디스켓,
연필, 톱니 …)만 직접 그린다. 설치 파일에 넣을 자원이 늘지 않고, 테마 색을
그대로 받아 다크/라이트 어디서든 같은 모양으로 보인다.

좌표는 0~1로 정규화해 그린다(`_Pen.p(x, y)` → 픽셀). `icon(name, color, size)`로
부르고, 고해상도 화면에서도 흐리지 않도록 1배·2배 픽스맵을 함께 넣는다.
"""
from math import cos, radians, sin

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


class _Pen:
    """정규화 좌표(0~1)로 그리는 작은 도우미."""

    def __init__(self, painter, size, color):
        self.painter = painter
        self.s = float(size)
        self.color = QColor(color)
        self.stroke()

    def p(self, x, y):
        return QPointF(x * self.s, y * self.s)

    def r(self, x, y, w, h):
        return QRectF(x * self.s, y * self.s, w * self.s, h * self.s)

    def stroke(self, width=0.085, color=None):
        pen = QPen(QColor(color) if color is not None else self.color)
        pen.setWidthF(max(1.0, width * self.s))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self.painter.setPen(pen)
        self.painter.setBrush(Qt.NoBrush)

    def fill(self, color=None):
        self.painter.setPen(Qt.NoPen)
        self.painter.setBrush(QBrush(QColor(color) if color is not None else self.color))

    def line(self, x1, y1, x2, y2):
        self.painter.drawLine(self.p(x1, y1), self.p(x2, y2))

    def poly(self, *points, closed=True):
        polygon = QPolygonF([self.p(x, y) for x, y in points])
        if closed:
            self.painter.drawPolygon(polygon)
        else:
            self.painter.drawPolyline(polygon)

    def rect(self, x, y, w, h, radius=0.0):
        if radius:
            self.painter.drawRoundedRect(self.r(x, y, w, h), radius * self.s, radius * self.s)
        else:
            self.painter.drawRect(self.r(x, y, w, h))

    def circle(self, cx, cy, radius):
        self.painter.drawEllipse(self.p(cx, cy), radius * self.s, radius * self.s)

    def text(self, x, y, w, h, value, bold=True, scale=0.5):
        font = self.painter.font()
        font.setBold(bold)
        font.setPixelSize(max(6, round(self.s * scale)))
        self.painter.setFont(font)
        self.painter.setPen(QPen(self.color))
        self.painter.drawText(self.r(x, y, w, h), Qt.AlignCenter, value)


# ---------- 그리기 함수 (이름 → 함수) ----------

def _folder(d):
    d.poly((0.08, 0.26), (0.38, 0.26), (0.46, 0.34), (0.92, 0.34), (0.92, 0.82), (0.08, 0.82))
    d.line(0.08, 0.44, 0.92, 0.44)


def _folder_open(d):
    d.poly((0.08, 0.82), (0.08, 0.22), (0.36, 0.22), (0.44, 0.30), (0.80, 0.30), (0.80, 0.42), closed=False)
    d.poly((0.08, 0.82), (0.22, 0.44), (0.96, 0.44), (0.82, 0.82))


def _folder_add(d):
    d.poly((0.70, 0.82), (0.06, 0.82), (0.06, 0.24), (0.34, 0.24), (0.42, 0.32), (0.84, 0.32), (0.84, 0.48),
           closed=False)
    d.stroke(0.10)
    d.line(0.80, 0.56, 0.80, 0.96)
    d.line(0.60, 0.76, 1.00, 0.76)


def _document(d):
    d.poly((0.22, 0.08), (0.60, 0.08), (0.80, 0.28), (0.80, 0.92), (0.22, 0.92))
    d.poly((0.60, 0.08), (0.60, 0.28), (0.80, 0.28), closed=False)
    for y in (0.46, 0.60, 0.74):
        d.line(0.34, y, 0.68, y)


def _eraser(d):
    # 기울어진 지우개 + 바닥선
    d.poly((0.12, 0.62), (0.50, 0.24), (0.86, 0.60), (0.58, 0.88), (0.38, 0.88))
    d.line(0.30, 0.44, 0.68, 0.82)
    d.line(0.38, 0.88, 0.92, 0.88)


def _trash(d):
    d.line(0.14, 0.24, 0.86, 0.24)
    d.poly((0.38, 0.24), (0.40, 0.12), (0.60, 0.12), (0.62, 0.24), closed=False)
    d.poly((0.22, 0.24), (0.28, 0.90), (0.72, 0.90), (0.78, 0.24), closed=False)
    d.line(0.42, 0.38, 0.43, 0.76)
    d.line(0.58, 0.38, 0.57, 0.76)


def _pencil(d):
    d.poly((0.16, 0.84), (0.20, 0.64), (0.66, 0.18), (0.82, 0.34), (0.36, 0.80))
    d.line(0.58, 0.26, 0.74, 0.42)
    d.line(0.20, 0.64, 0.36, 0.80)


def _save(d):
    d.poly((0.12, 0.12), (0.74, 0.12), (0.88, 0.26), (0.88, 0.88), (0.12, 0.88))
    d.rect(0.28, 0.12, 0.40, 0.24)
    d.rect(0.26, 0.54, 0.48, 0.34)


def _key(d):
    d.circle(0.30, 0.50, 0.17)
    d.line(0.47, 0.50, 0.90, 0.50)
    d.line(0.76, 0.50, 0.76, 0.66)
    d.line(0.88, 0.50, 0.88, 0.62)


def _run(d):
    # 표 + 오른쪽 아래 재생 삼각형(툴리스트 산출)
    d.rect(0.08, 0.14, 0.62, 0.56, 0.04)
    d.line(0.08, 0.32, 0.70, 0.32)
    d.line(0.08, 0.50, 0.70, 0.50)
    d.line(0.30, 0.14, 0.30, 0.70)
    d.fill()
    d.poly((0.58, 0.54), (0.58, 0.96), (0.96, 0.75))


def _table(d):
    d.rect(0.10, 0.16, 0.80, 0.68, 0.05)
    d.line(0.10, 0.36, 0.90, 0.36)
    d.line(0.10, 0.60, 0.90, 0.60)
    d.line(0.36, 0.16, 0.36, 0.84)


def _cube3d(d):
    top = ((0.50, 0.10), (0.88, 0.30), (0.50, 0.50), (0.12, 0.30))
    d.poly(*top)
    d.poly((0.12, 0.30), (0.12, 0.72), (0.50, 0.92), (0.88, 0.72), (0.88, 0.30), closed=False)
    d.line(0.50, 0.50, 0.50, 0.92)


def _toolpath(d):
    # Viewer 모드: 지그재그 경로 + 끝점
    d.poly((0.10, 0.80), (0.10, 0.22), (0.36, 0.22), (0.36, 0.66), (0.62, 0.66), (0.62, 0.22), (0.86, 0.22),
           closed=False)
    d.fill()
    d.circle(0.86, 0.22, 0.09)
    d.circle(0.10, 0.80, 0.07)


def _gear(d):
    cx = cy = 0.5
    points = []
    teeth = 8
    for i in range(teeth * 2):
        angle = radians(i * 180.0 / teeth - 90.0)
        radius = 0.44 if i % 2 == 0 else 0.33
        # 이빨을 사다리꼴로: 각 꼭짓점 앞뒤로 조금씩 벌린다
        for offset in (-6.0, 6.0):
            a = angle + radians(offset)
            points.append((cx + radius * cos(a), cy + radius * sin(a)))
    d.poly(*points)
    d.circle(cx, cy, 0.13)


def _help(d):
    d.circle(0.5, 0.5, 0.40)
    d.text(0.10, 0.08, 0.80, 0.80, '?', scale=0.56)


def _info(d):
    d.circle(0.5, 0.5, 0.40)
    d.stroke(0.11)
    d.line(0.5, 0.46, 0.5, 0.72)
    d.fill()
    d.circle(0.5, 0.31, 0.06)


def _search(d):
    d.circle(0.42, 0.42, 0.26)
    d.stroke(0.12)
    d.line(0.62, 0.62, 0.88, 0.88)


def _endmill(d, x0):
    # 엔드밀 실루엣(자루 + 날 사선)
    d.rect(x0 + 0.06, 0.10, 0.16, 0.34)
    d.poly((x0 + 0.04, 0.44), (x0 + 0.24, 0.44), (x0 + 0.24, 0.84), (x0 + 0.04, 0.84))
    d.line(x0 + 0.04, 0.56, x0 + 0.24, 0.50)
    d.line(x0 + 0.04, 0.70, x0 + 0.24, 0.64)


def _tool_prev(d):
    _endmill(d, 0.60)
    d.fill()
    d.poly((0.06, 0.50), (0.40, 0.28), (0.40, 0.72))


def _tool_next(d):
    _endmill(d, 0.12)
    d.fill()
    d.poly((0.94, 0.50), (0.60, 0.28), (0.60, 0.72))


def _home(d):
    d.poly((0.10, 0.50), (0.50, 0.14), (0.90, 0.50), closed=False)
    d.poly((0.22, 0.40), (0.22, 0.86), (0.78, 0.86), (0.78, 0.40), closed=False)
    d.rect(0.42, 0.60, 0.16, 0.26)


def _check_all(d):
    d.rect(0.12, 0.12, 0.76, 0.76, 0.12)
    d.stroke(0.11)
    d.poly((0.28, 0.50), (0.44, 0.66), (0.72, 0.34), closed=False)


def _check_none(d):
    d.rect(0.12, 0.12, 0.76, 0.76, 0.12)


def _stock(d):
    # 소재 블록(납작한 육면체)
    d.poly((0.10, 0.38), (0.50, 0.20), (0.90, 0.38), (0.50, 0.56))
    d.poly((0.10, 0.38), (0.10, 0.64), (0.50, 0.82), (0.90, 0.64), (0.90, 0.38), closed=False)
    d.line(0.50, 0.56, 0.50, 0.82)


def _plus(d):
    d.stroke(0.12)
    d.line(0.5, 0.16, 0.5, 0.84)
    d.line(0.16, 0.5, 0.84, 0.5)


def _list(d):
    for y in (0.26, 0.50, 0.74):
        d.fill()
        d.circle(0.18, y, 0.065)
        d.stroke()
        d.line(0.34, y, 0.88, y)


def _pdf(d):
    d.poly((0.16, 0.06), (0.58, 0.06), (0.80, 0.28), (0.80, 0.94), (0.16, 0.94))
    d.poly((0.58, 0.06), (0.58, 0.28), (0.80, 0.28), closed=False)
    d.fill()
    d.rect(0.04, 0.46, 0.72, 0.30, 0.05)
    d.painter.setPen(QPen(Qt.transparent))
    font = d.painter.font()
    font.setBold(True)
    font.setPixelSize(max(6, round(d.s * 0.26)))
    d.painter.setFont(font)
    # 글자는 투명하게 파내 배경색이 비치게 한다
    d.painter.setCompositionMode(QPainter.CompositionMode_Clear)
    path = QPainterPath()
    path.addText(d.p(0.08, 0.70), font, 'PDF')
    d.painter.fillPath(path, QBrush(Qt.black))
    d.painter.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _copy(d):
    d.rect(0.30, 0.30, 0.56, 0.60, 0.06)
    d.poly((0.70, 0.30), (0.70, 0.10), (0.14, 0.10), (0.14, 0.70), (0.30, 0.70), closed=False)


def _drag_zoom(d):
    pen = QPen(d.color)
    pen.setWidthF(max(1.0, 0.07 * d.s))
    pen.setStyle(Qt.DashLine)
    d.painter.setPen(pen)
    d.rect(0.06, 0.06, 0.56, 0.48)
    d.stroke()
    d.circle(0.56, 0.58, 0.20)
    d.stroke(0.11)
    d.line(0.71, 0.73, 0.92, 0.94)


def _chevron_right(d):
    d.stroke(0.12)
    d.poly((0.36, 0.20), (0.66, 0.50), (0.36, 0.80), closed=False)


def _chevron_down(d):
    d.stroke(0.12)
    d.poly((0.20, 0.36), (0.50, 0.66), (0.80, 0.36), closed=False)


def _stop(d):
    # 재생 정지 조건(팔각형 정지 표지)
    points = []
    for i in range(8):
        a = radians(22.5 + i * 45.0)
        points.append((0.5 + 0.40 * cos(a), 0.5 + 0.40 * sin(a)))
    d.poly(*points)
    d.stroke(0.11)
    d.line(0.32, 0.5, 0.68, 0.5)


def _filter(d):
    d.poly((0.10, 0.16), (0.90, 0.16), (0.58, 0.52), (0.58, 0.86), (0.42, 0.76), (0.42, 0.52))


ICON_PAINTERS = {
    'folder': _folder,
    'folder_open': _folder_open,
    'folder_add': _folder_add,
    'document': _document,
    'eraser': _eraser,
    'trash': _trash,
    'pencil': _pencil,
    'save': _save,
    'key': _key,
    'run': _run,
    'table': _table,
    'cube3d': _cube3d,
    'toolpath': _toolpath,
    'gear': _gear,
    'help': _help,
    'info': _info,
    'search': _search,
    'tool_prev': _tool_prev,
    'tool_next': _tool_next,
    'home': _home,
    'check_all': _check_all,
    'check_none': _check_none,
    'stock': _stock,
    'plus': _plus,
    'list': _list,
    'pdf': _pdf,
    'copy': _copy,
    'drag_zoom': _drag_zoom,
    'chevron_right': _chevron_right,
    'chevron_down': _chevron_down,
    'stop': _stop,
    'filter': _filter,
}


def icon_pixmap(name, color, size):
    """이름에 해당하는 아이콘을 size×size 투명 픽스맵에 그린다."""
    painter_fn = ICON_PAINTERS[name]
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    try:
        painter_fn(_Pen(painter, size, color))
    finally:
        painter.end()
    return pixmap


def icon(name, color, size=20):
    """QIcon(1배 + 2배 픽스맵). 버튼 아이콘 크기는 호출하는 쪽에서 setIconSize로 정한다."""
    result = QIcon()
    result.addPixmap(icon_pixmap(name, color, size))
    result.addPixmap(icon_pixmap(name, color, size * 2))
    return result


def line_width_pixmap(width_px, color, length=64, height=16):
    """선 굵기 드롭다운 항목용 미리보기: 실제 굵기의 가로선을 그린다."""
    pixmap = QPixmap(length, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    try:
        pen = QPen(QColor(color))
        pen.setWidthF(max(0.5, float(width_px)))
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        y = height / 2.0
        painter.drawLine(QPointF(3, y), QPointF(length - 3, y))
    finally:
        painter.end()
    return pixmap
