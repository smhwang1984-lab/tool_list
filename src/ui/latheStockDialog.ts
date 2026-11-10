// 선반 소재 창 — 원본 LatheStockDialog (지름·길이·앞면 Z·내경·해상도)
import { getPref, setPref } from '../platform/prefs';
import { LatheStockSpec } from '../sim/latheStock';
import type { SimStatus } from '../viewer/simLayer';
import { el, showDialog, toast } from './dialog';

export interface LatheStockDialogContext {
  /** 툴패스 (z, r) 범위. 없으면 null */
  extent: () => { zMin: number; zMax: number; rMax: number } | null;
  apply: (spec: LatheStockSpec, resolution: number | null, enabled: boolean) => void;
  clear: () => void;
  status: () => SimStatus;
  setToolpathVisible: (on: boolean) => void;
  excludedWhy: () => Record<string, string>;
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
  note.textContent = '소재는 앞면 Z 에서 -Z 쪽으로 길이만큼, 중심축은 X0 입니다. 선삭·홈·중심 드릴/엔드밀을 깎고 나사(G76)·턴밀 3D 는 아직 깎지 않습니다. 형상은 3/4 단면으로 보입니다.';
  const statusLabel = el('div', { class: 'stock-status' });
  body.append(enableLabel, lineLabel, note, statusLabel);

  const refreshStatus = (): void => {
    const st = ctx.status();
    const parts: string[] = [];
    if (st.hasStock) parts.push(`선반 격자 ${st.nx}×${st.ny} (${(st.cells / 1000).toFixed(0)}천 칸, ${st.resolution}mm) · 깎은 선분 ${st.cutSegments}/${st.totalSegments}${st.busy ? ' · 계산 중…' : ''}`);
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
