import { z } from 'zod';

export const provider = z.enum(['jira', 'github', 'gitlab', 'msgraph', 'spinach']);
export type Provider = z.infer<typeof provider>;

export const connectionState = z.enum(['connected', 'needs_reauth', 'not_connected']);
export type ConnectionState = z.infer<typeof connectionState>;

export const connectionView = z.object({
  provider,
  state: connectionState,
  externalAccountId: z.string().nullable(),
  scopes: z.array(z.string()),
  expiresAt: z.string().nullable(),
  connectedAt: z.string().nullable(),
});
export type ConnectionView = z.infer<typeof connectionView>;
