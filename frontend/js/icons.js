/** Набор линейных SVG-иконок. Наследуют цвет текста, размер задаётся параметром. */

const PATHS = {
  dashboard:
    '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>',
  truck:
    '<path d="M3 16V6a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v10"/><path d="M15 9h3.5L21 12v4h-2"/><circle cx="7" cy="17.5" r="2"/><circle cx="17" cy="17.5" r="2"/><path d="M9 17.5h6"/><path d="M3 17.5h2"/>',
  receipt:
    '<path d="M5 3v18l2.5-1.5L10 21l2.5-1.5L15 21l2.5-1.5L20 21V3l-2.5 1.5L15 3l-2.5 1.5L10 3 7.5 4.5Z"/><path d="M9 9h7"/><path d="M9 13h7"/>',
  chart: '<path d="M4 20h16"/><path d="M7 20v-6"/><path d="M12 20V6"/><path d="M17 20v-9"/>',
  pin: '<path d="M20 10.5c0 6-8 12-8 12s-8-6-8-12a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10.5" r="2.75"/>',
  users:
    '<path d="M16 20v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20"/><circle cx="9.5" cy="7.5" r="3.5"/><path d="M21 20v-1.5a4 4 0 0 0-3-3.87"/><path d="M16 4.13a4 4 0 0 1 0 7.75"/>',
  sliders:
    '<path d="M4 7h9"/><path d="M17 7h3"/><path d="M4 17h4"/><path d="M12 17h8"/><circle cx="15" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  history:
    '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  logout:
    '<path d="M10 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4"/><path d="M16 16l4-4-4-4"/><path d="M20 12H10"/>',
  close: '<path d="M18 6 6 18"/><path d="M6 6l12 12"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  menu: '<path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/>',
  download: '<path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3"/><path d="M8 11l4 4 4-4"/><path d="M12 15V4"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  next: '<path d="M9 6l6 6-6 6"/>',
  check: '<path d="M5 12.5 10 17 19 7"/>',
  alert: '<path d="M12 4.5 2.8 20h18.4L12 4.5Z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
  filter: '<path d="M3 5h18l-7 8v5l-4 2v-7L3 5Z"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="M14.5 5.5 18.5 9.5"/>',
  ban: '<circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/>',
  coins: '<ellipse cx="9" cy="6.5" rx="5.5" ry="2.5"/><path d="M3.5 6.5v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5v-4"/><path d="M3.5 10.5v4c0 1.4 2.5 2.5 5.5 2.5"/><ellipse cx="16" cy="15.5" rx="4.5" ry="2.2"/><path d="M11.5 15.5v3c0 1.2 2 2.2 4.5 2.2s4.5-1 4.5-2.2v-3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2"/><path d="M12 19v2"/><path d="M5.6 5.6l1.4 1.4"/><path d="M17 17l1.4 1.4"/><path d="M3 12h2"/><path d="M19 12h2"/><path d="M5.6 18.4L7 17"/><path d="M17 7l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
  trash: '<path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M6 7l1 13h10l1-13"/>',
};

/**
 * @param {string} name - имя из набора
 * @param {{size?: number, className?: string}} options
 * @returns {SVGElement}
 */
export function icon(name, { size = 18, className = '' } = {}) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.6');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  if (className) svg.setAttribute('class', className);
  svg.innerHTML = PATHS[name] || '';
  return svg;
}

/** Подставляет иконки во все элементы с data-icon="имя". */
export function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach((node) => {
    if (node.dataset.iconReady) return;
    const size = Number(node.dataset.iconSize) || 18;
    node.prepend(icon(node.dataset.icon, { size }));
    node.dataset.iconReady = '1';
  });
}
