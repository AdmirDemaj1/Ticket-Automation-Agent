import type { LoginRequest, PublicUser, RegisterRequest } from '@mtj/contracts';
import { createContext } from 'react';

export type AuthState =
  | { status: 'loading'; user: null }
  | { status: 'anonymous'; user: null }
  | { status: 'authenticated'; user: PublicUser };

export interface AuthContextValue {
  state: AuthState;
  login(body: LoginRequest): Promise<void>;
  register(body: RegisterRequest): Promise<void>;
  logout(): Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
