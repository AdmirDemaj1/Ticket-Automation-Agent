import { Global, Module } from '@nestjs/common';
import { ConfigModule as NestConfigModule, ConfigService } from '@nestjs/config';
import { AppConfig } from './app-config';
import { Env, validateEnv } from './env';

export { AppConfig };

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
