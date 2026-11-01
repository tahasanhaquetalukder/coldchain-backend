import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import axios from 'axios';
import { QRCodeSVG } from 'qrcode.react';
import { Snowflake, DoorOpen, DoorClosed, Zap, BatteryLow, Fan, ShieldCheck, LogOut, AlertTriangle } from 'lucide-react';

// A published build must never fall back to 127.0.0.1: that is the visitor's own machine, not this server.
const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');
const TONE = { Safe: '#1f8a5b', Warning: '#c98a0a', Breach: '#c8372d', 'At Risk': '#c98a0a', Discard: '#c8372d' };
const font = { fontFamily: "'Public Sans', sans-serif" };
const serif = { fontFamily: "'Fraunces', serif" };

const AUTH_KEY = 'coldchain.auth';
const readAuth = () => { try { return JSON.parse(localStorage.getItem(AUTH_KEY)); } catch { return null; } };

// FastAPI sends a string for HTTPException but an array for pydantic validation errors.
const errMsg = (e) => {
  const d = e.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (e.response) return 'Request rejected by the server';
  // Naming the host is what separates a stale VITE_API_URL from a backend that is merely asleep.
  return `Server not reachable: ${API || location.origin}`;
};

const Pill = ({ s }) => (
  s ? <span className="px-2.5 py-1 rounded-full text-xs font-bold text-white" style={{ background: TONE[s] }}>{s}</span>
    : <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-slate-200 text-slate-600">No data</span>
);

const fmtClock = (s) => new Date(s * 1000).toLocaleTimeString([], { hour12: false });

const Cells = ({ f }) => (
  <div className="grid grid-cols-4 gap-2 mt-4 text-xs text-center">
    <div className="rounded-xl bg-slate-50 p-2">{f.door_open ? <DoorOpen className="mx-auto text-amber-600" /> : <DoorClosed className="mx-auto text-slate-500" />}Door {f.door_open ? 'open' : 'closed'}</div>
    <div className="rounded-xl bg-slate-50 p-2">{f.power_ok ? <Zap className="mx-auto text-emerald-600" /> : <BatteryLow className="mx-auto text-red-600" />}{f.power_ok ? 'Mains' : `Battery ${f.battery}%`}</div>
    <div className="rounded-xl bg-slate-50 p-2"><Fan className={`mx-auto ${f.compressor_on ? 'text-sky-600' : 'text-slate-400'}`} />Compressor {f.compressor_on ? 'on' : 'off'}</div>
    <div className="rounded-xl bg-slate-50 p-2">{f.door_alert ? <AlertTriangle className="mx-auto text-red-600" /> : <ShieldCheck className="mx-auto text-emerald-600" />}{f.door_alert ? 'Door alert' : 'No alerts'}</div>
  </div>
);

