// 소재(STOCK) 창 — 원본 StockDialog(밀링). T/W/L 치수 · 축 배정 · 기준 위치 · 추가 이동 · 해상도 · 형상 켜기.
import { getPref, setPref } from '../platform/prefs';
import { AXES, DIM_KEYS, StockSpec, parseStockSizeComment, type Axis, type Bounds, type DimKey, type Reference } from '../sim/stock';
import type { SimStatus } from '../viewer/simLayer';
import { el, showDialog, toast } from './dialog';
import { precisionRow } from './precisionRow';

export interface StockDialogContext {
  /** 프로그램 줄(주석에서 소재 치수를 읽는다) */
  lines: () => string[];
  /** 툴패스 범위 + 여유(mm). 경로가 없으면 null */
  toolpathBounds: (margin: number) => Bounds | null;
  /** resolution null = 자동 */
  apply: (spec: StockSpec, resolution: number | null, enabled: boolean) => void;
  clear: () => void;
  status: () => SimStatus;
  /** 급속 절삭 줄로 이동 */
  gotoLine: (line: number) => void;
  /** 툴패스 선 표시/숨김 */
  setToolpathVisible: (on: boolean) => void;
}

const XY_REFS: [Reference, string][] = [['center', '중심'], ['neg', '-쪽 끝 = 0'], ['pos', '+쪽 끝 = 0']];
const Z_REFS: [Reference, string][] = [['top', '윗면 = 0'], ['bottom', '바닥 = 0'], ['center', '중심']];
const DIM_LABEL: Record<DimKey, string> = { T: 'T (두께)', W: 'W (폭)', L: 'L (길이)' };
const RES_ITEMS = ['자동', '0.05', '0.1', '0.2', '0.5', '1.0'];
const KEY = 'sim_stock_v1';

interface Saved {
  dims: Record<DimKey, number>;
  axisOf: Record<DimKey, Axis>;
  ref: Record<Axis, Reference>;
  offset: Record<Axis, number>;
  resolution: string;
  enabled: boolean;
  seenComment: string;
}

const defaults = (): Saved => ({
  dims: { T: 50, W: 100, L: 100 }, axisOf: { T: 'Z', W: 'Y', L: 'X' }, ref: { X: 'center', Y: 'center', Z: 'top' },
  offset: { X: 0, Y: 0, Z: 0 }, resolution: '자동', enabled: true, seenComment: '',
});

function load(): Saved {
  try {
    const raw = getPref(KEY);
    if (raw) return { ...defaults(), ...(JSON.parse(raw) as Partial<Saved>) };
  } catch { /* 저장값이 깨졌으면 기본값 */ }
  return defaults();
}

let openDialog: HTMLDialogElement | null = null;

