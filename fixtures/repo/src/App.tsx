import { useState } from 'react';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';

export function App() {
  const [user, setUser] = useState<string | null>(null);
  return user ? <Dashboard user={user} /> : <Login onLogin={setUser} />;
}
