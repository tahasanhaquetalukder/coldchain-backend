import { AlertTriangle } from 'lucide-react';

/** The one alert that must be impossible to miss while someone is scrolling the dashboard.
 *
 * The red here is a fill, not text: on the dark surface the old `#c8372d` was 3.2:1 against white,
 * so the banner now uses the strong danger text on the soft danger ground with a 2 px rule beside it.
 */
export default function DoorBanner({ fridges }) {
  const open = fridges.filter((f) => f.door_alert);
  if (open.length === 0) return null;
  return (
    <div
      className="sticky top-0 z-20 mb-6 rounded-2xl border border-danger bg-danger-soft px-4 py-3 text-sm flex flex-wrap items-center gap-2"
      style={{ color: 'var(--danger-strong)', borderLeftWidth: 6 }}
      role="alert"
    >
      <AlertTriangle className="h-5 w-5 shrink-0" style={{ color: 'var(--danger-strong)' }} />
      <strong>{open.map((f) => f.name).join(', ')}</strong>
      <span>— door has been open for more than 60 seconds. Close it and check the doses.</span>
    </div>
  );
}
