import { zodResolver } from '@hookform/resolvers/zod';
import { loginRequest, type LoginRequest } from '@mtj/contracts';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/auth/use-auth';
import { FormField } from '@/components/FormField';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api';

export function LoginPage() {
  const { state, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? '/';
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginRequest>({ resolver: zodResolver(loginRequest) });

  if (state.status === 'authenticated') return <Navigate to={from} replace />;

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values);
      navigate(from, { replace: true });
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.');
    }
  });

  return (
    <Card className="mx-auto max-w-sm">
      <CardTitle>Log in</CardTitle>
      <CardDescription>Use your email and password.</CardDescription>
      <form className="mt-6 space-y-4" onSubmit={onSubmit} noValidate>
        <FormField
          label="Email"
          type="email"
          autoComplete="email"
          error={errors.email?.message}
          {...register('email')}
        />
        <FormField
          label="Password"
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          {...register('password')}
        />
        {formError && (
          <p role="alert" className="text-sm text-destructive">
            {formError}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? 'Logging in…' : 'Log in'}
        </Button>
      </form>
      <p className="mt-4 text-sm text-muted-foreground">
        No account?{' '}
        <Link to="/register" className="text-primary underline-offset-4 hover:underline">
          Create one
        </Link>
      </p>
    </Card>
  );
}
