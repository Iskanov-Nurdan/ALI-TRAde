/**
 * Появление блоков при прокрутке.
 *
 * Анимируется только то, что появилось после загрузки данных: карточки, таблицы
 * и строки, которые дорисовывают страницы. Статическая разметка уже отрисована
 * браузером и видна пользователю — гасить её через opacity после ответа сервера
 * значит показать вспышку на ровном месте.
 *
 * Только IntersectionObserver: слушатель scroll вызывает постоянные перерисовки.
 * Анимируются исключительно transform/opacity/filter — layout не пересчитывается.
 */

const REVEAL_TARGETS = '.stat, .card, .table-wrapper, .detail-grid > *';
const STEP = 20;
const MAX_DELAY = 80;

let observer = null;
let revealFallback = null;

function ensureObserver() {
  if (observer || typeof IntersectionObserver === 'undefined') return observer;
  observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.dataset.reveal = 'in';
        observer.unobserve(entry.target);
      });
    },
    { rootMargin: '0px 0px -8% 0px', threshold: 0.05 }
  );
  return observer;
}

function showEverything() {
  document.querySelectorAll('[data-reveal="out"]').forEach((node) => {
    node.dataset.reveal = 'in';
  });
}

/**
 * Помечает элементы к появлению и ставит им сдвиг по времени.
 * @param {ParentNode} root - корень, внутри которого искать цели
 */
export function revealIn(root = document) {
  const targets = [];
  if (root.matches && root.matches(REVEAL_TARGETS) && !root.dataset.reveal) {
    targets.push(root);
  }
  if (root.querySelectorAll) {
    root.querySelectorAll(REVEAL_TARGETS).forEach((node) => {
      if (!node.dataset.reveal) targets.push(node);
    });
  }
  if (!targets.length) return;

  const io = ensureObserver();
  targets.forEach((node, index) => {
    node.dataset.reveal = 'out';
    node.style.setProperty('--reveal-delay', `${Math.min(index * STEP, MAX_DELAY)}ms`);
    if (io) io.observe(node);
    else node.dataset.reveal = 'in';
  });

  // Страховка: если наблюдатель почему-то не сработал (печать, скриншот всей
  // страницы, свёрнутая вкладка), содержимое всё равно должно быть видимым.
  clearTimeout(revealFallback);
  revealFallback = setTimeout(showEverything, 1200);
}

if (typeof window !== 'undefined' && window.matchMedia) {
  window.matchMedia('print').addEventListener?.('change', (event) => {
    if (event.matches) showEverything();
  });
}

/**
 * Наблюдает за появлением новых блоков (страницы дорисовывают карточки после
 * загрузки данных) и подключает к появлению только их.
 * @param {Element} root - контейнер, за которым следим
 */
export function watchReveal(root = document.querySelector('.app-main')) {
  if (!root || typeof MutationObserver === 'undefined') return;
  const mo = new MutationObserver((records) => {
    records.forEach((record) => {
      record.addedNodes.forEach((node) => {
        // Текстовые узлы и уже помеченные элементы пропускаем.
        if (node.nodeType === 1) revealIn(node);
      });
    });
  });
  mo.observe(root, { childList: true, subtree: true });
}
