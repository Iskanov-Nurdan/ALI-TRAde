/**
 * Скруглённый выпадающий список вместо системного.
 * Нативный <select> остаётся в форме (скрытым), поэтому FormData и весь
 * остальной код продолжают работать без изменений.
 */
import { icon } from '../icons.js';
import { el } from '../ui.js';

let openMenu = null;

function closeOpen() {
  if (openMenu) openMenu();
  openMenu = null;
}

document.addEventListener('click', (event) => {
  // Меню живёт в body, поэтому проверяем и его тоже
  if (openMenu && !event.target.closest('.select, .select__menu')) closeOpen();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeOpen();
});

export function enhanceSelect(select) {
  if (!select || select.multiple || select.dataset.enhanced) return;
  select.dataset.enhanced = '1';

  const wrap = el('div', { class: 'select' });
  select.parentNode.insertBefore(wrap, select);
  wrap.append(select);
  select.classList.add('select__native');
  select.setAttribute('tabindex', '-1');

  const label = el('span', { class: 'select__label' });
  const button = el('button', {
    class: 'select__button',
    type: 'button',
    'aria-haspopup': 'listbox',
    'aria-expanded': 'false',
  });
  button.append(label, icon('next', { size: 14, className: 'select__chevron' }));

  // Меню выносится в body: карточки страницы создают собственный стековый
  // контекст (isolation), и внутри них выпадающий список уходил под соседний блок.
  const menu = el('div', { class: 'select__menu', role: 'listbox', hidden: true });
  wrap.append(button);

  const syncLabel = () => {
    const option = select.options[select.selectedIndex];
    label.textContent = option ? option.textContent : '';
    label.classList.toggle('select__label--muted', !select.value);
    button.disabled = select.disabled || !select.options.length;
  };

  // Прокрутка страницы уводит меню от кнопки, поэтому его закрываем. Но у
  // самого меню есть своя полоса прокрутки, и её события тоже долетают сюда
  // в фазе перехвата — список закрывался на первом движении колеса внутри него.
  const onScroll = (event) => {
    const target = event.target;
    // Прокрутка внутри самого списка закрывать его не должна.
    if (target === menu) return;
    if (target?.nodeType === 1 && menu.contains(target)) return;
    close();
  };

  const close = () => {
    menu.hidden = true;
    menu.remove();
    button.setAttribute('aria-expanded', 'false');
    window.removeEventListener('scroll', onScroll, true);
    window.removeEventListener('resize', close);
  };

  /** Ставит меню под кнопку, а при нехватке места снизу — над ней. */
  const place = () => {
    const rect = button.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom;
    const height = Math.min(menu.scrollHeight, 260);
    const up = below < height + 12 && rect.top > below;

    menu.style.left = `${rect.left}px`;
    menu.style.width = `${rect.width}px`;
    menu.style.top = up ? '' : `${rect.bottom + 4}px`;
    menu.style.bottom = up ? `${window.innerHeight - rect.top + 4}px` : '';
  };

  const buildMenu = () => {
    menu.replaceChildren(
      ...Array.from(select.options).map((option) => {
        const item = el('button', {
          class: `select__option${option.selected ? ' select__option--active' : ''}`,
          type: 'button',
          role: 'option',
          'aria-selected': String(option.selected),
          text: option.textContent,
          disabled: option.disabled,
        });
        item.addEventListener('click', () => {
          select.value = option.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          syncLabel();
          close();
          button.focus();
        });
        return item;
      })
    );
  };

  const open = () => {
    closeOpen();
    buildMenu();
    document.body.append(menu);
    menu.hidden = false;
    place();
    button.setAttribute('aria-expanded', 'true');
    menu.querySelector('.select__option--active')?.scrollIntoView({ block: 'nearest' });
    // Страница прокрутилась — меню больше не под кнопкой, закрываем
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', close);
    openMenu = close;
  };

  button.addEventListener('click', () => (menu.hidden ? open() : close()));
  button.addEventListener('keydown', (event) => {
    if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
      event.preventDefault();
      if (menu.hidden) open();
      else menu.querySelector('.select__option')?.focus();
    }
  });
  menu.addEventListener('keydown', (event) => {
    const items = Array.from(menu.querySelectorAll('.select__option:not([disabled])'));
    const index = items.indexOf(document.activeElement);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      items[Math.min(index + 1, items.length - 1)]?.focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (index <= 0) button.focus();
      else items[index - 1].focus();
    }
  });

  // Опции подгружаются с сервера, а значения фильтров подставляются из адреса
  new MutationObserver(syncLabel).observe(select, { childList: true, subtree: true, attributes: true });
  select.addEventListener('change', syncLabel);

  // Присваивание select.value = '...' (восстановление фильтров из адреса,
  // открытие карточки сотрудника) не шлёт change и не меняет ни одного
  // атрибута, поэтому наблюдатель выше его не видит. Перехватываем сеттер,
  // иначе кнопка показывает одно значение, а применено другое.
  const descriptor = valueDescriptor(select);
  if (descriptor) {
    Object.defineProperty(select, 'value', {
      configurable: true,
      enumerable: descriptor.enumerable,
      get() {
        return descriptor.get.call(this);
      },
      set(next) {
        descriptor.set.call(this, next);
        syncLabel();
      },
    });
  }

  syncLabel();
}

/** Дескриптор value из цепочки прототипов элемента. */
function valueDescriptor(node) {
  let proto = Object.getPrototypeOf(node);
  while (proto) {
    const found = Object.getOwnPropertyDescriptor(proto, 'value');
    if (found && found.get && found.set) return found;
    proto = Object.getPrototypeOf(proto);
  }
  return null;
}

export function enhanceSelects(root = document) {
  root.querySelectorAll('select:not([multiple])').forEach(enhanceSelect);
}

/** Следит за формами, которые дорисовываются после загрузки данных. */
export function watchSelects(root = document.body) {
  if (!root || typeof MutationObserver === 'undefined') return;
  new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) return;
        if (node.tagName === 'SELECT') enhanceSelect(node);
        else node.querySelectorAll?.('select:not([multiple])').forEach(enhanceSelect);
      });
    });
  }).observe(root, { childList: true, subtree: true });
}
