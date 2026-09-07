window.API_BASE_URL = window.API_BASE_URL || 'https://legal-metrology-1.onrender.com';

const navigation = [
  { href: 'dashboard.html', icon: '▦', label: 'Dashboard' },
  { href: 'inspection.html', icon: '+', label: 'New Inspection' },
  { href: 'result.html', icon: '✓', label: 'Inspection Results' },
  { href: 'violation.html', icon: '!', label: 'Violations & Evidence' },
  { href: 'comparison.html', icon: '⇄', label: 'Market Comparison' },
  { href: 'risk.html', icon: '◒', label: 'Risk Dashboard' },
  { href: 'reports.html', icon: '▤', label: 'Reports & History' },
  { href: 'rules.html', icon: '§', label: 'Rule Repository' }
];

function renderShell() {
  const page = document.body.dataset.page || '';
  const title = document.body.dataset.title || 'Inspector workspace';
  const content = document.querySelector('[data-content]');
  const navMarkup = navigation.map(item => `
    <a href="${item.href}" class="${page === item.href.replace('.html', '') ? 'active' : ''}">
      <span class="nav-icon" aria-hidden="true">${item.icon}</span><span>${item.label}</span>
    </a>`).join('');

  document.body.insertAdjacentHTML('afterbegin', `
    <div class="app-shell">
      <aside class="sidebar" id="sidebar" aria-label="Primary navigation">
        <div class="brand">
          <div class="brand-mark" aria-hidden="true">LM</div>
          <div class="brand-title">Legal Metrology<span class="brand-subtitle">Compliance Inspection System</span></div>
        </div>
        <div class="nav-label">Inspector workspace</div>
        <nav class="nav">${navMarkup}</nav>
        <div class="sidebar-footer">Government of India<br><span>Department of Consumer Affairs</span></div>
      </aside>
      <div class="main-area">
        <header class="topbar">
          <div class="profile">
            <button class="menu-toggle" id="menuToggle" aria-label="Open navigation">☰</button>
            <div><div class="topbar-title">${title}</div><div class="topbar-context">National Legal Metrology Portal</div></div>
          </div>
          <div class="profile"><div><div class="profile-name">Inspector workspace</div><div class="profile-role">Real inspection data</div></div><div class="avatar" aria-label="Inspector workspace">LM</div></div>
        </header>
        <main class="page-content">${content.innerHTML}</main>
      </div>
    </div>`);
  content.remove();

  const sidebar = document.getElementById('sidebar');
  document.getElementById('menuToggle')?.addEventListener('click', () => sidebar.classList.toggle('open'));
  document.querySelectorAll('.sidebar a').forEach(link => link.addEventListener('click', () => sidebar.classList.remove('open')));
  document.querySelectorAll('[data-action="print"]').forEach(button => button.addEventListener('click', () => window.print()));
  document.querySelectorAll('[data-action="upload"]').forEach(button => button.addEventListener('click', () => document.querySelector('input[type="file"]')?.click()));
}

document.addEventListener('DOMContentLoaded', renderShell);
