import { Injectable, NotFoundException } from '@nestjs/common';
import { Connection, ConnectionStatus, Prisma, Provider } from '@prisma/client';
import { AuditService } from '../audit/audit.service';
import { RequestContext } from '../common/request-context';
import { TokenCipher } from '../crypto/token-cipher';
import { PrismaService } from '../prisma/prisma.service';

export const PROVIDERS = Object.values(Provider);

export interface ProviderTokens {
  accessToken: string;
  refreshToken?: string | null;
  expiresAt?: Date | null;
  scopes: string[];
  externalAccountId?: string | null;
  meta?: Prisma.InputJsonObject;
}

export interface DecryptedTokens {
  accessToken: string;
  refreshToken: string | null;
  expiresAt: Date | null;
}

export type ConnectionState = 'connected' | 'needs_reauth' | 'not_connected';

/** Safe view of a connection. Never includes token material. */
export interface ConnectionView {
  provider: Provider;
  state: ConnectionState;
  externalAccountId: string | null;
  scopes: string[];
  expiresAt: Date | null;
  connectedAt: Date | null;
}

/**
 * Token vault. Every method is scoped by `userId`; there is no way to read a connection
 * without it. Tokens are encrypted with AES-256-GCM, bound to `userId:provider` via AAD.
 */
@Injectable()
export class ConnectionsService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly cipher: TokenCipher,
    private readonly audit: AuditService,
  ) {}

  async list(userId: string): Promise<ConnectionView[]> {
    const rows = await this.prisma.connection.findMany({ where: { userId } });
    const byProvider = new Map(rows.map((r) => [r.provider, r]));
    return PROVIDERS.map((provider) => toView(provider, byProvider.get(provider)));
  }

  /** Store (or replace) tokens after a successful OAuth callback. */
  async saveTokens(
    userId: string,
    provider: Provider,
    tokens: ProviderTokens,
    ctx: RequestContext,
  ): Promise<ConnectionView> {
    const aad = aadFor(userId, provider);
    const data = {
      status: ConnectionStatus.active,
      accessTokenEnc: this.cipher.encrypt(tokens.accessToken, aad),
      refreshTokenEnc: tokens.refreshToken ? this.cipher.encrypt(tokens.refreshToken, aad) : null,
      expiresAt: tokens.expiresAt ?? null,
      scopes: tokens.scopes,
      externalAccountId: tokens.externalAccountId ?? null,
      meta: tokens.meta ?? {},
      revokedAt: null,
    };
    const row = await this.prisma.connection.upsert({
      where: { userId_provider: { userId, provider } },
      create: { userId, provider, ...data },
      update: data,
    });
    await this.audit.record({
      userId,
      action: 'connection.connected',
      target: provider,
      ip: ctx.ip,
      meta: { scopes: tokens.scopes },
    });
    return toView(provider, row);
  }

  /**
   * Decrypt tokens for run dispatch. Values written with a retired key are re-encrypted
   * with the current key on the way out (lazy key rotation).
   */
  async getTokens(userId: string, provider: Provider): Promise<DecryptedTokens> {
    const row = await this.prisma.connection.findUnique({
      where: { userId_provider: { userId, provider } },
    });
    if (!row || row.status !== ConnectionStatus.active || !row.accessTokenEnc) {
      throw new NotFoundException(`No active ${provider} connection`);
    }
    const aad = aadFor(userId, provider);
    const accessToken = this.cipher.decrypt(row.accessTokenEnc, aad);
    const refreshToken = row.refreshTokenEnc ? this.cipher.decrypt(row.refreshTokenEnc, aad) : null;

    const stale =
      this.cipher.needsReencrypt(row.accessTokenEnc) ||
      (row.refreshTokenEnc !== null && this.cipher.needsReencrypt(row.refreshTokenEnc));
    if (stale) {
      await this.prisma.connection.update({
        where: { id: row.id },
        data: {
          accessTokenEnc: this.cipher.encrypt(accessToken, aad),
          refreshTokenEnc: refreshToken ? this.cipher.encrypt(refreshToken, aad) : null,
        },
      });
    }
    return { accessToken, refreshToken, expiresAt: row.expiresAt };
  }

  async markNeedsReauth(userId: string, provider: Provider): Promise<void> {
    const { count } = await this.prisma.connection.updateMany({
      where: { userId, provider, status: ConnectionStatus.active },
      data: { status: ConnectionStatus.needs_reauth },
    });
    if (count > 0) {
      await this.audit.record({ userId, action: 'connection.needs_reauth', target: provider });
    }
  }

  /** Wipe stored tokens and mark the connection revoked. Provider-side revocation comes with each OAuth integration. */
  async disconnect(userId: string, provider: Provider, ctx: RequestContext): Promise<void> {
    const { count } = await this.prisma.connection.updateMany({
      where: { userId, provider, status: { not: ConnectionStatus.revoked } },
      data: {
        status: ConnectionStatus.revoked,
        accessTokenEnc: null,
        refreshTokenEnc: null,
        expiresAt: null,
        revokedAt: new Date(),
      },
    });
    if (count === 0) throw new NotFoundException(`No ${provider} connection`);
    await this.audit.record({
      userId,
      action: 'connection.disconnected',
      target: provider,
      ip: ctx.ip,
    });
  }
}

function aadFor(userId: string, provider: Provider): string {
  return `${userId}:${provider}`;
}

function toView(provider: Provider, row: Connection | undefined): ConnectionView {
  const state: ConnectionState =
    !row || row.status === ConnectionStatus.revoked
      ? 'not_connected'
      : row.status === ConnectionStatus.needs_reauth
        ? 'needs_reauth'
        : 'connected';
  const live = state !== 'not_connected' && row;
  return {
    provider,
    state,
    externalAccountId: live ? row.externalAccountId : null,
    scopes: live ? row.scopes : [],
    expiresAt: live ? row.expiresAt : null,
    connectedAt: live ? row.updatedAt : null,
  };
}
