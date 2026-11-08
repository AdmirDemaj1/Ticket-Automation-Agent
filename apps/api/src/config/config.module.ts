import { Global, Module } from '@nestjs/common';
import { ConfigModule as NestConfigModule, ConfigService } from '@nestjs/config';
import { Env, validateEnv } from './env';

export class AppConfig {
  constructor(private readonly config: ConfigService<Env, true>) {}

  get<K extends keyof Env>(key: K): Env[K] {
    return this.config.get(key, { infer: true });
  }
}

@Global()
@Module({
  imports: [
    NestConfigModule.forRoot({ isGlobal: true, ignoreEnvFile: true, validate: validateEnv }),
  ],
  providers: [
    {
      provide: AppConfig,
      inject: [ConfigService],
      useFactory: (c: ConfigService<Env, true>) => new AppConfig(c),
    },
  ],
  exports: [AppConfig],
})
export class ConfigModule {}
