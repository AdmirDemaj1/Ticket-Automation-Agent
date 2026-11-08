import { ConfigService } from '@nestjs/config';
import type { Env } from './env';

/** Typed accessor for validated env. Kept separate from ConfigModule so importing it has no side effects. */
export class AppConfig {
  constructor(private readonly config: ConfigService<Env, true>) {}

  get<K extends keyof Env>(key: K): Env[K] {
    return this.config.get(key, { infer: true });
  }
}
