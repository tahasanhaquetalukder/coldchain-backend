import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { QRCodeSVG } from 'qrcode.react';
import { Snowflake, DoorOpen, DoorClosed, Zap, BatteryLow, Fan, ShieldCheck, LogOut, AlertTriangle } from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
const TONE = { Safe: '#1f8a5b', Warning: '#c98a0a', Breach: '#c8372d', 'At Risk': '#c98a0a', Discard: '#c8372d' };
const font = { fontFamily: "'Public Sans', sans-serif" };
const serif = { fontFamily: "'Fraunces', serif" };

const Pill = ({ s }) => (
  <span className="px-2.5 py-1 rounded-full text-xs font-bold text-white" style={{ background: TONE[s] }}>{s}</span>
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
  const go = async () => { try { onAuth((await axios.post(`${API}/api/auth/login`, { username: u, password: p })).data); } catch (x) { setE(x.response?.data?.detail || 'Server not reachable'); } };
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
  const [auth, setAuth] = useState(null);
  const [tab, setTab] = useState('dashboard');
  const [fr, setFr] = useState([]), [bt, setBt] = useState([]), [logs, setLogs] = useState([]);
  const [ver, setVer] = useState(null), [msg, setMsg] = useState('');
  const [nb, setNb] = useState({ code: '', vaccine: '', expiry: '', fridge_id: '' });
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => { const h = () => setHash(window.location.hash); window.addEventListener('hashchange', h); return () => window.removeEventListener('hashchange', h); }, []);

  const api = useCallback(() => axios.create({ baseURL: API, headers: { Authorization: `Bearer ${auth?.token}` } }), [auth]);
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

  const act = async (fn) => { try { await fn(); setMsg(''); load(); } catch (e) { setMsg(e.response?.data?.detail || 'Action failed'); } };
  const canEdit = auth.role !== 'inspector', isAdmin = auth.role === 'admin', canAudit = auth.role !== 'pharmacist';
  const tabs = ['dashboard', 'inventory', ...(canAudit ? ['audit log'] : [])];

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

        {tab === 'dashboard' && <div className="grid md:grid-cols-2 gap-6">
          {fr.map(f => (
            <section key={f.id} className="bg-white rounded-3xl p-6" style={{ borderTop: `6px solid ${TONE[f.status]}` }}>
              <div className="flex justify-between items-start">
                <div><h2 className="text-xl font-bold">{f.name}</h2><p className="text-xs text-slate-500">{f.device_id} · {f.online ? 'online' : 'offline'}</p></div>
                <Pill s={f.status} />
              </div>
              <p className="mt-3 text-7xl font-extrabold tracking-tight" style={serif}>{f.temperature.toFixed(1)}<span className="text-2xl text-slate-400">°C</span></p>
              <Spark data={f.history} />
              <div className="grid grid-cols-4 gap-2 mt-4 text-xs text-center">
                <div className="rounded-xl bg-slate-50 p-2">{f.door_open ? <DoorOpen className="mx-auto text-amber-600" /> : <DoorClosed className="mx-auto text-slate-500" />}Door {f.door_open ? 'open' : 'closed'}</div>
                <div className="rounded-xl bg-slate-50 p-2">{f.power_ok ? <Zap className="mx-auto text-emerald-600" /> : <BatteryLow className="mx-auto text-red-600" />}{f.power_ok ? 'Mains' : `Battery ${f.battery}%`}</div>
                <div className="rounded-xl bg-slate-50 p-2"><Fan className={`mx-auto ${f.compressor_on ? 'text-sky-600' : 'text-slate-400'}`} />Compressor {f.compressor_on ? 'on' : 'off'}</div>
                <div className="rounded-xl bg-slate-50 p-2">{f.door_alert ? <AlertTriangle className="mx-auto text-red-600" /> : <ShieldCheck className="mx-auto text-emerald-600" />}{f.door_alert ? 'Door alert' : 'No alerts'}</div>
              </div>
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