import { tone } from './status.js';

/** The status pill, and the honest placeholder for a node that has never been heard of. */
export default function StatusBadge({ status }) {
  if (!status) {
    return (
      <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-slate-200 text-slate-600">
        No data
      </span>
    );
  }
  return (
    <span className="px-2.5 py-1 rounded-full text-xs font-bold text-white" style={{ background: tone(status) }}>
      {status}
    </span>
  );
}
