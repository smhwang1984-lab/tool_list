// 원본 NC_Tool_List.py THEMES(v2.2.8)의 키 구성을 따르되, 바탕·글자·테두리는 회색 계열로 낮추고 강조색(accent) 하나만 남겼다. NC 색은 원본 그대로. 3D 캔버스는 테마와 무관하게 항상 어둡다(원본 v1.5.7).
export const THEMES = {
  light: {
    window_bg: '#eef0f2', panel_bg: '#ffffff', text: '#1d2125',
    muted_text: '#5c636b', faint_text: '#878d94', border: '#d9dcdf',
    header_bg: '#ffffff', header_text: '#1d2125', header_caption: '#6b7178',
    accent: '#2f6fb0', accent_text: '#ffffff', accent_hover: '#285f97',
    success: '#3f7a3a', success_text: '#ffffff',
    neutral_button: '#34383d', neutral_button_text: '#ffffff',
    editor_bg: '#ffffff', editor_text: '#1d2125', current_line: '#e8eef5',
    list_bg: '#ffffff', list_text: '#1d2125', list_hover: '#f4f5f6',
    list_selected_bg: '#2f6fb0', list_selected_text: '#ffffff',
    info_bg: '#f4f5f6', info_text: '#5c636b', error: '#b03a2e',
    mode_active_bg: '#e4e7ea', mode_active_text: '#1d2125',
    mode_inactive_bg: '#f4f5f6', mode_inactive_text: '#1d2125',
    nc_g0: '#b71c1c', nc_g1: '#256b29', nc_g2: '#1565c0', nc_g3: '#7b1fa2',
    nc_cycle: '#8d4e1f', nc_spindle: '#7a6000', nc_coolant: '#a84300',
    toolbar_bg: '#f7f8f9', toolbar_sep: '#dcdfe2', toolbar_hover: '#eceef0',
    icon: '#4a5058',
  },
  dark: {
    window_bg: '#121315', panel_bg: '#1a1b1e', text: '#e4e5e7',
    muted_text: '#9a9ea5', faint_text: '#6c7077', border: '#2b2d31',
    header_bg: '#1a1b1e', header_text: '#e4e5e7', header_caption: '#8a8e95',
    accent: '#3a78c2', accent_text: '#ffffff', accent_hover: '#4886d0',
    success: '#4f9a38', success_text: '#ffffff',
    neutral_button: '#3a3c41', neutral_button_text: '#ffffff',
    editor_bg: '#161719', editor_text: '#dcdee1', current_line: '#24282f',
    list_bg: '#17181b', list_text: '#dcdee1', list_hover: '#202125',
    list_selected_bg: '#3a78c2', list_selected_text: '#ffffff',
    info_bg: '#202125', info_text: '#a6aab1', error: '#e06a5a',
    mode_active_bg: '#2c2e33', mode_active_text: '#f0f1f2',
    mode_inactive_bg: '#202125', mode_inactive_text: '#c9ccd1',
    nc_g0: '#ff7b7b', nc_g1: '#5fd068', nc_g2: '#6bb2ff', nc_g3: '#c792ff',
    nc_cycle: '#d9a066', nc_spindle: '#ffd84d', nc_coolant: '#ffa040',
    toolbar_bg: '#1a1b1e', toolbar_sep: '#2b2d31', toolbar_hover: '#26282c',
    icon: '#b8bcc3',
  },
} as const;

export type ThemeName = keyof typeof THEMES;

/** 테마 색을 CSS 변수(--window_bg 등)로 올린다. */
export function applyTheme(name: ThemeName): void {
  const root = document.documentElement;
  for (const [key, value] of Object.entries(THEMES[name])) {
    root.style.setProperty(`--${key}`, value);
  }
  root.dataset.theme = name;
}
