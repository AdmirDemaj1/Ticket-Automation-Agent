import { randomBytes } from 'node:crypto';
import { TokenCipher, TokenCipherError } from './token-cipher';

const key = () => randomBytes(32);
const AAD = 'user-1:jira';

describe('TokenCipher', () => {
  it('round-trips a value', () => {
    const c = new TokenCipher('k1', key());
    const enc = c.encrypt('secret-access-token', AAD);
    expect(c.decrypt(enc, AAD)).toBe('secret-access-token');
  });

  it('round-trips empty and unicode strings', () => {
    const c = new TokenCipher('k1', key());
    for (const s of ['', 'ünïcødé 🔐', 'x'.repeat(10_000)]) {
      expect(c.decrypt(c.encrypt(s, AAD), AAD)).toBe(s);
    }
  });

  it('uses the stored format v1:<keyId>:<nonce>|<ct>|<tag> and never contains the plaintext', () => {
    const c = new TokenCipher('k1', key());
    const enc = c.encrypt('plain-token-value', AAD);
    expect(enc).toMatch(/^v1:k1:[A-Za-z0-9+/=]+\|[A-Za-z0-9+/=]+\|[A-Za-z0-9+/=]+$/);
    expect(enc).not.toContain('plain-token-value');
  });

  it('uses a fresh nonce per encryption', () => {
    const c = new TokenCipher('k1', key());
    expect(c.encrypt('same', AAD)).not.toBe(c.encrypt('same', AAD));
  });

  it('rejects a value bound to a different aad (row swap)', () => {
    const c = new TokenCipher('k1', key());
    const enc = c.encrypt('t', 'user-1:jira');
    expect(() => c.decrypt(enc, 'user-2:jira')).toThrow(TokenCipherError);
  });

  it('rejects tampered ciphertext and tag', () => {
    const c = new TokenCipher('k1', key());
    const enc = c.encrypt('token', AAD);
    const [prefix, rest] = [enc.slice(0, enc.indexOf('|') + 1), enc.slice(enc.indexOf('|') + 1)];
    const [ct, tag] = rest.split('|');
    const flip = (b64: string) => {
      const b = Buffer.from(b64, 'base64');
      b[0] ^= 0xff;
      return b.toString('base64');
    };
    expect(() => c.decrypt(`${prefix}${flip(ct)}|${tag}`, AAD)).toThrow('Token decryption failed');
    expect(() => c.decrypt(`${prefix}${ct}|${flip(tag)}`, AAD)).toThrow('Token decryption failed');
  });

  it('rejects malformed values', () => {
    const c = new TokenCipher('k1', key());
    for (const bad of ['', 'nope', 'v2:k1:a|b|c', 'v1:k1:a|b', 'v1:bad id:a|b|c']) {
      expect(() => c.decrypt(bad, AAD)).toThrow(TokenCipherError);
    }
  });

  describe('key ids and rotation', () => {
    it('decrypts values written with an old key and flags them for re-encryption', () => {
      const oldKey = key();
      const before = new TokenCipher('k1', oldKey);
      const enc = before.encrypt('token', AAD);

      const after = new TokenCipher('k2', key(), new Map([['k1', oldKey]]));
      expect(after.decrypt(enc, AAD)).toBe('token');
      expect(after.needsReencrypt(enc)).toBe(true);

      const reenc = after.encrypt(after.decrypt(enc, AAD), AAD);
      expect(reenc.startsWith('v1:k2:')).toBe(true);
      expect(after.needsReencrypt(reenc)).toBe(false);
    });

    it('fails clearly for an unknown key id', () => {
      const enc = new TokenCipher('k1', key()).encrypt('t', AAD);
      expect(() => new TokenCipher('k9', key()).decrypt(enc, AAD)).toThrow(
        /Unknown encryption key id "k1"/,
      );
    });

    it('does not decrypt with a different key under the same id', () => {
      const enc = new TokenCipher('k1', key()).encrypt('t', AAD);
      expect(() => new TokenCipher('k1', key()).decrypt(enc, AAD)).toThrow(
        'Token decryption failed',
      );
    });

    it('validates key length and id', () => {
      expect(() => new TokenCipher('k1', randomBytes(16))).toThrow(/32 bytes/);
      expect(() => new TokenCipher('bad:id', key())).toThrow(/Invalid key id/);
    });

    it('parses old keys from config', () => {
      const k0 = key();
      const enc = new TokenCipher('k0', k0).encrypt('t', AAD);
      const c = TokenCipher.fromConfig(
        'k1',
        key().toString('base64'),
        ` k0:${k0.toString('base64')} `,
      );
      expect(c.decrypt(enc, AAD)).toBe('t');
      expect(() => TokenCipher.fromConfig('k1', key().toString('base64'), 'garbage')).toThrow(
        /keyId:base64/,
      );
    });
  });
});
