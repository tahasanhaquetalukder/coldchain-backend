import { lazy, Suspense } from 'react';
import { Boxes, Cpu, LayoutDashboard, LogOut, Moon, ScrollText, Snowflake, Sun } from 'lucide-react';
import { API_BASE } from './api.js';
import { AuthProvider, useAuth } from './auth.jsx';
import { Loading } from './components/States.jsx';
import { navigate, useHashRoute } from './components/useRoute.js';
import { useTheme } from './components/theme.js';
import Login from './pages/Login.jsx';
import PublicCheck from './pages/PublicCheck.jsx';

// The tabs a signed-in person gets. Nothing else is reachable by typing a hash, because a route
// only becomes a page when it matches one of these four paths.
const TABS = [
  { path: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, show: () => true },
  { path: 'inventory', label: 'Inventory', icon: Boxes, show: () => true },
  { path: 'devices', label: 'Devices', icon: Cpu, show: () => true },
  { path: 'audit', label: 'Audit trail', icon: ScrollText, show: (auth) => auth.canReadAudit },
];

// Only the signed-in views are split out: recharts rides in with them, and a phone that scanned a
// QR label should not have to download it to read one word — "Safe".
const PAGES = {
  dashboard: lazy(() => import('./pages/Dashboard.jsx')),
  inventory: lazy(() => import('./pages/Inventory.jsx')),
  devices: lazy(() => import('./pages/Devices.jsx')),
  audit: lazy(() => import('./pages/Audit.jsx')),
};

function Shell() {
  const route = useHashRoute();
  const auth = useAuth();
  const { theme, toggleTheme } = useTheme();

  // A scanned QR label opens #/check/CODE on whoever's phone it is. Resolved before the auth gate
  // and outside the header, so a login cannot block it and it cannot show the console.
  const scanned = route.match(/^check\/(.+)$/);
  if (scanned) return <PublicCheck code={decodeURIComponent(scanned[1])} />;

  if (!auth.session) return <Login />;

  const active = TABS.some((t) => t.path === route) ? route : 'dashboard';
  const tab = TABS.find((t) => t.path === active);
  const Page = PAGES[active];

  return (
    <div className="min-h-screen bg-page">
      <header className="bg-sidebar text-on-dark">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-4">
          <div className="flex items-center gap-3">
            <Snowflake className="h-6 w-6 shrink-0 text-accent-2" />
            <div className="min-w-0 flex-1">
              <p className="display leading-tight truncate">Cold-chain Console</p>
              <p className="text-[11px] text-on-dark-2 truncate">
                {/* naming the API host: "no data" and "wrong VITE_API_BASE" look identical otherwise */}
                {auth.username} · {auth.role} · API {API_BASE || window.location.origin}
              </p>
            </div>
            <button
              className="flex items-center gap-2 rounded-xl border border-[var(--on-dark-line)] px-3 py-1.5 text-sm hover:bg-[var(--on-dark-hover)]"
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme'}
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              <span className="hidden sm:inline">{theme === 'dark' ? 'Light' : 'Dark'}</span>
            </button>
            <button
              className="flex items-center gap-2 rounded-xl border border-[var(--on-dark-line)] px-3 py-1.5 text-sm hover:bg-[var(--on-dark-hover)]"
              onClick={() => {
                auth.logout();
                navigate('/dashboard');
              }}
            >
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
          <nav className="mt-3 flex gap-1 overflow-x-auto text-sm" aria-label="Sections">
            {TABS.filter((t) => t.show(auth)).map((t) => {
              const Icon = t.icon;
              const on = t.path === active;
              return (
                <button
                  key={t.path}
                  onClick={() => navigate(`/${t.path}`)}
                  aria-current={on ? 'page' : undefined}
                  className={`flex shrink-0 items-center gap-2 rounded-t-xl px-4 py-2 font-bold ${
                    on ? 'bg-page text-text' : 'text-on-dark-2 hover:bg-[var(--on-dark-hover)]'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {t.label}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 sm:px-6 py-6">
        {tab.show(auth) ? (
          <Suspense fallback={<Loading rows={4} h="h-24" />}>
            <Page />
          </Suspense>
        ) : (
          <p className="card text-sm text-text-2">
            The {tab.label.toLowerCase()} view belongs to the admin and inspector roles. You are
            signed in as <span className="font-bold">{auth.role}</span>.
          </p>
        )}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
