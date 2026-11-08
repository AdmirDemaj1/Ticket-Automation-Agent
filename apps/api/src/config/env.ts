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
  TRUST_PROXY: z.string().default('loopback, uniquelocal'),

  JWT_SECRET: z.string().min(32, 'JWT_SECRET must be at least 32 characters'),
  JWT_ACCESS_TTL_SECONDS: z.coerce.number().int().min(60).max(3600).default(900),
  REFRESH_TTL_DAYS: z.coerce.number().int().min(1).max(90).default(14),
  /** A rotated refresh token replayed within this window (e.g. two tabs refreshing at once) gets a 401 but does not revoke the session family. */
  REFRESH_REUSE_GRACE_SECONDS: z.coerce.number().int().min(0).max(60).default(10),
  AUTH_RATE_LIMIT_PER_MIN: z.coerce.number().int().positive().default(10),

  TOKEN_ENC_KEY: z
    .string()
    .refine((v) => Buffer.from(v, 'base64').length === 32, 'must be base64 of exactly 32 bytes'),
  TOKEN_ENC_KEY_ID: z
    .string()
    .regex(/^[A-Za-z0-9_-]{1,32}$/)
    .default('k1'),
  TOKEN_ENC_OLD_KEYS: z.string().default(''),
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
