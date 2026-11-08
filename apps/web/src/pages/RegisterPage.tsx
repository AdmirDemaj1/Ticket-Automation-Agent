import { zodResolver } from '@hookform/resolvers/zod';
import { registerRequest, type RegisterRequest } from '@mtj/contracts';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '@/auth/use-auth';
import { FormField } from '@/components/FormField';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api';

export function RegisterPage() {
  const { state, register: signUp } = useAuth();
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterRequest>({ resolver: zodResolver(registerRequest) });

  if (state.status === 'authenticated') return <Navigate to="/" replace />;

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await signUp(values);
      navigate('/connections', { replace: true });
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.');
    }
  });

  return (
    <Card className="mx-auto max-w-sm">
      <CardTitle>Create an account</CardTitle>
      <CardDescription>You will connect Jira and your code host next.</CardDescription>
      <form className="mt-6 space-y-4" onSubmit={onSubmit} noValidate>
        <FormField
          label="Name"
          autoComplete="name"
          error={errors.name?.message}
          {...register('name')}
        />
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
          autoComplete="new-password"
          error={errors.password?.message}
          {...register('password')}
        />
        {formError && (
          <p role="alert" className="text-sm text-destructive">
            {formError}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
      <p className="mt-4 text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link to="/login" className="text-primary underline-offset-4 hover:underline">
          Log in
        </Link>
      </p>
    </Card>
  );
}
