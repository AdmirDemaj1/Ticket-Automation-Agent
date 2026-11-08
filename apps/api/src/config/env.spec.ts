import { validateEnv } from './env';

const base = {
  DATABASE_URL: 'postgres://u:p@localhost:5432/db',
  SERVICE_TOKEN: 'x'.repeat(32),
  JWT_SECRET: 'j'.repeat(32),
  TOKEN_ENC_KEY: Buffer.alloc(32, 1).toString('base64'),
};

describe('validateEnv', () => {
  it('applies defaults', () => {
    const env = validateEnv(base);
    expect(env.PORT).toBe(3000);
    expect(env.NODE_ENV).toBe('development');
  });

  it('rejects an encryption key that is not 32 bytes', () => {
    const bad = Buffer.alloc(16, 1).toString('base64');
    expect(() => validateEnv({ ...base, TOKEN_ENC_KEY: bad })).toThrow(/TOKEN_ENC_KEY/);
    expect(() => validateEnv({ ...base, TOKEN_ENC_KEY: bad })).not.toThrow(new RegExp(bad));
  });

  it('rejects a short service token without echoing its value', () => {
    expect(() => validateEnv({ ...base, SERVICE_TOKEN: 'secretvalue' })).toThrow(/SERVICE_TOKEN/);
    expect(() => validateEnv({ ...base, SERVICE_TOKEN: 'secretvalue' })).not.toThrow(/secretvalue/);
  });
});
