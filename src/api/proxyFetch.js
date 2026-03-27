export async function proxyFetch(targetUrl, options = {}) {
  const headers = { ...options.headers, 'x-target-url': targetUrl };

  const response = await fetch('/api/proxy', {
    ...options,
    headers,
  });

  return response;
}
