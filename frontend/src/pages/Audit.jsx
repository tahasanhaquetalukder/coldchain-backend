import { useEffect, useState } from 'react';
import { CheckCircle2, ShieldAlert } from 'lucide-react';
import { http, errorMessage } from '../api.js';
import { ErrorNote, Loading } from '../components/States.jsx';
import { fmtTime } from '../components/status.js';

const RED_ACTIONS = /REJECT|ALERT|FAILED|MOVED|RESET|REMOVED/;

export default function Audit() {
  const [rows, setRows] = useState(null);
  const [check, setCheck] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setRows((await http.get('/api/audits')).data);
      setError('');
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  // The chain is append-only and heavy to read, so this page loads on entry instead of polling.
  useEffect(() => {
    load();
  }, []);

  const verify = async () => {
    setBusy(true);
    try {
      setCheck((await http.get('/api/audits/verify')).data);
      setError('');
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!rows) return <Loading rows={10} />;

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-primary" onClick={verify} disabled={busy}>
            Verify integrity
          </button>
          <button className="btn-quiet" onClick={load} disabled={busy}>
            Reload log
          </button>
          {check &&
            (check.valid ? (
              <p className="flex items-center gap-2 font-bold text-safe-strong text-sm">
                <CheckCircle2 className="h-5 w-5" />
                Chain intact, {check.checked} records
              </p>
            ) : (
              <p className="flex items-center gap-2 font-bold text-danger-strong text-sm">
                <ShieldAlert className="h-5 w-5" />
                Tampering detected at record #{check.broken_at}: {check.reason}
              </p>
            ))}
          {check?.valid && check.head && (
            <p className="text-xs text-muted ml-auto">
              head <span className="font-mono">{check.head.slice(0, 16)}…</span>
            </p>
          )}
        </div>
        <p className="mt-3 text-xs text-muted">
          Every record hashes the one before it, and the newest hash is mirrored in an anchor file
          outside the database - that is what makes deleting the tail as visible as editing the middle.
        </p>
      </div>

      <ErrorNote message={error} onRetry={load} />

      <div className="card !p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left min-w-[760px]">
            <thead className="text-muted">
              <tr>{['#', 'Event', 'Details', 'Hash', 'Time (UTC)'].map((h) => (
                <th key={h} className="py-2 pr-4 font-medium whitespace-nowrap">{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {rows.map((l) => (
                <tr key={l.id} className="border-t">
                  <td className="py-2 pr-4 tabular-nums">{l.id}</td>
                  <td className="pr-4 font-bold whitespace-nowrap"
                      style={{ color: RED_ACTIONS.test(l.action) ? 'var(--danger-strong)' : undefined }}>
                    {l.action}
                  </td>
                  <td className="pr-4 break-all">{l.details}</td>
                  <td className="pr-4 font-mono text-xs" title={`${l.current_hash} ← ${l.previous_hash}`}>
                    {l.current_hash.slice(0, 12)}…
                  </td>
                  <td className="text-xs whitespace-nowrap">{fmtTime(l.timestamp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length >= 200 && (
          <p className="p-4 pt-0 text-xs text-muted">
            The server returns the newest 200 records; the chain check runs over every row it holds.
          </p>
        )}
      </div>
    </div>
  );
}
