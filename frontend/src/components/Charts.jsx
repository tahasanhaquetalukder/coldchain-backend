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

const AXIS = { stroke: '#94a3b8', fontSize: 11, tickLine: false, axisLine: false };

/** The 40-point trace on the dashboard card: shape only, no axes, no tooltip.
 *
 * A hand-drawn polyline cannot tell you where a reading was buffered or when it arrived, which is
 * the first thing anyone asks about a cold chain that looks wrong.
 */
export function Sparkline({ history }) {
  if (!history || history.length < 2) {
    return <div className="h-11 text-xs text-slate-400 grid items-end">Waiting for readings…</div>;
  }
  const data = history.map((t, i) => ({ i, t }));
  return (
    <div className="h-11 mt-2" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <YAxis hide domain={[0, 14]} />
          <XAxis hide dataKey="i" />
          <ReferenceArea y1={2} y2={8} fill="#e2f0e8" />
          <ReferenceLine y={8} stroke="#c8372d" strokeDasharray="3 3" strokeWidth={0.8} />
          <Line type="linear" dataKey="t" stroke="#0e5a7a" strokeWidth={1.8} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** A node's own readings, with the queue marks and the two thresholds the budget is computed on. */
export function Trace({ rows }) {
  if (!rows || rows.length < 2) {
    return (
      <div className="h-52">
        <Empty title="Waiting for readings from this node" hint="Every accepted packet shows up here within a couple of seconds." />
      </div>
    );
  }
  const data = rows.map((r, i) => ({ ...r, i, bufferedTemp: r.buffered ? r.temperature : null }));
  return (
    <div>
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} {...AXIS} />
            <YAxis domain={[0, 14]} width={38} {...AXIS} />
            <ReferenceArea y1={2} y2={8} fill="#e2f0e8" stroke="none" />
            <ReferenceLine y={8} stroke="#c8372d" strokeDasharray="4 3" label={{ value: '8', position: 'right', fontSize: 10, fill: '#c8372d' }} />
            <ReferenceLine y={12} stroke="#c8372d" strokeDasharray="4 3" label={{ value: '12', position: 'right', fontSize: 10, fill: '#c8372d' }} />
            <Tooltip
              isAnimationActive={false}
              formatter={(v, name) => [`${Number(v).toFixed(1)} °C`, name]}
              labelFormatter={(ts) => fmtClock(ts)}
              contentStyle={{ fontSize: 12, borderRadius: 12 }}
            />
            <Line type="linear" dataKey="temperature" name="temperature" stroke="#0e5a7a" strokeWidth={1.8} dot={false} connectNulls activeDot={false} isAnimationActive={false} />
            {/* nulls on every live row leave the queue marks as dots only - no second line to draw */}
            <Line dataKey="bufferedTemp" name="replayed from buffer" stroke="none" dot={{ r: 2.4, fill: '#2f8fbf', strokeWidth: 0 }} activeDot={false} isAnimationActive={false} legendType="none" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-slate-500 mt-1">
        {rows.length} readings · shaded band is the 2-8 °C store · blue dots arrived from the node's
        offline buffer
      </p>
    </div>
  );
}
