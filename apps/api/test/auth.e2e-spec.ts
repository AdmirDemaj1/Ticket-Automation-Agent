import { INestApplication } from '@nestjs/common';
import request from 'supertest';
import { App } from 'supertest/types';
import { PrismaService } from '../src/prisma/prisma.service';
import { createTestApp, refreshCookie, registerUser, uniqueEmail } from './utils';

const PASSWORD = 'correct horse battery staple';

describe('auth (e2e)', () => {
  let app: INestApplication<App>;
  let prisma: PrismaService;
  const http = () => request(app.getHttpServer());

  beforeAll(async () => {
    app = await createTestApp();
    prisma = app.get(PrismaService);
  });
  afterAll(async () => {
    await app.close();
  });

  describe('register', () => {
    it('creates a user, returns an access token and sets a hardened refresh cookie', async () => {
      const email = uniqueEmail('reg');
      const res = await http()
        .post('/auth/register')
        .send({ email: `  ${email.toUpperCase()} `, name: 'Ada', password: PASSWORD })
        .expect(201);

      expect(res.body).toEqual({
        accessToken: expect.any(String),
        expiresIn: 900,
        user: { id: expect.any(String), email, name: 'Ada' },
      });
      expect(JSON.stringify(res.body)).not.toMatch(/refresh|password/i);

      const cookie = (res.headers['set-cookie'] as unknown as string[]).find((c) =>
        c.startsWith('mtj_rt='),
      )!;
      expect(cookie).toMatch(/HttpOnly/);
      expect(cookie).toMatch(/SameSite=Strict/);

      const user = await prisma.user.findUniqueOrThrow({ where: { email } });
      expect(user.passwordHash).toMatch(/^\$argon2id\$/);
    });

    it('rejects a duplicate email', async () => {
      const email = uniqueEmail('dup');
      await http()
        .post('/auth/register')
        .send({ email, name: 'A', password: PASSWORD })
        .expect(201);
      await http()
        .post('/auth/register')
        .send({ email, name: 'B', password: PASSWORD })
        .expect(409);
    });

    it.each([
      [{ email: 'not-an-email', name: 'A', password: PASSWORD }],
      [{ email: uniqueEmail('short'), name: 'A', password: 'short' }],
      [{ email: uniqueEmail('extra'), name: 'A', password: PASSWORD, isAdmin: true }],
      [{ email: uniqueEmail('noname'), password: PASSWORD }],
    ])('validates the body: %j', async (body) => {
      await http().post('/auth/register').send(body).expect(400);
    });
  });

  describe('login', () => {
    it('logs in with the right password and records an audit entry', async () => {
      const u = await registerUser(app, 'login');
      const res = await http()
        .post('/auth/login')
        .send({ email: u.email, password: PASSWORD })
        .expect(200);
      expect(res.body.user.id).toBe(u.id);
      expect(refreshCookie(res.headers['set-cookie'])).toBeDefined();
      const actions = await prisma.auditLog.findMany({ where: { userId: u.id } });
      expect(actions.map((a) => a.action)).toEqual(
        expect.arrayContaining(['auth.register', 'auth.login']),
      );
    });

    it('gives the same generic error for a wrong password and an unknown email', async () => {
      const u = await registerUser(app, 'wrongpw');
      const wrong = await http()
        .post('/auth/login')
        .send({ email: u.email, password: 'definitely wrong pw' })
        .expect(401);
      const unknown = await http()
        .post('/auth/login')
        .send({ email: uniqueEmail('nobody'), password: 'definitely wrong pw' })
        .expect(401);
      expect(wrong.body.message).toBe('Invalid email or password');
      expect(unknown.body.message).toBe(wrong.body.message);
      const failed = await prisma.auditLog.count({
        where: { userId: u.id, action: 'auth.login_failed' },
      });
      expect(failed).toBe(1);
    });
  });

  describe('access token', () => {
    it('protects routes by default', async () => {
      await http().get('/users/me').expect(401);
      await http().get('/users/me').set('Authorization', 'Bearer garbage').expect(401);
      await http().get('/connections').expect(401);
    });

    it('returns the current user', async () => {
      const u = await registerUser(app, 'me');
      const res = await http()
        .get('/users/me')
        .set('Authorization', `Bearer ${u.accessToken}`)
        .expect(200);
      expect(res.body).toMatchObject({ id: u.id, email: u.email });
      expect(res.body.passwordHash).toBeUndefined();
    });

    it('rejects a token signed with another secret', async () => {
      const [h, , s] = (await registerUser(app, 'forge')).accessToken.split('.');
      const forgedPayload = Buffer.from(JSON.stringify({ sub: 'x', email: 'x' })).toString(
        'base64url',
      );
      await http()
        .get('/users/me')
        .set('Authorization', `Bearer ${h}.${forgedPayload}.${s}`)
        .expect(401);
    });
  });

  describe('refresh', () => {
    it('rotates the refresh token', async () => {
      const u = await registerUser(app, 'rotate');
      const res = await http().post('/auth/refresh').set('Cookie', u.cookie).expect(200);
      const next = refreshCookie(res.headers['set-cookie']);
      expect(next).toBeDefined();
      expect(next).not.toBe(u.cookie);
      expect(res.body.user.id).toBe(u.id);
    });

    it('detects reuse of a rotated token and revokes the whole family', async () => {
      const u = await registerUser(app, 'reuse');
      const res = await http().post('/auth/refresh').set('Cookie', u.cookie).expect(200);
      const next = refreshCookie(res.headers['set-cookie'])!;

      await http().post('/auth/refresh').set('Cookie', u.cookie).expect(401); // replay
      await http().post('/auth/refresh').set('Cookie', next).expect(401); // family revoked

      const audit = await prisma.auditLog.count({
        where: { userId: u.id, action: 'auth.refresh_reuse_detected' },
      });
      expect(audit).toBe(2); // both attempts used a revoked token
    });

    it('rejects a missing or unknown cookie', async () => {
      await http().post('/auth/refresh').expect(401);
      await http().post('/auth/refresh').set('Cookie', 'mtj_rt=unknown').expect(401);
    });

    it('rejects a foreign Origin', async () => {
      const u = await registerUser(app, 'origin');
      await http()
        .post('/auth/refresh')
        .set('Cookie', u.cookie)
        .set('Origin', 'https://evil.example')
        .expect(403);
      await http()
        .post('/auth/refresh')
        .set('Cookie', u.cookie)
        .set('Origin', 'http://localhost:5173')
        .expect(200);
    });
  });

  it('logout revokes the refresh token', async () => {
    const u = await registerUser(app, 'logout');
    await http().post('/auth/logout').set('Cookie', u.cookie).expect(204);
    await http().post('/auth/refresh').set('Cookie', u.cookie).expect(401);
  });
});
