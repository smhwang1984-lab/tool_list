// 원본 NC_Tool_List.py THEMES(v2.2.8) 그대로. 3D 캔버스는 테마와 무관하게 항상 어둡다(원본 v1.5.7).
export const THEMES = {
  light: {
    window_bg: '#f0f4f8', panel_bg: '#ffffff', text: '#1f2937',
    muted_text: '#5a6577', faint_text: '#8a94a3', border: '#c5ced8',
    header_bg: '#1f3a5f', header_text: '#ffffff', header_caption: '#c8d4e2',
    accent: '#2f6fb0', accent_text: '#ffffff', accent_hover: '#255a92',
    success: '#4c7f31', success_text: '#ffffff',
    neutral_button: '#555555', neutral_button_text: '#ffffff',
    editor_bg: '#ffffff', editor_text: '#1f2937', current_line: '#dbe7f5',
    list_bg: '#ffffff', list_text: '#1f2937', list_hover: '#eaf1f8',
    list_selected_bg: '#2f6fb0', list_selected_text: '#ffffff',
    info_bg: '#eaf1f8', info_text: '#40536b', error: '#b03a2e',
    mode_active_bg: '#34577f', mode_active_text: '#ffffff',
    mode_inactive_bg: '#f0f4f8', mode_inactive_text: '#1f3a5f',
    nc_g0: '#b71c1c', nc_g1: '#256b29', nc_g2: '#1565c0', nc_g3: '#7b1fa2',
    nc_cycle: '#8d4e1f', nc_spindle: '#7a6000', nc_coolant: '#a84300',
    toolbar_bg: '#e3e9f0', toolbar_sep: '#b9c4d0', toolbar_hover: '#d2dce8',
    icon: '#34577f',
  },
  dark: {
    window_bg: '#1b1f27', panel_bg: '#242a35', text: '#e4e8f0',
    muted_text: '#9aa5b8', faint_text: '#7a8494', border: '#3a4250',
    header_bg: '#10192b', header_text: '#e4e8f0', header_caption: '#8ea3c4',
    accent: '#3f7fc9', accent_text: '#ffffff', accent_hover: '#5090d6',
    success: '#4f9a38', success_text: '#ffffff',
    neutral_button: '#4a5164', neutral_button_text: '#ffffff',
    editor_bg: '#1a1f29', editor_text: '#dbe3f0', current_line: '#2c3a52',
    list_bg: '#20262f', list_text: '#dbe3f0', list_hover: '#2c3644',
    list_selected_bg: '#3f7fc9', list_selected_text: '#ffffff',
    info_bg: '#233047', info_text: '#b7c8e6', error: '#e06a5a',
    mode_active_bg: '#3f7fc9', mode_active_text: '#ffffff',
    mode_inactive_bg: '#2a2f3a', mode_inactive_text: '#c7d0e0',
    nc_g0: '#ff7b7b', nc_g1: '#5fd068', nc_g2: '#6bb2ff', nc_g3: '#c792ff',
    nc_cycle: '#d9a066', nc_spindle: '#ffd84d', nc_coolant: '#ffa040',
    toolbar_bg: '#222936', toolbar_sep: '#3a4250', toolbar_hover: '#2f3949',
    icon: '#c7d0e0',
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
