/**
 * Логотип и название компании.
 * Файл кладётся в frontend/assets (путь задаётся в js/config.js).
 * Если файла нет, остаётся стандартный значок — интерфейс не ломается.
 */

export function applyBranding() {
  const config = window.APP_CONFIG || {};

  const name = document.querySelector('#app-name');
  if (name && config.appName) {
    name.textContent = config.appName;
    // Заголовок вкладки собирается как «Раздел — Название»: так смена названия
    // в config.js подхватывается сама, без правки каждой страницы.
    const [section] = document.title.split('—');
    document.title = section.trim() ? `${section.trim()} — ${config.appName}` : config.appName;
  }

  const holder = document.querySelector('#app-logo');
  if (!holder || !config.logo) return;

  const image = new Image();
  image.src = config.logo;
  image.alt = config.appName || 'Логотип';
  image.className = 'brand-logo';

  image.addEventListener('load', () => {
    // Логотип есть — убираем запасной значок
    holder.replaceChildren(image);
    holder.classList.add('brand-mark--image');
    holder.removeAttribute('data-icon');
  });
  // Ошибку загрузки игнорируем: значок по умолчанию уже на месте
}
