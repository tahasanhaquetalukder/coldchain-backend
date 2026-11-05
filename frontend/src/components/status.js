// One table of status colours, because "Safe" on a fridge, "At Risk" on a batch and "Discard" on a
// scanned label have to look like the same three decisions.
//
// The values are CSS variables, not hex: an inline `style={{ color: tone(s) }}` resolves a var()
// against whatever theme is on the document, so one table serves dark and light without a re-render
// and without a second palette to keep in step. Recharts is the exception - it needs real colour
// strings, which is what useThemeColors() in theme.js is for.
export const TONE = {
  Safe: 'var(--safe)',
  Warning: 'var(--warn)',
  'At Risk': 'var(--warn)',
  Breach: 'var(--danger)',
  Discard: 'var(--danger)',
};

export const NEUTRAL = 'var(--neutral)';

// The same status in the two other roles it has to play: a pill (soft background, strong text) and
// nothing else. A white word on #2fb37a is 2.9:1, which is why the badge never does that.
const SET = {
  Safe: { soft: 'var(--safe-soft)', strong: 'var(--safe-strong)', ring: 'var(--safe-ring)' },
  Warning: { soft: 'var(--warn-soft)', strong: 'var(--warn-strong)', ring: 'var(--warn-ring)' },
  'At Risk': { soft: 'var(--warn-soft)', strong: 'var(--warn-strong)', ring: 'var(--warn-ring)' },
  Breach: { soft: 'var(--danger-soft)', strong: 'var(--danger-strong)', ring: 'var(--danger-ring)' },
  Discard: { soft: 'var(--danger-soft)', strong: 'var(--danger-strong)', ring: 'var(--danger-ring)' },
};

export const tone = (status) => TONE[status] || NEUTRAL;

/** { soft, strong, ring } for a pill, a panel or a dot halo that carries this status as text. */
export const toneSet = (status) => SET[status] || { soft: 'var(--neutral-soft)', strong: 'var(--neutral-strong)', ring: 'var(--neutral-ring)' };

export const fmtClock = (epoch) =>
  new Date(epoch * 1000).toLocaleTimeString([], { hour12: false });

// The log's own UTC text, unconverted: an audit row shown in browser-local time is a row whose
// timestamp depends on which laptop opened it.
export const fmtTime = (iso) => `${iso.replace('T', ' ').slice(0, 19)}`;

/** How long ago the node last reached the server, in the words the operator needs. */
export function freshness(ageS) {
  if (ageS == null) return { tone: NEUTRAL, ring: 'var(--neutral-ring)', label: 'never reported' };
  // a node whose clock runs ahead of the server stamps readings in the future, and an age counter
  // that reads "live -2472s" looks like a broken widget rather than a clock that needs setting
  const s = Math.max(0, Math.round(ageS));
  if (s < 20) return { tone: 'var(--safe)', ring: 'var(--safe-ring)', label: `live ${s}s` };
  if (s < 120) return { tone: 'var(--warn)', ring: 'var(--warn-ring)', label: `stale ${s}s` };
  return { tone: 'var(--danger)', ring: 'var(--danger-ring)', label: `offline ${Math.round(s / 60)}m` };
}

export const fmtTemp = (t) => (t == null ? '--.-' : t.toFixed(1));
