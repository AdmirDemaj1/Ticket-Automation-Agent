import { UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { AuditService } from '../audit/audit.service';
import { AppConfig } from '../config/app-config';
import { PrismaService } from '../prisma/prisma.service';
import { AuthService } from './auth.service';

function setup(revokedSecondsAgo: number, graceSeconds: number) {
  const record = {
    id: 'rt1',
    userId: 'u1',
    familyId: 'f1',
    revokedAt: new Date(Date.now() - revokedSecondsAgo * 1000),
    expiresAt: new Date(Date.now() + 86_400_000),
    user: { id: 'u1', email: 'a@b.c', name: 'A' },
  };
  const updateMany = jest.fn().mockResolvedValue({ count: 1 });
  const prisma = {
    refreshToken: { findUnique: jest.fn().mockResolvedValue(record), updateMany },
  } as unknown as PrismaService;
  const audit = { record: jest.fn() } as unknown as AuditService;
  const config = {
    get: (k: string) => (k === 'REFRESH_REUSE_GRACE_SECONDS' ? graceSeconds : undefined),
  } as unknown as AppConfig;
  const service = new AuthService(prisma, {} as JwtService, config, audit);
  return { service, updateMany, audit };
}

describe('AuthService.refresh reuse handling', () => {
  it('revokes the family when a rotated token is replayed after the grace window', async () => {
    const { service, updateMany, audit } = setup(30, 10);
    await expect(service.refresh('raw', { ip: null })).rejects.toBeInstanceOf(
      UnauthorizedException,
    );
    expect(updateMany).toHaveBeenCalledWith({
      where: { familyId: 'f1', revokedAt: null },
      data: { revokedAt: expect.any(Date) },
    });
    expect(audit.record).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'auth.refresh_reuse_detected' }),
    );
  });

  it('only rejects (no family revocation) within the grace window', async () => {
    const { service, updateMany, audit } = setup(2, 10);
    await expect(service.refresh('raw', { ip: null })).rejects.toBeInstanceOf(
      UnauthorizedException,
    );
    expect(updateMany).not.toHaveBeenCalled();
    expect(audit.record).not.toHaveBeenCalled();
  });
});
