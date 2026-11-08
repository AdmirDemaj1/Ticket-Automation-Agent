export interface Order {
  id: string;
  customer: string;
  total: number;
  createdAt: string;
}

// Only the last 7 days are supported for now.
const DEFAULT_RANGE_DAYS = 7;

export async function fetchOrders(): Promise<Order[]> {
  const since = new Date(Date.now() - DEFAULT_RANGE_DAYS * 86_400_000).toISOString();
  const res = await fetch(`/api/orders?since=${encodeURIComponent(since)}`);
  if (!res.ok) throw new Error('Could not load orders');
  return (await res.json()) as Order[];
}
