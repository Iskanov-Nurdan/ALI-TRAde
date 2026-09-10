/** Переключение светлой и тёмной темы. Выбор запоминается в браузере. */
import { icon } from './icons.js';

const THEME_KEY = 'delivery.theme';

export function currentTheme() {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

export function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch (error) {
    /* приватный режим — тема просто не запомнится */
  }
}

/**
 * @param {string} className - классы кнопки
 * @returns {HTMLButtonElement}
 */
export function createThemeToggle(className = 'topbar__menu topbar__theme') {
  const button = document.createElement('button');
  button.className = className;
  button.type = 'button';
  button.setAttribute('aria-label', 'Переключить тему');

  const paint = () => {
    const dark = currentTheme() === 'dark';
    button.replaceChildren(icon(dark ? 'sun' : 'moon', { size: 17 }));
    button.title = dark ? 'Светлая тема' : 'Тёмная тема';
    button.setAttribute('aria-pressed', String(dark));
  };

  button.addEventListener('click', () => {
    setTheme(currentTheme() === 'dark' ? 'light' : 'dark');
    paint();
  });

  paint();
  return button;
}
