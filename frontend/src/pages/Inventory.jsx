import { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { http, errorMessage } from '../api.js';
import { useAuth } from '../auth.jsx';
import BudgetBar from '../components/BudgetBar.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import QrModal, { checkUrl } from '../components/QrModal.jsx';
import { Empty, ErrorNote, FormNote, Loading } from '../components/States.jsx';
import { usePoll } from '../components/usePoll.js';

const EMPTY = { code: '', vaccine: '', expiry: '', fridge_id: '' };

const fridgeName = (fridges, id) => fridges.find((f) => f.id === id)?.name || 'Unassigned';

export default function Inventory() {
  const { isAdmin, canEditStock } = useAuth();
  const [draft, setDraft] = useState(EMPTY);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [qr, setQr] = useState(null);

  const { data, error, loading, refresh } = usePoll(async () => {
    const [batches, dashboard] = await Promise.all([http.get('/api/batches'), http.get('/api/dashboard')]);
    return { batches: batches.data, fridges: dashboard.data };
  }, 10000);

  const rows = data?.batches || [];
  const fridges = data?.fridges || [];

  /** Writes keep the server's own words: a 403 here is a role question, not a bug. */
  const act = async (fn, done, onOk) => {
    setBusy(true);
    setNote('');
    try {
      await fn();
      setNote(done || '');
      onOk?.();
      await refresh();
    } catch (e) {
      setNote(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const add = () =>
    act(
      () =>
        http.post('/api/batches', {
          ...draft,
          fridge_id: draft.fridge_id ? Number(draft.fridge_id) : null,
        }),
      `${draft.code} added.`,
      () => setDraft(EMPTY),
    );

  const move = (batch, value) =>
    act(
      () => http.put(`/api/batches/${batch.id}/move`, { fridge_id: value ? Number(value) : null }),
      `${batch.code} moved to ${fridgeName(fridges, value)}.`,
    );

  const reset = (batch) => {
    if (!window.confirm(`Reset the heat budget of ${batch.code}? This clears the discard condition and is written to the audit log.`)) return;
    act(() => http.post(`/api/batches/${batch.id}/reset`), `${batch.code} budget reset.`);
  };

  if (loading) return <Loading rows={8} />;

  return (
    <div className="space-y-6">
      <ErrorNote message={error && !data} onRetry={refresh} />

      {canEditStock && (
        <div className="card">
          <h2 className="font-bold">Register a batch</h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-6 gap-2 mt-3">
            <label className="text-sm">
              <span className="label">Code</span>
              <input className="field w-full mt-1" placeholder="VAX-003" value={draft.code}
                     onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
            </label>
            <label className="text-sm">
              <span className="label">Vaccine</span>
              <input className="field w-full mt-1" placeholder="Rotavirus" value={draft.vaccine}
                     onChange={(e) => setDraft({ ...draft, vaccine: e.target.value })} />
            </label>
            <label className="text-sm">
              <span className="label">Expiry</span>
              <input className="field w-full mt-1" type="date" value={draft.expiry}
                     onChange={(e) => setDraft({ ...draft, expiry: e.target.value })} />
            </label>
            <label className="text-sm">
              <span className="label">Fridge</span>
              <select className="field w-full mt-1" value={draft.fridge_id}
                      onChange={(e) => setDraft({ ...draft, fridge_id: e.target.value })}>
                <option value="">Unassigned</option>
                {fridges.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </label>
            <div className="lg:col-span-2 flex items-end">
              <button className="btn-primary w-full" disabled={busy || !draft.code || !draft.vaccine || !draft.expiry} onClick={add}>
                Add batch
              </button>
            </div>
          </div>
          <div className="min-h-11 mt-3">
            {note && <FormNote message={note} kind={/added|moved|reset/i.test(note) ? 'ok' : 'error'} />}
          </div>
        </div>
      )}

      <div className="card !p-0 overflow-hidden">
        {rows.length === 0 ? (
          <div className="p-6">
            <Empty title="No batches yet" hint="Register one above, or scan a printed label." />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left min-w-[860px]">
              <thead className="text-muted">
                <tr>{['Batch', 'Vaccine', 'Expiry', 'Status', 'Budget', 'Fridge', 'Label', 'Actions'].map((h) => (
                  <th key={h} className="p-4 font-medium whitespace-nowrap">{h}</th>
                ))}</tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.id} className="border-t align-top">
                    <td className="p-4 font-bold">{b.code}</td>
                    <td>{b.vaccine}</td>
                    <td className="whitespace-nowrap">{b.expiry}</td>
                    <td><StatusBadge status={b.status} /></td>
                    <td className="min-w-48 max-w-64"><BudgetBar batch={b} /></td>
                    <td>
                      {canEditStock ? (
                        <select className="field" value={b.fridge_id ?? ''} disabled={busy}
                                onChange={(e) => move(b, e.target.value)}>
                          <option value="">Unassigned</option>
                          {fridges.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                        </select>
                      ) : (
                        fridgeName(fridges, b.fridge_id)
                      )}
                    </td>
                    <td>
                      <button className="p-1 bg-white rounded" onClick={() => setQr(b)} aria-label={`Show the QR code for ${b.code}`}>
                        <QRCodeSVG value={checkUrl(b.code)} size={56} level="M" />
                      </button>
                    </td>
                    <td className="whitespace-nowrap">
                      <a className="text-accent underline" href={checkUrl(b.code)} target="_blank" rel="noreferrer">
                        Open check page
                      </a>
                      {isAdmin && b.status !== 'Safe' && (
                        <div>
                          <button className="btn-danger" disabled={busy} onClick={() => reset(b)}>
                            Admin reset
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="text-xs text-muted">
        A batch is charged heat minutes by the fridge it is stored in, so moving it here is what
        decides which node's temperature counts against it.
      </p>

      {qr && <QrModal batch={qr} onClose={() => setQr(null)} />}
    </div>
  );
}
