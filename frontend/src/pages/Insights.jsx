import { Suspense, lazy, useCallback, useState } from 'react';
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Fan, Minus, ShieldCheck } from 'lucide-react';
import { errorMessage, http } from '../api.js';
import { useAuth } from '../auth.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import { OnlineDot } from '../components/Readouts.jsx';
import { Empty, ErrorNote, FormNote, Loading } from '../components/States.jsx';
import { fmtClock, fmtTemp, tone, toneSet } from '../components/status.js';
import { usePoll } from '../components/usePoll.js';

// A forecast is a question about the next thirty minutes; ten seconds is far finer than the answer.
const POLL_MS = 10000;

// recharts is the heaviest thing on this page and the chart is the last part of it anyone reads, so
// the badges, the reasons and the confirm button paint from this shell while the chart is still
// downloading.
const Forecast = lazy(() => import('../components/Charts.jsx').then((m) => ({ default: m.Forecast })));

// The server's three risk levels, each with a word and an icon as well as a colour: a red or green
// dot is the one thing an operator who cannot distinguish them has no way to read across a ward.
const RISK = {
  low: { status: 'Safe', label: 'Low risk', Icon: ShieldCheck },
  watch: { status: 'Warning', label: 'Watch', Icon: AlertTriangle },
  high: { status: 'Breach', label: 'High risk', Icon: AlertTriangle },
};

function RiskBadge({ risk }) {
  const r = RISK[risk];
  if (!r) {
    return <span className="badge bg-neutral-soft text-neutral-strong">No forecast yet</span>;
  }
  const set = toneSet(r.status);
  return (
    <span className="badge inline-flex items-center gap-1.5" style={{ background: set.soft, color: set.strong }}>
      <r.Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      {r.label}
    </span>
  );
}

/** The one sentence the page is really asking the model, in the words a pharmacist needs. */
function breachWords(fc) {
  if (!fc || fc.state !== 'forecast') return '';
  const line = `${fc.threshold_c} °C`;
  if (fc.now_c != null && fc.now_c > fc.threshold_c) return `already above ${line}`;
  if (!fc.breach) return '';
  return fc.lead_min_est
    ? `may exceed ${line} in about ${fc.lead_min_est} min`
    : `may exceed ${line} within ${fc.horizon_min} min`;
}

/** The cooling rate of each clean cycle, newest at the right, as divs rather than a second chart.
 *
 * A full recharts instance per fridge is the wrong price for a shape that is eight millimetres tall,
 * and the numbers underneath it are what a technician argues with anyway.
 */
function MiniTrend({ trend }) {
  const values = (trend?.values || []).filter((v) => typeof v === 'number');
  const Icon = trend?.state === 'improving' ? ArrowUpRight : trend?.state === 'declining' ? ArrowDownRight : Minus;
  if (values.length < 2) {
    return (
      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
        <Minus className="h-3.5 w-3.5" aria-hidden />
        {trend?.state === 'not enough cycles' ? 'trend needs more cycles' : 'no trend yet'}
      </p>
    );
  }
  const top = Math.max(...values.map((v) => Math.abs(v)));
  return (
    <div className="mt-2">
      <div className="flex h-8 items-end gap-px" aria-hidden>
        {values.map((v, i) => (
          <div
            key={i}
            className="flex-1 rounded-sm bg-primary-soft"
            style={{ height: `${Math.max(6, (Math.abs(v) / top) * 100)}%` }}
          />
        ))}
      </div>
      <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-text-2">
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {trend.state} · {trend.first_half_median_c_per_min} → {trend.second_half_median_c_per_min} °C per minute
      </p>
    </div>
  );
}

/** 0-100 health, the band it falls in, and why.
 *
 * The score, the band word and the reasons all come from /api/ai/compressor; the caption quotes the
 * same cut-offs the server used (compressor.py: good at 80, watch at 50) so the bar can be read as a
 * decision rather than as a decoration.
 */
