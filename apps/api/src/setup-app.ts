import { INestApplication, ValidationPipe } from '@nestjs/common';
import { NestExpressApplication } from '@nestjs/platform-express';
import cookieParser from 'cookie-parser';
import helmet from 'helmet';
import { AppConfig } from './config/app-config';

/** Shared HTTP setup for main.ts and e2e tests. */
export function setupApp(app: INestApplication): void {
  const config = app.get(AppConfig);
  (app as NestExpressApplication).set('trust proxy', config.get('TRUST_PROXY'));
  app.use(helmet());
  app.use(cookieParser());
  app.enableCors({ origin: [config.get('WEB_ORIGIN')], credentials: true });
  app.useGlobalPipes(
    new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }),
  );
  app.enableShutdownHooks();
}
