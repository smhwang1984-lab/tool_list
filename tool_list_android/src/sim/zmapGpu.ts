// GPU Z-map (안드로이드, v2.8.1 G4) — 원본 nc_sim_gpu.py / nc_sim_surface.py 와 같은 셰이더(sim_shaders/)를 three.js(WebGL2)로 돌린다.
//
// 구성
//   GpuCutter     소재 한 개의 렌더 대상(깊이 + R32F 색 id)과 절삭 패스. 칸 하나 = 화소 하나.
//   GpuZMapStock  ZMapStock 과 같은 인터페이스(cutRange / reset / rapidWarnings …) — 상태는 GPU에 있고, 필요할 때만 읽어 온다.
//   GpuSurface    깎인 높이 텍스처를 정점 셰이더가 직접 읽어 그리는 표시(윗면 + 옆면 4개).
// 셰이더는 데스크톱과 같은 파일이다(저장소 루트 sim_shaders/). 앞에 붙이는 줄만 다르다(three 가 #version 300 es 를 붙인다).
// 계산 기준(정답표)은 zmapGpuRef.ts — 실제 GPU 결과는 tests/gpu/ (Playwright)에서 그것과 비교한다.
import * as THREE from 'three';
import cutVert from '../../../sim_shaders/cut.vert?raw';
import cutFrag from '../../../sim_shaders/cut.frag?raw';
import fillVert from '../../../sim_shaders/fill.vert?raw';
import heightFrag from '../../../sim_shaders/height.frag?raw';
import surfaceVert from '../../../sim_shaders/surface.vert?raw';
import surfaceFrag from '../../../sim_shaders/surface.frag?raw';
import type { Bounds } from './stock';
import type { ToolShape } from './toolShape';
import { DEFAULT_STOCK_COLOR } from './mesh';
import { displayBlock } from './gpuCells';
import { ZMapStock, type SimSegments } from './zmap';

export { GPU_AUTO_CELLS, GPU_DISPLAY_GRID_MAX, displayBlock, resolutionForCells } from './gpuCells';

const HEADER = 'precision highp float;\nprecision highp int;\nprecision highp sampler2D;\n';

/** 선분 한 묶음으로 그리는 최대 수(인스턴스 버퍼 크기) */
export const GPU_CHUNK_SEGMENTS = 20_000;

const SOFTWARE_RENDERERS = ['swiftshader', 'llvmpipe', 'softpipe', 'software', 'basic render', 'gdi generic', 'mesa offscreen', 'android emulator'];

export interface GpuProbe { ok: boolean; reason: string; renderer: string; maxTexture: number }

/** 이 화면(WebGL2)이 GPU 절삭을 할 수 있나: WebGL2 + 실수 색 첨부(EXT_color_buffer_float) + 소프트웨어 렌더러가 아님 */
export function gpuProbe(renderer: THREE.WebGLRenderer, allowSoftware = false): GpuProbe {
  const gl = renderer.getContext();
  let name = '';
  try {
    const info = renderer.extensions.get('WEBGL_debug_renderer_info') as { UNMASKED_RENDERER_WEBGL: number } | null;
    name = String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
  } catch { name = ''; }
  const maxTexture = Number(gl.getParameter(gl.MAX_TEXTURE_SIZE)) || 0;
  const bad = (reason: string): GpuProbe => ({ ok: false, reason, renderer: name, maxTexture });
  if (!(gl instanceof WebGL2RenderingContext)) return bad('WebGL2를 쓸 수 없습니다');
  if (!renderer.extensions.has('EXT_color_buffer_float')) return bad('실수 렌더 대상(EXT_color_buffer_float)을 쓸 수 없습니다');
  if (maxTexture < 2048) return bad('텍스처 크기 제한이 너무 작습니다');
  if (!allowSoftware && SOFTWARE_RENDERERS.some((s) => name.toLowerCase().includes(s))) return bad('소프트웨어 렌더러입니다');
  return { ok: true, reason: '', renderer: name, maxTexture };
}

const QUAD_INDEX = [0, 1, 2, 2, 1, 3];

/** gl_VertexID = 색인 값으로 쓰는 사각형(셰이더가 gl_VertexID로 모서리를 고른다) */
function quadGeometry(): THREE.InstancedBufferGeometry {
  const g = new THREE.InstancedBufferGeometry();
  g.instanceCount = 1;          // 기본값 Infinity는 아무것도 그리지 않는다
  g.setIndex(QUAD_INDEX);
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(12), 3)); // 쓰이지 않는 자리 채움
  return g;
}

