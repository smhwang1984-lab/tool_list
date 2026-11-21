"""nc_sim_surface.py — GPU 소재 표시 (v2.8.0, G3).

고해상도 엔진(GpuZMapStock)의 결과를 삼각형 메쉬로 바꾸지 않고, 높이·색 id 텍스처를 셰이더(sim_shaders/surface.*)가
직접 읽어 그린다. 칸 단위 법선 음영, 공구 색·깎인 깊이·단색 모드, 옆면을 낸다. 기존 메쉬 경로의 600칸 표시 제한이 없다.

- SurfaceRenderer: moderngl 문맥 하나 위에서 동작(Qt 비의존). 시험은 독립 문맥으로 그려 본다.
- ZMapSurfaceItem: pyqtgraph GLGraphicsItem. 뷰어의 GL 문맥에서 SurfaceRenderer를 만들어 그린다.
  GL 3.3 미만이거나 만들기·그리기에서 오류가 나면 on_failure를 한 번 불러 뷰어가 기존 메쉬 경로로 돌아가게 한다.
"""

from __future__ import annotations

import numpy as np

import nc_sim
import nc_sim_gpu

MODE_TOOL, MODE_DEPTH, MODE_SOLID = 0, 1, 2
MODE_BY_NAME = {'tool': MODE_TOOL, 'depth': MODE_DEPTH, 'solid': MODE_SOLID}
# 화면에 그리는 격자 변당 칸 수 상한(이보다 크면 nc_sim.ZMapStock.display_grid가 블록 최솟값으로 줄인다)
SURFACE_GRID_MAX = 4096
SURFACE_GRID_MAX_SAFE = 1024


def build_palette(color_map):
    """{색 id: (r, g, b, a)} → (K, 4) float32. 없는 id는 기본색."""
    if not color_map:
        return np.zeros((0, 4), dtype=np.float32)
    top = max(color_map)
    pal = np.tile(np.array(nc_sim.DEFAULT_STOCK_COLOR, dtype=np.float32), (top + 1, 1))
    for cid, rgba in color_map.items():
        if cid >= 0:
            pal[cid] = rgba
    return pal


class SurfaceRenderer:
    def __init__(self, ctx):
        import moderngl
        self._mgl = moderngl
        self.ctx = ctx
        self._prog = ctx.program(vertex_shader=nc_sim_gpu.shader_source('surface.vert'),
                                 fragment_shader=nc_sim_gpu.shader_source('surface.frag'))
        self._tex = {}
        self.nx = self.ny = 0
        self.zlo = 0.0
        self.ztop = 0.0
        self._palette_n = 0
        self._vao = ctx.vertex_array(self._prog, [])

    def release(self):
        for tex in self._tex.values():
            try:
                tex.release()
            except Exception:
                pass
        self._tex.clear()
        for obj in (self._vao, self._prog):
            try:
                obj.release()
            except Exception:
                pass

    def _put(self, name, size, comps, data):
        mgl = self._mgl
        old = self._tex.get(name)
        if old is not None:
            old.release()
        tex = self.ctx.texture(size, comps, dtype='f4', data=np.ascontiguousarray(data, dtype=np.float32).tobytes())
        tex.filter = (mgl.NEAREST, mgl.NEAREST)
        tex.repeat_x = tex.repeat_y = False
        self._tex[name] = tex

    def set_data(self, xs, ys, heights, color_ids, palette, zlo, ztop):
        """xs, ys: 열·행 좌표(mm), heights/color_ids: (ny, nx)."""
        heights = np.asarray(heights, dtype=np.float32)
        self.ny, self.nx = heights.shape
        self.zlo, self.ztop = float(zlo), float(ztop)
        self._put('h', (self.nx, self.ny), 1, heights)
        self._put('c', (self.nx, self.ny), 1, np.asarray(color_ids, dtype=np.float32))
        self._put('x', (self.nx, 1), 1, np.asarray(xs, dtype=np.float32))
        self._put('y', (self.ny, 1), 1, np.asarray(ys, dtype=np.float32))
        pal = np.asarray(palette, dtype=np.float32).reshape(-1, 4)
        self._palette_n = pal.shape[0]
        if self._palette_n == 0:
            pal = np.zeros((1, 4), dtype=np.float32)
        self._put('p', (pal.shape[0], 1), 4, pal)

    def draw(self, mvp, mv, mode=MODE_TOOL, default_color=nc_sim.DEFAULT_STOCK_COLOR):
        """현재 바인딩된 렌더 대상에 그린다. mvp/mv: 4x4 열 우선(float32, QMatrix4x4.data() 순서)."""
        if self.nx < 2 or self.ny < 2:
            return
        mgl = self._mgl
        prog = self._prog
        for unit, name in enumerate(('h', 'x', 'y', 'c', 'p')):
            self._tex[name].use(unit)
        prog['u_height'].value = 0
        prog['u_xs'].value = 1
        prog['u_ys'].value = 2
        prog['u_cid'].value = 3
        prog['u_palette'].value = 4
        prog['u_mvp'].write(np.asarray(mvp, dtype=np.float32).tobytes())
        prog['u_mv'].write(np.asarray(mv, dtype=np.float32).tobytes())
        prog['u_n'].value = (self.nx, self.ny)
        prog['u_zlo'].value = self.zlo
        prog['u_default'].value = tuple(float(c) for c in default_color)
        prog['u_stops'].write(np.array(nc_sim.DEPTH_COLOR_STOPS, dtype=np.float32).tobytes())
        prog['u_depth'].value = (self.ztop, self.zlo)
        prog['u_mode'].value = int(mode)
        prog['u_palette_n'].value = self._palette_n
        prog['u_side'].value = -1
        self._vao.render(mgl.TRIANGLE_STRIP, vertices=2 * self.nx, instances=self.ny - 1)
        for side, count in ((0, self.nx), (1, self.nx), (2, self.ny), (3, self.ny)):
            prog['u_side'].value = side
            self._vao.render(mgl.TRIANGLE_STRIP, vertices=2 * count)


