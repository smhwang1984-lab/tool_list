// 선반 절삭 선분 만들기 — 원본 NCViewerWidget._rebuild_sim_nodes 의 선반 경로 (선삭·홈·중심 드릴)
import type { ToolGeometry } from '../core/latheInsertSpec';
import type { ToolpathResult, Vec3 } from '../core/toolpath';
import { latheToolFromGeometry, ToolShapeError, type LatheTool } from './latheTool';
import { entryAxes } from './latheEntry';
import type { ToolShape } from './toolShape';
import type { SimSegments } from './zmap';

export interface LatheProgram {
  /** 'lathe3d' = 턴밀(M35) 절삭이 있어 3D 복셀을 함께 쓴다 */
  engine: 'lathe' | 'lathe3d';
  tilted: 0;
  seg: SimSegments;
  tools: (LatheTool | null)[];
  /** 턴밀(3D)용 공구 형상(공구 슬롯별) */
  millTools: (ToolShape | null)[];
  snapPositions: number[];
  /** 선분별: 1 = 턴밀 */
  mill: Uint8Array;
  threadPitch: Float64Array;
  threadHeight: Float64Array;
  axes0: Float64Array;
  axes1: Float64Array;
  excluded: string[];
  /** 제외 사유(공구번호 → 이유) */
  excludedWhy: Record<string, string>;
  noToolMoves: number;
  turnmillMoves: number;
  turnmillSkipped: number;
  axisCorrected: number;
  threadMoves: number;
  /** 공구번호 → [이유, 이동 수] */
  unusable: Record<string, [string, number]>;
}

/** 공정 공구번호 → 형상 맵 키 후보 (T0101 → T01, T1, 1) */
function lookupKeys(toolNo: string): string[] {
  const t = toolNo.trim().toUpperCase();
  const keys = [t];
  const m = /^T?(\d{1,2})(\d{2})?$/.exec(t);
  if (m) { const n = parseInt(m[1]!, 10); keys.push(`T${String(n).padStart(2, '0')}`, `T${n}`, String(n)); }
  return keys;
}

interface Row {
  p0: Vec3; p1: Vec3; seq1: number; src: number; rapid: boolean; slot: number; color: number;
  mill: boolean; plane: string | null; cdeg: number | null; c0: number; c1: number; brk: boolean; tp: number; th: number;
}