/** TRIANGLE_STRIP 정점 m개를 삼각형 목록 색인으로 풀어 쓴다(색인 값 = 띠 정점 번호 = gl_VertexID) */
export function stripIndex(m: number): Uint32Array {
  const tris = Math.max(m - 2, 0);
  const out = new Uint32Array(tris * 3);
  for (let k = 0; k < tris; k++) {
    if (k % 2 === 0) { out[k * 3] = k; out[k * 3 + 1] = k + 1; out[k * 3 + 2] = k + 2; }
    else { out[k * 3] = k + 1; out[k * 3 + 1] = k; out[k * 3 + 2] = k + 2; }
  }
  return out;
}

function rawMaterial(vertex: string, fragment: string, uniforms: Record<string, THREE.IUniform>): THREE.RawShaderMaterial {
  return new THREE.RawShaderMaterial({
    glslVersion: THREE.GLSL3,
    vertexShader: HEADER + vertex,
    fragmentShader: HEADER + fragment,
    uniforms,
    side: THREE.DoubleSide,
    blending: THREE.NoBlending,
    transparent: false,
  });
}

function floatTarget(w: number, h: number, count = 1): THREE.WebGLRenderTarget {
  return new THREE.WebGLRenderTarget(w, h, {
    count, type: THREE.FloatType, format: THREE.RedFormat, internalFormat: 'R32F',
    minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: false, generateMipmaps: false,
  });
}

/** 급속 선분 하나가 소재를 낮췄는지 알기 위한 질의. WebGL은 질의 결과를 그 작업(task)이 끝난 뒤에야 주므로 나중에 모은다. */
export interface PendingHit { src: number | null; seq: number; query: WebGLQuery }

export class GpuCutter {
  readonly nx: number;
  readonly ny: number;
  readonly x0: number;
  readonly y0: number;
  readonly zlo: number;
  readonly ztop: number;
  readonly rt: THREE.WebGLRenderTarget;
  private readonly cutScene = new THREE.Scene();
  private readonly cutMesh: THREE.Mesh;
  private readonly cutMat: THREE.RawShaderMaterial;
  private readonly passScene = new THREE.Scene();
  private readonly passMesh: THREE.Mesh;
  private readonly passMat: THREE.RawShaderMaterial;
  private readonly camera = new THREE.Camera();
  private readonly passUniforms: Record<string, THREE.IUniform>;
  private pending: PendingHit[] = [];

  constructor(readonly renderer: THREE.WebGLRenderer, bounds: Bounds, readonly resolution: number) {
    this.x0 = bounds.X[0];
    this.y0 = bounds.Y[0];
    this.nx = Math.max(2, Math.round((bounds.X[1] - bounds.X[0]) / resolution) + 1);
    this.ny = Math.max(2, Math.round((bounds.Y[1] - bounds.Y[0]) / resolution) + 1);
    this.zlo = bounds.Z[0];
    this.ztop = bounds.Z[1];

    const depth = new THREE.DepthTexture(this.nx, this.ny, THREE.FloatType);
    depth.format = THREE.DepthFormat;
    depth.minFilter = THREE.NearestFilter;
    depth.magFilter = THREE.NearestFilter;
    this.rt = new THREE.WebGLRenderTarget(this.nx, this.ny, {
      type: THREE.FloatType, format: THREE.RedFormat, internalFormat: 'R32F',
      minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: true, depthTexture: depth, generateMipmaps: false,
    });

    this.cutMat = rawMaterial(cutVert, cutFrag, {
      u_size: { value: new THREE.Vector2(this.nx, this.ny) }, u_res: { value: resolution }, u_z: { value: new THREE.Vector2(this.zlo, this.ztop) },
    });
    this.cutMat.depthTest = true;
    this.cutMat.depthWrite = true;
    this.cutMat.depthFunc = THREE.LessDepth;
    this.cutMesh = new THREE.Mesh(quadGeometry(), this.cutMat);
    this.cutMesh.frustumCulled = false;
    this.cutScene.add(this.cutMesh);

    this.passUniforms = {
      u_depth: { value: depth }, u_cid: { value: this.rt.texture }, u_z: { value: new THREE.Vector2(this.zlo, this.ztop) },
      u_n: { value: new THREE.Vector2(this.nx, this.ny) }, u_block: { value: new THREE.Vector2(1, 1) },
      u_origin: { value: new THREE.Vector2(0, 0) },
    };
    this.passMat = rawMaterial(fillVert, heightFrag, this.passUniforms);
    this.passMat.depthTest = false;
    this.passMat.depthWrite = false;
    this.passMesh = new THREE.Mesh(quadGeometry(), this.passMat);
    this.passMesh.frustumCulled = false;
    this.passScene.add(this.passMesh);
    this.reset();
  }

