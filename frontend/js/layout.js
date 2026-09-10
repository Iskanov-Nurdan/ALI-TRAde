/** Каркас страницы: проверка доступа, боковая панель, верхняя строка с поиском. */
import { api, tokenStore, redirectToLogin } from './api.js';
import { hydrateIcons, icon } from './icons.js';
import { enhanceSelects, watchSelects } from './components/select.js';
import { applyBranding } from './branding.js';
import { createThemeToggle } from './theme.js';
import { watchReveal } from './motion.js';
import { el, qs, toast } from './ui.js';

export function currentUser() {
  return tokenStore.user;
}

export function isAdmin() {
  const user = currentUser();
  return Boolean(user && user.role === 'ADMIN');
}

/** Подключается на каждой защищённой странице. */
export async function initLayout({ active, adminOnly = false } = {}) {
  if (!tokenStore.access) {
    redirectToLogin();
    return null;
  }

  // Каркас рисуется сразу из сохранённых данных пользователя: иначе при переходе
  // между страницами панель на мгновение исчезает, пока идёт запрос к серверу.
  let user = currentUser();
  const drawShell = (person) => {
    renderSidebar(person, active);
    renderTopbar();
    setupFilters();
    hydrateIcons(document);
    applyBranding();
    enhanceSelects(document);
    watchSelects();
  };

  let shellReady = false;
  if (user) {
    if (adminOnly && user.role !== 'ADMIN') {
      renderDenied();
      return null;
    }
    drawShell(user);
    shellReady = true;
  }

  try {
    const fresh = await api.me();
    const changed =
      !user || fresh.role !== user.role || fresh.full_name !== user.full_name;
    user = fresh;
    tokenStore.save({ user });

    if (adminOnly && user.role !== 'ADMIN') {
      renderDenied();
      return null;
    }
    // Без кэша каркас ещё не собран: без этого на телефоне не было бы даже
    // кнопки меню — сайдбар уведён за край экрана и открыть его нечем.
    if (!shellReady) {
      drawShell(user);
      shellReady = true;
    } else if (changed) {
      renderSidebar(user, active);
    }
  } catch (error) {
    if (error.status === 401) {
      // Сессия мертва: токены уже очищены, переход на вход запущен. Экран не
      // оставляем пустым — иначе непонятно, что произошло.
      renderDenied('Сессия завершена. Войдите в систему заново.', 'Вход');
      toast('Сессия завершена. Войдите заново.', 'error');
      return null;
    }
    if (adminOnly) {
      // Роль из кэша подделывается в один клик, а сервер её не подтвердил.
      // Административный раздел в таком состоянии открывать нельзя.
      renderDenied('Не удалось проверить права доступа. Повторите позже.');
      return null;
    }
    if (!user) {
      renderDenied('Не удалось загрузить данные пользователя. Обновите страницу.');
      return null;
    }
    toast('Не удалось обновить данные пользователя.', 'error');
  }

  if (!user) return null;

  watchReveal();
  return user;
}

function renderDenied(
  message = 'Раздел доступен только главному администратору.',
  title = 'Доступ запрещён'
) {
  // Роль из кэша не подтверждена сервером — административный раздел меню
  // (css: :root:not([data-role="ADMIN"]) .sidebar__admin) должен быть скрыт.
  document.documentElement.dataset.role = 'EMPLOYEE';
  const main = qs('.app-main') || document.body;
  main.replaceChildren(
    el('div', { class: 'card' }, [
      el('h1', { text: title === 'Вход' ? 'Сессия завершена' : 'Доступ запрещён' }),
      el('p', { class: 'cell-muted', text: message }),
      title === 'Вход'
        ? el('a', { class: 'btn btn--primary', href: 'index.html', text: 'Войти заново' })
        : el('a', { class: 'btn btn--primary', href: 'dashboard.html', text: 'Вернуться на панель' }),
    ])
  );
  const sidebar = qs('#app-sidebar');
  const topbar = qs('#app-header');
  if (sidebar) sidebar.hidden = true;
  if (topbar) topbar.hidden = true;
}