function Health({ health }) {
  if (!health) return <Loading rows={3} />;
  if (health.score == null) {
    return (
      <div>
        <p className="flex items-center gap-2 text-sm text-text-2">
          <Fan className="h-4 w-4 text-muted" aria-hidden />
          {health.state}
        </p>
        <p className="mt-2 text-xs text-muted">
          The score needs clean compressor cycles to compare against this fridge&rsquo;s own history. A
          node that has been running for a few minutes, or one that never stops, has nothing to score
          yet - and a made-up number would be worse than none.
        </p>
        {(health.warnings || []).map((w) => (
          <p key={w} className="mt-1 text-xs text-warn-strong">{w}</p>
        ))}
      </div>
    );
  }
  const status = health.band === 'good' ? 'Safe' : health.band === 'watch' ? 'Warning' : 'Breach';
  const set = toneSet(status);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="display text-4xl font-extrabold leading-none tabular-nums" style={{ color: tone(status) }}>
          {health.score}
          <span className="text-sm text-muted"> / 100</span>
        </p>
        {/* the server's own word, not the batch statuses: "At Risk" on a compressor would read as
            though a vaccine in it had spent its budget */}
        <span className="badge shrink-0" style={{ background: set.soft, color: set.strong }}>
          {health.band}
        </span>
      </div>
      <div className="mt-3 h-3 overflow-hidden rounded-full bg-surface-2 border border-border">
        <div className="h-3 rounded-full" style={{ width: `${health.score}%`, background: tone(status) }} />
      </div>
      <p className="mt-1 text-[11px] text-muted tabular-nums">
        weak below 50 · watch 50-79 · good 80 and up · {health.cycles_used} cycle(s) measured
      </p>
      <ul className="mt-3 space-y-1 text-sm text-text-2">
        {(health.reasons || []).map((r) => <li key={r}>• {r}</li>)}
      </ul>
      <MiniTrend trend={health.trend} />
      {(health.warnings || []).map((w) => (
        <p key={w} className="mt-1 text-xs text-warn-strong">{w}</p>
      ))}
    </div>
  );
}

/** One fridge as a button in the selector strip. */
function FridgeChip({ f, selected, onSelect }) {
  const set = toneSet(RISK[f.risk]?.status || null);
  return (
    <button
      onClick={() => onSelect(f.device_id)}
      aria-pressed={selected}
      className={`rounded-2xl border bg-surface px-4 py-2 text-left min-w-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${
        selected ? 'outline outline-2 outline-primary' : 'hover:bg-surface-2'
      }`}
      style={f.at_risk ? { borderColor: set.ring } : undefined}
    >
      <span className="block text-sm font-bold truncate">{f.name}</span>
      <span className="block text-xs text-muted font-mono truncate">{f.device_id}</span>
      <span className="mt-1 flex flex-wrap items-center gap-2">
        <OnlineDot ageS={null} online={f.online} />
        <span className="text-xs tabular-nums text-text-2">{fmtTemp(f.temperature)} °C</span>
        {f.at_risk && (
          <span className="badge text-[11px]" style={{ background: set.soft, color: set.strong }}>
            at risk
          </span>
        )}
      </span>
    </button>
  );
}

/** A suggested move, with the server&rsquo;s own sentence and the button that commits it. */
function Suggestion({ s, canConfirm, role, busy, onConfirm }) {
  // The id stops being accepted when the server's ten-minute window rolls over, not ten minutes after
  // this card was made - a suggestion built two minutes before a roll lives for two minutes. That
  // boundary is computed from the server's own clock, so a laptop with a wrong time shows the right one.
  const acceptedUntil = (Math.floor(s.created_at / s.ttl_s) + 1) * s.ttl_s;
  return (
    <li className="rounded-2xl bg-surface-2 border border-border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-bold truncate">
            {s.batch_code} <span className="font-normal text-muted">· {s.vaccine}</span>
          </p>
          <p className="mt-0.5 text-xs text-muted">
            {s.from_fridge_name} → <span className="font-bold text-text-2">{s.to_fridge_name}</span> ·{' '}
            {fmtTemp(s.to_temperature)} °C there · {s.remaining_min} budget-minutes left
          </p>
        </div>
        <StatusBadge status={s.batch_status} />
      </div>
      <p className="mt-2 text-sm text-text-2 break-words">{s.reason}</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {canConfirm ? (
          <button
            className="btn-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            onClick={() => onConfirm(s)}
            disabled={busy}
          >
            {busy ? 'Confirming…' : 'Confirm move'}
          </button>
        ) : (
          <p className="text-xs text-muted">
            Signed in as {role}: only a pharmacist or an admin can confirm a move.
          </p>
        )}
        <p className="text-[11px] text-muted tabular-nums">
          made at {fmtClock(s.created_at)} · this id is accepted until {fmtClock(acceptedUntil)}, when the{' '}
          {Math.round(s.ttl_s / 60)}-minute window rolls
        </p>
      </div>
    </li>
  );
}

