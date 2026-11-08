export interface AuthUser {
  id: string;
  email: string;
}

export interface AccessTokenPayload {
  sub: string;
  email: string;
}

export interface PublicUser {
  id: string;
  email: string;
  name: string;
}

export interface AuthSession {
  accessToken: string;
  expiresIn: number;
  user: PublicUser;
  /** Raw refresh token; only ever placed in the httpOnly cookie, never in a response body. */
  refreshToken: string;
  refreshExpiresAt: Date;
}
