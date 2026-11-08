import { z } from 'zod';

/**
 * Environment schema. Validated once at boot; the app refuses to start on invalid config.
 * Secrets are never logged.
 */
export const envSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().int().positive().default(3000),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace']).default('info'),
  DATABASE_URL: z.string().min(1),
  WEB_ORIGIN: z.string().url().default('http://localhost:5173'),
  SERVICE_TOKEN: z.string().min(16, 'SERVICE_TOKEN must be at least 16 characters'),
  AGENT_BASE_URL: z.string().url().default('http://agent:8000'),
});

export type Env = z.infer<typeof envSchema>;

export function validateEnv(raw: Record<string, unknown>): Env {
  const parsed = envSchema.safeParse(raw);
  if (!parsed.success) {
    // Only report which keys are wrong, never their values.
    const issues = parsed.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ');
    throw new Error(`Invalid environment configuration: ${issues}`);
  }
  return parsed.data;
}
