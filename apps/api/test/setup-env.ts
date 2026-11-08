// Defaults for e2e runs. DATABASE_URL must point at a disposable database.
process.env.NODE_ENV = 'test';
process.env.LOG_LEVEL ??= 'error';
process.env.DATABASE_URL ??= 'postgresql://mtj:mtj@localhost:5433/mtj_test';
process.env.SERVICE_TOKEN ??= 'test-service-token-0123456789';
process.env.JWT_SECRET ??= 'test-jwt-secret-0123456789abcdef0123456789';
process.env.TOKEN_ENC_KEY ??= Buffer.alloc(32, 7).toString('base64');
process.env.TOKEN_ENC_KEY_ID ??= 'k1';
process.env.AUTH_RATE_LIMIT_PER_MIN ??= '1000';
process.env.REFRESH_REUSE_GRACE_SECONDS ??= '0';
