import { createContext, useContext, useState, useCallback } from 'react';

const AuthContext = createContext(null);

const STORAGE_KEYS = {
  token: 'erp_token',
  server: 'erp_server',
  storeCode: 'erp_store_code',
  products: 'erp_products',
};

function loadAuth() {
  const token = localStorage.getItem(STORAGE_KEYS.token);
  const email = localStorage.getItem('erp_email');
  const serverUrl = localStorage.getItem(STORAGE_KEYS.server);
  if (token && email && serverUrl) {
    return { token, email, serverUrl };
  }
  return null;
}

export function loadStoreCode() {
  return localStorage.getItem(STORAGE_KEYS.storeCode) || '';
}

export function saveStoreCode(code) {
  if (code) {
    localStorage.setItem(STORAGE_KEYS.storeCode, code);
  } else {
    localStorage.removeItem(STORAGE_KEYS.storeCode);
  }
}

export function loadProducts() {
  try {
    const data = localStorage.getItem(STORAGE_KEYS.products);
    return data ? JSON.parse(data) : null;
  } catch {
    return null;
  }
}

export function saveProducts(products) {
  localStorage.setItem(STORAGE_KEYS.products, JSON.stringify(products));
}

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(loadAuth);

  const login = useCallback((token, email, serverUrl) => {
    localStorage.setItem(STORAGE_KEYS.token, token);
    localStorage.setItem('erp_email', email);
    localStorage.setItem(STORAGE_KEYS.server, serverUrl);
    setAuth({ token, email, serverUrl });
  }, []);

  const logout = useCallback(() => {
    Object.values(STORAGE_KEYS).forEach((key) => localStorage.removeItem(key));
    localStorage.removeItem('erp_email');
    localStorage.removeItem('erp_search');
    localStorage.removeItem('erp_category');
    setAuth(null);
  }, []);

  return (
    <AuthContext.Provider value={{ auth, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
