import { randomBytes } from 'node:crypto';
import { Connection } from '@prisma/client';
import { AuditService } from '../audit/audit.service';
import { TokenCipher } from '../crypto/token-cipher';
import { PrismaService } from '../prisma/prisma.service';
import { ConnectionsService } from './connections.service';

describe('ConnectionsService key rotation', () => {
  it('re-encrypts tokens written with a retired key on read', async () => {
    const k1 = randomBytes(32);
    const oldCipher = new TokenCipher('k1', k1);
    const newCipher = new TokenCipher('k2', randomBytes(32), new Map([['k1', k1]]));
    const aad = 'u1:jira';

    const row = {
      id: 'c1',
      userId: 'u1',
      provider: 'jira',
      status: 'active',
      accessTokenEnc: oldCipher.encrypt('access', aad),
      refreshTokenEnc: oldCipher.encrypt('refresh', aad),
      expiresAt: null,
    } as unknown as Connection;

    const update = jest.fn().mockResolvedValue(row);
    const prisma = {
      connection: { findUnique: jest.fn().mockResolvedValue(row), update },
    } as unknown as PrismaService;
    const service = new ConnectionsService(prisma, newCipher, {} as AuditService);

    await expect(service.getTokens('u1', 'jira')).resolves.toEqual({
      accessToken: 'access',
      refreshToken: 'refresh',
      expiresAt: null,
    });

    expect(update).toHaveBeenCalledTimes(1);
    const data = update.mock.calls[0][0].data as {
      accessTokenEnc: string;
      refreshTokenEnc: string;
    };
    expect(data.accessTokenEnc.startsWith('v1:k2:')).toBe(true);
    expect(newCipher.decrypt(data.refreshTokenEnc, aad)).toBe('refresh');
  });

  it('does not rewrite tokens already on the current key', async () => {
    const cipher = new TokenCipher('k1', randomBytes(32));
    const row = {
      id: 'c1',
      status: 'active',
      accessTokenEnc: cipher.encrypt('a', 'u1:jira'),
      refreshTokenEnc: null,
      expiresAt: null,
    } as unknown as Connection;
    const update = jest.fn();
    const prisma = {
      connection: { findUnique: jest.fn().mockResolvedValue(row), update },
    } as unknown as PrismaService;
    await new ConnectionsService(prisma, cipher, {} as AuditService).getTokens('u1', 'jira');
    expect(update).not.toHaveBeenCalled();
  });
});