  cellCount(): number { return this.nx * this.ny; }

  dispose(): void {
    this.dropPending();
    this.rt.depthTexture?.dispose();
    this.rt.dispose();
    this.cutMat.dispose();
    this.passMat.dispose();
    this.cutMesh.geometry.dispose();
    this.passMesh.geometry.dispose();
  }

  /** 이 패스 동안만 렌더러 상태를 바꾸고 끝나면 되돌린다 */
  private withTarget<T>(target: THREE.WebGLRenderTarget, body: (gl: WebGL2RenderingContext) => T): T {
    const r = this.renderer;
    const prev = r.getRenderTarget();
    const autoClear = r.autoClear;
    r.autoClear = false;
    r.setRenderTarget(target);
    try { return body(r.getContext() as WebGL2RenderingContext); }
    finally { r.setRenderTarget(prev); r.autoClear = autoClear; }
  }

  /** 소재를 처음(깎이지 않은) 상태로: 깊이 1.0(= 소재 윗면), 색 -1 */
  reset(): void {
    this.dropPending();
    this.withTarget(this.rt, (gl) => {
      this.renderer.state.buffers.depth.setMask(true);
      this.renderer.state.buffers.color.setMask(true);
      gl.clearBufferfv(gl.COLOR, 0, new Float32Array([-1, 0, 0, 0]));
      gl.clearBufferfv(gl.DEPTH, 0, new Float32Array([1]));
    });
  }

  private dropPending(): void {
    const gl = this.renderer.getContext() as WebGL2RenderingContext;
    for (const p of this.pending) gl.deleteQuery(p.query);
    this.pending = [];
  }

  hasPending(): boolean { return this.pending.length > 0; }

  /** 결과가 나온 급속 선분 질의를 순서대로 거둔다. 소재를 낮춘 선분의 (src, seq) 목록. 아직 안 나온 것은 남긴다. */
  poll(): { src: number | null; seq: number }[] {
    const gl = this.renderer.getContext() as WebGL2RenderingContext;
    const hits: { src: number | null; seq: number }[] = [];
    while (this.pending.length) {
      const p = this.pending[0]!;
      if (!gl.getQueryParameter(p.query, gl.QUERY_RESULT_AVAILABLE)) break;
      if (gl.getQueryParameter(p.query, gl.QUERY_RESULT)) hits.push({ src: p.src, seq: p.seq });
      gl.deleteQuery(p.query);
      this.pending.shift();
    }
    return hits;
  }

  /** 선분 인스턴스 버퍼 한 묶음 그리기 */
  private draw(rows: Float32Array, n: number): void {
    const g = this.cutMesh.geometry as THREE.InstancedBufferGeometry;
    const old = Object.keys(g.attributes).filter((k) => k.startsWith('a_'));
    for (const k of old) g.deleteAttribute(k);
    const stride = 12;
    const attr = (name: string, off: number): void => {
      const a = new Float32Array(n * 4);
      for (let i = 0; i < n; i++) for (let k = 0; k < 4; k++) a[i * 4 + k] = rows[i * stride + off + k]!;
      g.setAttribute(name, new THREE.InstancedBufferAttribute(a, 4));
    };
    attr('a_seg_xy', 0); attr('a_seg_z', 4); attr('a_prof', 8);
    g.instanceCount = n;
    this.renderer.render(this.cutScene, this.camera);
  }

