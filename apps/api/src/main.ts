import { NestFactory } from '@nestjs/core';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { Logger } from 'nestjs-pino';
import { AppModule } from './app.module';
import { AppConfig } from './config/config.module';
import { setupApp } from './setup-app';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, { bufferLogs: true });
  app.useLogger(app.get(Logger));
  setupApp(app);

  const config = app.get(AppConfig);
  if (config.get('NODE_ENV') !== 'production') {
    const doc = SwaggerModule.createDocument(
      app,
      new DocumentBuilder().setTitle('Meeting-to-Jira API').addBearerAuth().build(),
    );
    SwaggerModule.setup('docs', app, doc);
  }

  await app.listen(config.get('PORT'), '0.0.0.0');
}

void bootstrap();