export function buildLatheProgram(res: ToolpathResult, geometry: Readonly<Record<string, ToolGeometry>>): LatheProgram {
  const tools: (LatheTool | null)[] = [];
  const slotOf = new Map<string, number>();
  const cache = new Map<string, LatheTool | null>();
  const excluded = new Set<string>();
  const excludedWhy: Record<string, string> = {};
  const unusable: Record<string, [string, number]> = {};
  let noToolMoves = 0, turnmillMoves = 0, turnmillSkipped = 0, threadMoves = 0;
  const rows: Row[] = [];
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
    let processStart = true;
    for (let index = 0; index < path.length; index++) {
      const node = path[index]!;
      if (!node.valid) { prev = null; continue; }
      if (colorIdx === 0 && index === 0 && !node.pt.some((v) => v !== 0)) continue; // 프로그램 첫 공정의 가상 시작점
      if (prev) {
        const info = res.line_lathe_map.get(node.src_line);
        const mill = info ? info[0] : false;
        const plane = info ? info[1] : null;
        const thread = info ? info[2] : null;
        const cutting = node.type !== 'G00';
        if (mill && cutting) turnmillMoves++;
        const usable = mill ? tool.millShape !== null : tool.poly !== null;
        if (!usable) {
          if (mill && cutting) turnmillSkipped++;
          if (cutting) {
            const why = mill ? '선삭 공구라 턴밀(M35) 구간에서는 깎지 않음' : '턴밀 전용 공구라 선삭 구간(M35 밖)에서는 깎지 않음';
            const cur = unusable[toolNo];
            unusable[toolNo] = [why, (cur ? cur[1] : 0) + 1];
          }
        } else {
          rows.push({
            p0: prev.pt, p1: node.pt, seq1: node.seq ?? 0, src: node.src_line ?? -1, rapid: node.type === 'G00', slot, color: colorIdx,
            mill, plane, cdeg: res.line_to_c_rot.get(node.src_line) ?? null,
            c0: prev.c ?? res.line_to_c_rot.get(prev.src_line) ?? 0, c1: node.c ?? res.line_to_c_rot.get(node.src_line) ?? 0,
            brk: processStart, tp: thread ? thread[0] : 0, th: thread ? thread[1] : 0,
          });
          processStart = false;
          if (thread) {
            threadMoves++;
            // G76 은 끝나면 시작점으로 복귀한다 — 다음 이동은 시작점에서 출발한 것으로 본다
            prev = { ...node, pt: prev.pt };
            continue;
          }
        }
      }
      prev = node;
    }
  }
  // 턴밀 공구 축 = 가공 묶음 진입 벡터의 반대 방향(원본 결정 I). 수집(공정) 순서로 계산한다.
  const n = rows.length;
  const ax0: Vec3[] = Array.from({ length: n }, () => [1, 0, 0]);
  const ax1: Vec3[] = Array.from({ length: n }, () => [1, 0, 0]);
  let axisCorrected = 0;
  let anyMillCut = false;
  const idx: number[] = [];
  rows.forEach((r, i) => { if (r.mill) { idx.push(i); if (!r.rapid) anyMillCut = true; } });
  if (idx.length) {
    const brk = idx.map((rowI, k) => rows[rowI]!.brk || k === 0 || idx[k]! - idx[k - 1]! > 1);
    const out = entryAxes({
      p0: idx.map((i) => rows[i]!.p0), p1: idx.map((i) => rows[i]!.p1), rapid: idx.map((i) => rows[i]!.rapid), breaks: brk,
      planes: idx.map((i) => rows[i]!.plane), cAngles: idx.map((i) => rows[i]!.cdeg),
      cStart: idx.map((i) => rows[i]!.c0), cEnd: idx.map((i) => rows[i]!.c1),
    });
    idx.forEach((rowI, k) => { ax0[rowI] = out.axes0[k]!; ax1[rowI] = out.axes1[k]!; });
    axisCorrected = out.corrected;
  }
  const order = rows.map((_, i) => i).sort((a, b) => rows[a]!.seq1 - rows[b]!.seq1 || a - b);
  const count = n;
  const seg: SimSegments = {
    count, p0: new Float64Array(count * 3), p1: new Float64Array(count * 3), seq1: new Int32Array(count),
    src: new Int32Array(count), rapid: new Uint8Array(count), slot: new Int32Array(count), color: new Int16Array(count),
  };
  const mill = new Uint8Array(count), tpitch = new Float64Array(count), theight = new Float64Array(count);
  const axes0 = new Float64Array(count * 3), axes1 = new Float64Array(count * 3);
  const colorFirst = new Map<number, number>();
  order.forEach((ri, m) => {
    const r = rows[ri]!;
    seg.p0.set(r.p0, m * 3); seg.p1.set(r.p1, m * 3);
    seg.seq1[m] = r.seq1; seg.src[m] = r.src; seg.rapid[m] = r.rapid ? 1 : 0; seg.slot[m] = r.slot; seg.color[m] = r.color;
    mill[m] = r.mill ? 1 : 0; tpitch[m] = r.tp; theight[m] = r.th;
    axes0.set(ax0[ri]!, m * 3); axes1.set(ax1[ri]!, m * 3);
    if (!colorFirst.has(r.color)) colorFirst.set(r.color, m);
  });
  return {
    engine: anyMillCut ? 'lathe3d' : 'lathe', tilted: 0, seg, tools, millTools: tools.map((t) => t?.millShape ?? null), mill, threadPitch: tpitch, threadHeight: theight,
    axes0, axes1, snapPositions: [...colorFirst.values()].sort((a, b) => a - b), excluded: [...excluded], excludedWhy, noToolMoves,
    turnmillMoves, turnmillSkipped, axisCorrected, threadMoves, unusable,
  };
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
