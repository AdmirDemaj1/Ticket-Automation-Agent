import { useEffect, useState } from 'react';
import { fetchOrders, type Order } from '../api/orders';

export function Dashboard({ user }: { user: string }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchOrders().then(setOrders, (e: Error) => setError(e.message));
  }, []);

  return (
    <main>
      <h1>Welcome, {user}</h1>
      <p className="muted">Orders from the last 7 days</p>
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>Order</th>
            <th>Customer</th>
            <th>Total</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>{o.id}</td>
              <td>{o.customer}</td>
              <td>{o.total.toFixed(2)}</td>
              <td>{new Date(o.createdAt).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
