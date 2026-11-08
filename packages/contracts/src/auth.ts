import { z } from 'zod';

export const email = z.string().trim().toLowerCase().email('Enter a valid email').max(254);

export const registerRequest = z.object({
  email,
  name: z.string().trim().min(1, 'Name is required').max(100),
  password: z.string().min(12, 'Use at least 12 characters').max(128, 'Use at most 128 characters'),
});
export type RegisterRequest = z.infer<typeof registerRequest>;

export const loginRequest = z.object({
  email,
  password: z.string().min(1, 'Password is required').max(128),
});
export type LoginRequest = z.infer<typeof loginRequest>;

export const publicUser = z.object({ id: z.string(), email: z.string(), name: z.string() });
export type PublicUser = z.infer<typeof publicUser>;

/** Body of /auth/register, /auth/login and /auth/refresh. The refresh token is only in an httpOnly cookie. */
export const sessionResponse = z.object({
  accessToken: z.string(),
  expiresIn: z.number(),
  user: publicUser,
});
export type SessionResponse = z.infer<typeof sessionResponse>;
