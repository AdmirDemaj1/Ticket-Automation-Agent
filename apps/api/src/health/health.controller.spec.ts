import { ServiceUnavailableException } from '@nestjs/common';
import { HealthController } from './health.controller';
import { PrismaService } from '../prisma/prisma.service';

describe('HealthController', () => {
  it('returns ok when the database answers', async () => {
    const prisma = { $queryRaw: jest.fn().mockResolvedValue([1]) } as unknown as PrismaService;
    await expect(new HealthController(prisma).healthz()).resolves.toEqual({
      status: 'ok',
      db: 'ok',
    });
  });

  it('returns 503 when the database is down', async () => {
    const prisma = {
      $queryRaw: jest.fn().mockRejectedValue(new Error('down')),
    } as unknown as PrismaService;
    await expect(new HealthController(prisma).healthz()).rejects.toBeInstanceOf(
      ServiceUnavailableException,
    );
  });
});