  /**
   * seg[from, to) 를 깎는다(tools[slot]이 공구). 공구 형상을 GPU가 모르면 Error(호출부가 CPU 엔진으로 가야 한다).
   * 급속 선분은 하나씩 따로 그리며 질의를 건다(결과는 poll()로 나중에 거둔다).
   */
  cutRange(seg: SimSegments, tools: readonly (ToolShape | null)[], from: number, to: number): void {
    const rows = new Float32Array(Math.min(Math.max(to - from, 0), GPU_CHUNK_SEGMENTS) * 12);
    const params = tools.map((t) => {
      if (!t) return null;
      const p = t.profileParams();
      if (!p) throw new Error(`GPU 엔진이 모르는 공구 형상입니다(${t.typeName}) — CPU 엔진으로 깎아야 합니다`);
      return p;
    });
    this.withTarget(this.rt, (gl) => {
      this.renderer.state.buffers.depth.setMask(true);
      this.renderer.state.buffers.color.setMask(true);
      let n = 0;
      const flush = (): void => { if (n) { this.draw(rows, n); n = 0; } };
      for (let m = from; m < to; m++) {
        const slot = seg.slot[m]!;
        const tool = slot >= 0 ? tools[slot] ?? null : null;
        const p = slot >= 0 ? params[slot] ?? null : null;
        if (!tool || !p) continue;
        const az = seg.p0[m * 3 + 2]!, bz = seg.p1[m * 3 + 2]!;
        if (Math.min(az, bz) >= this.ztop) continue;
        const o = n * 12;
        rows[o] = seg.p0[m * 3]! - this.x0;
        rows[o + 1] = seg.p0[m * 3 + 1]! - this.y0;
        rows[o + 2] = seg.p1[m * 3]! - this.x0;
        rows[o + 3] = seg.p1[m * 3 + 1]! - this.y0;
        rows[o + 4] = az;
        rows[o + 5] = bz;
        rows[o + 6] = seg.color[m]!;
        rows[o + 7] = tool.radius;
        rows[o + 8] = p[0]; rows[o + 9] = p[1]; rows[o + 10] = p[2]; rows[o + 11] = p[3];
        if (seg.rapid[m]) {
          // 급속 선분은 따로 그려 "소재를 낮췄는가"를 질의로 본다(이전까지 쌓인 것을 먼저 그린다)
          flush();
          rows.copyWithin(0, o, o + 12);
          const query = gl.createQuery();
          if (query) {
            gl.beginQuery(gl.ANY_SAMPLES_PASSED, query);
            try { this.draw(rows, 1); } finally { gl.endQuery(gl.ANY_SAMPLES_PASSED); }
            this.pending.push({ src: seg.src[m]! >= 0 ? seg.src[m]! : null, seq: seg.seq1[m]!, query });
          } else this.draw(rows, 1);
          continue;
        }
        n++;
        if (n >= GPU_CHUNK_SEGMENTS) flush();
      }
      flush();
    });
  }

  /** 깊이 → 높이·색 텍스처(표시용). block > 1이면 블록 최솟값으로 줄인다. target은 count=2(높이, 색) R32F 렌더 대상. */
  convertTo(target: THREE.WebGLRenderTarget, block: [number, number], origin: [number, number] = [0, 0]): void {
    (this.passUniforms.u_block!.value as THREE.Vector2).set(block[0], block[1]);
    (this.passUniforms.u_origin!.value as THREE.Vector2).set(origin[0], origin[1]);
    this.withTarget(target, () => { this.renderer.render(this.passScene, this.camera); });
  }

  /**
   * 지금 상태를 CPU 배열로 읽는다((ny*nx) 높이·색 id). STL 내보내기·시험용 — 느리니 필요할 때만.
   * 휴대폰 GPU는 RGBA/FLOAT 읽기만 보장하므로 RGBA32F 대상에 행 띠(STRIP_ROWS)씩 나눠 읽는다(메모리도 억제).
   */
  read(): { heights: Float32Array; colorIds: Int16Array } {
    const strip = Math.min(GpuCutter.STRIP_ROWS, this.ny);
    const target = new THREE.WebGLRenderTarget(this.nx, strip, {
      count: 2, type: THREE.FloatType, format: THREE.RGBAFormat,
      minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: false, generateMipmaps: false,
    });
    const heights = new Float32Array(this.nx * this.ny);
    const colorIds = new Int16Array(this.nx * this.ny);
    const hb = new Float32Array(this.nx * strip * 4);
    const cb = new Float32Array(this.nx * strip * 4);
    try {
      for (let y0 = 0; y0 < this.ny; y0 += strip) {
        const rows = Math.min(strip, this.ny - y0);
        this.convertTo(target, [1, 1], [0, y0]);
        this.renderer.readRenderTargetPixels(target, 0, 0, this.nx, rows, hb, undefined, 0);
        this.renderer.readRenderTargetPixels(target, 0, 0, this.nx, rows, cb, undefined, 1);
        for (let i = 0; i < this.nx * rows; i++) {
          heights[y0 * this.nx + i] = hb[i * 4]!;
          colorIds[y0 * this.nx + i] = Math.round(cb[i * 4]!);
        }
      }
      return { heights, colorIds };
    } finally {
      target.dispose();
    }
  }
  private static readonly STRIP_ROWS = 512;
}

