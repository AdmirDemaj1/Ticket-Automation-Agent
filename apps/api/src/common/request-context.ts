import type { Request } from 'express';

export interface RequestContext {
  ip: string | null;
}

export function requestContext(req: Request): RequestContext {
  return { ip: req.ip ?? null };
}