export default function Insights() {
  const { canEditStock, role } = useAuth();
  const [selected, setSelected] = useState('');
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(0);
  const [note, setNote] = useState(null);

  // The suggestions and the health scores are both fleet-wide, so the whole page costs two requests
  // per poll. /api/ai/relocations is the read-only half: it recomputes every forecast with
  // episode=False, which is why refreshing this page cannot spend the ward's one breach warning.
  const { data, error, loading, refresh } = usePoll(
    async () => {
      const [plan, health] = await Promise.all([
        http.get('/api/ai/relocations').then((r) => r.data),
        http.get('/api/ai/compressor').then((r) => r.data),
      ]);
      return {
        plan,
        byDevice: Object.fromEntries((health.fridges || []).map((h) => [h.device_id, h])),
      };
    },
    POLL_MS,
    { paused },
  );

  const plan = data?.plan;
  const fridges = plan?.fridges || [];

  // Open on the fridge that needs looking at: with a ward and a breached box on screen together, the
  // breached one is the one the pharmacist came for.
  const current = fridges.find((f) => f.device_id === selected)
    || fridges.find((f) => f.at_risk)
    || fridges.find((f) => f.online)
    || fridges[0];

  const loadForecast = useCallback(
    () => current
      ? http.get('/api/ai/forecast', { params: { device_id: current.device_id } }).then((r) => r.data)
      : Promise.resolve(null),
    [current?.device_id],   // eslint-disable-line react-hooks/exhaustive-deps
  );
  // This is the route that raises BREACH_WARNING for the episode, because a forecast asked out loud is
  // an answer somebody is looking at. The key makes switching fridges fetch immediately.
  const fc = usePoll(loadForecast, POLL_MS, { paused, key: current?.device_id || '' });

  const confirm = async (s) => {
    setBusy(s.batch_id);
    setNote(null);
    try {
      const { data: done } = await http.post('/api/ai/relocations/confirm', {
        batch_id: s.batch_id,
        to_fridge_id: s.to_fridge_id,
        suggestion_id: s.suggestion_id,
      });
      setNote({
        kind: 'ok',
        text: done.already_confirmed
          ? done.reason                       // the server's own "this click moved nothing"
          : `${done.batch_code} is now in ${done.to_fridge_name}. Recorded as audit entry ${done.audit_id}.`,
      });
    } catch (e) {
      // 403 and 409 verbatim: the page showed one card and the server has since seen the numbers move,
      // and the reason it refused is the information.
      setNote({ kind: 'error', text: errorMessage(e) });
    } finally {
      setBusy(0);
      await refresh();
    }
  };

  if (loading) return <Loading rows={6} h="h-24" />;

  const words = breachWords(fc.data);

  return (
    <div className="space-y-6">
      <p className="text-sm text-text-2">
        Everything here is a prediction or a rule, never a measurement of the future. The forecast is
        the model&rsquo;s answer about the next 30 minutes, the health score compares each fridge with its
        own recent compressor cycles, and the moves below are plain rules over those two numbers - every
        one carries the figures it was decided from so you can disagree with it.
      </p>

      <ErrorNote message={error && !plan ? error : ''} onRetry={refresh} />
      {error && plan && (
        <p className="text-xs text-danger-strong">Last refresh failed: {error}</p>
      )}
      {fc.error && !loading && (
        <p className="text-xs text-danger-strong">
          This fridge&rsquo;s forecast did not refresh: {fc.error}
        </p>
      )}

      {!fridges.length ? (
        <Empty
          title="No fridges to read"
          hint="Register a node on the Devices page; its readings are what every number here is computed from."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {fridges.map((f) => (
              <FridgeChip
                key={f.id}
                f={f}
                selected={current?.device_id === f.device_id}
                onSelect={setSelected}
              />
            ))}
            <div className="ml-auto flex items-center gap-2">
              <button
                className="btn-quiet focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                onClick={() => setPaused((p) => !p)}
              >
                {paused ? 'resume' : 'pause'}
              </button>
              <button
                className="btn-quiet focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                onClick={refresh}
                aria-label="Refresh the numbers now"
              >
                refresh
              </button>
            </div>
          </div>

          <p className="card text-sm">
            {plan.message}
            <span className="block mt-1 text-xs text-muted">
              Capacity is assumed, not measured: the server holds{' '}
              <span className="font-bold text-text-2">{plan.capacity_per_fridge}</span> batches per
              fridge, set by <span className="font-mono">MAX_BATCHES_PER_FRIDGE</span>.{' '}
              {fridges.length} fridge(s), {plan.at_risk_fridges.length} at risk,{' '}
              {plan.eligible_destinations.length} able to receive stock.
            </span>
          </p>

          {current && (
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
              <section className="card min-w-0">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-xl font-bold truncate">{current.name}</h2>
                    <p className="text-xs text-muted font-mono truncate">{current.device_id}</p>
                  </div>
                  <RiskBadge risk={current.risk} />
                </div>
                <p className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="display text-5xl font-extrabold leading-none tabular-nums">
                    {fmtTemp(current.temperature)}
                    <span className="text-xl text-muted"> °C</span>
                  </span>
                  {fc.data?.breach && (
                    <span className="text-sm font-bold" style={{ color: tone('Breach') }}>{words}</span>
                  )}
                  {!fc.data?.breach && fc.data?.state === 'forecast' && (
                    <span className="text-sm text-muted">staying under {fc.data.threshold_c} °C</span>
                  )}
                </p>
                <div className="mt-4">
                  <Suspense fallback={<Loading rows={3} h="h-40" />}>
                    <Forecast fc={fc.data} />
                  </Suspense>
                </div>
                <p className="mt-3 text-xs text-muted">
                  model: <span className="font-bold text-text-2">{fc.data?.model || '—'}</span>
                  {fc.data?.model === 'fallback'
                    ? ' - no usable trained model, so this is a straight line drawn from the last 15 minutes'
                    : ''}
                  {fc.data?.state === 'not enough data'
                    ? ` - ${fc.data.minutes_of_history} of the ${fc.data.minutes_needed} minutes needed`
                    : ''}
                </p>
                {(fc.data?.warnings || [])
                  .filter((w) => !w.startsWith('no usable trained model'))
                  .map((w) => <p key={w} className="mt-1 text-xs text-warn-strong">{w}</p>)}
                {(current.destination_blockers || []).length > 0 && (
                  <p className="mt-2 text-xs text-muted">
                    Not a place to move stock into:{' '}
                    {current.destination_blockers.join(' · ')}.
                  </p>
                )}
              </section>

              <section className="card min-w-0">
                <h3 className="label">Compressor health</h3>
                <Health health={data?.byDevice[current.device_id]} />
                {(current.risk_reasons || []).length > 0 && (
                  <div className="mt-4 rounded-xl bg-danger-soft border border-danger p-3">
                    <p className="text-xs font-bold uppercase tracking-wide text-danger-strong">
                      Why this fridge is flagged
                    </p>
                    <ul className="mt-1 space-y-1 text-sm text-danger-strong">
                      {current.risk_reasons.map((r) => <li key={r}>{r}</li>)}
                    </ul>
                  </div>
                )}
                <p className="mt-3 text-xs text-muted">
                  {current.batch_count} of {plan.capacity_per_fridge} places holding batches ·{' '}
                  {current.free_slots} free
                </p>
              </section>
            </div>
          )}

          <section className="card">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-xl font-bold">Suggested moves</h2>
              <p className="text-xs text-muted">
                recomputed on every request; confirming re-decides them on the server first
              </p>
            </div>
            <FormNote message={note?.text} kind={note?.kind === 'ok' ? 'ok' : 'error'} />
            {(plan?.suggestions || []).length === 0 ? (
              <p className="mt-3 text-sm text-text-2">
                Nothing is recommended right now. {plan?.message}
              </p>
            ) : (
              <ul className="mt-4 space-y-3">
                {plan.suggestions.map((s) => (
                  <Suggestion
                    key={s.suggestion_id}
                    s={s}
                    role={role}
                    canConfirm={canEditStock}
                    busy={busy !== 0}
                    onConfirm={confirm}
                  />
                ))}
              </ul>
            )}
            {(plan?.unplaced || []).length > 0 && (
              <div className="mt-5">
                <h3 className="label">Stock with nowhere to go</h3>
                <ul className="mt-2 space-y-2">
                  {plan.unplaced.map((u) => (
                    <li key={u.batch_id} className="rounded-xl bg-warn-soft border border-warn p-3 text-sm">
                      <p className="font-bold text-warn-strong break-words">
                        {u.batch_code} in {u.from_fridge_name} — {u.remaining_min} budget-minutes left
                      </p>
                      <p className="mt-1 text-warn-strong break-words">{u.why}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <p className="text-xs text-muted">
            Polled every {POLL_MS / 1000} seconds from{' '}
            <span className="font-mono">/api/ai/relocations</span>,{' '}
            <span className="font-mono">/api/ai/compressor</span> and{' '}
            <span className="font-mono">/api/ai/forecast</span>.{' '}
            {fc.data?.data || 'The model behind these numbers has not been loaded.'}
          </p>
        </>
      )}
    </div>
  );
}
