import { proxyFetch } from './proxyFetch';

function getLayoutId(price, salePrice) {
  if (salePrice !== 0 && salePrice < price) {
    return 'demo_sale';
  }
  return 'demo_normal';
}

function buildProductEntry({ productCode, productName, price, salePrice }) {
  const priceNum = parseFloat(price) || 0;
  const salePriceNum = parseFloat(salePrice) || 0;
  return {
    layoutId: getLayoutId(priceNum, salePriceNum),
    nfc: 'www.partronesl.com',
    prCode: productCode,
    prInfo: [productCode, productName, String(priceNum), String(salePriceNum)],
    secondCode: '',
  };
}

async function postProducts(serverUrl, token, storeCode, productEntries) {
  const url = `${serverUrl.replace(/\/+$/, '')}/api/product`;

  const body = {
    product: productEntries,
    storeCode,
    taskId: -1,
  };

  const response = await proxyFetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Access-Token': token,
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

export async function updateProduct(serverUrl, token, storeCode, product) {
  return postProducts(serverUrl, token, storeCode, [buildProductEntry(product)]);
}

export async function updateProductsBulk(serverUrl, token, storeCode, products) {
  const entries = products.map(buildProductEntry);
  return postProducts(serverUrl, token, storeCode, entries);
}
