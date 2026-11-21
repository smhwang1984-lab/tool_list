"""nc_sim_gpu.py — GPU Z-map 절삭 실행기 (v2.8.0, G2 핵심).

sim_shaders/cut.vert · cut.frag 를 ModernGL(OpenGL 3.3)로 돌려 선분들을 소재 격자에 훑는다.
소재 격자 한 칸 = 렌더 대상 화소 하나, 높이 = 깊이 버퍼(깊이 시험 LESS), 공구 색 id = 색 버퍼(R32F).
같은 식의 CPU 기준 구현은 nc_sim_gpu_ref.py — 이 모듈의 결과는 그 구현과 비교한다(tests/test_nc_sim_gpu_shader.py).

이 모듈은 Qt·pyqtgraph에 의존하지 않고 moderngl도 함수 안에서만 가져온다 — 없어도 앱은 그대로 켜진다.
쓸 수 있는지는 gpu_available(ctx)로 먼저 본다(OpenGL 3.3 이상, moderngl 있음). 안 되면 호출부가 CPU 엔진을
쓴다(PLAN_gpu_sim_and_licensing.md 4.3).
"""

from __future__ import annotations

import os
import sys

import numpy as np

import nc_sim

SHADER_HEADER_330 = '#version 330 core\n'
MIN_GL_VERSION = 330
# 공구 한 개를 인스턴스 속성에 펴 넣으므로 선분당 12 float(48바이트). 한 번에 보내는 선분 수 상한 — 그 이상은 나눠 그린다.
MAX_SEGMENTS_PER_DRAW = 200_000


