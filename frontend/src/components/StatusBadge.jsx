import { toneSet } from './status.js';

/** The status pill, and the honest placeholder for a node that has never been heard of. */
export default function StatusBadge({ status }) {
  if (!status) {
    return (
      <span className="badge bg-neutral-soft text-neutral-strong">
        No data
      </span>
    );
  }
  const set = toneSet(status);
  return (
    <span className="badge shrink-0" style={{ background: set.soft, color: set.strong }}>
      {status}
    </span>
  );
}
