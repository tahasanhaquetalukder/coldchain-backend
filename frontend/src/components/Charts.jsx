import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { fmtClock } from './status.js';
import { Empty } from './States.jsx';
import { useThemeColors } from './theme.js';

/** A node's own readings, with the queue marks and the two thresholds the budget is computed on. */
export function Trace({ rows }) {
  const c = useThemeColors();
  if (!rows || rows.length < 2) {
    return (
      <div className="h-52">
        <Empty title="Waiting for readings from this node" hint="Every accepted packet shows up here within a couple of seconds." />
      </div>
    );
  }
  const data = rows.map((r, i) => ({ ...r, i, bufferedTemp: r.buffered ? r.temperature : null }));
  const axis = { stroke: c.muted, fontSize: 11, tickLine: false, axisLine: false };
  return (
    <div>
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} {...axis} />
            <YAxis domain={[0, 14]} width={38} {...axis} />
            <ReferenceArea y1={2} y2={8} fill={c.band} stroke="none" />
            <ReferenceLine y={8} stroke={c.danger} strokeDasharray="4 3" label={{ value: '8', position: 'right', fontSize: 10, fill: c.danger }} />
            <ReferenceLine y={12} stroke={c.danger} strokeDasharray="4 3" label={{ value: '12', position: 'right', fontSize: 10, fill: c.danger }} />
            <Tooltip
              isAnimationActive={false}
              formatter={(v, name) => [`${Number(v).toFixed(1)} °C`, name]}
              labelFormatter={(ts) => fmtClock(ts)}
              contentStyle={{
                fontSize: 12,
                borderRadius: 12,
                background: c.surface,
                border: `1px solid ${c.border}`,
                color: c.text,
              }}
            />
            <Line type="linear" dataKey="temperature" name="temperature" stroke={c.primary} strokeWidth={1.8} dot={false} connectNulls activeDot={false} isAnimationActive={false} />
            {/* nulls on every live row leave the queue marks as dots only - no second line to draw */}
            <Line dataKey="bufferedTemp" name="replayed from buffer" stroke="none" dot={{ r: 2.4, fill: c.accent, strokeWidth: 0 }} activeDot={false} isAnimationActive={false} legendType="none" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-muted mt-1">
        {rows.length} readings · shaded band is the 2-8 °C store · blue dots arrived from the node's
        offline buffer
      </p>
    </div>
  );
}

/** The next half hour, drawn as an estimate rather than as a measurement.
 *
 * Two series on purpose: the solid line is what the node reported and the dashed line is what the
 * model expects, and they meet at the newest reading. A forecast drawn in the same ink as the trace is
 * the one thing an operator ends up trusting as though it had been measured.
 */
export function Forecast({ fc }) {
  const c = useThemeColors();
  if (!fc || fc.state !== 'forecast') {
    return (
      <div className="h-56">
        <Empty
          title={fc ? 'No forecast for this node yet' : 'Loading the forecast'}
          hint={fc?.warnings?.[0]
            || 'A node needs 30 unbroken minutes of readings before the model has anything to work from.'}
        />
      </div>
    );
  }
  const actual = fc.history.map((h) => ({ ts: h.ts, actual: h.c }));
  const seam = actual[actual.length - 1];
  // the dashed line starts on the last real point, or it floats half a grid square away from the trace
  const dashed = [{ ts: seam.ts, forecast: seam.actual },
    ...fc.projection.map((p) => ({ ts: p.ts, forecast: p.c }))];
  const axis = { stroke: c.muted, fontSize: 11, tickLine: false, axisLine: false };
  return (
    <div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={[...actual, ...dashed]} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} {...axis} />
            <YAxis domain={[0, (max) => Math.max(14, Math.ceil(max + 1))]} width={38} {...axis} />
            <ReferenceArea y1={2} y2={8} fill={c.band} stroke="none" />
            <ReferenceLine
              y={8}
              stroke={c.danger}
              strokeDasharray="4 3"
              label={{ value: '8 °C', position: 'right', fontSize: 10, fill: c.danger }}
            />
            <Tooltip
              isAnimationActive={false}
              formatter={(v, name) => [`${Number(v).toFixed(1)} °C`, name]}
              labelFormatter={(ts) => fmtClock(ts)}
              contentStyle={{
                fontSize: 12,
                borderRadius: 12,
                background: c.surface,
                border: `1px solid ${c.border}`,
                color: c.text,
              }}
            />
            <Line type="linear" dataKey="actual" name="measured" stroke={c.primary} strokeWidth={1.8}
              dot={false} connectNulls={false} activeDot={false} isAnimationActive={false} />
            <Line type="linear" dataKey="forecast" name="model estimate" stroke={c.accent} strokeWidth={1.8}
              strokeDasharray="5 4" dot={false} connectNulls={false} activeDot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-muted mt-1">
        {actual.length} measured minutes · the dashed line is the model&rsquo;s next{' '}
        {fc.horizon_min} minutes, not a reading · shaded band is the 2-8 °C store
      </p>
    </div>
  );
}

/** The 40-point trace on the dashboard card: shape only, no axes, no tooltip.
 *
 * A hand-drawn polyline cannot tell you where a reading was buffered or when it arrived, which is
 * the first thing anyone asks about a cold chain that looks wrong.
 */
export function Sparkline({ history }) {
  const c = useThemeColors();
  if (!history || history.length < 2) {
    return <div className="h-11 text-xs text-muted grid items-end">Waiting for readings…</div>;
  }
  const data = history.map((t, i) => ({ i, t }));
  return (
    <div className="h-11 mt-2" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <YAxis hide domain={[0, 14]} />
          <XAxis hide dataKey="i" />
          <ReferenceArea y1={2} y2={8} fill={c.band} />
          <ReferenceLine y={8} stroke={c.danger} strokeDasharray="3 3" strokeWidth={0.8} />
          <Line type="linear" dataKey="t" stroke={c.primary} strokeWidth={1.8} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
