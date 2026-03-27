import { useState } from 'react';
import { loginApi } from '../api/authApi';

export default function LoginPage({ t, lang, setLang, onLogin }) {
  const [serverUrl, setServerUrl] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!serverUrl || !email || !password) {
      setError(t.loginFieldsRequired);
      return;
    }

    let url = serverUrl.trim();
    if (!/^https?:\/\//i.test(url)) {
      url = 'https://' + url;
    }

    setLoading(true);
    try {
      const data = await loginApi(url, email, password);
      const token = data['Access-Token'] || data['access-token'] || data.accessToken || data.token;
      if (!token) {
        throw new Error(t.loginTokenNotFound);
      }
      onLogin(token, email, url);
    } catch (err) {
      setError(err.message || t.loginFailed);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <h1 className="login-logo">PartronESL</h1>
          <p className="login-subtitle">{t.appTitle}</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label>{t.serverUrl}</label>
            <input
              type="text"
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
              placeholder={t.serverUrlPlaceholder}
            />
          </div>

          <div className="form-group">
            <label>{t.email}</label>
            <input
              type="text"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t.emailPlaceholder}
            />
          </div>

          <div className="form-group">
            <label>{t.password}</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t.passwordPlaceholder}
            />
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="btn-login" disabled={loading}>
            {loading ? t.loggingIn : t.loginButton}
          </button>
        </form>

        <div className="login-footer">
          <select
            className="lang-select"
            value={lang}
            onChange={(e) => setLang(e.target.value)}
          >
            <option value="en">{t.english}</option>
            <option value="ko">{t.korean}</option>
            <option value="es">{t.spanish}</option>
            <option value="vi">{t.vietnamese}</option>
            <option value="ja">{t.japanese}</option>
          </select>
        </div>
      </div>
    </div>
  );
}
