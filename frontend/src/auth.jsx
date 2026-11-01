import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { http, readSession, registerExpiredHandler, writeSession } from './api.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(readSession);

  // The interceptor in api.js cannot reach React state on its own; this is the one place a dead
  // token turns into "show the login page".
  useEffect(() => registerExpiredHandler(() => setSession(readSession())), []);

  const login = useCallback(async (username, password) => {
    const { data } = await http.post('/api/auth/login', { username, password });
    writeSession(data);
    setSession(data);
    return data;
  }, []);

  const logout = useCallback(() => {
    writeSession(null);
    setSession(null);
  }, []);

  const value = useMemo(() => {
    const role = session?.role || null;
    return {
      session,
      role,
      username: session?.username || '',
      login,
      logout,
      // every gate in the UI asks the server's own role list, never a name in the URL
      isAdmin: role === 'admin',
      canEditStock: role === 'admin' || role === 'pharmacist',
      canReadAudit: role === 'admin' || role === 'inspector',
    };
  }, [session, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
