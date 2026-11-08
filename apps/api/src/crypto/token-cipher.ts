import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';

const VERSION = 'v1';
const ALGO = 'aes-256-gcm';
const NONCE_BYTES = 12;
const TAG_BYTES = 16;
const KEY_ID_RE = /^[A-Za-z0-9_-]{1,32}$/;

export class TokenCipherError extends Error {}

/**
 * AES-256-GCM envelope for OAuth tokens.
 *
 * Stored format: `v1:<keyId>:<nonce>|<ciphertext>|<tag>` (each part standard base64).
 * - A fresh random 12-byte nonce per value.
 * - `aad` binds a ciphertext to its owner (e.g. `userId:provider`), so a value copied
 *   to another row fails to decrypt.
 * - Several keys can be loaded; new values always use the current key. Values written
 *   with an older key still decrypt, and `needsReencrypt` reports them for lazy rotation.
 */
export class TokenCipher {
  private readonly keys: ReadonlyMap<string, Buffer>;

  constructor(
    private readonly currentKeyId: string,
    currentKey: Buffer,
    oldKeys: ReadonlyMap<string, Buffer> = new Map(),
  ) {
    assertKey(currentKeyId, currentKey);
    const all = new Map<string, Buffer>();
    for (const [id, key] of oldKeys) {
      assertKey(id, key);
      all.set(id, key);
    }
    all.set(currentKeyId, currentKey);
    this.keys = all;
  }

  /**
   * @param currentKeyB64 base64 of 32 bytes
   * @param oldKeysSpec comma-separated `keyId:base64` pairs, may be empty
   */
  static fromConfig(currentKeyId: string, currentKeyB64: string, oldKeysSpec = ''): TokenCipher {
    const old = new Map<string, Buffer>();
    for (const entry of oldKeysSpec
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)) {
      const sep = entry.indexOf(':');
      if (sep <= 0) throw new TokenCipherError('TOKEN_ENC_OLD_KEYS entries must be "keyId:base64"');
      old.set(entry.slice(0, sep), Buffer.from(entry.slice(sep + 1), 'base64'));
    }
    return new TokenCipher(currentKeyId, Buffer.from(currentKeyB64, 'base64'), old);
  }

  encrypt(plaintext: string, aad: string): string {
    const key = this.keys.get(this.currentKeyId)!;
    const nonce = randomBytes(NONCE_BYTES);
    const cipher = createCipheriv(ALGO, key, nonce, { authTagLength: TAG_BYTES });
    cipher.setAAD(Buffer.from(aad, 'utf8'));
    const ct = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
    const tag = cipher.getAuthTag();
    return `${VERSION}:${this.currentKeyId}:${b64(nonce)}|${b64(ct)}|${b64(tag)}`;
  }

  decrypt(value: string, aad: string): string {
    const { keyId, nonce, ct, tag } = parse(value);
    const key = this.keys.get(keyId);
    if (!key) throw new TokenCipherError(`Unknown encryption key id "${keyId}"`);
    try {
      const decipher = createDecipheriv(ALGO, key, nonce, { authTagLength: TAG_BYTES });
      decipher.setAAD(Buffer.from(aad, 'utf8'));
      decipher.setAuthTag(tag);
      return Buffer.concat([decipher.update(ct), decipher.final()]).toString('utf8');
    } catch {
      // Do not leak crypto internals; the cause is tampering, wrong key, or wrong aad.
      throw new TokenCipherError('Token decryption failed');
    }
  }

  /** True when the value was written with a key other than the current one. */
  needsReencrypt(value: string): boolean {
    return parse(value).keyId !== this.currentKeyId;
  }
}

function assertKey(id: string, key: Buffer): void {
  if (!KEY_ID_RE.test(id)) throw new TokenCipherError(`Invalid key id "${id}"`);
  if (key.length !== 32) throw new TokenCipherError(`Key "${id}" must be 32 bytes`);
}

function b64(buf: Buffer): string {
  return buf.toString('base64');
}

function parse(value: string): { keyId: string; nonce: Buffer; ct: Buffer; tag: Buffer } {
  const first = value.indexOf(':');
  const second = value.indexOf(':', first + 1);
  if (first < 0 || second < 0) throw new TokenCipherError('Malformed encrypted value');
  const version = value.slice(0, first);
  const keyId = value.slice(first + 1, second);
  const parts = value.slice(second + 1).split('|');
  if (version !== VERSION || !KEY_ID_RE.test(keyId) || parts.length !== 3) {
    throw new TokenCipherError('Malformed encrypted value');
  }
  const [nonce, ct, tag] = parts.map((p) => Buffer.from(p, 'base64'));
  if (nonce.length !== NONCE_BYTES || tag.length !== TAG_BYTES) {
    throw new TokenCipherError('Malformed encrypted value');
  }
  return { keyId, nonce, ct, tag };
}
