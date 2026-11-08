import request from 'supertest';
import { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { AppModule } from '../src/app.module';
import { setupApp } from '../src/setup-app';

export async function createTestApp(): Promise<INestApplication> {
  const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
  const app = moduleRef.createNestApplication();
  setupApp(app);
  await app.init();
  return app;
}

export function uniqueEmail(tag: string): string {
  return `${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.test`;
}

/** Extract the refresh cookie (name=value) from a Set-Cookie header. */
export function refreshCookie(setCookie: string[] | string | undefined): string | undefined {
  const list = Array.isArray(setCookie) ? setCookie : setCookie ? [setCookie] : [];
  const raw = list.find((c) => c.startsWith('mtj_rt='));
  return raw?.split(';')[0];
}

export async function registerUser(
  app: INestApplication,
  tag: string,
): Promise<{ id: string; email: string; accessToken: string; cookie: string }> {
  const email = uniqueEmail(tag);
  const res = await request(app.getHttpServer())
    .post('/auth/register')
    .send({ email, name: tag, password: 'correct horse battery staple' })
    .expect(201);
  return {
    id: res.body.user.id,
    email,
    accessToken: res.body.accessToken,
    cookie: refreshCookie(res.headers['set-cookie'])!,
  };
}
