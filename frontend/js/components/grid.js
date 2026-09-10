/**
 * Таблица с редактированием прямо в ячейках — привычная по Google Таблицам.
 *
 * Навигация стрелками, Tab и Enter; правка по Enter, F2, двойному клику или
 * просто началом ввода; Escape отменяет. Каждая правка уходит на сервер
 * отдельно — тем же PATCH, что и обычная форма, поэтому проверки и журнал
 * действий работают как раньше.
 *
 * Колонка описывает и показ, и правку: `format` готовит текст ячейки,
 * `editValue` — значение для поля ввода. Второе намеренно названо не `valueOf`:
 * такой метод есть у любого объекта, и проверка `column.valueOf` была бы
 * истинной всегда, подставляя в поле сам объект колонки.
 */
import { el, clear } from '../ui.js';

const EDIT_KEYS = new Set(['Enter', 'F2']);

/**
 * @param {HTMLElement} container
 * @param {{
 *   columns: Array<{key, title, width?, type?, options?, format?, editable?, align?, editValue?}>,
 *   rows: Array<object>,
 *   rowKey: (row) => string|number,
 *   rowClass?: (row) => string,
 *   readOnly?: boolean,
 *   onSave: (row, column, value) => Promise<object|void>,
 * }} config
 */
export function createGrid(container, config) {
  const { columns, rowKey, onSave, rowClass = () => '', readOnly = false } = config;
  let rows = config.rows.slice();
  let active = { row: 0, col: 0 };
  let editor = null;

  const table = el('table', { class: 'grid__table' });
  const thead = el('thead');
  const tbody = el('tbody');
  table.append(thead, tbody);

  const scroller = el('div', { class: 'grid' }, [table]);
  clear(container);
  container.append(scroller);

  const editable = (column) => !readOnly && column.editable !== false && column.type !== 'readonly';

  const renderHead = () => {
    const tr = el('tr');
    tr.append(el('th', { class: 'grid__corner', text: '#', scope: 'col' }));
    columns.forEach((column) => {
      const th = el('th', { scope: 'col', text: column.title });
      if (column.width) th.style.width = `${column.width}px`;
      if (column.align === 'right') th.classList.add('grid__cell--right');
      tr.append(th);
    });
    clear(thead);
    thead.append(tr);
  };

  /** Текст ячейки: колонка может форматировать значение по-своему. */
  const display = (row, column) => {
    const value = row[column.key];
    if (column.format) return column.format(value, row);
    if (value === null || value === undefined || value === '') return '';
    return String(value);
  };

  const renderBody = () => {
    clear(tbody);
    rows.forEach((row, rowIndex) => {
      const tr = el('tr', { class: rowClass(row) || '' });
      tr.dataset.key = String(rowKey(row));
      tr.append(el('th', { class: 'grid__rownum', scope: 'row', text: String(rowIndex + 1) }));

      columns.forEach((column, colIndex) => {
        const locked = !editable(column);
        const td = el('td', {
          class: `grid__cell${locked ? ' grid__cell--locked' : ''}${
            column.align === 'right' ? ' grid__cell--right' : ''
          }`,
          tabindex: '-1',
          role: 'gridcell',
          text: display(row, column),
        });
        td.dataset.row = String(rowIndex);
        td.dataset.col = String(colIndex);
        if (locked) td.setAttribute('aria-readonly', 'true');
        tr.append(td);
      });
      tbody.append(tr);
    });
    highlight();
  };

  const cellAt = (rowIndex, colIndex) =>
    tbody.querySelector(`td[data-row="${rowIndex}"][data-col="${colIndex}"]`);

  const highlight = () => {
    tbody
      .querySelectorAll('.grid__cell--active')
      .forEach((node) => node.classList.remove('grid__cell--active'));
    const cell = cellAt(active.row, active.col);
    if (cell) cell.classList.add('grid__cell--active');
  };

  const focusCell = (rowIndex, colIndex, { scroll = true } = {}) => {
    if (rowIndex < 0 || rowIndex >= rows.length) return;
    if (colIndex < 0 || colIndex >= columns.length) return;
    active = { row: rowIndex, col: colIndex };
    highlight();
    const cell = cellAt(rowIndex, colIndex);
    if (cell && scroll) {
      cell.focus({ preventScroll: true });
      cell.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  };

  /** Поле ввода под тип колонки. */
  const buildInput = (column, row) => {
    if (column.type === 'select') {
      const select = el('select', { class: 'grid__input' });
      (column.options || []).forEach((option) => {
        select.append(el('option', { value: String(option.value), text: option.label }));
      });
      select.value = String(column.editValue ? column.editValue(row) : row[column.key] ?? '');
      return select;
    }
    const type =
      column.type === 'datetime' ? 'datetime-local' : column.type === 'number' ? 'number' : 'text';
    const input = el('input', { class: 'grid__input', type });
    input.value = column.editValue ? column.editValue(row) ?? '' : row[column.key] ?? '';
    return input;
  };

  const closeEditor = ({ restore = true } = {}) => {
    if (!editor) return;
    const { cell, row, column } = editor;
    editor = null;
    cell.classList.remove('grid__cell--editing');
    clear(cell);
    if (restore) cell.textContent = display(row, column);
  };

  const flash = (cell, className, ms) => {
    cell.classList.add(className);
    setTimeout(() => cell.classList.remove(className), ms);
  };

  const commit = async () => {
    if (!editor) return;
    const { cell, row, column, input, initial } = editor;
    const value = input.value;
    if (value === initial) {
      closeEditor();
      return;
    }

    editor = null;
    cell.classList.remove('grid__cell--editing');
    cell.classList.add('grid__cell--saving');
    clear(cell);
    cell.textContent = value;

    try {
      const updated = await onSave(row, column, value);
      if (updated) Object.assign(row, updated);
      cell.classList.remove('grid__cell--saving');
      flash(cell, 'grid__cell--saved', 1200);
      // Сервер мог поправить значение (нормализация номера, пересчёт срока) —
      // показываем то, что действительно сохранено, а не то, что ввели.
      cell.textContent = display(row, column);
      const tr = cell.closest('tr');
      if (tr) tr.className = rowClass(row) || '';
    } catch (error) {
      cell.classList.remove('grid__cell--saving');
      flash(cell, 'grid__cell--error', 2500);
      cell.textContent = display(row, column);
      throw error;
    }
  };

  const startEdit = (rowIndex, colIndex, initialChar = null) => {
    const column = columns[colIndex];
    const row = rows[rowIndex];
    if (!row || !editable(column)) return;
    if (editor) closeEditor();

    const cell = cellAt(rowIndex, colIndex);
    if (!cell) return;

    const input = buildInput(column, row);
    if (initialChar !== null && input.tagName === 'INPUT') input.value = initialChar;

    editor = { cell, row, column, input, initial: input.value, rowIndex, colIndex };
    cell.classList.add('grid__cell--editing');
    clear(cell);
    cell.append(input);
    input.focus();
    if (input.select && initialChar === null) input.select();

    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        closeEditor();
        focusCell(rowIndex, colIndex);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        event.stopPropagation();
        commit().catch(() => {});
        focusCell(Math.min(rowIndex + 1, rows.length - 1), colIndex);
      } else if (event.key === 'Tab') {
        event.preventDefault();
        event.stopPropagation();
        commit().catch(() => {});
        const next = event.shiftKey ? colIndex - 1 : colIndex + 1;
        focusCell(rowIndex, Math.max(0, Math.min(next, columns.length - 1)));
      }
    });
    // Уход мышью в другое место — сохраняем, как поступает любая таблица
    input.addEventListener('blur', () => {
      if (editor && editor.input === input) commit().catch(() => {});
    });
  };

  tbody.addEventListener('click', (event) => {
    const cell = event.target.closest('.grid__cell');
    if (!cell || cell.classList.contains('grid__cell--editing')) return;
    focusCell(Number(cell.dataset.row), Number(cell.dataset.col));
  });

  tbody.addEventListener('dblclick', (event) => {
    const cell = event.target.closest('.grid__cell');
    if (!cell) return;
    startEdit(Number(cell.dataset.row), Number(cell.dataset.col));
  });

  tbody.addEventListener('keydown', (event) => {
    if (editor) return;
    const { row, col } = active;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusCell(row + 1, col);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusCell(row - 1, col);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      focusCell(row, col + 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      focusCell(row, col - 1);
    } else if (event.key === 'Tab') {
      event.preventDefault();
      const next = event.shiftKey ? col - 1 : col + 1;
      if (next < 0) focusCell(row - 1, columns.length - 1);
      else if (next >= columns.length) focusCell(row + 1, 0);
      else focusCell(row, next);
    } else if (EDIT_KEYS.has(event.key)) {
      event.preventDefault();
      startEdit(row, col);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      // Начали печатать — это правка, как в любой таблице
      event.preventDefault();
      startEdit(row, col, event.key);
    }
  });

  renderHead();
  renderBody();

  return {
    /** Заменить строки целиком (перезагрузка, смена фильтра). */
    setRows(next) {
      rows = next.slice();
      active = { row: 0, col: 0 };
      renderBody();
    },
    /** Дописать строки снизу (подгрузка следующей страницы). */
    appendRows(next) {
      rows = rows.concat(next);
      renderBody();
    },
    get rows() {
      return rows;
    },
    focusCell,
  };
}
