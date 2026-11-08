import { validateEnv } from './env';

const base = {
  DATABASE_URL: 'postgres://u:p@localhost:5432/db',
  SERVICE_TOKEN: 'x'.repeat(32),
};

describe('validateEnv', () => {
  it('applies defaults', () => {
    const env = validateEnv(base);
    expect(env.PORT).toBe(3000);
    expect(env.NODE_ENV).toBe('development');
  });

  it('rejects a short service token without echoing its value', () => {
    expect(() => validateEnv({ ...base, SERVICE_TOKEN: 'secretvalue' })).toThrow(/SERVICE_TOKEN/);
    expect(() => validateEnv({ ...base, SERVICE_TOKEN: 'secretvalue' })).not.toThrow(/secretvalue/);
  });
});
