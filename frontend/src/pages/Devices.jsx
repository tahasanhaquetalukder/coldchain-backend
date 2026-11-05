import { useCallback, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { http, errorMessage } from '../api.js';
import { useAuth } from '../auth.jsx';
import { BigTemp, Cells, KeyBadge, OnlineDot, StatusRow } from '../components/Readouts.jsx';
import { Trace } from '../components/Charts.jsx';
import SecretCard from '../components/SecretCard.jsx';
import { Empty, ErrorNote, FormNote, Loading } from '../components/States.jsx';
import { fmtClock, tone } from '../components/status.js';
import { usePoll } from '../components/usePoll.js';

const DEVICE_POLL = 3000;
// /api/readings clamps the limit to 600, so the choices stop there rather than offering a number
// the server quietly answers with a smaller one.
const LIMITS = [60, 180, 600];

// Why a packet the node sent never reached the trace, in the words the server used.
const WHY = {
  'invalid signature':
    'the HMAC_KEY flashed into the node is not the key this server issued for that id. Registering a node hands out its own key; only nodes that predate that still sign with the shared HMAC_SECRET_KEY.',
  'stale timestamp':
    "the node's clock has not synced yet, or is off by more than the window (60 s live, 3 h for a replayed buffer)",
  'unknown device': 'no device is registered under that id - register it, then restart the node',
  'replayed nonce': 'the node resent a reading the server already stored - harmless, the queue moves on',
};

function RejectList({ title, count, reasons, children }) {
  return (
    <div className="rounded-2xl bg-danger-soft border border-danger p-4 text-sm">
      <p className="font-bold text-danger-strong flex items-center gap-2">
        <AlertTriangle className="h-4 w-4" />
        {title} — {count} packet{count === 1 ? '' : 's'} rejected in the last hour
      </p>
      <ul className="mt-2 space-y-1 text-danger-strong">
        {Object.entries(reasons).map(([reason, n]) => (
          <li key={reason}>
            <span className="font-bold">{n} × {reason}</span> — {WHY[reason] || 'see the audit log'}
          </li>
        ))}
      </ul>
      {children}
    </div>
  );
}

export default function Devices() {
  const { isAdmin } = useAuth();
  const [selected, setSelected] = useState('');
  const [paused, setPaused] = useState(false);
  const [limit, setLimit] = useState(180);
  const [draft, setDraft] = useState({ name: '', device_id: '' });
  const [secret, setSecret] = useState(null);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);

  const { data, error, loading, refresh } = usePoll(
    () => http.get('/api/devices').then((r) => r.data),
    DEVICE_POLL,
    { paused },
  );
  const devices = data?.devices || [];
  const unknown = data?.unknown || [];

  // Land on a node that is actually talking: with two seeded fridges and one real ESP32, the first
  // row is not the interesting one.
  const current = devices.find((d) => d.device_id === selected)
    || devices.find((d) => d.online)
    || devices.find((d) => d.last_ts)
    || devices[0];

  const loadReadings = useCallback(
    () =>
      current
        ? http
            .get('/api/readings', { params: { device_id: current.device_id, limit } })
            .then((r) => r.data)
        : Promise.resolve([]),
    [current?.device_id, limit],   // eslint-disable-line react-hooks/exhaustive-deps
  );
  const readings = usePoll(loadReadings, DEVICE_POLL, { paused, key: `${current?.device_id}-${limit}` });
  const rows = readings.data || [];

  /** Admin actions: the server's answer is the only thing the operator gets, so it is shown verbatim. */
  const run = async (fn) => {
    setBusy(true);
    setNote(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setNote({ kind: 'error', text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  const register = () =>
    run(async () => {
      const { data: issued } = await http.post('/api/devices', draft);
      setSecret(issued);                       // shown once, then gone for good
      setSelected(issued.device_id);
      setDraft({ name: '', device_id: '' });
    });

  const rotate = (d) => {
    if (!window.confirm(`Issue a new key for ${d.name}? The one it uses now stops working on the next packet, so the node has to be reflashed with what comes back.`)) return;
    run(async () => {
      const { data } = await http.post(`/api/devices/${d.id}/key`);
      setSecret({ ...data, rotated: true });
    });
  };

  const remove = (d) => {
    if (!window.confirm(`Unregister ${d.name} (${d.device_id}) and delete its ${d.readings} stored readings? Batches keep their budget but lose their location.`)) return;
    run(async () => {
      await http.delete(`/api/devices/${d.id}`);
      setSelected('');
      setSecret(null);
      setNote({ kind: 'ok', text: `${d.device_id} unregistered.` });
    });
  };

  if (loading) return <Loading rows={6} />;

  return (
    <div className="space-y-6">
      <p className="text-sm text-text-2">
        Everything here is a packet the server verified: HMAC signature, timestamp window and nonce. A
        node whose key or clock is wrong cannot appear in the trace, so the rejection counts are shown
        beside it.
      </p>
      <ErrorNote message={error} onRetry={refresh} />
      {readings.error && <p className="text-xs text-danger-strong">Trace not refreshed: {readings.error}</p>}

      <div className="flex flex-wrap gap-2 items-center">
        {devices.map((d) => (
          <button
            key={d.id}
            onClick={() => setSelected(d.device_id)}
            className={`rounded-2xl px-4 py-2 text-left border bg-surface min-w-40 ${current?.id === d.id ? 'outline outline-2 outline-primary' : 'hover:bg-surface-2'}`}
          >
            <span className="block text-sm font-bold truncate">{d.name}</span>
            <span className="block text-xs text-muted font-mono truncate">{d.device_id}</span>
            <span className="mt-1 flex flex-wrap items-center gap-1">
              <OnlineDot ageS={d.age_s} online={d.online} />
              <KeyBadge ownKey={d.own_key} />
              {d.replaying && (
                <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-primary-soft text-accent">
                  emptying buffer
                </span>
              )}
            </span>
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 text-sm">
          <select className="field" value={limit} onChange={(e) => setLimit(Number(e.target.value))}
                  aria-label="How many readings to plot">
            {LIMITS.map((n) => <option key={n} value={n}>last {n} readings</option>)}
          </select>
          <button className="btn-quiet" onClick={() => setPaused((p) => !p)}>{paused ? 'resume' : 'pause'}</button>
        </div>
      </div>

      {current && (
        <section className="card" style={{ borderTop: `6px solid ${tone(current.status)}` }}>
          <StatusRow device={current} />
          <BigTemp temperature={current.temperature} status={current.status} />

          <div className="mt-6"><Trace rows={rows} /></div>
          <Cells device={current} />

          <div className="grid sm:grid-cols-3 gap-2 mt-4 text-xs text-text-2">
            <div className="rounded-xl bg-surface-2 p-2">
              {current.last_ts
                ? `signed ${fmtClock(current.last_ts)} · arrived ${Math.round(current.age_s)}s ago`
                : 'nothing accepted yet'}
            </div>
            <div className="rounded-xl bg-surface-2 p-2">
              {current.drift_s == null
                ? 'clock drift unknown'
                : `node clock is ${current.drift_s > 0 ? '+' : ''}${current.drift_s}s against the server`}
            </div>
            <div className="rounded-xl bg-surface-2 p-2">
              {current.readings} readings stored
              {current.last_ts ? ` · battery ${Math.round(current.battery)}%` : ''}
            </div>
          </div>

          {current.rejects > 0 && (
            <div className="mt-4">
              <RejectList title={current.device_id} count={current.rejects} reasons={current.reasons} />
            </div>
          )}

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-muted">
                <tr>{['Device clock', 'Stored at', '°C', 'Door', 'Source'].map((h) => (
                  <th key={h} className="py-1 pr-4 font-medium">{h}</th>
                ))}</tr>
              </thead>
              <tbody>
                {rows.slice(-10).reverse().map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="py-1.5 pr-4 font-mono">{fmtClock(r.ts)}</td>
                    <td className="py-1.5 pr-4 font-mono">{r.received_ts ? fmtClock(r.received_ts) : '—'}</td>
                    <td className="py-1.5 pr-4">{r.temperature.toFixed(1)}</td>
                    <td className="py-1.5 pr-4">{r.door_open ? 'open' : 'shut'}</td>
                    <td className="py-1.5 pr-4">
                      {r.buffered ? <span className="text-accent font-bold">buffered</span> : 'live'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {isAdmin && (
            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
              <span className="text-muted">
                {current.own_key
                  ? 'Signs with the key issued to this node alone.'
                  : 'Signs with the shared fleet key - rotate to give this node its own.'}
              </span>
              <button className="text-primary underline disabled:opacity-50" disabled={busy} onClick={() => rotate(current)}>
                Rotate its key
              </button>
              <button className="btn-danger" disabled={busy} onClick={() => remove(current)}>
                Unregister this node
              </button>
            </div>
          )}
        </section>
      )}

      {secret && <SecretCard secret={secret} onDismiss={() => setSecret(null)} />}

      {devices.length === 0 && (
        <Empty title="No devices registered" hint="Add the node below using the DEVICE_ID you flashed into cc_config.h." />
      )}

      {unknown.length > 0 && (
        <div className="rounded-3xl bg-warn-soft border border-warn p-6 text-sm">
          <p className="font-bold text-warn-strong">Packets arriving for ids that are not registered</p>
          <ul className="mt-2 space-y-1">
            {unknown.map((u) => (
              <li key={u.device_id}>
                <span className="font-mono">{u.device_id}</span> — {u.n} rejected, latest{' '}
                {Object.keys(u.reasons)[0] || 'unknown'}
                {isAdmin && (
                  <button className="ml-3 underline text-warn-strong"
                          onClick={() => setDraft({ name: u.device_id, device_id: u.device_id })}>
                    register this id
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {isAdmin && (
        <div className="card">
          <h3 className="font-bold">Register a node</h3>
          <p className="text-xs text-muted mt-1">
            The server makes up a private key for the node and shows it once - paste it into{' '}
            <span className="font-mono">cc_config.h</span> together with the DEVICE_ID you flashed. An
            unregistered id is refused with "unknown device", and the node keeps buffering.
          </p>
          <div className="grid sm:grid-cols-3 gap-2 mt-3">
            <label className="text-sm">
              <span className="label">Name</span>
              <input className="field w-full mt-1" placeholder="Clinic fridge" value={draft.name}
                     onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </label>
            <label className="text-sm">
              <span className="label">Device id</span>
              <input className="field w-full mt-1 font-mono" placeholder="fridge-3" value={draft.device_id}
                     onChange={(e) => setDraft({ ...draft, device_id: e.target.value })} />
            </label>
            <div className="flex items-end">
              <button className="btn-primary w-full" disabled={busy || !draft.name || !draft.device_id} onClick={register}>
                Register and get its key
              </button>
            </div>
          </div>
          <div className="min-h-11 mt-3">
            {note && <FormNote message={note.text} kind={note.kind} />}
          </div>
        </div>
      )}

      {current && (
        <p className="text-xs text-muted">
          The node flushes its offline buffer oldest-first before live readings, because anything at or
          before the last accepted timestamp is ignored - see the buffer rule in README.md.
        </p>
      )}
    </div>
  );
}
