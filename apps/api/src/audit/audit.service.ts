import { Injectable } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service';

export type AuditAction =
  | 'auth.register'
  | 'auth.login'
  | 'auth.login_failed'
  | 'auth.logout'
  | 'auth.refresh_reuse_detected'
  | 'connection.connected'
  | 'connection.disconnected'
  | 'connection.needs_reauth'
  | 'run.created'
  | 'run.approved'
  | 'run.tickets_created';

export interface AuditEntry {
  userId: string | null;
  action: AuditAction;
  target?: string;
  ip?: string | null;
  /** Must never contain secrets, tokens, transcript or code content. */
  meta?: Prisma.InputJsonObject;
}

@Injectable()
export class AuditService {
  constructor(private readonly prisma: PrismaService) {}

  async record(entry: AuditEntry): Promise<void> {
    await this.prisma.auditLog.create({
      data: {
        userId: entry.userId,
        action: entry.action,
        target: entry.target ?? null,
        ip: entry.ip ?? null,
        meta: entry.meta ?? {},
      },
    });
  }
}
