import { Controller, Get, HttpCode, ServiceUnavailableException } from '@nestjs/common';
import { SkipThrottle } from '@nestjs/throttler';
import { PrismaService } from '../prisma/prisma.service';

@SkipThrottle()
@Controller()
export class HealthController {
  constructor(private readonly prisma: PrismaService) {}

  @Get('healthz')
  @HttpCode(200)
  async healthz(): Promise<{ status: 'ok'; db: 'ok' }> {
    try {
      await this.prisma.$queryRaw`SELECT 1`;
    } catch {
      throw new ServiceUnavailableException({ status: 'error', db: 'unreachable' });
    }
    return { status: 'ok', db: 'ok' };
  }
}
