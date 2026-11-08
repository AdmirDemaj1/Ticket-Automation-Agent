import { Controller, Delete, Get, HttpCode, Param, ParseEnumPipe, Req } from '@nestjs/common';
import { ApiBearerAuth, ApiTags } from '@nestjs/swagger';
import { Provider } from '@prisma/client';
import type { Request } from 'express';
import { CurrentUser } from '../auth/current-user.decorator';
import type { AuthUser } from '../auth/auth.types';
import { requestContext } from '../common/request-context';
import { ConnectionsService, ConnectionView } from './connections.service';

@ApiTags('connections')
@ApiBearerAuth()
@Controller('connections')
export class ConnectionsController {
  constructor(private readonly connections: ConnectionsService) {}

  @Get()
  list(@CurrentUser() user: AuthUser): Promise<ConnectionView[]> {
    return this.connections.list(user.id);
  }

  @Delete(':provider')
  @HttpCode(204)
  async disconnect(
    @CurrentUser() user: AuthUser,
    @Param('provider', new ParseEnumPipe(Provider)) provider: Provider,
    @Req() req: Request,
  ): Promise<void> {
    await this.connections.disconnect(user.id, provider, requestContext(req));
  }
}
