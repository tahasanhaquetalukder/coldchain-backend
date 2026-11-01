// One table of status colours, because "Safe" on a fridge, "At Risk" on a batch and "Discard" on a
// scanned label have to look like the same three decisions.
export const TONE = {
  Safe: '#1f8a5b',
  Warning: '#c98a0a',
  'At Risk': '#c98a0a',
  Breach: '#c8372d',
  Discard: '#c8372d',
};

export const NEUTRAL = '#94a3b8';

export const tone = (status) => TONE[status] || NEUTRAL;

export const fmtClock = (epoch) =>
  new Date(epoch * 1000).toLocaleTimeString([], { hour12: false });

// The log's own UTC text, unconverted: an audit row shown in browser-local time is a row whose
// timestamp depends on which laptop opened it.
export const fmtTime = (iso) => `${iso.replace('T', ' ').slice(0, 19)}`;

/** How long ago the node last reached the server, in the words the operator needs. */
export function freshness(ageS) {
  if (ageS == null) return { tone: NEUTRAL, label: 'never reported' };
  // a node whose clock runs ahead of the server stamps readings in the future, and an age counter
  // that reads "live -2472s" looks like a broken widget rather than a clock that needs setting
  const s = Math.max(0, Math.round(ageS));
  if (s < 20) return { tone: '#1f8a5b', label: `live ${s}s` };
  if (s < 120) return { tone: '#c98a0a', label: `stale ${s}s` };
  return { tone: '#c8372d', label: `offline ${Math.round(s / 60)}m` };
}

export const fmtTemp = (t) => (t == null ? '--.-' : t.toFixed(1));
