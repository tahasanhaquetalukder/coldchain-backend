import { useState } from 'react';
import { Snowflake } from 'lucide-react';
import { errorMessage } from '../api.js';
import { useAuth } from '../auth.jsx';
import { FormNote } from '../components/States.jsx';

const ROLES = ['admin', 'pharmacist', 'inspector'];

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin123');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await login(username, password);
    } catch (x) {
      setError(errorMessage(x));
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-sidebar text-on-dark grid md:grid-cols-2">
      <div className="p-8 sm:p-12 flex flex-col justify-end">
        <Snowflake className="h-10 w-10 text-accent-2 mb-6" />
        <h1 className="display text-4xl sm:text-6xl leading-none">
          Every dose,
          <br />
          kept between 2 and 8 degrees.
        </h1>
        <p className="mt-5 text-on-dark-2 max-w-md">
          Live fridge monitoring, heat-exposure budgets and a tamper-evident log for vaccine batches.
        </p>
      </div>

      <div className="bg-page text-text p-8 sm:p-12 flex flex-col justify-center gap-3">
        <h2 className="text-2xl font-bold">Sign in</h2>
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <label className="text-sm">
            <span className="label">Username</span>
            <input
              className="field w-full mt-1"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label className="text-sm">
            <span className="label">Password</span>
            <input
              className="field w-full mt-1"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {/* the note keeps its own row so the button cannot jump when a password is wrong */}
          <div className="min-h-11">
            {error && <FormNote message={error} />}
          </div>
          <button className="btn-primary w-full py-3" disabled={busy} type="submit">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="text-xs text-muted">
          Demo accounts: {ROLES.map((r) => `${r} / ${r}123`).join(' · ')}. Sessions end when the tab
          closes.
        </p>
      </div>
    </div>
  );
}