function renderSidebar(user, active) {
  const sidebar = qs('#app-sidebar');
  if (!sidebar) return;

  // Разметка панели статична — она уже отрисована браузером. Здесь только
  // подставляем данные пользователя: так панель не мигает при переходах.
  document.documentElement.dataset.role = user.role;

  const name = qs('#sidebar-user-name');
  const role = qs('#sidebar-user-role');
  if (name) name.textContent = user.full_name;
  if (role) role.textContent = user.role_display || '';

  if (active) {
    sidebar.querySelectorAll('.sidebar__link').forEach((link) => {
      const isCurrent = link.getAttribute('href') === active;
      if (isCurrent) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  const logout = qs('#sidebar-logout');
  if (logout && !logout.dataset.bound) {
    logout.dataset.bound = '1';
    logout.addEventListener('click', () => {
      tokenStore.clear();
      window.location.href = 'index.html';
    });
  }
}

function renderTopbar() {
  const topbar = qs('#app-header');
  const sidebar = qs('#app-sidebar');
  if (!topbar) return;

  const menuButton = el('button', {
    class: 'topbar__menu',
    type: 'button',
    'aria-label': 'Открыть меню',
    'aria-controls': 'app-sidebar',
    'aria-expanded': 'false',
  });
  // Линии перетекают в «X» — без подмены иконки, чистый transform.
  menuButton.append(el('span', { class: 'burger' }, [el('span'), el('span')]));

  const overlay = el('div', { class: 'sidebar-overlay', 'aria-hidden': 'true' });
  document.body.append(overlay);

  const wideScreen = window.matchMedia('(min-width: 1024px)');

  // Состояние меню — только классы: смена display гасила бы затемнение рывком.
  // Отдельно помечаем панель недоступной, пока она уведена за край экрана:
  // иначе Tab уходит на невидимые ссылки, а скринридер их зачитывает.
  const setMenu = (open) => {
    sidebar.classList.toggle('sidebar--open', open);
    overlay.classList.toggle('sidebar-overlay--visible', open);
    overlay.setAttribute('aria-hidden', String(!open));
    document.body.classList.toggle('has-menu-open', open);
    menuButton.setAttribute('aria-expanded', String(open));

    const offscreen = !open && !wideScreen.matches;
    if (offscreen) sidebar.setAttribute('inert', '');
    else sidebar.removeAttribute('inert');
    sidebar.setAttribute('aria-hidden', String(offscreen));

    if (open) {
      // Фокус переходит внутрь панели — с клавиатуры меню предсказуемо.
      const target =
        sidebar.querySelector('.sidebar__link[aria-current="page"]') ||
        sidebar.querySelector('.sidebar__link');
      if (target) target.focus();
    } else if (!wideScreen.matches) {
      menuButton.focus();
    }
  };
  menuButton.addEventListener('click', () => setMenu(!sidebar.classList.contains('sidebar--open')));
  overlay.addEventListener('click', () => setMenu(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setMenu(false);
  });

  // На широком экране панель видна всегда — состояние мобильного меню сбрасываем,
  // иначе после поворота телефона остаётся висеть затемнение.
  const syncMenu = () => setMenu(false);
  if (wideScreen.addEventListener) wideScreen.addEventListener('change', syncMenu);
  else wideScreen.addListener(syncMenu);

  // Стартовое состояние: на телефоне панель закрыта и исключена из обхода.
  setMenu(false);

  const input = el('input', {
    id: 'global-search',
    name: 'q',
    type: 'search',
    placeholder: 'Поиск по номеру машины',
    autocomplete: 'off',
  });
  const searchField = el('div', { class: 'search-field' }, [icon('search', { size: 15 }), input]);

  const form = el('form', { class: 'topbar__search', role: 'search' }, [
    el('label', { class: 'visually-hidden', for: 'global-search', text: 'Поиск машины по номеру' }),
    searchField,
    el('button', { class: 'btn', type: 'submit', text: 'Найти' }),
  ]);

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const value = String(new FormData(form).get('q') || '').trim();
    if (value.length < 2) {
      toast('Введите не менее двух символов номера.', 'error');
      return;
    }
    window.location.href = `deliveries.html?vehicle_number=${encodeURIComponent(value)}`;
  });

  topbar.replaceChildren(menuButton, form, createThemeToggle());
}

/**
 * На телефоне блок фильтров сворачивается: иначе он занимает весь первый экран.
 * На широких экранах он всегда раскрыт.
 */
function setupFilters() {
  const card = qs('.card.filters');
  if (!card) return;

  const title = card.querySelector('.card__title');
  const form = card.querySelector('form');
  if (!title || !form) return;
  form.classList.add('filters__body');

  const toggle = el('button', { class: 'btn btn--sm filters__toggle', type: 'button' });
  const mobile = window.matchMedia('(max-width: 767px)');

  const paint = () => {
    const collapsed = card.classList.contains('filters--collapsed');
    toggle.replaceChildren(
      icon('filter', { size: 14 }),
      el('span', { text: collapsed ? 'Показать' : 'Скрыть' })
    );
    toggle.setAttribute('aria-expanded', String(!collapsed));
  };

  toggle.addEventListener('click', () => {
    card.classList.toggle('filters--collapsed');
    paint();
  });

  const sync = () => {
    card.classList.toggle('filters--collapsed', mobile.matches);
    paint();
  };

  title.append(toggle);
  sync();
  mobile.addEventListener('change', sync);
}

/** Параметры адресной строки как обычный объект. */
export function queryParams() {
  return Object.fromEntries(new URLSearchParams(window.location.search).entries());
}

export function setQueryParams(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value);
  });
  const query = search.toString();
  window.history.replaceState({}, '', query ? `${window.location.pathname}?${query}` : window.location.pathname);
}