# ---------------------------------------------------------------------------
# pyqtgraph 아이템
# ---------------------------------------------------------------------------
try:
    import pyqtgraph.opengl as _gl
    from OpenGL import GL as _GL
    _BaseItem = _gl.GLGraphicsItem.GLGraphicsItem
except Exception:  # noqa: BLE001 - pyqtgraph 없는 환경(시험 일부)에서도 이 모듈을 불러올 수 있게
    _gl = None
    _GL = None
    _BaseItem = object


class ZMapSurfaceItem(_BaseItem):
    """뷰어의 GL 장면에 소재 윗면을 그리는 아이템. 모양을 바꾸려면 set_surface()를 부른다(텍스처는 그릴 때 올린다)."""

    def __init__(self, glOptions='opaque', on_failure=None):
        super().__init__()
        self.setGLOptions(glOptions)
        self._pending = None
        self._renderer = None
        self._mode = MODE_TOOL
        self._on_failure = on_failure
        self.failed = False
        self.xs = self.ys = None
        self.shape = (0, 0)

    def set_surface(self, xs, ys, heights, color_ids, palette, zlo, ztop, mode='tool'):
        self._pending = (np.asarray(xs), np.asarray(ys), np.asarray(heights), np.asarray(color_ids),
                         np.asarray(palette), float(zlo), float(ztop))
        self._mode = MODE_BY_NAME.get(mode, MODE_TOOL)
        self.xs, self.ys = self._pending[0], self._pending[1]
        self.shape = self._pending[2].shape
        self.update()

    def set_mode(self, mode):
        self._mode = MODE_BY_NAME.get(mode, MODE_TOOL)
        self.update()

    def _fail(self, why):
        self.failed = True
        self.last_error = str(why)
        callback, self._on_failure = self._on_failure, None
        if callback is not None:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, callback)

    def paint(self):
        if self.failed or (self._pending is None and self._renderer is None):
            return
        try:
            self.setupGLState()
            if self._renderer is None:
                import moderngl
                major = int(_GL.glGetIntegerv(_GL.GL_MAJOR_VERSION))
                minor = int(_GL.glGetIntegerv(_GL.GL_MINOR_VERSION))
                if (major, minor) < (3, 3):
                    raise RuntimeError('OpenGL %d.%d — 3.3 이상이 필요합니다' % (major, minor))
                self._renderer = SurfaceRenderer(moderngl.create_context())
            if self._pending is not None:
                self._renderer.set_data(*self._pending)
                self._pending = None
            mvp = np.array(self.mvpMatrix().data(), dtype=np.float32)
            mv = np.array(self.modelViewMatrix().data(), dtype=np.float32)
            self._renderer.draw(mvp, mv, self._mode)
        except Exception as exc:  # noqa: BLE001 - 뷰어가 메쉬 경로로 돌아간다
            self._fail(exc)
        finally:
            if _GL is not None:
                try:
                    _GL.glBindVertexArray(0)
                    _GL.glUseProgram(0)
                    for unit in (4, 3, 2, 1, 0):
                        _GL.glActiveTexture(_GL.GL_TEXTURE0 + unit)
                        _GL.glBindTexture(_GL.GL_TEXTURE_2D, 0)
                except Exception:  # noqa: BLE001
                    pass
