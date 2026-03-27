export default function Header({ t, lang, setLang, email }) {
  return (
    <div className="header">
      <h1>{t.appTitle}</h1>
      <div className="header-right">
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
        <div className="user-info">
          <span className="user-icon">&#128100;</span>
          <span>{email}</span>
        </div>
      </div>
    </div>
  );
}
