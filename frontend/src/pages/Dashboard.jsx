import { http } from '../api.js';
import { BatteryBar, BigTemp, Cells, OnlineDot } from '../components/Readouts.jsx';
import BudgetBar from '../components/BudgetBar.jsx';
import DoorBanner from '../components/DoorBanner.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import { Sparkline } from '../components/Charts.jsx';
import { Empty, ErrorNote, Loading } from '../components/States.jsx';
import { navigate } from '../components/useRoute.js';
import { usePoll } from '../components/usePoll.js';
import { tone } from '../components/status.js';

const POLL_MS = 5000;

function FridgeCard({ fridge }) {
  return (
    <section className="card" style={{ borderTop: `6px solid ${tone(fridge.status)}` }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-bold truncate">{fridge.name}</h2>
          <p className="text-xs text-muted truncate">{fridge.device_id}</p>
          <div className="mt-1 flex items-center gap-3">
            <OnlineDot ageS={null} online={fridge.online} />
            <BatteryBar battery={fridge.battery} powerOk={fridge.power_ok} />
          </div>
        </div>
        <StatusBadge status={fridge.status} />
      </div>

      <BigTemp temperature={fridge.temperature} status={fridge.status} />
      <Sparkline history={fridge.history} />
      <Cells device={fridge} />

      <h3 className="mt-5 mb-2 label">Heat budget per batch</h3>
      {fridge.batches.length === 0 ? (
        <p className="text-sm text-muted pb-3">No batches stored in this fridge.</p>
      ) : (
        fridge.batches.map((b) => <BudgetBar key={b.id} batch={b} />)
      )}
    </section>
  );
}

export default function Dashboard() {
  const { data, error, loading, refresh } = usePoll(
    () => http.get('/api/dashboard').then((r) => r.data),
    POLL_MS,
  );
  const fridges = data || [];

  return (
    <div>
      <DoorBanner fridges={fridges} />
      <ErrorNote message={error && fridges.length === 0 ? error : ''} onRetry={refresh} />
      {error && fridges.length > 0 && (
        <p className="text-xs text-danger-strong mb-2">Last refresh failed: {error}</p>
      )}

      {loading ? (
        <div className="grid md:grid-cols-2 gap-6">
          <Loading rows={6} />
          <Loading rows={6} />
        </div>
      ) : fridges.length === 0 ? (
        <Empty
          title="No fridges registered yet"
          hint="Add your ESP32 on the Devices page - it gets its own key to paste into cc_config.h."
        />
      ) : (
        <>
          <div className="grid md:grid-cols-2 gap-6">
            {fridges.map((f) => (
              <FridgeCard key={f.id} fridge={f} />
            ))}
          </div>
          <p className="mt-6 text-xs text-muted">
            Numbers refresh every {POLL_MS / 1000} seconds from <span className="font-mono">/api/dashboard</span>.
            A fridge that has never reported shows <em>No data</em> rather than a safe-looking 5.0.
          </p>
          <button className="btn-quiet mt-2" onClick={() => navigate('/devices')}>
            Open the live device view
          </button>
        </>
      )}
    </div>
  );
}
