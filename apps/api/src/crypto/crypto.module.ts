import { Global, Module } from '@nestjs/common';
import { AppConfig } from '../config/app-config';
import { TokenCipher } from './token-cipher';

@Global()
@Module({
  providers: [
    {
      provide: TokenCipher,
      inject: [AppConfig],
      useFactory: (config: AppConfig) =>
        TokenCipher.fromConfig(
          config.get('TOKEN_ENC_KEY_ID'),
          config.get('TOKEN_ENC_KEY'),
          config.get('TOKEN_ENC_OLD_KEYS'),
        ),
    },
  ],
  exports: [TokenCipher],
})
export class CryptoModule {}
