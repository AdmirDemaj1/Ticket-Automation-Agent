// Defaults for e2e runs. DATABASE_URL must point at a disposable database.
process.env.NODE_ENV = 'test';
process.env.LOG_LEVEL ??= 'error';
process.env.DATABASE_URL ??= 'postgresql://mtj:mtj@localhost:5433/mtj_test';
process.env.SERVICE_TOKEN ??= 'test-service-token-0123456789';
