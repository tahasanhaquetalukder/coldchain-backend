import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Activity, ShieldCheck, Server, RefreshCw, Cpu, Database, AlertTriangle, CheckCircle2 } from 'lucide-react';

const API_BASE_URL = "http://127.0.0.1:8000";

function App() {
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(new Date().toLocaleTimeString());

  const fetchData = async () => {
    setLoading(true);
    try {
      const auditRes = await axios.get(`${API_BASE_URL}/api/audits`);
      setAuditLogs(auditRes.data);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (error) {
      console.error("Error fetching data from backend:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 4000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-teal-500 selection:text-slate-950">
      {/* Top Header */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50 px-8 py-4 flex justify-between items-center shadow-lg">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-teal-500/10 border border-teal-500/30 rounded-xl text-teal-400 shadow-[0_0_15px_rgba(20,184,166,0.2)]">
            <Activity className="h-6 w-6 animate-pulse" />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-wider text-white flex items-center gap-2">
              COLD<span className="text-teal-400">CHAIN</span> 
              <span className="text-xs px-2 py-0.5 rounded-full bg-teal-500/20 text-teal-300 border border-teal-500/30 font-normal">IoT Security v2.0</span>
            </h1>
            <p className="text-xs text-slate-400">Secure Hash-Chain Telemetry & Audit Dashboard</p>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          <div className="text-right hidden sm:block">
            <p className="text-xs text-slate-400">Last Synced</p>
            <p className="text-xs font-mono text-teal-400">{lastUpdated}</p>
          </div>
          <button 
            onClick={fetchData} 
            className="flex items-center space-x-2 bg-gradient-to-r from-teal-500 to-emerald-600 hover:from-teal-400 hover:to-emerald-500 text-slate-950 font-bold px-4 py-2.5 rounded-xl text-sm transition shadow-lg shadow-teal-500/20 active:scale-95"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            <span>Sync Telemetry</span>
          </button>
        </div>
      </header>

      {/* Main Dashboard Content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        
        {/* Metric Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          
          {/* Card 1 */}
          <div className="bg-slate-900/80 border border-slate-800/80 p-6 rounded-2xl relative overflow-hidden shadow-xl backdrop-blur-sm group hover:border-teal-500/50 transition">
            <div className="absolute top-0 right-0 w-32 h-32 bg-teal-500/5 rounded-full blur-2xl group-hover:bg-teal-500/10 transition"></div>
            <div className="flex items-center justify-between relative z-10">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">System Status</p>
                <div className="flex items-center gap-2 mt-2">
                  <span className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                  </span>
                  <h3 className="text-2xl font-extrabold text-emerald-400 tracking-tight">Operational</h3>
                </div>
              </div>
              <div className="p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-2xl text-emerald-400">
                <Server className="h-6 w-6" />
              </div>
            </div>
          </div>

          {/* Card 2 */}
          <div className="bg-slate-900/80 border border-slate-800/80 p-6 rounded-2xl relative overflow-hidden shadow-xl backdrop-blur-sm group hover:border-indigo-500/50 transition">
            <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/5 rounded-full blur-2xl group-hover:bg-indigo-500/10 transition"></div>
            <div className="flex items-center justify-between relative z-10">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Security Audit Trail</p>
                <h3 className="text-3xl font-extrabold text-white mt-1 tracking-tight">{auditLogs.length} <span className="text-xs text-indigo-400 font-normal">Blocks Linked</span></h3>
              </div>
              <div className="p-4 bg-indigo-500/10 border border-indigo-500/20 rounded-2xl text-indigo-400">
                <ShieldCheck className="h-6 w-6" />
              </div>
            </div>
          </div>

          {/* Card 3 */}
          <div className="bg-slate-900/80 border border-slate-800/80 p-6 rounded-2xl relative overflow-hidden shadow-xl backdrop-blur-sm group hover:border-cyan-500/50 transition">
            <div className="absolute top-0 right-0 w-32 h-32 bg-cyan-500/5 rounded-full blur-2xl group-hover:bg-cyan-500/10 transition"></div>
            <div className="flex items-center justify-between relative z-10">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Validation Algorithm</p>
                <h3 className="text-2xl font-extrabold text-cyan-400 mt-1 tracking-tight">HMAC-SHA256</h3>
              </div>
              <div className="p-4 bg-cyan-500/10 border border-cyan-500/20 rounded-2xl text-cyan-400">
                <Cpu className="h-6 w-6" />
              </div>
            </div>
          </div>

        </div>

        {/* Audit Logs Table Section */}
        <div className="bg-slate-900/80 border border-slate-800/80 rounded-2xl shadow-2xl overflow-hidden backdrop-blur-sm">
          <div className="px-6 py-5 border-b border-slate-800 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-slate-900/50">
            <div>
              <h3 className="font-bold text-lg text-white flex items-center gap-2">
                <Database className="h-5 w-5 text-teal-400" />
                Cryptographic Hash-Chain Audit Logs
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">Real-time immutable telemetry tracking logs submitted by IoT simulators.</p>
            </div>
            <span className="text-xs bg-teal-500/10 text-teal-300 border border-teal-500/20 px-3 py-1.5 rounded-xl font-medium flex items-center gap-1.5 shadow-inner">
              <CheckCircle2 className="h-3.5 w-3.5" /> Tamper-Evident Ledger
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-950/60 text-slate-400 text-xs uppercase tracking-wider font-semibold border-b border-slate-800">
                  <th className="py-4 px-6">ID</th>
                  <th className="py-4 px-6">Action / Event</th>
                  <th className="py-4 px-6">Details / Telemetry</th>
                  <th className="py-4 px-6">Current Hash (SHA-256)</th>
                  <th className="py-4 px-6">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-sm">
                {auditLogs.length > 0 ? (
                  auditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-800/40 transition group">
                      <td className="py-4 px-6 font-mono font-bold text-teal-400">#{log.id}</td>
                      <td className="py-4 px-6">
                        <span className="bg-teal-500/10 text-teal-300 border border-teal-500/20 text-xs px-3 py-1 rounded-lg font-semibold shadow-sm">
                          {log.action}
                        </span>
                      </td>
                      <td className="py-4 px-6 text-slate-300 font-medium">{log.details}</td>
                      <td className="py-4 px-6 font-mono text-xs text-slate-400 max-w-xs truncate group-hover:text-slate-200 transition" title={log.current_hash}>
                        {log.current_hash}
                      </td>
                      <td className="py-4 px-6 text-slate-400 text-xs font-mono">
                        {new Date(log.timestamp).toLocaleString()}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="5" className="text-center py-16 text-slate-500">
                      <div className="flex flex-col items-center justify-center space-y-3">
                        <AlertTriangle className="h-8 w-8 text-slate-600 animate-bounce" />
                        <p className="text-slate-400 font-medium">No audit logs found yet.</p>
                        <p className="text-xs text-slate-600">Run your IoT python simulator script to start streaming live telemetry data!</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

      </main>
    </div>
  );
}

export default App;