import { useEffect, useState } from 'react';

/** Theme state, kept outside React so the very first paint can already be dark.
 *
 * sessionStorage rather than localStorage, and no matchMedia: the app starts dark whatever the
 * operating system says, because that is the design, and a per-tab choice is the only thing an
 * operator can actually undo.
 */
const KEY = 'coldchain.theme';

export const readTheme = () => (sessionStorage.getItem(KEY) === 'light' ? 'light' : 'dark');

export function applyTheme(theme) {
  if (theme === 'light') document.documentElement.dataset.theme = 'light';
  else delete document.documentElement.dataset.theme;
  return theme;
}

applyTheme(readTheme());

const watchers = new Set();

export function useTheme() {
  const [theme, setThemeState] = useState(readTheme);

  useEffect(() => {
    const bump = (next) => setThemeState(next);
    watchers.add(bump);
    return () => watchers.delete(bump);
  }, []);

  const setTheme = (next) => {
    sessionStorage.setItem(KEY, next);
    applyTheme(next);
    watchers.forEach((f) => f(next));
  };

  return { theme, setTheme, toggleTheme: () => setTheme(theme === 'dark' ? 'light' : 'dark') };
}

// The names Charts.jsx needs, in the CSS variables that hold them.
const TOKENS = {
  grid: '--grid',
  band: '--safe-band',
  primary: '--primary',
  accent: '--accent',
  danger: '--danger',
  muted: '--muted',
  surface: '--surface',
  text: '--text',
  border: '--border',
  safe: '--safe',
  warn: '--warn',
};

/** Resolve the tokens to real colour strings for recharts.
 *
 * Recharts writes SVG attributes from props, and an attribute value of `var(--grid)` is not
 * resolved by the renderer the way a CSS declaration is, so the chart gets the computed colour
 * instead and re-reads it whenever the theme changes.
 */
export function useThemeColors() {
  const { theme } = useTheme();
  const read = () => {
    const cs = getComputedStyle(document.documentElement);
    const out = {};
    for (const [name, variable] of Object.entries(TOKENS)) out[name] = cs.getPropertyValue(variable).trim();
    return out;
  };

  const [colors, setColors] = useState(read);
  useEffect(() => setColors(read()), [theme]);   // eslint-disable-line react-hooks/exhaustive-deps
  return colors;
}