/** ZMapStock 과 같은 인터페이스인 GPU 소재. heights/colorIds 는 read()를 부른 뒤에만 의미가 있다. */
export class GpuZMapStock extends ZMapStock {
  readonly isGpu = true;
  /** 엔진이 한 번에 맡기는 선분 수 */
  readonly chunk = GPU_CHUNK_SEGMENTS;
  readonly cutter: GpuCutter;
  /** 마지막 cutRange 때 GPU를 썼나(공구를 몰라 CPU로 갔으면 false) — 시험·표시용 */
  lastCutUsedGpu = false;
  private synced = true;

  constructor(renderer: THREE.WebGLRenderer, bounds: Bounds, resolution: number) {
    super(bounds, resolution, false);
    this.cutter = new GpuCutter(renderer, bounds, resolution);
  }

  override reset(): void {
    this.cutter.reset();     // 아직 안 나온 질의도 버린다
    this.rapidWarnings = [];
    this.synced = false;
  }

  override cutRange(seg: SimSegments, tools: readonly (ToolShape | null)[], from: number, to: number): void {
    this.cutter.cutRange(seg, tools, from, to);
    this.collect();
    this.lastCutUsedGpu = true;
    this.synced = false;
  }

  /** 끝난 급속 선분 질의를 rapidWarnings 에 반영한다 */
  collect(): void { for (const h of this.cutter.poll()) this.rapidWarnings.push(h); }

  /** 모든 질의 결과가 나올 때까지 기다린다(결과는 작업이 끝난 뒤에야 나온다) */
  async settle(): Promise<void> {
    this.collect();
    while (this.cutter.hasPending()) {
      await new Promise<void>((r) => setTimeout(r, 0));
      this.collect();
    }
  }

  /** GPU 상태를 heights/colorIds 로 읽어 와(STL·충돌 표시 등이 쓰는) ZMapStock 배열을 채운다 */
  sync(): void {
    if (this.synced && this.heights.length) return;
    const { heights, colorIds } = this.cutter.read();
    this.heights = heights;
    this.colorIds = colorIds;
    this.synced = true;
  }

  override anyCut(): boolean { this.sync(); return super.anyCut(); }
  override snapshot(): { h: Float32Array; c: Int16Array } { this.sync(); return super.snapshot(); }
  override restore(): void { throw new Error('GPU 소재는 스냅샷 복원을 쓰지 않는다(처음부터 다시 깎는다)'); }

  dispose(): void { this.cutter.dispose(); }
}

// ───────────────────────────── 표시 ─────────────────────────────

function srgbEncode(v: number): number {
  const c = Math.min(Math.max(v, 0), 1);
  return c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
}

/** 색 id → 화면 색(기존 메시 경로의 정점 색과 같은 겉모습이 되도록 sRGB로 인코딩해서 넣는다) */
export function buildPaletteData(colorOf: (id: number) => readonly [number, number, number], count: number): Float32Array {
  const out = new Float32Array(Math.max(count, 1) * 4);
  for (let i = 0; i < count; i++) {
    const c = colorOf(i);
    out[i * 4] = srgbEncode(c[0]); out[i * 4 + 1] = srgbEncode(c[1]); out[i * 4 + 2] = srgbEncode(c[2]); out[i * 4 + 3] = 1;
  }
  return out;
}

function dataTexture(data: Float32Array, w: number, h: number, format: THREE.PixelFormat): THREE.DataTexture {
  const t = new THREE.DataTexture(data, w, h, format, THREE.FloatType);
  t.internalFormat = format === THREE.RedFormat ? 'R32F' : 'RGBA32F';
  t.minFilter = THREE.NearestFilter;
  t.magFilter = THREE.NearestFilter;
  t.generateMipmaps = false;
  t.needsUpdate = true;
  return t;
}

/** 깎인 소재 표시: 높이 텍스처를 정점 셰이더가 읽는다. add()로 장면에 넣고 update()로 지금 상태를 반영한다. */
export class GpuSurface extends THREE.Group {
  private display: THREE.WebGLRenderTarget | null = null;
  private meshes: THREE.Mesh[] = [];
  private textures: THREE.Texture[] = [];
  private shared: Record<string, THREE.IUniform> | null = null;
  private dn: [number, number] = [0, 0];
  private key = '';

