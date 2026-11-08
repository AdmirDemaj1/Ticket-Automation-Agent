import { INestApplication } from '@nestjs/common';
import request from 'supertest';
import { App } from 'supertest/types';
import { ConnectionsService } from '../src/connections/connections.service';
import { TokenCipher, TokenCipherError } from '../src/crypto/token-cipher';
import { PrismaService } from '../src/prisma/prisma.service';
import { createTestApp, registerUser } from './utils';

const ACCESS = 'plaintext-jira-access-token';
const REFRESH = 'plaintext-jira-refresh-token';

describe('connections and per-user isolation (e2e)', () => {
  let app: INestApplication<App>;
  let prisma: PrismaService;
  let vault: ConnectionsService;
  let alice: Awaited<ReturnType<typeof registerUser>>;
  let bob: Awaited<ReturnType<typeof registerUser>>;
  const http = () => request(app.getHttpServer());
  const as = (u: { accessToken: string }) => ({ Authorization: `Bearer ${u.accessToken}` });

  beforeAll(async () => {
    app = await createTestApp();
    prisma = app.get(PrismaService);
    vault = app.get(ConnectionsService);
    alice = await registerUser(app, 'alice');
    bob = await registerUser(app, 'bob');
    await vault.saveTokens(
      alice.id,
      'jira',
      {
        accessToken: ACCESS,
        refreshToken: REFRESH,
        expiresAt: new Date(Date.now() + 3600_000),
        scopes: ['read:jira-work', 'write:jira-work'],
        externalAccountId: 'atl-123',
      },
      { ip: null },
    );
  });
  afterAll(async () => {
    await app.close();
  });

  it('stores tokens encrypted, never in plaintext', async () => {
    const row = await prisma.connection.findFirstOrThrow({
      where: { userId: alice.id, provider: 'jira' },
    });
    expect(row.accessTokenEnc).toMatch(/^v1:k1:/);
    expect(row.refreshTokenEnc).toMatch(/^v1:k1:/);
    expect(JSON.stringify(row)).not.toContain(ACCESS);
    expect(JSON.stringify(row)).not.toContain(REFRESH);
  });

  it('lists the owner connection without any token material', async () => {
    const res = await http().get('/connections').set(as(alice)).expect(200);
    const jira = res.body.find((c: { provider: string }) => c.provider === 'jira');
    expect(jira).toMatchObject({ state: 'connected', externalAccountId: 'atl-123' });
    expect(res.body).toHaveLength(5);
    const text = JSON.stringify(res.body);
    expect(text).not.toContain(ACCESS);
    expect(text).not.toMatch(/Enc|v1:k1/);
  });

  it("does not show another user's connections", async () => {
    const res = await http().get('/connections').set(as(bob)).expect(200);
    expect(res.body.every((c: { state: string }) => c.state === 'not_connected')).toBe(true);
  });

  it("cannot disconnect another user's connection", async () => {
    await http().delete('/connections/jira').set(as(bob)).expect(404);
    const row = await prisma.connection.findFirstOrThrow({
      where: { userId: alice.id, provider: 'jira' },
    });
    expect(row.status).toBe('active');
  });

  it("cannot decrypt another user's tokens through the vault", async () => {
    await expect(vault.getTokens(alice.id, 'jira')).resolves.toMatchObject({
      accessToken: ACCESS,
      refreshToken: REFRESH,
    });
    await expect(vault.getTokens(bob.id, 'jira')).rejects.toThrow(/No active jira connection/);
  });

  it("a ciphertext copied into another user's row does not decrypt", async () => {
    const row = await prisma.connection.findFirstOrThrow({
      where: { userId: alice.id, provider: 'jira' },
    });
    const cipher = app.get(TokenCipher);
    expect(() => cipher.decrypt(row.accessTokenEnc!, `${bob.id}:jira`)).toThrow(TokenCipherError);
  });

  it('rejects an unknown provider', async () => {
    await http().delete('/connections/dropbox').set(as(alice)).expect(400);
  });

  it('disconnect wipes tokens and is audited', async () => {
    await vault.saveTokens(alice.id, 'github', { accessToken: 'gh', scopes: [] }, { ip: null });
    await http().delete('/connections/github').set(as(alice)).expect(204);

    const row = await prisma.connection.findFirstOrThrow({
      where: { userId: alice.id, provider: 'github' },
    });
    expect(row).toMatchObject({ status: 'revoked', accessTokenEnc: null, refreshTokenEnc: null });
    expect(row.revokedAt).not.toBeNull();

    await http().delete('/connections/github').set(as(alice)).expect(404);
    const audit = await prisma.auditLog.findMany({
      where: { userId: alice.id, action: { startsWith: 'connection.' } },
      orderBy: { id: 'asc' },
    });
    expect(audit.map((a) => [a.action, a.target])).toEqual([
      ['connection.connected', 'jira'],
      ['connection.connected', 'github'],
      ['connection.disconnected', 'github'],
    ]);
  });

  it('needs_reauth is reported to the owner', async () => {
    await vault.saveTokens(alice.id, 'gitlab', { accessToken: 'gl', scopes: [] }, { ip: null });
    await vault.markNeedsReauth(alice.id, 'gitlab');
    const res = await http().get('/connections').set(as(alice)).expect(200);
    expect(res.body.find((c: { provider: string }) => c.provider === 'gitlab').state).toBe(
      'needs_reauth',
    );
    await expect(vault.getTokens(alice.id, 'gitlab')).rejects.toThrow();
  });
});
