import { CircleAlert, Loader, ScanLine } from 'lucide-react';

/** A bar of the height the real content will occupy, so loading never moves the page. */
export function Loading({ rows = 3, h = 'h-4' }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={`${h} rounded bg-surface-2`} style={{ width: `${100 - i * 12}%` }} />
      ))}
      <span className="sr-only">
        <Loader className="inline h-3 w-3 animate-spin" /> loading
      </span>
    </div>
  );
}

export function Empty({ title, hint }) {
  return (
    <div className="rounded-2xl bg-surface-2 border border-border p-6 text-center text-sm text-muted">
      <ScanLine className="mx-auto h-6 w-6 text-neutral" />
      <p className="mt-2 font-bold text-text-2">{title}</p>
      {hint && <p className="mt-1">{hint}</p>}
    </div>
  );
}

/** Errors quote the server. A paraphrased 403 is how an operator learns to distrust the console. */
export function ErrorNote({ message, onRetry }) {
  if (!message) return null;
  return (
    <p className="flex flex-wrap items-center gap-2 bg-danger-soft text-danger-strong border border-danger rounded-xl px-4 py-2 text-sm">
      <CircleAlert className="h-4 w-4 shrink-0" />
      <span className="flex-1 min-w-40">{message}</span>
      {onRetry && (
        <button className="underline font-bold text-danger-strong" onClick={onRetry}>
          try again
        </button>
      )}
    </p>
  );
}

/** Inline message from a write that failed, kept in the same slot as the form so nothing shifts. */
export function FormNote({ message, kind = 'error' }) {
  if (!message) return null;
  const look = kind === 'ok'
    ? 'bg-safe-soft text-safe-strong border-safe'
    : 'bg-danger-soft text-danger-strong border-danger';
  return <p className={`rounded-xl border px-3 py-2 text-sm ${look}`}>{message}</p>;
}