  /** 지금 상태를 그린다. 소재 크기가 바뀌었으면 표시 자원을 새로 만든다. */
  update(stock: GpuZMapStock, colorOf: (id: number) => readonly [number, number, number], colorCount: number): void {
    const c = stock.cutter;
    const block = displayBlock(c.nx, c.ny);
    const dnx = Math.ceil(c.nx / block[0]);
    const dny = Math.ceil(c.ny / block[1]);
    const key = `${c.nx}x${c.ny}/${block}/${stock.resolution}/${c.x0},${c.y0}/${colorCount}`;
    if (key !== this.key || !this.display) this.build(stock, block, dnx, dny, colorOf, colorCount, key);
    c.convertTo(this.display!, block);
  }

  private build(stock: GpuZMapStock, block: [number, number], dnx: number, dny: number,
    colorOf: (id: number) => readonly [number, number, number], colorCount: number, key: string): void {
    this.disposeResources();
    this.key = key;
    this.dn = [dnx, dny];
    const c = stock.cutter;
    this.display = floatTarget(dnx, dny, 2);
    const xs = new Float32Array(dnx), ys = new Float32Array(dny);
    // 표시 격자 열 i = 계산 칸 [i*bx, i*bx+bx) 블록의 가운데
    for (let i = 0; i < dnx; i++) xs[i] = c.x0 + (Math.min(i * block[0] + (block[0] - 1) / 2, c.nx - 1)) * stock.resolution;
    for (let j = 0; j < dny; j++) ys[j] = c.y0 + (Math.min(j * block[1] + (block[1] - 1) / 2, c.ny - 1)) * stock.resolution;
    const xsT = dataTexture(xs, dnx, 1, THREE.RedFormat);
    const ysT = dataTexture(ys, dny, 1, THREE.RedFormat);
    const palette = dataTexture(buildPaletteData(colorOf, colorCount), Math.max(colorCount, 1), 1, THREE.RGBAFormat);
    this.textures = [xsT, ysT, palette];
    const def = DEFAULT_STOCK_COLOR.map(srgbEncode);
    this.shared = {
      u_height: { value: this.display.textures[0] }, u_cid: { value: this.display.textures[1] },
      u_xs: { value: xsT }, u_ys: { value: ysT }, u_palette: { value: palette },
      u_n: { value: new THREE.Vector2(dnx, dny) }, u_zlo: { value: c.zlo },
      u_default: { value: new THREE.Vector4(def[0], def[1], def[2], 1) },
      u_stops: { value: [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()] },
      u_depth: { value: new THREE.Vector2(c.ztop, c.zlo) },
      u_mode: { value: 0 }, u_palette_n: { value: colorCount },
      u_mvp: { value: new THREE.Matrix4() }, u_mv: { value: new THREE.Matrix4() },
    };
    const make = (side: number, vertices: number, instances: number): void => {
      const g = new THREE.InstancedBufferGeometry();
      g.setIndex(new THREE.BufferAttribute(stripIndex(vertices), 1));
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3), 3));
      g.instanceCount = instances;
      const mat = rawMaterial(surfaceVert, surfaceFrag, { ...this.shared!, u_side: { value: side } });
      mat.depthTest = true;
      mat.depthWrite = true;
      const mesh = new THREE.Mesh(g, mat);
      mesh.frustumCulled = false;
      const mvp = this.shared!.u_mvp!.value as THREE.Matrix4;
      const mv = this.shared!.u_mv!.value as THREE.Matrix4;
      mesh.onBeforeRender = (_r, _s, camera) => {
        mv.multiplyMatrices(camera.matrixWorldInverse, mesh.matrixWorld);
        mvp.multiplyMatrices(camera.projectionMatrix, mv);
      };
      this.meshes.push(mesh);
      this.add(mesh);
    };
    make(-1, dnx * 2, dny - 1);          // 윗면: 행 하나 = 인스턴스 하나
    make(0, dnx * 2, 1);                 // 앞(y 최소)
    make(1, dnx * 2, 1);                 // 뒤
    make(2, dny * 2, 1);                 // 왼쪽
    make(3, dny * 2, 1);                 // 오른쪽
  }

  /** 마지막으로 만든 표시 격자 크기 — 시험·정보 표시용 */
  displaySize(): [number, number] { return this.dn; }

  private disposeResources(): void {
    for (const m of this.meshes) { this.remove(m); m.geometry.dispose(); (m.material as THREE.Material).dispose(); }
    this.meshes = [];
    for (const t of this.textures) t.dispose();
    this.textures = [];
    this.display?.dispose();
    this.display = null;
    this.key = '';
  }

  dispose(): void { this.disposeResources(); }
}
