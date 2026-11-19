// 밀링/선반 공통 정규식 — 원본 NC_Tool_List.py 144~165, 624~635행
import { RE_I, RE_M, pyRe } from './py';

// 공구명 뒤 "[SO nn]"은 있어도 되고 없어도 된다(그룹 3). 홀더 앞 "T번호"도 선택 항목.
export const TOOL_RE = pyRe(
  String.raw`\(\s*T(\d+)\s*//\s*(.*?)\s*(?:\[SO\s*([\d.]+)\]\s*)?//\s*(?:T\d+\s*)?([^)]*?)\s*\)`, RE_I,
);
/** 공구 정보 주석의 "(SO    90.000000 GL ...)" 줄에서 SO 값만 */
export const COMMENT_SO_RE = pyRe(String.raw`^\s*\(\s*SO\s+(-?\d+(?:\.\d+)?)`, RE_I | RE_M);
export const N_RE = pyRe(String.raw`^\s*N(\d+)\s*\(\s*#\d+\s*:\s*Tool\s*Change`, RE_I);
export const M6_RE = pyRe(String.raw`^\s*M0?6\s*T0*(\d+)\b`, RE_I);
export const M6_SEARCH_RE = pyRe(String.raw`^\s*M0?6\s*T0*\d+\b`, RE_I | RE_M);

// 선반은 M6가 없고 툴체인지 기준이 Tnn00 (옵셋 00). T0000은 옵셋 취소라 제외.
export const LATHE_T_RE = pyRe(String.raw`T(?!0000)(\d{2})00(?!\d)`, RE_I);
export const LATHE_T_SEARCH_RE = pyRe(String.raw`T(?!0000)\d{2}00(?!\d)`, RE_I | RE_M);

// 키 뒤 숫자만 추출. 긴 키를 앞에 둬서 FL이 F로 잘못 잡히지 않게 한다.
export const KV_RE = pyRe(String.raw`\b(LCF|SPINDL|FEED|FL|GL|DC|RE|SIG|PL|F)\s+(-?\d+(?:\.\d+)?)`, RE_I);
