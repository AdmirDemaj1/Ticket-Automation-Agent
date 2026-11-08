import { NavLink, Route, Routes } from 'react-router-dom';
import { RequireAuth } from '@/auth/RequireAuth';
import { useAuth } from '@/auth/use-auth';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { ConnectionsPage } from '@/pages/ConnectionsPage';
import { HomePage } from '@/pages/HomePage';
import { LoginPage } from '@/pages/LoginPage';
import { RegisterPage } from '@/pages/RegisterPage';

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'text-sm',
    isActive ? 'font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground',
  );

function Header() {
  const { state, logout } = useAuth();
  return (
    <header className="flex items-center gap-6 border-b border-border px-6 py-3">
      <span className="font-semibold">Meeting → Jira</span>
      {state.status === 'authenticated' && (
        <>
          <nav aria-label="Main" className="flex gap-4">
            <NavLink to="/" end className={navClass}>
              Home
            </NavLink>
            <NavLink to="/connections" className={navClass}>
              Connections
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-sm text-muted-foreground">{state.user.email}</span>
            <Button size="sm" variant="ghost" onClick={() => void logout()}>
              Log out
            </Button>
          </div>
        </>
      )}
    </header>
  );
}

export function App() {
  return (
    <div className="min-h-screen">
      <Header />
      <main className="p-6">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <HomePage />
              </RequireAuth>
            }
          />
          <Route
            path="/connections"
            element={
              <RequireAuth>
                <ConnectionsPage />
              </RequireAuth>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
