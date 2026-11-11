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


def placement_matrix(tip, axis):
    """원점·+Z 기준으로 만든 공구 메시를 tip 위치·axis 방향으로 옮기는 4x4(행 우선, 16개 값)."""
    axis = _unit(axis)
    u, v = _frame(axis)
    tip = np.asarray(tip, dtype=np.float64)
    return [
        float(u[0]), float(v[0]), float(axis[0]), float(tip[0]),
        float(u[1]), float(v[1]), float(axis[1]), float(tip[1]),
        float(u[2]), float(v[2]), float(axis[2]), float(tip[2]),
        0.0, 0.0, 0.0, 1.0,
    ]


def _same_axis(a, b, tol=1e-6):
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def cut_groups(path_data, axis_of_line=None):
    """공정 경로를 '같은 공구 축으로 가공하는 구간'으로 나눈다(v2.4.5).

    각 구간 = 그 축에서 처음 만난 절삭 이동(G1/G2/G3/사이클 가공 이동)부터, 공구 축이 바뀌는
    지점(축 회전)까지. 진입 방향 화살표는 구간의 첫 절삭 이동 시작점에 그린다.
    반환: [{'entry', 'direction', 'axis', 'start_seq', 'end_seq'}] (end_seq는 끝까지면 None)."""
    z_axis = (0.0, 0.0, 1.0)

    def axis_of(node):
        if axis_of_line is None:
            return z_axis
        return tuple(axis_of_line.get(node.get("src_line"), z_axis))

    groups = []
    current = None
    previous = None
    for node in path_data:
        if not node.get("valid"):
            previous = None
            continue
        axis = axis_of(node)
        if current is not None and not _same_axis(axis, current['axis']):
            current['end_seq'] = node.get("seq", 0)
            current = None
        if previous is not None and current is None and node.get("type") != "G00":
            p0 = np.asarray(previous["pt"], dtype=np.float64)
            delta = np.asarray(node["pt"], dtype=np.float64) - p0
            if float(np.linalg.norm(delta)) > 1e-9:
                current = {'entry': p0, 'direction': _unit(delta), 'axis': axis,
                           'start_seq': node.get("seq", 0), 'end_seq': None}
                groups.append(current)
        previous = node
    return groups


def group_at(groups, seq):
    """seq(재생 위치)에 해당하는 가공 구간. 없으면 None(= 화살표를 지운다)."""
    found = None
    for group in groups:
        if group['start_seq'] <= seq and (group['end_seq'] is None or seq < group['end_seq']):
            found = group
    return found


def marker_for_process(path_data, values, axis_of_line=None):
    """공정 하나의 마커 데이터. values = 툴리스트 공구값(type/D/FL/R/SIG/PL/SO).

    공구 모양은 재생(PG 매칭) 때만 보이므로, 메시는 원점·+Z 기준으로 한 번만 만들고
    재생 위치마다 placement_matrix로 옮긴다.
    반환 dict(verts, faces, groups) 또는 None(공구 정보/절삭 이동 없음)."""
    shape = None
    if values:
        shape = nc_sim.tool_shape_from_values(
            values.get('type'), values.get('D'), fl=values.get('FL'), r=values.get('R'),
            sig=values.get('SIG'), pl=values.get('PL'), so=values.get('SO'))
    groups = cut_groups(path_data, axis_of_line)
    if not groups:
        return None
    if shape is None:
        # v2.5.1: 공구 정보가 없어도 진입 방향 화살표는 보여야 한다 — 눈에 안 보이는 빈 메시를 쓴다.
        verts = np.zeros((3, 3), dtype=np.float32)
        faces = np.array([[0, 1, 2]], dtype=np.int32)
        return {'verts': verts, 'faces': faces, 'groups': groups, 'has_shape': False}
    body = max(shape.cut_length, shape.radius * 2.0)
    verts, faces = build_tool_mesh(shape, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), body)
    return {'verts': verts, 'faces': faces, 'groups': groups, 'has_shape': True}
