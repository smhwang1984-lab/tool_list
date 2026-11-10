// 선반 절삭 선분 만들기 — 원본 NCViewerWidget._rebuild_sim_nodes 의 선반 경로 (선삭·홈·중심 드릴)
import type { ToolGeometry } from '../core/latheInsertSpec';
import type { ToolpathResult, Vec3 } from '../core/toolpath';
import { latheToolFromGeometry, ToolShapeError, type LatheTool } from './latheTool';
import type { SimSegments } from './zmap';

export interface LatheProgram {
  engine: 'lathe';
  tilted: 0;
  seg: SimSegments;
  tools: (LatheTool | null)[];
  snapPositions: number[];
  excluded: string[];
  /** 제외 사유(공구번호 → 이유) */
  excludedWhy: Record<string, string>;
  noToolMoves: number;
}

/** 공정 공구번호 → 형상 맵 키 후보 (T0101 → T01, T1, 1) */
function lookupKeys(toolNo: string): string[] {
  const t = toolNo.trim().toUpperCase();
  const keys = [t];
  const m = /^T?(\d{1,2})(\d{2})?$/.exec(t);
  if (m) { const n = parseInt(m[1]!, 10); keys.push(`T${String(n).padStart(2, '0')}`, `T${n}`, String(n)); }
  return keys;
}

export function buildLatheProgram(res: ToolpathResult, geometry: Readonly<Record<string, ToolGeometry>>): LatheProgram {
  const tools: (LatheTool | null)[] = [];
  const slotOf = new Map<string, number>();
  const cache = new Map<string, LatheTool | null>();
  const excluded = new Set<string>();
  const excludedWhy: Record<string, string> = {};
  let noToolMoves = 0;
  const rows: { p0: Vec3; p1: Vec3; seq1: number; src: number; rapid: boolean; slot: number; color: number }[] = [];
  let colorIdx = -1;
  for (const [key, path] of res.tool_paths) {
    colorIdx++;
    const toolNo = res.process_tool_map.get(key) ?? '';
    if (!cache.has(toolNo)) {
      const g = lookupKeys(toolNo).map((k) => geometry[k]).find((x) => !!x);
      let tool: LatheTool | null = null;
      if (g) {
        try { tool = latheToolFromGeometry(g, toolNo); } catch (e) {
          if (!(e instanceof ToolShapeError)) throw e;
          excludedWhy[toolNo] = e.message;
        }
      } else if (toolNo) excludedWhy[toolNo] = '툴리스트에 이 공구가 없음';
      cache.set(toolNo, tool);
      if (!tool && toolNo) excluded.add(toolNo);
    }
    const tool = cache.get(toolNo) ?? null;
    if (!tool) {
      if (!toolNo) noToolMoves += path.filter((n) => n.valid && n.type !== 'G00').length;
      continue;
    }
    if (!slotOf.has(toolNo)) { slotOf.set(toolNo, tools.length); tools.push(tool); }
    const slot = slotOf.get(toolNo)!;
    let prev: (typeof path)[number] | null = null;
    for (const node of path) {
      if (!node.valid) { prev = null; continue; }
      if (prev) rows.push({ p0: prev.pt, p1: node.pt, seq1: node.seq ?? 0, src: node.src_line ?? -1, rapid: node.type === 'G00', slot, color: colorIdx });
      prev = node;
    }
  }
  const order = rows.map((_, i) => i).sort((a, b) => rows[a]!.seq1 - rows[b]!.seq1 || a - b);
  const count = order.length;
  const seg: SimSegments = {
    count, p0: new Float64Array(count * 3), p1: new Float64Array(count * 3), seq1: new Int32Array(count),
    src: new Int32Array(count), rapid: new Uint8Array(count), slot: new Int32Array(count), color: new Int16Array(count),
  };
  const colorFirst = new Map<number, number>();
  order.forEach((ri, m) => {
    const r = rows[ri]!;
    seg.p0.set(r.p0, m * 3); seg.p1.set(r.p1, m * 3);
    seg.seq1[m] = r.seq1; seg.src[m] = r.src; seg.rapid[m] = r.rapid ? 1 : 0; seg.slot[m] = r.slot; seg.color[m] = r.color;
    if (!colorFirst.has(r.color)) colorFirst.set(r.color, m);
  });
  return { engine: 'lathe', tilted: 0, seg, tools, snapPositions: [...colorFirst.values()].sort((a, b) => a - b), excluded: [...excluded], excludedWhy, noToolMoves };
}

/** 이동선분의 (z, r) 범위 + 여유로 소재 후보 크기를 구한다(절삭 이송만) */
export function latheToolpathExtent(res: ToolpathResult): { zMin: number; zMax: number; rMax: number } | null {
  let zMin = Infinity, zMax = -Infinity, rMax = 0, any = false;
  for (const path of res.tool_paths.values()) for (const n of path) {
    if (!n.valid || n.type === 'G00') continue;
    any = true; zMin = Math.min(zMin, n.pt[0]); zMax = Math.max(zMax, n.pt[0]);
    rMax = Math.max(rMax, Math.abs(n.pt[2]), Math.hypot(n.pt[1], n.pt[2]));
  }
  return any ? { zMin, zMax, rMax } : null;
}
