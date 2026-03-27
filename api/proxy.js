export default async function handler(req, res) {
  const targetUrl = req.headers['x-target-url'];

  if (!targetUrl) {
    return res.status(400).json({ error: 'Missing x-target-url header' });
  }

  const headers = { ...req.headers };
  delete headers['x-target-url'];
  delete headers['host'];
  delete headers['connection'];
  delete headers['accept-encoding'];

  try {
    const response = await fetch(targetUrl, {
      method: req.method,
      headers,
      body: req.method !== 'GET' && req.method !== 'HEAD' ? JSON.stringify(req.body) : undefined,
    });

    const data = await response.text();

    res.status(response.status);

    for (const [key, value] of response.headers.entries()) {
      const lowerKey = key.toLowerCase();
      if (lowerKey === 'transfer-encoding' || lowerKey === 'content-encoding') continue;
      res.setHeader(key, value);
    }

    res.send(data);
  } catch (error) {
    res.status(502).json({ error: 'Proxy request failed', message: error.message });
  }
}
