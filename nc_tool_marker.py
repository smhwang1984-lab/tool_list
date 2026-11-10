"""v2.4.3: 공정마다 공구 모양(회전체)과 진입 방향 화살표를 3D 뷰에 얹기 위한 순수 계산.

화면(Qt/OpenGL)과 무관하게 numpy로 메시/선 좌표만 만든다.
- 공구 모양: nc_sim.ToolShape의 팁 프로파일(평/볼/코너R/드릴 원뿔/챔퍼) + 날 길이만큼의 몸통.
  공구 팁이 진입점에 놓이고, 몸통은 공구 축 방향(기본 +Z)으로 뻗는다.
- 진입 방향: 첫 절삭 이동의 방향. 진입점에서 그 방향으로 뻗는 화살표(선 + 화살촉).
"""
import numpy as np

import nc_sim

SEGMENTS = 28            # 회전체 둘레 분할 수
PROFILE_STEPS = 8        # 팁 프로파일 샘플 수


def _unit(vec, fallback=(0.0, 0.0, 1.0)):
    arr = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if norm < 1e-9:
        arr = np.asarray(fallback, dtype=np.float64)
        norm = float(np.linalg.norm(arr))
    return arr / norm


def _frame(axis):
    """axis에 수직인 단위벡터 두 개(u, v)."""
    axis = _unit(axis)
    helper = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = _unit(np.cross(axis, helper))
    v = np.cross(axis, u)
    return u, v


def tool_profile(shape, body_length=None):
    """(반경, 팁에서의 높이) 점 목록 — 중심(0,0)에서 시작해 날끝 둘레를 지나 몸통 윗면까지."""
    radius = shape.radius
    steps = np.linspace(0.0, radius, PROFILE_STEPS + 1)
    heights = np.asarray(shape.height_grid(steps), dtype=np.float64)
    heights = np.nan_to_num(heights, nan=0.0)
    top = float(body_length) if body_length else float(shape.length)
    top = max(top, float(heights[-1]) + radius * 0.5)
    pts = [(float(r), float(h)) for r, h in zip(steps, heights)]
    pts.append((radius, top))
    pts.append((0.0, top))
    return pts


def build_tool_mesh(shape, tip, axis=(0.0, 0.0, 1.0), body_length=None):
    """공구 회전체 메시. 반환: (verts (N,3) float32, faces (M,3) int32)."""
    tip = np.asarray(tip, dtype=np.float64)
    axis = _unit(axis)
    u, v = _frame(axis)
    prof = tool_profile(shape, body_length)
    angles = np.linspace(0.0, 2.0 * np.pi, SEGMENTS, endpoint=False)
    ring_dirs = np.outer(np.cos(angles), u) + np.outer(np.sin(angles), v)
    verts = []
    for r, h in prof:
        for k in range(SEGMENTS):
            verts.append(tip + axis * h + ring_dirs[k] * r)
    faces = []
    for i in range(len(prof) - 1):
        for k in range(SEGMENTS):
            k2 = (k + 1) % SEGMENTS
            a = i * SEGMENTS + k
            b = i * SEGMENTS + k2
            c = (i + 1) * SEGMENTS + k
            d = (i + 1) * SEGMENTS + k2
            faces.append((a, b, c))
            faces.append((b, d, c))
    return np.asarray(verts, dtype=np.float32), np.asarray(faces, dtype=np.int32)


def build_entry_arrow(entry, direction, length, head=None):
    """진입점에서 direction 방향으로 length만큼 뻗는 화살표를 선분 쌍(lines 모드)으로.
    반환: (K,3) float32, 2개씩 한 선분."""
    entry = np.asarray(entry, dtype=np.float64)
    d = _unit(direction)
    head = float(head) if head else length * 0.25
    end = entry + d * length
    u, v = _frame(d)
    base = end - d * head
    spread = head * 0.45
    pts = [entry, end]
    for vec in (u, -u, v, -v):
        pts.extend([end, base + vec * spread])
    return np.asarray(pts, dtype=np.float32)


def first_cut_entry(path_data):
    """공정 경로에서 첫 절삭(비 G00) 이동의 (시작점, 방향, 시작 src_line).
    없으면 None."""
    previous = None
    for node in path_data:
        if not node.get("valid"):
            previous = None
            continue
        if previous is not None and node.get("type") != "G00":
            p0 = np.asarray(previous["pt"], dtype=np.float64)
            p1 = np.asarray(node["pt"], dtype=np.float64)
            delta = p1 - p0
            if float(np.linalg.norm(delta)) > 1e-9:
                return p0, delta, previous.get("src_line")
        previous = node
    return None


def marker_for_process(path_data, values, axis_of_line=None):
    """공정 하나의 마커 데이터. values = 툴리스트 공구값(type/D/FL/R/SIG/PL/SO).

    반환 dict(verts, faces, arrow, entry, direction, axis) 또는 None(공구 정보/절삭 이동 없음)."""
    if not values:
        return None
    shape = nc_sim.tool_shape_from_values(
        values.get('type'), values.get('D'), fl=values.get('FL'), r=values.get('R'),
        sig=values.get('SIG'), pl=values.get('PL'), so=values.get('SO'))
    if shape is None:
        return None
    entry = first_cut_entry(path_data)
    if entry is None:
        return None
    p0, delta, src_line = entry
    axis = (0.0, 0.0, 1.0)
    if axis_of_line is not None and src_line is not None:
        axis = axis_of_line.get(src_line, axis)
    axis = _unit(axis)
    body = max(shape.cut_length, shape.radius * 2.0)
    verts, faces = build_tool_mesh(shape, p0, axis, body)
    arrow_len = max(shape.radius * 4.0, body * 0.8, 6.0)
    arrow = build_entry_arrow(p0, delta, arrow_len)
    return {
        'verts': verts, 'faces': faces, 'arrow': arrow,
        'entry': p0, 'direction': _unit(delta), 'axis': axis,
    }
