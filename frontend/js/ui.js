/** Небольшая библиотека UI-помощников: элементы, состояния, форматирование. */
import { hydrateIcons } from './icons.js';

export const qs = (selector, root = document) => root.querySelector(selector);
export const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/** Создание элемента: el('div', { class: 'card' }, [child, 'текст']). */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value === null || value === undefined || value === false) return;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'dataset') {
      Object.entries(value).forEach(([dataKey, dataValue]) => {
        node.dataset[dataKey] = dataValue;
      });
    } else {
      node.setAttribute(key, value === true ? '' : value);
    }
  });
  const list = Array.isArray(children) ? children : [children];
  list.filter((child) => child !== null && child !== undefined && child !== false).forEach((child) => {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/* ----------------------------- Форматирование ---------------------------- */

const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

const timeFormat = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' });
const dateFormat = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });

export const formatDateTime = (value) => (value ? dateTimeFormat.format(new Date(value)) : '—');
export const formatTime = (value) => (value ? timeFormat.format(new Date(value)) : '—');
export const formatDate = (value) => (value ? dateFormat.format(new Date(value)) : '—');

/** 87 -> «1 ч 27 мин». */
export function formatMinutes(minutes) {
  const value = Number(minutes) || 0;
  if (value <= 0) return '—';
  const hours = Math.floor(value / 60);
  const rest = value % 60;
  if (hours && rest) return `${hours} ч ${rest} мин`;
  if (hours) return `${hours} ч`;
  return `${rest} мин`;
}

export function formatMoney(amount, currency) {
  const value = Number(amount) || 0;
  return `${value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

/** {USD: '130.00', KGS: '500'} -> «130.00 USD + 500.00 KGS». */
export function formatTotals(totals) {
  const entries = Object.entries(totals || {});
  if (!entries.length) return '—';
  return entries.map(([currency, amount]) => formatMoney(amount, currency)).join(' + ');
}

/** «≈ 12 300.00 KGS» — сумма, сведённая к базовой валюте по курсу. */
export function formatConverted(converted) {
  if (!converted || Number(converted.amount) <= 0) return '';
  const missing = converted.missing_rates || [];
  const suffix = missing.length ? ` (без курса: ${missing.join(', ')})` : '';
  return `≈ ${formatMoney(converted.amount, converted.currency)}${suffix}`;
}

/** Значение для input[type=datetime-local] в местном времени. */
export function toLocalInputValue(date = new Date()) {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function fromLocalInputValue(value) {
  return value ? new Date(value).toISOString() : null;
}

/* ------------------------------- Состояния ------------------------------- */

export function renderLoading(container, message = 'Загрузка данных…') {
  clear(container).append(
    el('div', { class: 'state' }, [el('div', { class: 'spinner', role: 'status', 'aria-live': 'polite' }), el('p', { text: message })])
  );
}

export function renderEmpty(container, title = 'Данных нет', hint = '') {
  clear(container).append(
    el('div', { class: 'state' }, [el('p', { class: 'state__title', text: title }), hint ? el('p', { text: hint }) : null])
  );
}

export function renderError(container, message, onRetry) {
  clear(container).append(
    el('div', { class: 'state' }, [
      el('p', { class: 'state__title', text: 'Ошибка' }),
      el('p', { text: message }),
      onRetry ? el('button', { class: 'btn btn--primary', type: 'button', onClick: onRetry, text: 'Повторить' }) : null,
    ])
  );
}

/* --------------------------------- Тосты -------------------------------- */

function toastStack() {
  let stack = qs('.toast-stack');
  if (!stack) {
    stack = el('div', { class: 'toast-stack', role: 'status', 'aria-live': 'polite' });
    document.body.append(stack);
  }
  return stack;
}

export function toast(message, type = 'info') {
  const node = el('div', { class: `toast toast--${type}`, text: message });
  toastStack().append(node);
  setTimeout(() => node.remove(), 4500);
}

export function showApiError(error) {
  const details = error.fieldErrors ? error.fieldErrors : [];
  const message = details.length
    ? `${error.message} ${details.map((item) => item.message).join(' ')}`
    : error.message;
  toast(message, 'error');
}

/* -------------------------------- Модалка -------------------------------- */

export function openModal(modal) {
  modal.hidden = false;
  document.body.style.overflow = 'hidden';
  const focusable = modal.querySelector('input, select, textarea, button');
  if (focusable) focusable.focus();
}

export function closeModal(modal) {
  modal.hidden = true;
  document.body.style.overflow = '';
}

export function setupModal(modal) {
  hydrateIcons(modal);
  modal.addEventListener('click', (event) => {
    // closest — потому что клик может попасть по иконке внутри кнопки закрытия
    if (event.target === modal || event.target.closest('[data-close]')) closeModal(modal);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !modal.hidden) closeModal(modal);
  });
  return modal;
}

/* ------------------------- Адаптивность таблиц ---------------------------- */

/**
 * Проставляет ячейкам подпись колонки из шапки: на узком экране CSS показывает
 * её слева от значения, и таблица читается как список карточек.
 */
export function labelizeTable(table) {
  const headers = Array.from(table.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  if (!headers.length) return;
  table.querySelectorAll('tbody tr').forEach((row) => {
    Array.from(row.children).forEach((cell, index) => {
      const label = headers[index];
      if (label) cell.dataset.label = label;
      else cell.dataset.label = '';
    });
  });
}

export function labelizeTables(root = document) {
  root.querySelectorAll('table').forEach(labelizeTable);
}

// Таблицы рисуются динамически на всех страницах, поэтому подписи проставляются
// наблюдателем — не нужно помнить про вызов в каждом месте отрисовки.
if (typeof MutationObserver !== 'undefined') {
  const observer = new MutationObserver((mutations) => {
    const tables = new Set();
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) return;
        if (node.tagName === 'TABLE') tables.add(node);
        else node.querySelectorAll?.('table').forEach((table) => tables.add(table));
        const row = node.closest?.('table');
        if (row) tables.add(row);
      });
    });
    tables.forEach(labelizeTable);
  });
  const start = () => observer.observe(document.body, { childList: true, subtree: true });
  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start);
}

/* ------------------------------ Бейджи статуса --------------------------- */

export function statusBadge(delivery) {
  if (delivery.status === 'CANCELLED') return el('span', { class: 'badge', text: 'Отменён' });
  if (delivery.status === 'ARRIVED') {
    return delivery.arrived_late
      ? el('span', { class: 'badge badge--warning', text: `Прибыл с опозданием (${formatMinutes(delivery.late_minutes)})` })
      : el('span', { class: 'badge badge--success', text: 'Прибыл вовремя' });
  }
  if (delivery.is_overdue) {
    return el('span', { class: 'badge badge--danger', text: `Просрочен на ${formatMinutes(delivery.late_minutes)}` });
  }
  if (delivery.status === 'IN_TRANSIT') return el('span', { class: 'badge badge--primary', text: 'В пути' });
  return el('span', { class: 'badge', text: 'Создан' });
}

export function rowClass(delivery) {
  if (delivery.color === 'RED') return 'table-row--red';
  if (delivery.color === 'ORANGE') return 'table-row--orange';
  return '';
}

export function userName(user) {
  return user ? user.full_name : '—';
}

export function confirmAction(message) {
  return window.confirm(message);
}
