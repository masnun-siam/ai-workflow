export type Theme = 'system' | 'light' | 'dark';
const KEY = 'aiw.theme';

export function getTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    return t === 'light' || t === 'dark' ? t : 'system';
  } catch {
    return 'system';
  }
}

/** Applies the theme to <html data-theme> (absent = follow the OS) and remembers it. */
export function applyTheme(t: Theme) {
  const r = document.documentElement;
  if (t === 'system') delete r.dataset.theme;
  else r.dataset.theme = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* storage blocked: the choice lasts until reload */
  }
}
