import { useState } from 'react';

export default function Sidebar({ t, onLogout }) {
  const [active] = useState('productManagement');

  const menuItems = [
    { key: 'dashboard', icon: '\u229E', label: t.dashboard },
    { key: 'productManagement', icon: '\u27F3', label: t.productManagement },
    { key: 'inventory', icon: '\u2630', label: t.inventory },
    { key: 'orders', icon: '\u2630', label: t.orders },
    { key: 'settings', icon: '\u2699', label: t.settings },
  ];

  return (
    <div className="sidebar">
      <div className="sidebar-logo">
        <span className="logo-text">ERP</span>
      </div>
      <nav className="sidebar-nav">
        {menuItems.map((item) => (
          <div
            key={item.key}
            className={`nav-item ${active === item.key ? 'active' : ''}`}
          >
            <span className="nav-icon">{item.icon}</span>
            <span className="nav-label">{item.label}</span>
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="nav-item" onClick={onLogout}>
          <span className="nav-icon">{'\u23FB'}</span>
          <span className="nav-label">{t.logout}</span>
        </div>
      </div>
    </div>
  );
}
