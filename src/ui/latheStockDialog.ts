// 선반 소재 창 — 원본 LatheStockDialog (지름·길이·앞면 Z·내경·해상도)
import { getPref, setPref } from '../platform/prefs';
import { LatheStockSpec } from '../sim/latheStock';
import type { SimStatus } from '../viewer/simLayer';
import { el, showDialog, toast } from './dialog';
import { precisionRow } from './precisionRow';

export interface LatheStockDialogContext {
  /** 툴패스 (z, r) 범위. 없으면 null */
  extent: () => { zMin: number; zMax: number; rMax: number } | null;
  apply: (spec: LatheStockSpec, resolution: number | null, enabled: boolean) => void;
  clear: () => void;
  status: () => SimStatus;
  setToolpathVisible: (on: boolean) => void;
  excludedWhy: () => Record<string, string>;
  /** 프로그램 진단(턴밀·나사·사용 불가 공구) */
  info: () => { turnmillMoves: number; turnmillSkipped: number; axisCorrected: number; threadMoves: number; unusable: Record<string, [string, number]> } | null;
}

const KEY = 'sim_lathe_stock_v1';
const RES_ITEMS = ['자동', '0.02', '0.05', '0.1', '0.2'];
interface Saved { diameter: number; length: number; frontZ: number; bore: number; resolution: string; enabled: boolean }
const defaults = (): Saved => ({ diameter: 50, length: 100, frontZ: 0, bore: 0, resolution: '자동', enabled: true });
function load(): Saved {
  try { const raw = getPref(KEY); if (raw) return { ...defaults(), ...(JSON.parse(raw) as Partial<Saved>) }; } catch { /* 기본값 */ }
  return defaults();
}

let openDialog: HTMLDialogElement | null = null;

