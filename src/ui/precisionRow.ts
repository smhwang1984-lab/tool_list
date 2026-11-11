// 소재 창 공통: 정밀도 선택(낮음/보통/높음/최고). 고르면 바로 저장되고, 다음 "적용"부터 자동 해상도에 반영된다.
import { getPrecision, PRECISION_LABEL, PRECISIONS, setPrecision, type Precision } from '../sim/precision';
import { el } from './dialog';

export function precisionRow(): HTMLElement {
  const row = el('div', { class: 'stock-row single' });
  const name = el('span');
  name.textContent = '정밀도';
  const sel = el('select', { 'aria-label': '가공 형상 정밀도' });
  for (const p of PRECISIONS) sel.append(new Option(PRECISION_LABEL[p], p));
  sel.value = getPrecision();
  sel.addEventListener('change', () => setPrecision(sel.value as Precision));
  row.append(name, sel);
  return row;
}
