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
        self._fill = ctx.program(vertex_shader=shader_source('fill.vert'),
                                 fragment_shader=shader_source('fill.frag'))
        self._color = ctx.texture((self.nx, self.ny), 1, dtype='f4')
        self._depth = ctx.depth_texture((self.nx, self.ny))
        self._fbo = ctx.framebuffer(color_attachments=[self._color], depth_attachment=self._depth)
        self.reset()

    def release(self):
        for obj in (self._fbo, self._color, self._depth, self._program, self._fill):
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

    def upload(self, heights, color_ids):
        """이미 깎인 상태((ny, nx) 높이·색 id)를 렌더 대상에 올린다(되감기·복원 뒤 이어 깎을 때)."""
        mgl = self._mgl
        ctx = self.ctx
        htex = ctx.texture((self.nx, self.ny), 1, dtype='f4',
                           data=np.ascontiguousarray(heights, dtype=np.float32).tobytes())
        ctex = ctx.texture((self.nx, self.ny), 1, dtype='f4',
                           data=np.ascontiguousarray(color_ids, dtype=np.float32).tobytes())
        for tex in (htex, ctex):
            tex.filter = (mgl.NEAREST, mgl.NEAREST)
        try:
            self._fbo.use()
            ctx.viewport = (0, 0, self.nx, self.ny)
            ctx.enable(mgl.DEPTH_TEST)
            ctx.depth_func = '1'            # 항상 통과 — 깊이를 그대로 덮어쓴다
            self._fbo.clear(color=(-1.0, 0.0, 0.0, 0.0), depth=1.0)
            htex.use(0)
            ctex.use(1)
            self._fill['u_height'].value = 0
            self._fill['u_cid'].value = 1
            self._fill['u_z'].value = (self.zlo, self.ztop)
            vao = ctx.vertex_array(self._fill, [])
            try:
                vao.render(mgl.TRIANGLE_STRIP, vertices=4)
            finally:
                vao.release()
        finally:
            htex.release()
            ctex.release()

    def cut_batch(self, P0, P1, tools, tool_idx, color, rapid=None):
        """선분 묶음을 깎는다. tools는 nc_sim.ToolShape(또는 None) 목록, tool_idx[m]이 그 위치.
        profile_params()를 모르는 공구가 쓰이면 ValueError(호출부가 CPU 엔진으로 가야 한다).

        rapid(bool 배열)를 주면 그 선분을 하나씩 따로 그리며 소재를 실제로 낮췄는지(깊이 시험을 통과한
        화소가 있었는지, 오클루전 질의) 알아내어, 선분마다 bool 배열로 돌려준다. 주지 않으면 None."""
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
        hits = None if rapid is None else np.zeros(P0.shape[0], dtype=bool)
        if idx.size == 0:
            return hits
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
        rapid_sel = np.zeros(idx.size, dtype=bool) if rapid is None else np.asarray(rapid, dtype=bool)[idx]
        pos = 0
        while pos < idx.size:
            if rapid_sel[pos]:
                # 급속 선분은 하나씩, 질의로 "소재를 낮췄는가"를 본다
                query = self.ctx.query(samples=True)
                with query:
                    self._draw(rows[pos:pos + 1])
                hits[idx[pos]] = query.samples > 0
                pos += 1
                continue
            end = pos
            while end < idx.size and not rapid_sel[end]:
                end += 1
            for start in range(pos, end, MAX_SEGMENTS_PER_DRAW):
                self._draw(rows[start:min(start + MAX_SEGMENTS_PER_DRAW, end)])
            pos = end
        return hits

    def _draw(self, part):
        buf = self.ctx.buffer(part.tobytes())
        vao = self.ctx.vertex_array(self._program, [(buf, '4f 4f 4f/i', 'a_seg_xy', 'a_seg_z', 'a_prof')])
        try:
            vao.render(self._mgl.TRIANGLE_STRIP, vertices=4, instances=part.shape[0])
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


# ---------------------------------------------------------------------------
# GpuZMapStock — nc_sim.ZMapStock과 같은 인터페이스의 GPU 소재
# ---------------------------------------------------------------------------

# 취소 확인·진행 알림을 위해 선분을 이만큼씩 나눠 GPU에 보낸다.
GPU_CHUNK_SEGMENTS = 20_000


