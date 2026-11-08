import { Body, Controller, ForbiddenException, HttpCode, Post, Req, Res } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { Throttle } from '@nestjs/throttler';
import type { Request, Response } from 'express';
import { requestContext } from '../common/request-context';
import { AppConfig } from '../config/app-config';
import { LoginDto, RegisterDto } from './auth.dto';
import { AuthService } from './auth.service';
import type { AuthSession, PublicUser } from './auth.types';
import { Public } from './public.decorator';

export const REFRESH_COOKIE = 'mtj_rt';

interface SessionResponse {
  accessToken: string;
  expiresIn: number;
  user: PublicUser;
}

const authLimit = () => ({
  default: { limit: Number(process.env.AUTH_RATE_LIMIT_PER_MIN ?? 10), ttl: 60_000 },
});

@ApiTags('auth')
@Public()
@Controller('auth')
export class AuthController {
  constructor(
    private readonly auth: AuthService,
    private readonly config: AppConfig,
  ) {}

  @Post('register')
  @Throttle(authLimit())
  async register(
    @Body() dto: RegisterDto,
    @Req() req: Request,
    @Res({ passthrough: true }) res: Response,
  ): Promise<SessionResponse> {
    return this.respond(res, await this.auth.register(dto, requestContext(req)));
  }

  @Post('login')
  @HttpCode(200)
  @Throttle(authLimit())
  async login(
    @Body() dto: LoginDto,
    @Req() req: Request,
    @Res({ passthrough: true }) res: Response,
  ): Promise<SessionResponse> {
    return this.respond(res, await this.auth.login(dto, requestContext(req)));
  }

  @Post('refresh')
  @HttpCode(200)
  async refresh(
    @Req() req: Request,
    @Res({ passthrough: true }) res: Response,
  ): Promise<SessionResponse> {
    this.assertAllowedOrigin(req);
    try {
      return this.respond(res, await this.auth.refresh(readCookie(req), requestContext(req)));
    } catch (e) {
      this.clearCookie(res);
      throw e;
    }
  }

  @Post('logout')
  @HttpCode(204)
  async logout(@Req() req: Request, @Res({ passthrough: true }) res: Response): Promise<void> {
    this.assertAllowedOrigin(req);
    await this.auth.logout(readCookie(req), null, requestContext(req));
    this.clearCookie(res);
  }

  private respond(res: Response, session: AuthSession): SessionResponse {
    res.cookie(REFRESH_COOKIE, session.refreshToken, {
      ...this.cookieOptions(),
      expires: session.refreshExpiresAt,
    });
    return { accessToken: session.accessToken, expiresIn: session.expiresIn, user: session.user };
  }

  private clearCookie(res: Response): void {
    res.clearCookie(REFRESH_COOKIE, this.cookieOptions());
  }

  private cookieOptions() {
    return {
      httpOnly: true,
      secure: this.config.get('NODE_ENV') === 'production',
      sameSite: 'strict' as const,
      path: '/',
    };
  }

  /** CSRF defense in depth for cookie-authenticated endpoints (cookie is also SameSite=Strict). */
  private assertAllowedOrigin(req: Request): void {
    const origin = req.headers.origin;
    if (origin && origin !== this.config.get('WEB_ORIGIN')) {
      throw new ForbiddenException('Origin not allowed');
    }
  }
}

function readCookie(req: Request): string | undefined {
  const cookies = req.cookies as Record<string, string> | undefined;
  return cookies?.[REFRESH_COOKIE];
}
