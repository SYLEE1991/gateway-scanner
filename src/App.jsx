import { useState } from 'react';
import { AuthProvider, useAuth, loadProducts, saveProducts } from './context/AuthContext';
import LoginPage from './components/LoginPage';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import ProductTable from './components/ProductTable';
import translations from './i18n/translations';
import initialProducts from './data/products';
import './App.css';

function AppContent() {
  const [lang, setLang] = useState('en');
  const [products, setProducts] = useState(() => loadProducts() || initialProducts);
  const { auth, login, logout } = useAuth();
  const t = translations[lang];

  if (!auth) {
    return (
      <LoginPage
        t={t}
        lang={lang}
        setLang={setLang}
        onLogin={login}
      />
    );
  }

  return (
    <div className="app">
      <Sidebar t={t} onLogout={logout} />
      <div className="main">
        <Header t={t} lang={lang} setLang={setLang} email={auth.email} />
        <div className="content">
          <ProductTable products={products} setProducts={setProducts} saveProducts={saveProducts} t={t} />
        </div>
      </div>
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}

export default App;