function Spark({ data }) {
  if (data.length < 2) return <div className="h-10 text-xs text-slate-400">Waiting for readings</div>;
  const min = Math.min(...data, 0), max = Math.max(...data, 14);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * 200},${40 - ((v - min) / (max - min)) * 40}`).join(' ');
  const y8 = 40 - ((8 - min) / (max - min)) * 40;
  return (
    <svg viewBox="0 0 200 40" className="w-full h-10">
      <line x1="0" x2="200" y1={y8} y2={y8} stroke="#c8372d" strokeDasharray="3 3" strokeWidth="0.7" />
      <polyline points={pts} fill="none" stroke="#0e5a7a" strokeWidth="1.8" />
    </svg>
  );
}

// ---------- live device view ----------
// Why a packet the node sent never reached the trace, in the words the server actually used.
const WHY = {
  'invalid signature': 'the key baked into the node and the server HMAC_SECRET_KEY differ, or a number was printed differently than it was signed',
  'stale timestamp': "the node's clock has not synced yet, or is off by more than the window (60 s live, 3 h for a replayed buffer)",
  'unknown device': 'no device is registered under that id - register it, then restart the node',
  'replayed nonce': 'the node resent a reading the server already stored - harmless, the queue moves on',
};

const freshTone = (age) =>
  age == null ? ['bg-slate-200 text-slate-600', 'never reported']
    : age < 20 ? ['bg-emerald-100 text-emerald-800', `live ${Math.round(age)}s`]
    : age < 120 ? ['bg-amber-100 text-amber-800', `stale ${Math.round(age)}s`]
    : ['bg-red-100 text-red-800', `offline ${Math.round(age / 60)}m`];

function Trace({ rows }) {
  if (rows.length < 2) return <div className="h-28 rounded-xl bg-slate-50 grid place-items-center text-sm text-slate-400">Waiting for readings from this node…</div>;
  const W = 320, H = 104, P = 6;
  const t0 = rows[0].ts, t1 = Math.max(rows[rows.length - 1].ts, t0 + 1);
  const temps = rows.map(r => r.temperature);
  const lo = Math.min(0, ...temps), hi = Math.max(13, ...temps);
  const X = (t) => P + ((t - t0) / (t1 - t0)) * (W - 2 * P);
  const Y = (v) => H - P - ((v - lo) / (hi - lo || 1)) * (H - 2 * P);
  const gap = (t1 - t0) / 60;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-28 rounded-xl bg-slate-50">
        <rect x={P} y={Y(8)} width={W - 2 * P} height={Math.max(0, Y(2) - Y(8))} fill="#e2f0e8" />
        {[8, 12].map(v => <line key={v} x1={P} x2={W - P} y1={Y(v)} y2={Y(v)} stroke="#c8372d" strokeWidth="0.6" strokeDasharray="3 3" />)}
        <polyline points={rows.map(r => `${X(r.ts).toFixed(1)},${Y(r.temperature).toFixed(1)}`).join(' ')} fill="none" stroke="#0e5a7a" strokeWidth="1.6" />
        {rows.filter(r => r.buffered).map(r => <circle key={r.id} cx={X(r.ts)} cy={Y(r.temperature)} r="2.2" fill="#2f8fbf" />)}
      </svg>
      <div className="flex justify-between text-[11px] text-slate-500 mt-1">
        <span>{fmtClock(t0)}</span>
        <span>{rows.length} readings over ~{gap < 1.5 ? `${Math.round(gap * 60)} s` : `${gap.toFixed(1)} min`} · shaded band 2-8 °C · dots came from the offline buffer</span>
        <span>{fmtClock(t1)}</span>
      </div>
    </div>
  );
}

function Live({ api, isAdmin, onDone }) {
  const [dv, setDv] = useState(null), [rows, setRows] = useState([]);
  const [sel, setSel] = useState(''), [err, setErr] = useState(''), [busy, setBusy] = useState(false);
  const [limit, setLimit] = useState(180), [paused, setPaused] = useState(false);
  const [nd, setNd] = useState({ name: '', device_id: '' }), [made, setMade] = useState(null);
  // The poll runs from an interval, so it cannot read `sel` out of its own closure - by the time it
  // fires, that copy belongs to a render that no longer exists. The ref is the live value.
  const selRef = useRef('');
  const choose = (id) => { selRef.current = id; setSel(id); };

  const pull = useCallback(async () => {
    try {
      const data = (await api.get('/api/devices')).data;
      setDv(data); setErr('');
      // Land on a node that is actually talking: with two seeded fridges and one real ESP32, the
      // first row is not the interesting one.
      const id = selRef.current || (data.devices.find(x => x.online) || data.devices.find(x => x.last_ts) || data.devices[0])?.device_id;
      if (!id) return;
      selRef.current = id; setSel(id);
      setRows((await api.get('/api/readings', { params: { device_id: id, limit } })).data);
    } catch (e) { setErr(errMsg(e)); }
  }, [api, limit]);

  useEffect(() => {
    if (paused) return;
    pull();
    const i = setInterval(pull, 2000);
    return () => clearInterval(i);
  }, [pull, paused]);

  const d = dv?.devices.find(x => x.device_id === sel);
  const act = async (fn) => { setBusy(true); try { await fn(); setErr(''); await pull(); } catch (e) { setErr(errMsg(e)); } setBusy(false); };

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        Everything here is a packet the server verified: HMAC signature, timestamp window and nonce.
        A node whose key or clock is wrong cannot appear in the trace, so the rejection counts are shown beside it.
      </p>
      {err && <p className="bg-red-50 text-red-800 border border-red-200 rounded-xl px-4 py-2 text-sm">{err}</p>}

      <div className="flex flex-wrap gap-2 items-center">
        {(dv?.devices || []).map(x => {
          const [tone, label] = freshTone(x.age_s);
          return (
            <button key={x.id} onClick={() => choose(x.device_id)}
              className={`rounded-2xl px-4 py-2 text-left border bg-white ${sel === x.device_id ? 'outline outline-2 outline-[#0e5a7a]' : 'hover:bg-slate-50'}`}>
              <span className="block text-sm font-bold">{x.name}</span>
              <span className="block text-xs text-slate-500">{x.device_id}</span>
              <span className={`inline-block mt-1 px-2 py-0.5 rounded-full text-[11px] font-bold ${tone}`}>{label}</span>
              {x.replaying && <span className="ml-1 inline-block px-2 py-0.5 rounded-full text-[11px] font-bold bg-sky-100 text-sky-800">emptying buffer</span>}
            </button>
          );
        })}
        <div className="ml-auto flex items-center gap-2 text-sm">
          <select className="border rounded-xl px-2 py-1" value={limit} onChange={e => setLimit(+e.target.value)}>
            {[60, 180, 720, 600].map(n => <option key={n} value={n}>last {n} readings</option>)}
          </select>
          <button className="border rounded-xl px-3 py-1 bg-white" onClick={() => setPaused(p => !p)}>{paused ? 'resume' : 'pause'}</button>
        </div>
      </div>

      {d && (
        <section className="bg-white rounded-3xl p-6" style={{ borderTop: `6px solid ${TONE[d.status] || '#cbd5e1'}` }}>
          <div className="flex justify-between items-start flex-wrap gap-2">
            <div>
              <h2 className="text-xl font-bold">{d.name}</h2>
              <p className="text-xs text-slate-500">{d.device_id} · publishes <span className="font-mono">{d.topic}</span></p>
            </div>
            <Pill s={d.status} />
          </div>
          <p className="mt-3 text-7xl font-extrabold tracking-tight" style={serif}>
            {d.temperature == null ? '--.-' : d.temperature.toFixed(1)}<span className="text-2xl text-slate-400">°C</span>
          </p>
          <div className="mt-6"><Trace rows={rows} /></div>
          <Cells f={d} />
          <div className="grid sm:grid-cols-3 gap-2 mt-4 text-xs text-slate-600">
            <div className="rounded-xl bg-slate-50 p-2">{d.last_ts ? `signed ${fmtClock(d.last_ts)} · arrived ${d.age_s == null ? '?' : Math.round(d.age_s)}s ago` : 'nothing accepted yet'}</div>
            <div className="rounded-xl bg-slate-50 p-2">{d.drift_s == null ? 'clock drift unknown' : `node clock is ${d.drift_s > 0 ? '+' : ''}${d.drift_s}s against the server`}</div>
            <div className="rounded-xl bg-slate-50 p-2">{d.readings} readings stored{d.last_ts ? ` · battery ${d.battery}%` : ''}</div>
          </div>
          {d.rejects > 0 && (
            <div className="mt-4 rounded-2xl bg-red-50 border border-red-200 p-4 text-sm">
              <p className="font-bold text-red-800 flex items-center gap-2"><AlertTriangle className="h-4 w-4" />{d.rejects} packet{d.rejects > 1 ? 's' : ''} from this id rejected in the last hour</p>
              <ul className="mt-2 space-y-1 text-red-900/90">
                {Object.entries(d.reasons).map(([r, n]) => (
                  <li key={r}><span className="font-bold">{n} × {r}</span> — {WHY[r] || 'see the audit log'}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-slate-500"><tr>{['Device clock', 'Stored at', '°C', 'Door', 'Source'].map(h => <th key={h} className="py-1 pr-4 font-medium">{h}</th>)}</tr></thead>
              <tbody>{rows.slice(-10).reverse().map(r => (
                <tr key={r.id} className="border-t">
                  <td className="py-1.5 pr-4 font-mono">{fmtClock(r.ts)}</td>
                  <td className="py-1.5 pr-4 font-mono">{r.received_ts ? fmtClock(r.received_ts) : '-'}</td>
                  <td className="py-1.5 pr-4">{r.temperature.toFixed(1)}</td>
                  <td className="py-1.5 pr-4">{r.door_open ? 'open' : 'shut'}</td>
                  <td className="py-1.5 pr-4">{r.buffered ? <span className="text-sky-700 font-bold">buffered</span> : 'live'}</td>
                </tr>))}</tbody>
            </table>
          </div>
          {isAdmin && (
            <button disabled={busy} className="mt-4 text-xs text-red-700 underline disabled:opacity-50"
              onClick={() => {
                if (window.confirm(`Unregister ${d.name} (${d.device_id}) and delete its ${d.readings} stored readings?`))
                  act(async () => { await api.delete(`/api/devices/${d.id}`); choose(''); onDone(); });
              }}>
              Unregister this node
            </button>
          )}
        </section>
      )}
      {dv && dv.devices.length === 0 && <p className="text-slate-500">No devices registered. Add the node below using the DEVICE_ID from cc_config.h.</p>}

      {dv?.unknown?.length > 0 && (
        <div className="rounded-3xl bg-amber-50 border border-amber-200 p-6 text-sm">
          <p className="font-bold text-amber-900">Packets arriving for ids that are not registered</p>
          <ul className="mt-2 space-y-1">
            {dv.unknown.map(u => (
              <li key={u.device_id}>
                <span className="font-mono">{u.device_id}</span> — {u.n} rejected, latest {Object.keys(u.reasons)[0] || 'unknown'}
                {isAdmin && <button className="ml-3 underline text-amber-900" onClick={() => setNd({ name: u.device_id, device_id: u.device_id })}>register this id</button>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {isAdmin && (
        <div className="bg-white rounded-3xl p-6">
          <h3 className="font-bold">Register a node</h3>
          <p className="text-xs text-slate-500 mt-1">Use the exact DEVICE_ID you flashed into <span className="font-mono">cc_config.h</span>. An unregistered id is refused with "unknown device", and the node keeps buffering.</p>
          <div className="grid sm:grid-cols-3 gap-2 mt-3">
            <input className="border rounded-xl px-3 py-2" placeholder="Name, e.g. Clinic fridge" value={nd.name} onChange={e => setNd({ ...nd, name: e.target.value })} />
            <input className="border rounded-xl px-3 py-2 font-mono" placeholder="device id, e.g. fridge-3" value={nd.device_id} onChange={e => setNd({ ...nd, device_id: e.target.value })} />
            <button disabled={busy} className="bg-[#0e5a7a] text-white font-bold rounded-xl disabled:opacity-50"
              onClick={() => act(async () => {
                const added = (await api.post('/api/devices', nd)).data;
                setMade(added); choose(added.device_id);   // jump to the node that was just added
              })}>Register</button>
          </div>
          {made && (
            <p className="mt-3 text-sm text-emerald-800">
              {made.device_id} is live. It publishes <span className="font-mono">{made.topic}</span> and listens on <span className="font-mono">{made.command_topic}</span> for its batch status.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------- Public QR page: #/check/VAX-001 ----------
function PublicCheck({ code }) {
  const [b, setB] = useState(null), [err, setErr] = useState('');
  useEffect(() => { axios.get(`${API}/api/public/batch/${code}`).then(r => setB(r.data)).catch(() => setErr('No batch with this code.')); }, [code]);
  const s = b && (b.expired ? 'Discard' : b.status);
  return (
    <div className="min-h-screen grid place-items-center bg-[#eef4f6] p-6" style={font}>
      <div className="bg-white rounded-3xl p-8 w-full max-w-sm text-center shadow-sm">
        <p className="text-sm text-slate-500">Batch {code}</p>
        {err && <p className="mt-6 text-red-700">{err}</p>}
        {b && <>
          <div className="mt-4 mx-auto h-28 w-28 rounded-full grid place-items-center text-white text-xl font-extrabold" style={{ background: TONE[s] }}>{s}</div>
          <h1 className="mt-5 text-3xl" style={serif}>{b.vaccine}</h1>
          <p className="mt-1 text-slate-600">Expires {b.expiry}{b.expired && ' (expired)'}</p>
          <p className="mt-4 text-xs text-slate-400">{s === 'Safe' ? 'Stored within its temperature budget.' : 'Do not use until a pharmacist confirms.'}</p>
        </>}
      </div>
    </div>
  );
}

// ---------- Login ----------
function Login({ onAuth }) {
  const [u, setU] = useState('admin'), [p, setP] = useState('admin123'), [e, setE] = useState('');
  const go = async () => { try { onAuth((await axios.post(`${API}/api/auth/login`, { username: u, password: p })).data); } catch (x) { setE(errMsg(x)); } };
  return (
    <div className="min-h-screen grid md:grid-cols-2 bg-[#0b2a3b] text-white" style={font}>
      <div className="p-12 flex flex-col justify-end">
        <Snowflake className="h-10 w-10 text-sky-300 mb-6" />
        <h1 className="text-6xl leading-none" style={serif}>Every dose,<br />kept between 2 and 8 degrees.</h1>
        <p className="mt-5 text-sky-100/70 max-w-md">Live fridge monitoring, heat-exposure budgets and a tamper-evident log for vaccine batches.</p>
      </div>
      <div className="bg-[#eef4f6] text-slate-900 p-12 flex flex-col justify-center gap-3">
        <h2 className="text-2xl font-bold">Sign in</h2>
        <input className="border rounded-xl px-4 py-3" value={u} onChange={x => setU(x.target.value)} placeholder="Username" />
        <input className="border rounded-xl px-4 py-3" type="password" value={p} onChange={x => setP(x.target.value)} placeholder="Password" onKeyDown={x => x.key === 'Enter' && go()} />
        {e && <p className="text-red-700 text-sm">{e}</p>}
        <button onClick={go} className="bg-[#0e5a7a] text-white font-bold rounded-xl py-3 focus-visible:outline outline-2 outline-offset-2">Sign in</button>
        <p className="text-xs text-slate-500">Demo: admin / pharmacist / inspector, password is the name + 123.</p>
      </div>
    </div>
  );
}

// ---------- Main app ----------
export default function App() {
  const [auth, setAuth] = useState(readAuth);
  const [tab, setTab] = useState('live');
  const [fr, setFr] = useState([]), [bt, setBt] = useState([]), [logs, setLogs] = useState([]);
  const [ver, setVer] = useState(null), [msg, setMsg] = useState('');
  const [nb, setNb] = useState({ code: '', vaccine: '', expiry: '', fridge_id: '' });
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => { const h = () => setHash(window.location.hash); window.addEventListener('hashchange', h); return () => window.removeEventListener('hashchange', h); }, []);
  useEffect(() => {
    if (auth) localStorage.setItem(AUTH_KEY, JSON.stringify(auth)); else localStorage.removeItem(AUTH_KEY);
  }, [auth]);

  const api = useCallback(() => axios.create({ baseURL: API, headers: { Authorization: `Bearer ${auth?.token}` } }), [auth]);
  // One instance per session: the live view polls on an interval, and a fresh object every render
  // would tear that interval down and rebuild it.
  const client = useMemo(() => api(), [api]);
  const load = useCallback(async () => {
    if (!auth) return;
    try {
      const c = api();
      setFr((await c.get('/api/dashboard')).data); setBt((await c.get('/api/batches')).data);
      if (auth.role !== 'pharmacist') setLogs((await c.get('/api/audits')).data);
    } catch (e) { if (e.response?.status === 401) setAuth(null); }
  }, [auth, api]);
  useEffect(() => { load(); const i = setInterval(load, 4000); return () => clearInterval(i); }, [load]);

  if (hash.startsWith('#/check/')) return <PublicCheck code={decodeURIComponent(hash.slice(8))} />;
  if (!auth) return <Login onAuth={setAuth} />;

  const act = async (fn) => { try { await fn(); setMsg(''); load(); } catch (e) { setMsg(errMsg(e)); } };
  const canEdit = auth.role !== 'inspector', isAdmin = auth.role === 'admin', canAudit = auth.role !== 'pharmacist';
  const tabs = ['live', 'dashboard', 'inventory', ...(canAudit ? ['audit log'] : [])];

  return (
    <div className="min-h-screen bg-[#eef4f6] text-slate-900" style={font}>
      <header className="bg-[#0b2a3b] text-white px-6 py-3 flex items-center gap-6 flex-wrap">
        <span className="flex items-center gap-2 text-xl" style={serif}><Snowflake className="h-5 w-5 text-sky-300" />ColdChain</span>
        <nav className="flex gap-1">{tabs.map(t => <button key={t} onClick={() => setTab(t)} className={`px-4 py-1.5 rounded-full text-sm capitalize ${tab === t ? 'bg-white text-[#0b2a3b] font-bold' : 'text-sky-100/80 hover:bg-white/10'}`}>{t}</button>)}</nav>
        <span className="ml-auto text-sm text-sky-100/70">{auth.username} ({auth.role})</span>
        <button aria-label="Sign out" onClick={() => setAuth(null)}><LogOut className="h-4 w-4" /></button>
      </header>
      <main className="max-w-6xl mx-auto p-6">
        {msg && <p className="mb-4 bg-red-50 text-red-800 border border-red-200 rounded-xl px-4 py-2 text-sm">{msg}</p>}

        {tab === 'live' && <Live api={client} isAdmin={isAdmin} onDone={load} />}

        {tab === 'dashboard' && <div className="grid md:grid-cols-2 gap-6">
          {fr.map(f => (
            <section key={f.id} className="bg-white rounded-3xl p-6" style={{ borderTop: `6px solid ${TONE[f.status]}` }}>
              <div className="flex justify-between items-start">
                <div><h2 className="text-xl font-bold">{f.name}</h2><p className="text-xs text-slate-500">{f.device_id} · {f.online ? 'online' : 'offline'}</p></div>
                <Pill s={f.status} />
              </div>
              <p className="mt-3 text-7xl font-extrabold tracking-tight" style={serif}>{f.temperature == null ? '--.-' : f.temperature.toFixed(1)}<span className="text-2xl text-slate-400">°C</span></p>
              <Spark data={f.history} />
              <Cells f={f} />
              <h3 className="mt-5 mb-2 text-sm font-bold">Heat budget per batch</h3>
              {f.batches.length === 0 && <p className="text-sm text-slate-400">No batches in this fridge.</p>}
              {f.batches.map(b => (
                <div key={b.id} className="mb-2">
                  <div className="flex justify-between text-sm"><span>{b.code} · {b.vaccine}</span><span>{b.remaining_min} min left <Pill s={b.status} /></span></div>
                  <div className="h-2 rounded bg-slate-100 mt-1"><div className="h-2 rounded" style={{ width: `${b.remaining_pct}%`, background: TONE[b.status] }} /></div>
                </div>
              ))}
            </section>
          ))}
          {fr.length === 0 && <p className="text-slate-500">Loading fridges…</p>}
        </div>}

        {tab === 'inventory' && <div className="space-y-6">
          {canEdit && <div className="bg-white rounded-3xl p-6 grid sm:grid-cols-5 gap-2">
            {['code', 'vaccine', 'expiry'].map(k => <input key={k} type={k === 'expiry' ? 'date' : 'text'} placeholder={k} className="border rounded-xl px-3 py-2" value={nb[k]} onChange={e => setNb({ ...nb, [k]: e.target.value })} />)}
            <select className="border rounded-xl px-3 py-2" value={nb.fridge_id} onChange={e => setNb({ ...nb, fridge_id: e.target.value })}>
              <option value="">Unassigned</option>{fr.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            <button className="bg-[#0e5a7a] text-white font-bold rounded-xl" onClick={() => act(async () => { await api().post('/api/batches', { ...nb, fridge_id: nb.fridge_id ? +nb.fridge_id : null }); setNb({ code: '', vaccine: '', expiry: '', fridge_id: '' }); })}>Add batch</button>
          </div>}
          <div className="bg-white rounded-3xl overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-slate-500"><tr>{['Batch', 'Vaccine', 'Expiry', 'Status', 'Budget left', 'Fridge', 'QR', 'Actions'].map(h => <th key={h} className="p-4 font-medium">{h}</th>)}</tr></thead>
              <tbody>{bt.map(b => (
                <tr key={b.id} className="border-t">
                  <td className="p-4 font-bold">{b.code}</td><td>{b.vaccine}</td><td>{b.expiry}</td><td><Pill s={b.status} /></td><td>{b.remaining_min} min</td>
                  <td>{canEdit ? <select className="border rounded-lg px-2 py-1" value={b.fridge_id ?? ''} onChange={e => act(() => api().put(`/api/batches/${b.id}/move`, { fridge_id: e.target.value ? +e.target.value : null }))}>
                    <option value="">Unassigned</option>{fr.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select> : fr.find(f => f.id === b.fridge_id)?.name || '-'}</td>
                  <td className="py-2"><QRCodeSVG size={56} value={`${window.location.origin}/#/check/${b.code}`} /></td>
                  <td><a className="text-sky-700 underline" href={`#/check/${b.code}`} target="_blank" rel="noreferrer">Open QR page</a>
                    {isAdmin && b.status !== 'Safe' && <button className="ml-3 text-red-700 underline" onClick={() => act(() => api().post(`/api/batches/${b.id}/reset`))}>Admin reset</button>}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </div>}

        {tab === 'audit log' && <div className="bg-white rounded-3xl p-6">
          <div className="flex items-center gap-4 mb-4">
            <button className="bg-[#0e5a7a] text-white font-bold rounded-xl px-4 py-2" onClick={() => act(async () => setVer((await api().get('/api/audits/verify')).data))}>Verify integrity</button>
            {ver && <span className={`font-bold ${ver.valid ? 'text-emerald-700' : 'text-red-700'}`}>{ver.valid ? `Chain intact (${ver.checked} records)` : `Tampering detected at record #${ver.broken_at}: ${ver.reason}`}</span>}
          </div>
          <div className="overflow-x-auto"><table className="w-full text-sm text-left">
            <thead className="text-slate-500"><tr>{['#', 'Event', 'Details', 'Hash', 'Time'].map(h => <th key={h} className="py-2 pr-4 font-medium">{h}</th>)}</tr></thead>
            <tbody>{logs.map(l => <tr key={l.id} className="border-t"><td className="py-2 pr-4">{l.id}</td>
              <td className="pr-4 font-bold" style={{ color: /REJECT|ALERT|FAILED/.test(l.action) ? TONE.Breach : undefined }}>{l.action}</td>
              <td className="pr-4">{l.details}</td><td className="pr-4 font-mono text-xs" title={l.current_hash}>{l.current_hash.slice(0, 12)}…</td>
              <td className="text-xs">{new Date(l.timestamp + 'Z').toLocaleString()}</td></tr>)}</tbody>
          </table></div>
        </div>}
      </main>
    </div>
  );
}