def shader_dir():
    """sim_shaders 폴더. 소스 실행은 이 파일 옆, PyInstaller 빌드는 _internal 안."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'sim_shaders')


def shader_source(name, header=SHADER_HEADER_330):
    with open(os.path.join(shader_dir(), name), encoding='utf-8') as handle:
        return header + handle.read()


def create_headless_context():
    """창 없이 쓰는 OpenGL 3.3 문맥. 만들 수 없으면(moderngl 없음·드라이버 문제) None."""
    try:
        import moderngl
        return moderngl.create_standalone_context(require=MIN_GL_VERSION)
    except Exception:
        return None


def gpu_available(ctx):
    """이 문맥에서 GPU 절삭을 쓸 수 있는가: OpenGL 3.3 이상."""
    return ctx is not None and getattr(ctx, 'version_code', 0) >= MIN_GL_VERSION


class GpuCutter:
    """소재 하나의 GPU 렌더 대상(깊이 + 색)과 절삭 프로그램. ctx는 호출부가 만든 moderngl 문맥이다.

    heights()/color_ids()는 GPU에서 읽어 와 nc_sim.ZMapStock 과 같은 모양((ny, nx), float32/int16)으로 돌려준다."""

    def __init__(self, ctx, bounds, resolution):
        import moderngl
        self._mgl = moderngl
        self.ctx = ctx
        self.resolution = float(resolution)
        xlo, xhi = bounds['X']
        ylo, yhi = bounds['Y']
        zlo, zhi = bounds['Z']
        self.x0, self.y0 = float(xlo), float(ylo)
        self.nx = max(2, int(round((xhi - xlo) / self.resolution)) + 1)
        self.ny = max(2, int(round((yhi - ylo) / self.resolution)) + 1)
        self.zlo, self.ztop = float(zlo), float(zhi)
        self._program = ctx.program(vertex_shader=shader_source('cut.vert'),
                                    fragment_shader=shader_source('cut.frag'))
        self._color = ctx.texture((self.nx, self.ny), 1, dtype='f4')
        self._depth = ctx.depth_texture((self.nx, self.ny))
        self._fbo = ctx.framebuffer(color_attachments=[self._color], depth_attachment=self._depth)
        self.reset()

    def release(self):
        for obj in (self._fbo, self._color, self._depth, self._program):
            try:
                obj.release()
            except Exception:
                pass

    def cell_count(self):
        return self.nx * self.ny

    def reset(self):
        """소재를 처음(깎이지 않은) 상태로: 깊이 1.0(= 소재 윗면), 색 -1."""
        self._fbo.use()
        self._fbo.clear(color=(-1.0, 0.0, 0.0, 0.0), depth=1.0)

    def cut_batch(self, P0, P1, tools, tool_idx, color):
        """선분 묶음을 깎는다. tools는 nc_sim.ToolShape(또는 None) 목록, tool_idx[m]이 그 위치.
        profile_params()를 모르는 공구가 쓰이면 ValueError(호출부가 CPU 엔진으로 가야 한다)."""
        P0 = np.ascontiguousarray(P0, dtype=np.float64).reshape(-1, 3)
        P1 = np.ascontiguousarray(P1, dtype=np.float64).reshape(-1, 3)
        tool_idx = np.asarray(tool_idx, dtype=np.int64)
        color = np.asarray(color, dtype=np.float64)
        prof = np.zeros((len(tools), 5), dtype=np.float64)       # radius, kind, a, b, c
        ok = np.zeros(len(tools), dtype=bool)
        for k, tool in enumerate(tools):
            if tool is None:
                continue
            params = tool.profile_params()
            if params is None:
                raise ValueError('GPU 엔진이 모르는 공구 형상입니다(%s) — CPU 엔진으로 깎아야 합니다' % tool.type_name)
            prof[k] = (tool.radius,) + tuple(params)
            ok[k] = True
        use = (tool_idx >= 0) & (tool_idx < len(tools))
        use[use] = ok[tool_idx[use]]
        use &= np.minimum(P0[:, 2], P1[:, 2]) < self.ztop
        idx = np.nonzero(use)[0]
        if idx.size == 0:
            return
        tp = prof[tool_idx[idx]]
        rows = np.empty((idx.size, 12), dtype=np.float32)
        rows[:, 0] = P0[idx, 0] - self.x0
        rows[:, 1] = P0[idx, 1] - self.y0
        rows[:, 2] = P1[idx, 0] - self.x0
        rows[:, 3] = P1[idx, 1] - self.y0
        rows[:, 4] = P0[idx, 2]
        rows[:, 5] = P1[idx, 2]
        rows[:, 6] = color[idx]
        rows[:, 7] = tp[:, 0]
        rows[:, 8:12] = tp[:, 1:5]

        mgl = self._mgl
        ctx = self.ctx
        self._fbo.use()
        ctx.viewport = (0, 0, self.nx, self.ny)
        ctx.enable(mgl.DEPTH_TEST)
        ctx.depth_func = '<'
        self._program['u_size'].value = (float(self.nx), float(self.ny))
        self._program['u_res'].value = self.resolution
        self._program['u_z'].value = (self.zlo, self.ztop)
        for start in range(0, rows.shape[0], MAX_SEGMENTS_PER_DRAW):
            part = rows[start:start + MAX_SEGMENTS_PER_DRAW]
            buf = ctx.buffer(part.tobytes())
            vao = ctx.vertex_array(self._program, [(buf, '4f 4f 4f/i', 'a_seg_xy', 'a_seg_z', 'a_prof')])
            try:
                vao.render(mgl.TRIANGLE_STRIP, vertices=4, instances=part.shape[0])
            finally:
                vao.release()
                buf.release()

    def heights(self):
        """(ny, nx) float32 — 칸마다 남은 소재 윗면 높이."""
        self.ctx.finish()
        depth = np.frombuffer(self._depth.read(), dtype=np.float32).reshape(self.ny, self.nx)
        h = (self.zlo + depth.astype(np.float64) * (self.ztop - self.zlo)).astype(np.float32)
        h[depth >= 1.0] = np.float32(self.ztop)
        return h

    def color_ids(self):
        """(ny, nx) int16 — 칸을 마지막으로 낮춘 선분의 색 id, 안 깎였으면 -1."""
        self.ctx.finish()
        c = np.frombuffer(self._color.read(), dtype=np.float32).reshape(self.ny, self.nx)
        return np.rint(c).astype(np.int16)
