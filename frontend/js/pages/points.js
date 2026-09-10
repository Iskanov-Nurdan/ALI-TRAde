/** Управление справочником точек (раздел администратора). */
import { api } from '../api.js';
import { initLayout } from '../layout.js';
import {
  clear,
  closeModal,
  confirmAction,
  el,
  formatDate,
  openModal,
  qs,
  renderEmpty,
  renderError,
  renderLoading,
  setupModal,
  showApiError,
  toast,
} from '../ui.js';

const listBox = qs('#points');
const modal = setupModal(qs('#point-modal'));
const form = qs('#point-form');
const showInactive = qs('#show-inactive');

function renderTable(points) {
  clear(listBox);
  if (!points.length) {
    renderEmpty(listBox, 'Точек нет', 'Добавьте первую точку маршрута.');
    return;
  }

  const rows = points.map((point) =>
    el('tr', {}, [
      el('td', {}, [
        el('div', { class: 'cell-strong', text: point.name }),
        point.description ? el('div', { class: 'cell-muted', text: point.description }) : null,
      ]),
      el('td', { text: point.address || '—' }),
      el('td', { class: 'cell-nowrap', text: point.phone || '—' }),
      el('td', {}, [
        point.is_active
          ? el('span', { class: 'badge badge--success', text: 'Активна' })
          : el('span', { class: 'badge', text: 'Отключена' }),
      ]),
      el('td', { class: 'cell-nowrap', text: formatDate(point.created_at) }),
      el('td', {}, [
        el('div', { class: 'btn-group' }, [
          el('button', { class: 'btn btn--sm', type: 'button', text: 'Изменить', onClick: () => openEdit(point) }),
          el('button', {
            class: 'btn btn--sm',
            type: 'button',
            text: point.is_active ? 'Отключить' : 'Включить',
            onClick: () => toggleActive(point),
          }),
          el('button', { class: 'btn btn--sm btn--danger', type: 'button', text: 'Удалить', onClick: () => remove(point) }),
        ]),
      ]),
    ])
  );

  listBox.append(
    el('div', { class: 'table-wrapper' }, [
      el('table', {}, [
        el('thead', {}, [
          el(
            'tr',
            {},
            ['Название', 'Адрес', 'Телефон', 'Статус', 'Создана', 'Действия'].map((label) =>
              el('th', { scope: 'col', text: label })
            )
          ),
        ]),
        el('tbody', {}, rows),
      ]),
    ])
  );
}

async function load() {
  renderLoading(listBox);
  try {
    const params = { page_size: 200 };
    if (!showInactive.checked) params.is_active = true;
    const data = await api.listPoints(params);
    renderTable(data.results || data);
  } catch (error) {
    renderError(listBox, error.message, load);
  }
}

function openCreate() {
  form.reset();
  form.elements.id.value = '';
  form.elements.is_active.checked = true;
  qs('#point-modal-title').textContent = 'Новая точка';
  openModal(modal);
}

function openEdit(point) {
  form.reset();
  form.elements.id.value = point.id;
  form.elements.name.value = point.name;
  form.elements.address.value = point.address || '';
  form.elements.phone.value = point.phone || '';
  form.elements.description.value = point.description || '';
  form.elements.is_active.checked = point.is_active;
  qs('#point-modal-title').textContent = `Точка «${point.name}»`;
  openModal(modal);
}

async function toggleActive(point) {
  try {
    await api.setPointActive(point.id, !point.is_active);
    toast(point.is_active ? 'Точка отключена.' : 'Точка включена.', 'success');
    await load();
  } catch (error) {
    showApiError(error);
  }
}

async function remove(point) {
  if (!confirmAction(`Удалить точку «${point.name}»? Действие необратимо.`)) return;
  try {
    await api.deletePoint(point.id);
    toast('Точка удалена.', 'success');
    await load();
  } catch (error) {
    showApiError(error);
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  const submit = qs('#point-submit');

  const payload = {
    name: String(data.name || '').trim(),
    address: String(data.address || '').trim(),
    phone: String(data.phone || '').trim(),
    description: String(data.description || '').trim(),
    is_active: Boolean(data.is_active),
  };
  if (payload.name.length < 2) {
    toast('Укажите название точки.', 'error');
    return;
  }

  submit.disabled = true;
  try {
    if (data.id) {
      await api.updatePoint(Number(data.id), payload);
      toast('Точка обновлена.', 'success');
    } else {
      await api.createPoint(payload);
      toast('Точка создана.', 'success');
    }
    closeModal(modal);
    await load();
  } catch (error) {
    showApiError(error);
  } finally {
    submit.disabled = false;
  }
});

(async () => {
  const user = await initLayout({ active: 'points.html', adminOnly: true });
  if (!user) return;
  qs('#btn-new').addEventListener('click', openCreate);
  showInactive.addEventListener('change', load);
  await load();
})();
