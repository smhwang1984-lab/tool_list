// 절삭 선분 만들기 — 원본 NCViewerWidget._rebuild_sim_nodes (밀링 Z-map 경로)
import type { ToolpathResult, Vec3 } from '../core/toolpath';
import type { SimSegments } from './zmap';
import { toolShapeFromValues, type ToolShape, type ToolValues } from './toolShape';

export interface SimProgram {
  seg: SimSegments;
  tools: (ToolShape | null)[];
  /** 공정마다 첫 절삭 선분 번호(스냅샷 위치) */
  snapPositions: number[];
  /** 'voxel' 이면 공구 축이 기운 절삭 이동이 있어 3D 소재가 필요하다(원본 sim_engine '3d') */
  engine: 'zmap' | 'voxel';
  /** 공구 축이 기운 선분 수 */
  tilted: number;
  /** 선분 시작/끝의 공구 축(단위벡터, count*3) — 3D 소재용 */
  axes0: Float64Array;
  axes1: Float64Array;
  /** 공구 형상을 만들 수 없는 공구 번호 */
  excluded: string[];
  /** 공구 번호(T)가 잡히지 않아 건너뛴 이동 수 */
  noToolMoves: number;
}

const isTilt = (a: Vec3 | undefined): boolean => !!a && Math.abs(a[2] - 1) > 1e-9;
const Z_AXIS: Vec3 = [0, 0, 1];
function unit(a: Vec3 | undefined): Vec3 {
  const v = a ?? Z_AXIS;
  const n = Math.hypot(v[0], v[1], v[2]);
  return n < 1e-12 ? [v[0], v[1], v[2]] : [v[0] / n, v[1] / n, v[2] / n];
}

export function buildSimProgram(res: ToolpathResult, shapeMap: ReadonlyMap<string, ToolValues>): SimProgram {
  const shapes = new Map<string, ToolShape | null>();
  const excluded = new Set<string>();
  const tools: (ToolShape | null)[] = [];
  const slotOf = new Map<string, number>();
  let noToolMoves = 0;
  const rows: { p0: Vec3; p1: Vec3; seq1: number; src: number; rapid: boolean; slot: number; color: number; tilt: boolean; a0: Vec3; a1: Vec3 }[] = [];
  let colorIdx = -1;
  for (const [key, path] of res.tool_paths) {
    colorIdx++;
    const toolNo = res.process_tool_map.get(key) ?? '';
    if (!shapes.has(toolNo)) {
      const values = shapeMap.get(toolNo);
      const shape = values ? toolShapeFromValues(values) : null;
      shapes.set(toolNo, shape);
      if (!shape && toolNo) excluded.add(toolNo);
    }
    const shape = shapes.get(toolNo) ?? null;
    if (!shape) {
      if (!toolNo) noToolMoves += path.filter((n) => n.valid && n.type !== 'G00').length;
      continue;
    }
    if (!slotOf.has(toolNo)) { slotOf.set(toolNo, tools.length); tools.push(shape); }
    const slot = slotOf.get(toolNo)!;
    let prev: (typeof path)[number] | null = null;
    for (const node of path) {
      if (!node.valid) { prev = null; continue; }
      if (prev) {
        rows.push({
          p0: prev.pt, p1: node.pt, seq1: node.seq ?? 0, src: node.src_line ?? -1, rapid: node.type === 'G00', slot, color: colorIdx,
          tilt: isTilt(res.line_axis_map.get(prev.src_line)) || isTilt(res.line_axis_map.get(node.src_line)),
          a0: unit(res.line_axis_map.get(prev.src_line)), a1: unit(res.line_axis_map.get(node.src_line)),
        });
      }
      prev = node;
    }
  }
  // seq1 기준 안정 정렬(원본 np.argsort kind='stable')
  const order = rows.map((_, i) => i).sort((a, b) => rows[a]!.seq1 - rows[b]!.seq1 || a - b);
  const count = order.length;
  const seg: SimSegments = {
    count, p0: new Float64Array(count * 3), p1: new Float64Array(count * 3), seq1: new Int32Array(count),
    src: new Int32Array(count), rapid: new Uint8Array(count), slot: new Int32Array(count), color: new Int16Array(count),
  };
  const axes0 = new Float64Array(count * 3);
  const axes1 = new Float64Array(count * 3);
  let tilted = 0;
  let cutTilted = 0;
  const colorFirst = new Map<number, number>();
  order.forEach((ri, m) => {
    const r = rows[ri]!;
    seg.p0.set(r.p0, m * 3);
    seg.p1.set(r.p1, m * 3);
    seg.seq1[m] = r.seq1;
    seg.src[m] = r.src;
    seg.rapid[m] = r.rapid ? 1 : 0;
    seg.slot[m] = r.slot;
    axes0.set(r.a0, m * 3);
    axes1.set(r.a1, m * 3);
    if (r.tilt) { tilted++; if (!r.rapid) cutTilted++; }
    seg.color[m] = r.color;
    if (!colorFirst.has(r.color)) colorFirst.set(r.color, m);
  });
  const snapPositions = [...colorFirst.values()].sort((a, b) => a - b);
  return { seg, tools, snapPositions, engine: cutTilted > 0 ? 'voxel' : 'zmap', tilted, axes0, axes1, excluded: [...excluded], noToolMoves };
}

/** 절삭 이송(G01/G02/G03) 노드의 XYZ 범위 + 여유(mm). 없으면 null (원본 toolpath_bounds) */
export function toolpathBounds(res: ToolpathResult, margin = 2): { X: [number, number]; Y: [number, number]; Z: [number, number] } | null {
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  let any = false;
  for (const path of res.tool_paths.values()) {
    for (const n of path) {
      if (!n.valid || n.type === 'G00') continue;
      any = true;
      for (let i = 0; i < 3; i++) { lo[i] = Math.min(lo[i]!, n.pt[i]!); hi[i] = Math.max(hi[i]!, n.pt[i]!); }
    }
  }
  if (!any) return null;
  return {
    X: [lo[0]! - margin, hi[0]! + margin], Y: [lo[1]! - margin, hi[1]! + margin], Z: [lo[2]! - margin, hi[2]! + margin],
  };
}