export function showLatheStockDialog(ctx: LatheStockDialogContext): void {
  if (openDialog?.isConnected) return;
  const s = load();
  const body = el('div', { class: 'stock-body' });
  const num = (v: number): HTMLInputElement => { const i = el('input', { type: 'number', step: '0.1', inputmode: 'decimal' }); i.value = String(v); return i; };
  const row = (label: string, ...c: HTMLElement[]): HTMLElement => { const r = el('div', { class: 'stock-row' }); const n = el('span'); n.textContent = label; r.append(n, ...c); return r; };
  const dia = num(s.diameter), len = num(s.length), fz = num(s.frontZ), bore = num(s.bore);
  const resSel = el('select');
  for (const r of RES_ITEMS) resSel.append(new Option(r, r));
  resSel.value = s.resolution;
  const margin = num(2);
  const fit = el('button', { type: 'button' });
  fit.textContent = '툴패스 범위에 맞추기';
  for (const [l, c] of [['소재 지름 (mm)', dia], ['소재 길이 (mm)', len], ['앞면 Z', fz], ['내경 지름', bore]] as const) { const r = row(l, c); r.classList.add('single'); body.append(r); }
  body.append(precisionRow());
  { const r = row('해상도(mm)', resSel); r.classList.add('single'); body.append(r); }
  body.append(row('여유(mm)', margin, fit));
  const enable = el('input', { type: 'checkbox' });
  enable.checked = s.enabled;
  const enableLabel = el('label', { class: 'stock-enable' });
  enableLabel.append(enable, document.createTextNode(' 가공 형상 표시'));
  const lineCheck = el('input', { type: 'checkbox' });
  lineCheck.checked = getPref('sim_toolpath_visible') !== '0';
  lineCheck.addEventListener('change', () => { setPref('sim_toolpath_visible', lineCheck.checked ? '1' : '0'); ctx.setToolpathVisible(lineCheck.checked); });
  const lineLabel = el('label', { class: 'stock-enable' });
  lineLabel.append(lineCheck, document.createTextNode(' 툴패스 선 표시 (끄면 가공 형상이 잘 보입니다)'));
  const note = el('div', { class: 'stock-note' });
  note.textContent = '소재는 앞면 Z 에서 -Z 쪽으로 길이만큼, 중심축은 X0 입니다. 선삭·홈·나사(G76, 피치 간격 V홈)·중심 드릴/엔드밀을 깎고, 턴밀(M35) 이동은 3D 복셀로 깎습니다. 형상은 3/4 단면으로 보입니다.';
  const statusLabel = el('div', { class: 'stock-status' });
  body.append(enableLabel, lineLabel, note, statusLabel);

  const refreshStatus = (): void => {
    const st = ctx.status();
    const parts: string[] = [];
    if (st.hasStock) parts.push(`선반 격자 ${st.nx}×${st.ny} (${(st.cells / 1000).toFixed(0)}천 칸, ${st.resolution}mm) · 깎은 선분 ${st.cutSegments}/${st.totalSegments}${st.busy ? ' · 계산 중…' : ''}`);
    if (st.engine === 'lathe3d') parts.push('턴밀(M35)이 있어 3D 복셀로 계산합니다(선삭 세부는 복셀 크기로 표시됩니다).');
    const inf = ctx.info();
    if (inf) {
      if (inf.turnmillMoves) {
        const done = inf.turnmillMoves - inf.turnmillSkipped;
        parts.push(done > 0 ? `턴밀(M35) 이동 ${done}개를 3D 복셀로 계산` : `턴밀(M35) 이동 ${inf.turnmillMoves}개 — 계산할 수 있는 턴밀 공구가 없음`);
        if (inf.turnmillSkipped && done > 0) parts.push(`공구 형상이 없어 제외된 턴밀 이동 ${inf.turnmillSkipped}개`);
        if (inf.axisCorrected) parts.push(`진입 방향이 평면과 어긋나 평면 기준으로 공구 축을 정한 가공 ${inf.axisCorrected}곳`);
      }
      for (const k of Object.keys(inf.unusable)) parts.push(`${k}: ${inf.unusable[k]![0]}(이동 ${inf.unusable[k]![1]}개)`);
      if (inf.threadMoves) parts.push(`G76 나사 ${inf.threadMoves}구간 — 피치 간격 V홈으로 근사(나선은 표시 안 함)`);
    }
    const why = ctx.excludedWhy();
    for (const k of Object.keys(why)) parts.push(`공구 ${k} 제외: ${why[k]}`);
    if (st.noToolMoves) parts.push(`공구 번호가 없는 공정 이동 ${st.noToolMoves}개는 깎지 않습니다.`);
    if (st.rapidLines.length) parts.push(`급속(G00)이 소재를 건드린 줄: ${st.rapidLines.map((l) => l + 1).join(', ')}`);
    statusLabel.textContent = parts.join('\n');
  };
  refreshStatus();

  fit.addEventListener('click', () => {
    const e = ctx.extent();
    if (!e) { toast('절삭 이송(G01/G02/G03) 경로가 없습니다.'); return; }
    const m = parseFloat(margin.value) || 0;
    const r2 = (v: number): string => String(Math.round(v * 100) / 100);
    dia.value = r2(2 * (e.rMax + m));
    len.value = r2(e.zMax - e.zMin + 2 * m);
    fz.value = r2(e.zMax + m);
  });
  const save = (): void => setPref(KEY, JSON.stringify({
    diameter: parseFloat(dia.value) || 0, length: parseFloat(len.value) || 0, frontZ: parseFloat(fz.value) || 0,
    bore: parseFloat(bore.value) || 0, resolution: resSel.value, enabled: enable.checked,
  } satisfies Saved));

  const timer = window.setInterval(refreshStatus, 700);
  const dlg = showDialog('선반 소재 (STOCK)', body, [
    { label: '소재 지우기', onClick: () => { ctx.clear(); } },
    { label: '닫기' },
    {
      label: '적용', primary: true,
      onClick: () => {
        const d = parseFloat(dia.value) || 0, l = parseFloat(len.value) || 0, b = parseFloat(bore.value) || 0;
        if (d <= 0 || l <= 0) { toast('소재 지름과 길이는 0 보다 커야 합니다.'); return false; }
        if (b >= d) { toast('내경은 소재 지름보다 작아야 합니다.'); return false; }
        save();
        ctx.apply(new LatheStockSpec(d, l, parseFloat(fz.value) || 0, b), resSel.value === '자동' ? null : parseFloat(resSel.value), enable.checked);
        return true;
      },
    },
  ]);
  dlg.addEventListener('close', () => { window.clearInterval(timer); save(); });
  openDialog = dlg;
}