def resolution_for_cells(bounds, cells):
    """소재 긴 변이 cells 칸이 되는 격자 간격(mm). 고해상도 엔진 해상도 키 'gpu:4096'이 쓴다."""
    long_side = max(bounds['X'][1] - bounds['X'][0], bounds['Y'][1] - bounds['Y'][0], 1e-6)
    return long_side / max(int(cells) - 1, 1)


class GpuZMapStock(nc_sim.ZMapStock):
    """Z-map 소재를 GPU(깊이 버퍼)로 깎는다. 상태의 기준은 항상 numpy 배열(heights, color_ids)이라
    snapshot/restore/clone/reset/display_grid/any_cut 등 ZMapStock의 나머지는 그대로 쓴다.

    cut_batch마다 임시 OpenGL 문맥을 만들어(스레드마다 따로 써야 하므로 호출 스레드에서) 현재 상태를
    올리고 → 깎고 → 읽어 와 numpy 배열에 되쓴다. GPU를 쓸 수 없거나(문맥 실패) 공구 형상을 GPU가 모르면
    부모(CPU) 구현으로 같은 일을 한다 — 호출부는 차이를 몰라도 된다.

    CPU 엔진과의 차이(nc_sim_gpu_ref.py 머리말): 수평·수직 이동은 같고, 경사 이동은 CPU가 조각 크기만큼
    더 깊게 깎는다(GPU가 연속 선분이라 더 정확하다)."""

    heavy = True            # 뷰어가 짧은 계산도 백그라운드 스레드로 돌리게 한다
    engine_name = 'gpu'

    def __init__(self, bounds, resolution, context_factory=None):
        super().__init__(bounds, resolution)
        self._context_factory = context_factory or create_headless_context
        self.last_cut_used_gpu = False

    def cut_batch(self, P0, P1, tools, tool_idx, rapid, color, src_lines=None, seqs=None,
                  cancel=None, progress=None, chunk=None, use_numba=None):
        P0 = np.ascontiguousarray(P0, dtype=np.float64).reshape(-1, 3)
        P1 = np.ascontiguousarray(P1, dtype=np.float64).reshape(-1, 3)
        total = P0.shape[0]
        if total == 0:
            return True
        cpu_args = dict(src_lines=src_lines, seqs=seqs, cancel=cancel, progress=progress, use_numba=use_numba)
        if chunk is not None:
            cpu_args['chunk'] = chunk
        if any(t is not None and t.profile_params() is None for t in tools):
            self.last_cut_used_gpu = False
            return super().cut_batch(P0, P1, tools, tool_idx, rapid, color, **cpu_args)
        ctx = self._context_factory()
        if not gpu_available(ctx):
            self.last_cut_used_gpu = False
            return super().cut_batch(P0, P1, tools, tool_idx, rapid, color, **cpu_args)

        tool_idx = np.asarray(tool_idx, dtype=np.int64)
        rapid = np.asarray(rapid, dtype=bool)
        color = np.asarray(color, dtype=np.float64)
        cutter = None
        try:
            cutter = GpuCutter(ctx, {'X': (self.x0, self.x0 + (self.nx - 1) * self.resolution),
                                     'Y': (self.y0, self.y0 + (self.ny - 1) * self.resolution),
                                     'Z': (self.zlo, self.ztop)}, self.resolution)
            if (cutter.nx, cutter.ny) != (self.nx, self.ny):
                raise RuntimeError('GPU 격자 크기가 소재와 다릅니다')
            cutter.upload(self.heights, self.color_ids)
            step = int(chunk or GPU_CHUNK_SEGMENTS)
            hit_all = np.zeros(total, dtype=bool)
            for start in range(0, total, step):
                if cancel is not None and cancel():
                    return False
                end = min(start + step, total)
                part = cutter.cut_batch(P0[start:end], P1[start:end], tools, tool_idx[start:end],
                                        color[start:end], rapid=rapid[start:end])
                hit_all[start:end] = part
                if progress is not None:
                    progress(end, total)
            self.heights = cutter.heights()
            self.color_ids = cutter.color_ids()
            self.last_cut_used_gpu = True
        finally:
            if cutter is not None:
                cutter.release()
            try:
                ctx.release()
            except Exception:
                pass
        for m in np.nonzero(hit_all & rapid)[0]:
            src = None if src_lines is None else src_lines[int(m)]
            seq = None if seqs is None else seqs[int(m)]
            self.rapid_cut_warnings.append((None if src is None else int(src),
                                            None if seq is None else int(seq)))
        return True
