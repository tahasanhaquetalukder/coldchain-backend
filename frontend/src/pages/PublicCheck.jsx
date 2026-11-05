import { useEffect, useState } from 'react';
import axios from 'axios';
import { Snowflake } from 'lucide-react';
import { API_BASE } from '../api.js';
import { tone } from '../components/status.js';
import { Loading } from '../components/States.jsx';

const ADVICE = {
  Safe: 'Held between 2 and 8 °C for its whole life so far. Use normally.',
  'At Risk': 'Part of its heat budget is spent. A pharmacist should confirm before it is used.',
  Discard: 'Its heat budget is gone or it is past expiry. Do not use it.',
};

/** A scanned QR label. Deliberately standalone: no session is read, no navigation is offered, and
 * the response is the only endpoint that needs no token, so nothing here can fail with a 401. */
export default function PublicCheck({ code }) {
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    let live = true;
    setBusy(true);
    setError('');
    axios
      .get(`${API_BASE}/api/public/batch/${encodeURIComponent(code)}`)
      .then((r) => live && setBatch(r.data))
      .catch((e) => {
        if (!live) return;
        // 404 has a real answer; anything else is the visitor's network, not a missing batch.
        setError(e.response?.status === 404 ? `No batch ${code} is registered.` : `Cannot reach the service that checks batch ${code}.`);
      })
      .finally(() => live && setBusy(false));
    return () => {
      live = false;
    };
  }, [code]);

  const status = batch ? (batch.expired ? 'Discard' : batch.status) : null;

  return (
    <div className="min-h-screen grid place-items-center bg-page p-4 sm:p-6">
      <div className="card w-full max-w-sm text-center">
        <div className="flex items-center justify-center gap-2 text-primary">
          <Snowflake className="h-5 w-5" />
          <span className="text-sm font-bold tracking-wide">Cold-chain check</span>
        </div>
        <p className="mt-1 font-mono text-xs text-muted">Batch {code}</p>

        <div className="mt-5 min-h-[190px]">
          {busy && <Loading rows={4} h="h-8" />}
          {!busy && error && (
            <div className="rounded-2xl bg-surface-2 p-6">
              <p className="text-lg font-bold text-text">Unknown batch</p>
              <p className="mt-2 text-sm text-text-2">{error}</p>
            </div>
          )}
          {!busy && batch && (
            <>
              <div
                className="mx-auto h-28 w-28 rounded-full grid place-items-center text-on-dark text-xl font-extrabold"
                style={{ background: tone(status) }}
              >
                {status}
              </div>
              <h1 className="display mt-5 text-3xl leading-tight">{batch.vaccine}</h1>
              <p className="mt-1 text-sm text-text-2">
                Expires {batch.expiry}
                {batch.expired && <span className="font-bold text-danger-strong"> — expired</span>}
              </p>
              <p className="mt-4 text-sm text-text">{ADVICE[status]}</p>
            </>
          )}
        </div>

        <p className="mt-5 text-[11px] text-muted">
          Automatic reading of the fridge that stored this batch. A pharmacist's decision always
          overrides it.
        </p>
      </div>
    </div>
  );
}
