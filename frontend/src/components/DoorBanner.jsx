import { AlertTriangle } from 'lucide-react';

/** The one alert that must be impossible to miss while someone is scrolling the dashboard. */
export default function DoorBanner({ fridges }) {
  const open = fridges.filter((f) => f.door_alert);
  if (open.length === 0) return null;
  return (
    <div
      className="sticky top-0 z-20 -mx-6 mb-6 px-6 py-3 bg-[#c8372d] text-white text-sm flex flex-wrap items-center gap-2"
      role="alert"
    >
      <AlertTriangle className="h-5 w-5 shrink-0" />
      <strong>{open.map((f) => f.name).join(', ')}</strong>
      <span>— door has been open for more than 60 seconds. Close it and check the doses.</span>
    </div>
  );
}
