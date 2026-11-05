import StatusBadge from './StatusBadge.jsx';
import { tone } from './status.js';

/** Heat-exposure budget as one bar: the minutes a batch has left, not the ones it has lost. */
export default function BudgetBar({ batch }) {
  return (
    <div className="mb-3">
      <div className="flex justify-between gap-2 text-sm">
        <span className="truncate">
          {batch.code} · {batch.vaccine}
        </span>
        <span className="flex items-center gap-2 shrink-0">
          <span className="tabular-nums text-text-2">{batch.remaining_min} min left</span>
          <StatusBadge status={batch.status} />
        </span>
      </div>
      <div
        className="h-2 rounded bg-surface-2 mt-1 overflow-hidden"
        role="progressbar"
        aria-valuenow={batch.remaining_pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${batch.code} heat budget remaining`}
      >
        <div
          className="h-2 rounded"
          style={{ width: `${Math.max(0, Math.min(100, batch.remaining_pct))}%`, background: tone(batch.status) }}
        />
      </div>
    </div>
  );
}
