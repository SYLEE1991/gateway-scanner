import { proxyFetch } from './proxyFetch';

export async function loginApi(serverUrl, email, password) {
  const url = `${serverUrl.replace(/\/+$/, '')}/api/auth/login`;

  const response = await proxyFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    throw new Error(`Login failed: ${response.status}`);
  }

  return response.json();
}
