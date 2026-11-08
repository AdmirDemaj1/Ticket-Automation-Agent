import { INestApplication, ValidationPipe } from '@nestjs/common';
import helmet from 'helmet';
import { AppConfig } from './config/config.module';

/** Shared HTTP setup for main.ts and e2e tests. */
export function setupApp(app: INestApplication): void {
  const config = app.get(AppConfig);
  app.use(helmet());
  app.enableCors({ origin: [config.get('WEB_ORIGIN')], credentials: true });
  app.useGlobalPipes(
    new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }),
  );
  app.enableShutdownHooks();
}
