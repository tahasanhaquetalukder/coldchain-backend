import { BatteryMedium, BatteryWarning, Fan, DoorClosed, DoorOpen, ShieldCheck, AlertTriangle, PlugZap } from 'lucide-react';
import StatusBadge from './StatusBadge.jsx';
import { fmtTemp, freshness, NEUTRAL, tone, toneSet } from './status.js';

/** The number a clerk reads from across the room. Fixed height so a refresh cannot move the page. */
export function BigTemp({ temperature, status }) {
  return (
    <p className="mt-3 display text-7xl leading-none font-extrabold tracking-tight" style={{ color: tone(status) }}>
      {fmtTemp(temperature)}
      <span className="text-2xl text-muted">°C</span>
    </p>
  );
}

export function OnlineDot({ ageS, online }) {
  // the dashboard only gets a boolean from /api/dashboard; the devices page knows the real age
  const set = toneSet(online ? 'Safe' : null);
  const f = ageS != null
    ? freshness(ageS)
    : { tone: online ? 'var(--safe)' : NEUTRAL, ring: set.ring, label: online ? 'online' : 'offline' };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-text-2">
      <span
        className="inline-block h-2.5 w-2.5 rounded-full"
        style={{ background: f.tone, boxShadow: online ? `0 0 0 3px ${f.ring}` : 'none' }}
        aria-hidden
      />
      {f.label}
    </span>
  );
}

/** Battery as a bar, because "100.0" tells you nothing and a flat cell tells you everything. */
export function BatteryBar({ battery, powerOk }) {
  const pct = Math.max(0, Math.min(100, battery ?? 0));
  const colour = !powerOk ? 'var(--warn)' : pct > 50 ? 'var(--safe)' : pct > 20 ? 'var(--warn)' : 'var(--danger)';
  const Icon = powerOk ? PlugZap : pct > 40 ? BatteryMedium : BatteryWarning;
  return (
    <div className="flex items-center gap-2" title={powerOk ? 'on mains power' : 'running on battery'}>
      <Icon className="h-4 w-4 shrink-0" style={{ color: colour }} />
      <div className="h-2 w-16 rounded bg-surface-2 overflow-hidden">
        <div className="h-2 rounded" style={{ width: `${pct}%`, background: colour }} />
      </div>
      <span className="text-xs text-text-2 tabular-nums w-14">{battery == null ? '—' : `${Math.round(pct)}%`}</span>
    </div>
  );
}

/** The four states that decide whether the reading on screen can be trusted. */
export function Cells({ device }) {
  const cells = [
    device.door_open ? ['text-warn-strong', DoorOpen, 'Door open'] : ['text-muted', DoorClosed, 'Door shut'],
    device.power_ok ? ['text-safe-strong', PlugZap, 'Mains'] : ['text-danger-strong', BatteryWarning, `Battery ${Math.round(device.battery ?? 0)}%`],
    device.compressor_on ? ['text-accent', Fan, 'Compressor on'] : ['text-muted', Fan, 'Compressor off'],
    device.door_alert ? ['text-danger-strong', AlertTriangle, 'Door alert'] : ['text-safe-strong', ShieldCheck, 'No alerts'],
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-4 text-xs text-center">
      {cells.map(([colour, Icon, label]) => (
        <div key={label} className="rounded-xl bg-surface-2 border border-border p-2">
          <Icon className={`mx-auto ${colour}`} />
          <span className="block mt-1 text-text-2">{label}</span>
        </div>
      ))}
    </div>
  );
}

/** Which secret this node is expected to sign with - the difference between one cloned device and
 * every device in the fleet being cloned. */
export function KeyBadge({ ownKey }) {
  const set = toneSet(ownKey ? 'Safe' : null);
  return (
    <span
      className="badge text-[11px]"
      style={{ background: set.soft, color: set.strong }}
      title={ownKey ? 'issued to this node alone' : 'shared fleet key - rotate to give it its own'}
    >
      {ownKey ? 'own key' : 'fleet key'}
    </span>
  );
}

export function StatusRow({ device }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-xl font-bold truncate">{device.name}</h2>
        <p className="text-xs text-muted truncate">
          {device.device_id} · publishes <span className="font-mono">{device.topic}</span>
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <OnlineDot ageS={device.age_s} online={device.online} />
          <KeyBadge ownKey={device.own_key} />
          {device.replaying && (
            <span className="badge text-[11px] bg-primary-soft text-accent">
              emptying buffer
            </span>
          )}
        </div>
      </div>
      <StatusBadge status={device.status} />
    </div>
  );
}
