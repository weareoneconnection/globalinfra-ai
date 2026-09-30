export async function api<T>(path: string): Promise<T> {
  const base = process.env.API_INTERNAL_URL || 'http://localhost:8000';
  const res = await fetch(`${base}${path}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}
