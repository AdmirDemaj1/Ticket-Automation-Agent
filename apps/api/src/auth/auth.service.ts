import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { ConflictException, Injectable, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { Prisma, User } from '@prisma/client';
import * as argon2 from 'argon2';
import { AuditService } from '../audit/audit.service';
import { AppConfig } from '../config/app-config';
import { RequestContext } from '../common/request-context';
import { PrismaService } from '../prisma/prisma.service';
import type { AccessTokenPayload, AuthSession } from './auth.types';
import { LoginDto, RegisterDto } from './auth.dto';

const ARGON2_OPTIONS: argon2.Options = { type: argon2.argon2id };

@Injectable()
export class AuthService {
  /** Used to keep login timing similar whether or not the email exists. */
  private dummyHash: Promise<string> | undefined;

  constructor(
    private readonly prisma: PrismaService,
    private readonly jwt: JwtService,
    private readonly config: AppConfig,
    private readonly audit: AuditService,
  ) {}

  async register(dto: RegisterDto, ctx: RequestContext): Promise<AuthSession> {
    const passwordHash = await argon2.hash(dto.password, ARGON2_OPTIONS);
    let user: User;
    try {
      user = await this.prisma.user.create({
        data: { email: dto.email, name: dto.name.trim(), passwordHash },
      });
    } catch (e) {
      if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
        throw new ConflictException('Email already registered');
      }
      throw e;
    }
    await this.audit.record({ userId: user.id, action: 'auth.register', ip: ctx.ip });
    return this.issueSession(user, randomUUID());
  }

  async login(dto: LoginDto, ctx: RequestContext): Promise<AuthSession> {
    const user = await this.prisma.user.findUnique({ where: { email: dto.email } });
    const hash = user?.passwordHash ?? (await this.getDummyHash());
    const ok = await argon2.verify(hash, dto.password).catch(() => false);
    if (!user || !user.passwordHash || !ok) {
      await this.audit.record({
        userId: user?.id ?? null,
        action: 'auth.login_failed',
        ip: ctx.ip,
      });
      throw new UnauthorizedException('Invalid email or password');
    }
    await this.audit.record({ userId: user.id, action: 'auth.login', ip: ctx.ip });
    return this.issueSession(user, randomUUID());
  }

  /** Rotates the refresh token. Reusing an already-rotated token revokes the whole family. */
  async refresh(rawToken: string | undefined, ctx: RequestContext): Promise<AuthSession> {
    if (!rawToken) throw new UnauthorizedException();
    const record = await this.prisma.refreshToken.findUnique({
      where: { tokenHash: hashToken(rawToken) },
      include: { user: true },
    });
    if (!record) throw new UnauthorizedException();

    if (record.revokedAt) {
      const graceMs = this.config.get('REFRESH_REUSE_GRACE_SECONDS') * 1000;
      if (Date.now() - record.revokedAt.getTime() < graceMs) {
        // Likely a concurrent refresh from another tab; the browser already holds the new cookie.
        throw new UnauthorizedException();
      }
      await this.prisma.refreshToken.updateMany({
        where: { familyId: record.familyId, revokedAt: null },
        data: { revokedAt: new Date() },
      });
      await this.audit.record({
        userId: record.userId,
        action: 'auth.refresh_reuse_detected',
        ip: ctx.ip,
      });
      throw new UnauthorizedException();
    }
    if (record.expiresAt <= new Date()) throw new UnauthorizedException();

    // Conditional update makes concurrent refreshes with the same token safe: only one wins.
    const { count } = await this.prisma.refreshToken.updateMany({
      where: { id: record.id, revokedAt: null },
      data: { revokedAt: new Date() },
    });
    if (count !== 1) throw new UnauthorizedException();

    return this.issueSession(record.user, record.familyId);
  }

  async logout(
    rawToken: string | undefined,
    userId: string | null,
    ctx: RequestContext,
  ): Promise<void> {
    if (rawToken) {
      await this.prisma.refreshToken.updateMany({
        where: { tokenHash: hashToken(rawToken), revokedAt: null },
        data: { revokedAt: new Date() },
      });
    }
    await this.audit.record({ userId, action: 'auth.logout', ip: ctx.ip });
  }

  private async issueSession(user: User, familyId: string): Promise<AuthSession> {
    const expiresIn = this.config.get('JWT_ACCESS_TTL_SECONDS');
    const payload: AccessTokenPayload = { sub: user.id, email: user.email };
    const accessToken = await this.jwt.signAsync(payload, { expiresIn, algorithm: 'HS256' });

    const refreshToken = randomBytes(32).toString('base64url');
    const refreshExpiresAt = new Date(
      Date.now() + this.config.get('REFRESH_TTL_DAYS') * 86_400_000,
    );
    await this.prisma.refreshToken.create({
      data: {
        userId: user.id,
        tokenHash: hashToken(refreshToken),
        familyId,
        expiresAt: refreshExpiresAt,
      },
    });

    return {
      accessToken,
      expiresIn,
      user: { id: user.id, email: user.email, name: user.name },
      refreshToken,
      refreshExpiresAt,
    };
  }

  private getDummyHash(): Promise<string> {
    this.dummyHash ??= argon2.hash(randomBytes(16).toString('hex'), ARGON2_OPTIONS);
    return this.dummyHash;
  }
}

function hashToken(raw: string): string {
  return createHash('sha256').update(raw).digest('hex');
}