export function showStockDialog(ctx: StockDialogContext): void {
  if (openDialog?.isConnected) return;
  const s = load();
  const body = el('div', { class: 'stock-body' });
  const note = el('div', { class: 'stock-note' });
  const boundsLabel = el('div', { class: 'stock-bounds' });
  const statusLabel = el('div', { class: 'stock-status' });

  const fromComment = parseStockSizeComment(ctx.lines());
  const commentKey = fromComment ? JSON.stringify(fromComment) : '';
  if (fromComment && commentKey !== s.seenComment) {
    s.dims = { ...fromComment };
    s.seenComment = commentKey;
    note.textContent = `프로그램 주석 (STOCK SIZE) 에서 치수를 읽었습니다: T${fromComment.T} W${fromComment.W} L${fromComment.L}`;
  } else if (fromComment) note.textContent = '프로그램 주석에 STOCK SIZE 가 있습니다(고친 값은 그대로 둡니다).';
  else note.textContent = '프로그램 상단에 (STOCK SIZE : T50 W95 L385) 주석을 쓰면 치수를 자동으로 읽습니다.';

  const num = (value: number, step = '0.1'): HTMLInputElement => {
    const i = el('input', { type: 'number', step, inputmode: 'decimal' });
    i.value = String(value);
    return i;
  };
  const select = (items: readonly (readonly [string, string])[], value: string): HTMLSelectElement => {
    const sel = el('select');
    for (const [v, label] of items) sel.append(new Option(label, v));
    sel.value = value;
    return sel;
  };
  const row = (label: string, ...controls: HTMLElement[]): HTMLElement => {
    const r = el('div', { class: 'stock-row' });
    const name = el('span');
    name.textContent = label;
    r.append(name, ...controls);
    return r;
  };

  const dimInputs = {} as Record<DimKey, HTMLInputElement>;
  const axisSelects = {} as Record<DimKey, HTMLSelectElement>;
  for (const k of DIM_KEYS) {
    dimInputs[k] = num(s.dims[k]);
    axisSelects[k] = select(AXES.map((a) => [a, a] as const), s.axisOf[k]);
    body.append(row(DIM_LABEL[k], dimInputs[k], axisSelects[k]));
  }
  const refSelects = {} as Record<Axis, HTMLSelectElement>;
  const offInputs = {} as Record<Axis, HTMLInputElement>;
  for (const a of AXES) {
    refSelects[a] = select(a === 'Z' ? Z_REFS : XY_REFS, s.ref[a]);
    offInputs[a] = num(s.offset[a]);
    body.append(row(`${a} 기준 / 이동`, refSelects[a], offInputs[a]));
  }
  const resSelect = select(RES_ITEMS.map((r) => [r, r] as const), s.resolution);
  { const r = row('해상도(mm)', resSelect); r.classList.add('single'); body.append(r); }
  body.append(precisionRow());
  const margin = num(2, '1');
  const fitBtn = el('button', { type: 'button' });
  fitBtn.textContent = '툴패스 범위에 맞추기';
  body.append(row('여유(mm)', margin, fitBtn));
  const enable = el('input', { type: 'checkbox' });
  enable.checked = s.enabled;
  const enableLabel = el('label', { class: 'stock-enable' });
  enableLabel.append(enable, document.createTextNode(' 가공 형상 표시'));
  const lineLabel = el('label', { class: 'stock-enable' });
  const lineCheck = el('input', { type: 'checkbox' });
  lineCheck.checked = getPref('sim_toolpath_visible') !== '0';
  lineCheck.addEventListener('change', () => { setPref('sim_toolpath_visible', lineCheck.checked ? '1' : '0'); ctx.setToolpathVisible(lineCheck.checked); });
  lineLabel.append(lineCheck, document.createTextNode(' 툴패스 선 표시 (끄면 가공 형상이 잘 보입니다)'));
  body.append(enableLabel, lineLabel, boundsLabel, note, statusLabel);

  const readSpec = (): StockSpec => {
    const dims = {} as Record<DimKey, number>;
    const axisOf = {} as Record<DimKey, Axis>;
    for (const k of DIM_KEYS) { dims[k] = parseFloat(dimInputs[k].value) || 0; axisOf[k] = axisSelects[k].value as Axis; }
    const reference = {} as Record<Axis, Reference>;
    const offset = {} as Record<Axis, number>;
    for (const a of AXES) { reference[a] = refSelects[a].value as Reference; offset[a] = parseFloat(offInputs[a].value) || 0; }
    return new StockSpec(dims, axisOf, reference, offset);
  };
  const updatePreview = (): void => {
    try {
      const b = readSpec().bounds();
      boundsLabel.textContent = `X ${b.X[0].toFixed(1)} ~ ${b.X[1].toFixed(1)}  /  Y ${b.Y[0].toFixed(1)} ~ ${b.Y[1].toFixed(1)}  /  Z ${b.Z[0].toFixed(1)} ~ ${b.Z[1].toFixed(1)}`;
    } catch (e) { boundsLabel.textContent = (e as Error).message; }
  };
  const refreshStatus = (): void => {
    const st = ctx.status();
    const parts: string[] = [];
    if (st.hasStock) parts.push(`${st.engine === 'voxel' ? '3D 복셀' : 'Z-map'} 격자 ${st.nx}×${st.ny}${st.engine === 'voxel' ? '×' + st.nz : ''} (${(st.cells / 1000).toFixed(0)}천 칸, ${st.resolution}mm) · 깎은 선분 ${st.cutSegments}/${st.totalSegments}${st.busy ? ' · 계산 중…' : ''}`);
    if (st.engine === 'voxel' || st.tilted) parts.push(`공구 축이 기운 이동 ${st.tilted}개가 있어 3D 복셀로 깎습니다(자동 해상도는 거칠 수 있습니다).`);
    if (st.excluded.length) parts.push(`공구 형상을 못 만든 공구(지름 없음): ${st.excluded.join(', ')}`);
    if (st.noToolMoves) parts.push(`공구 번호가 없는 공정 이동 ${st.noToolMoves}개는 깎지 않습니다.`);
    if (st.rapidLines.length) parts.push(`급속(G00)이 소재를 깎은 줄: ${st.rapidLines.map((l) => l + 1).join(', ')}`);
    statusLabel.textContent = parts.join('\n');
  };

  // 축 배정이 겹치면 원래 쓰던 키를 비어 버린 축으로 돌려 준다(2-way swap)
  for (const k of DIM_KEYS) {
    axisSelects[k].addEventListener('change', () => {
      const counts: Record<string, number> = {};
      for (const kk of DIM_KEYS) counts[axisSelects[kk].value] = (counts[axisSelects[kk].value] ?? 0) + 1;
      const dup = Object.keys(counts).find((a) => counts[a]! > 1);
      if (dup) {
        const missing = AXES.find((a) => !(a in counts))!;
        const other = DIM_KEYS.find((kk) => kk !== k && axisSelects[kk].value === dup)!;
        axisSelects[other].value = missing;
      }
      updatePreview();
    });
  }
  for (const i of [...Object.values(dimInputs), ...Object.values(offInputs)]) i.addEventListener('input', updatePreview);
  for (const r of Object.values(refSelects)) r.addEventListener('change', updatePreview);
  fitBtn.addEventListener('click', () => {
    const b = ctx.toolpathBounds(parseFloat(margin.value) || 0);
    if (!b) { toast('절삭 이송(G01/G02/G03) 경로가 없습니다.'); return; }
    for (const k of DIM_KEYS) {
      const [lo, hi] = b[axisSelects[k].value as Axis];
      dimInputs[k].value = String(Math.max(Math.round((hi - lo) * 100) / 100, 0.1));
    }
    for (const a of AXES) {
      refSelects[a].value = 'center';
      offInputs[a].value = String(Math.round(((b[a][0] + b[a][1]) / 2) * 100) / 100);
    }
    updatePreview();
  });
  updatePreview();
  refreshStatus();

  const save = (): void => {
    const dims = {} as Record<DimKey, number>;
    const axisOf = {} as Record<DimKey, Axis>;
    for (const k of DIM_KEYS) { dims[k] = parseFloat(dimInputs[k].value) || 0; axisOf[k] = axisSelects[k].value as Axis; }
    const ref = {} as Record<Axis, Reference>;
    const offset = {} as Record<Axis, number>;
    for (const a of AXES) { ref[a] = refSelects[a].value as Reference; offset[a] = parseFloat(offInputs[a].value) || 0; }
    const saved: Saved = { dims, axisOf, ref, offset, resolution: resSelect.value, enabled: enable.checked, seenComment: commentKey || s.seenComment };
    setPref(KEY, JSON.stringify(saved));
  };

  const timer = window.setInterval(refreshStatus, 700);
  const dlg = showDialog('소재 (STOCK)', body, [
    { label: '소재 지우기', onClick: () => { ctx.clear(); } },
    { label: '닫기' },
    {
      label: '적용', primary: true,
      onClick: () => {
        let spec: StockSpec;
        try { spec = readSpec(); } catch (e) { toast((e as Error).message); return false; }
        const b = spec.bounds();
        if (!(b.X[1] > b.X[0] && b.Y[1] > b.Y[0] && b.Z[1] > b.Z[0])) { toast('소재 치수가 0 이하입니다.'); return false; }
        const resText = resSelect.value;
        const res = resText === '자동' ? null : parseFloat(resText);
        save();
        ctx.apply(spec, res, enable.checked);
        return true;
      },
    },
  ]);
  dlg.addEventListener('close', () => { window.clearInterval(timer); save(); });
  openDialog = dlg;
}
