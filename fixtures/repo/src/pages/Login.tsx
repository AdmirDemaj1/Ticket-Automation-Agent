import { useState, type FormEvent } from 'react';
import { login } from '../api/auth';
import { Button } from '../components/Button';

export function Login({ onLogin }: { onLogin: (name: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      onLogin(await login(email, password));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form onSubmit={submit} className="login">
      {error && <div className="banner banner-error">{error}</div>}
      <h1>Sign in</h1>
      <label>
        Email
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Password
        <input
          type={showPassword ? 'text' : 'password'}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      <button type="button" onClick={() => setShowPassword((v) => !v)}>
        {showPassword ? 'Hide' : 'Show'} password
      </button>
      <Button type="submit">Sign in</Button>
    </form>
  );
}
