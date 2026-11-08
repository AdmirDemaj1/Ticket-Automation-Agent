import { randomUUID } from 'node:crypto';
import { Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { ThrottlerGuard, ThrottlerModule } from '@nestjs/throttler';
import { LoggerModule } from 'nestjs-pino';
import { AuditModule } from './audit/audit.module';
import { AuthModule } from './auth/auth.module';
import { AppConfig } from './config/app-config';
import { ConfigModule } from './config/config.module';
import { ConnectionsModule } from './connections/connections.module';
import { CryptoModule } from './crypto/crypto.module';
import { HealthModule } from './health/health.module';
import { PrismaModule } from './prisma/prisma.module';
import { UsersModule } from './users/users.module';

@Module({
  imports: [
    ConfigModule,
    LoggerModule.forRootAsync({
      inject: [AppConfig],
      useFactory: (config: AppConfig) => ({
        pinoHttp: {
          level: config.get('LOG_LEVEL'),
          genReqId: (req, res) => {
            const incoming = req.headers['x-request-id'];
            const id =
              typeof incoming === 'string' && incoming.length <= 128 ? incoming : randomUUID();
            res.setHeader('x-request-id', id);
            return id;
          },
          // Never log credentials or bodies.
          redact: {
            paths: [
              'req.headers.authorization',
              'req.headers.cookie',
              'req.headers["x-service-token"]',
              'res.headers["set-cookie"]',
            ],
            censor: '[redacted]',
          },
          autoLogging: { ignore: (req) => req.url === '/healthz' },
          transport:
            config.get('NODE_ENV') === 'development' ? { target: 'pino-pretty' } : undefined,
        },
      }),
    }),
    ThrottlerModule.forRoot([{ ttl: 60_000, limit: 120 }]),
    PrismaModule,
    CryptoModule,
    AuditModule,
    HealthModule,
    AuthModule,
    UsersModule,
    ConnectionsModule,
  ],
  providers: [{ provide: APP_GUARD, useClass: ThrottlerGuard }],
})
export class AppModule {}
