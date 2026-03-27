import { proxyFetch } from './proxyFetch';

export async function verifyStore(serverUrl, token, storeCode) {
  const url = `${serverUrl.replace(/\/+$/, '')}/api/config/store/${encodeURIComponent(storeCode)}`;

  const response = await proxyFetch(url, {
    method: 'GET',
    headers: {
      'Access-Token': token,
    },
  });

  if (response.ok) {
    return response.json();
  }

  if (response.status === 404) {
    throw new Error('STORE_NOT_FOUND');
  }
  if (response.status === 401 || response.status === 403) {
    throw new Error('STORE_NO_PERMISSION');
  }
  throw new Error('STORE_FETCH_FAILED');
}
