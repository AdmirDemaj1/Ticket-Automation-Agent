import { z } from 'zod';

export const healthResponse = z.object({ status: z.literal('ok'), db: z.literal('ok') });
export type HealthResponse = z.infer<typeof healthResponse>;
