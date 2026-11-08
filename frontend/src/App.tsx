import { NavLink, Route, Routes } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { NewRunPage } from '@/pages/NewRunPage';
import { RunsPage } from '@/pages/RunsPage';
import { StatusPage } from '@/pages/StatusPage';

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'text-sm',
    isActive ? 'font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground',
  );

export function App() {
  return (
    <div className="min-h-screen">
      <header className="flex items-center gap-6 border-b border-border px-6 py-3">
        <span className="font-semibold">Meeting → Jira</span>
        <nav aria-label="Main" className="flex gap-4">
          <NavLink to="/" end className={navClass}>
            Runs
          </NavLink>
          <NavLink to="/runs/new" className={navClass}>
            New run
          </NavLink>
          <NavLink to="/status" className={navClass}>
            Status
          </NavLink>
        </nav>
      </header>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<RunsPage />} />
          <Route path="/runs/new" element={<NewRunPage />} />
          <Route path="/status" element={<StatusPage />} />
        </Routes>
      </main>
    </div>
  );
}
