/* Конфигурация фронтенда. Меняется без пересборки: адрес API. */
window.APP_CONFIG = {
  // Логотип: положите файл сюда и при необходимости поменяйте имя.
  // Если файла нет, вместо него показывается стандартный значок.
  logo: 'assets/logo.png',
  // Название рядом с логотипом и в заголовке вкладки
  appName: 'ALI trade',
  // Пустой префикс = тот же домен, что и страница (nginx проксирует /api на бэкенд).
  apiBase: '/api',
};

/* Тема применяется до отрисовки, иначе при загрузке мигает светлый фон. */
(function applyStoredTheme() {
  var stored = null;
  try {
    stored = localStorage.getItem('delivery.theme');
  } catch (error) {
    stored = null;
  }
  var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var theme = stored || (prefersDark ? 'dark' : 'light');
  document.documentElement.dataset.theme = theme;
})();

/* Роль тоже проставляется заранее: иначе у обычного сотрудника на миг
   мелькает административный раздел меню. */
(function applyStoredRole() {
  var role = 'EMPLOYEE';
  try {
    var user = JSON.parse(localStorage.getItem('delivery.user') || 'null');
    if (user && user.role) role = user.role;
  } catch (error) {
    role = 'EMPLOYEE';
  }
  document.documentElement.dataset.role = role;
})();
