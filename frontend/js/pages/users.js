/** Управление сотрудниками (раздел администратора). */
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

const listBox = qs('#users');
const modal = setupModal(qs('#user-modal'));
const form = qs('#user-form');
const searchForm = qs('#search-form');

let searchQuery = '';

function renderTable(users) {
  clear(listBox);
  if (!users.length) {
    renderEmpty(listBox, 'Сотрудники не найдены');
    return;
  }

  const rows = users.map((user) =>
    el('tr', {}, [
      el('td', {}, [
        el('div', { class: 'cell-strong', text: user.full_name }),
        el('div', { class: 'cell-muted', text: user.login }),
      ]),
      el('td', { class: 'cell-nowrap', text: user.phone || '—' }),
      el('td', {}, [
        user.role === 'ADMIN'
          ? el('span', { class: 'badge badge--primary', text: 'Администратор' })
          : el('span', { class: 'badge', text: 'Сотрудник' }),
      ]),
      el('td', {}, [
        user.is_active
          ? el('span', { class: 'badge badge--success', text: 'Активен' })
          : el('span', { class: 'badge badge--danger', text: 'Заблокирован' }),
      ]),
      el('td', { class: 'cell-nowrap', text: formatDate(user.created_at) }),
      el('td', {}, [
        el('div', { class: 'btn-group' }, [
          el('button', { class: 'btn btn--sm', type: 'button', text: 'Изменить', onClick: () => openEdit(user) }),
          el('button', {
            class: 'btn btn--sm',
            type: 'button',
            text: user.is_active ? 'Заблокировать' : 'Разблокировать',
            onClick: () => toggleActive(user),
          }),
          el('button', { class: 'btn btn--sm btn--danger', type: 'button', text: 'Удалить', onClick: () => remove(user) }),
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
            ['Сотрудник', 'Телефон', 'Роль', 'Статус', 'Создан', 'Действия'].map((label) =>
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
    const data = await api.listUsers({ page_size: 200, search: searchQuery || undefined });
    renderTable(data.results || data);
  } catch (error) {
    renderError(listBox, error.message, load);
  }
}

function openCreate() {
  form.reset();
  form.elements.id.value = '';
  form.elements.is_active.checked = true;
  form.elements.password.required = true;
  qs('#password-hint').textContent = 'Не менее 6 символов';
  qs('#user-modal-title').textContent = 'Новый сотрудник';
  openModal(modal);
}

function openEdit(user) {
  form.reset();
  form.elements.id.value = user.id;
  form.elements.full_name.value = user.full_name;
  form.elements.login.value = user.login;
  form.elements.phone.value = user.phone || '';
  form.elements.role.value = user.role;
  form.elements.is_active.checked = user.is_active;
  form.elements.password.required = false;
  qs('#password-hint').textContent = 'Оставьте пустым, чтобы не менять пароль';
  qs('#user-modal-title').textContent = user.full_name;
  openModal(modal);
}

async function toggleActive(user) {
  try {
    await api.setUserActive(user.id, !user.is_active);
    toast(user.is_active ? 'Сотрудник заблокирован.' : 'Сотрудник разблокирован.', 'success');
    await load();
  } catch (error) {
    showApiError(error);
  }
}

async function remove(user) {
  if (!confirmAction(`Удалить сотрудника «${user.full_name}»? Действие необратимо.`)) return;
  try {
    await api.deleteUser(user.id);
    toast('Сотрудник удалён.', 'success');
    await load();
  } catch (error) {
    showApiError(error);
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  const submit = qs('#user-submit');

  const payload = {
    full_name: String(data.full_name || '').trim(),
    login: String(data.login || '').trim().toLowerCase(),
    phone: String(data.phone || '').trim(),
    role: data.role,
    is_active: Boolean(data.is_active),
  };
  const password = String(data.password || '');

  if (payload.full_name.length < 3) {
    toast('Укажите полное имя сотрудника.', 'error');
    return;
  }
  if (!/^[a-zA-Z0-9_.\-]{3,60}$/.test(payload.login)) {
    toast('Логин: латиница, цифры, точка или дефис, от 3 символов.', 'error');
    return;
  }
  if (!data.id && password.length < 6) {
    toast('Пароль должен быть не короче 6 символов.', 'error');
    return;
  }
  if (password) payload.password = password;

  submit.disabled = true;
  try {
    if (data.id) {
      await api.updateUser(Number(data.id), payload);
      toast('Данные сотрудника обновлены.', 'success');
    } else {
      await api.createUser(payload);
      toast('Сотрудник создан.', 'success');
    }
    closeModal(modal);
    await load();
  } catch (error) {
    showApiError(error);
  } finally {
    submit.disabled = false;
  }
});

searchForm.addEventListener('submit', (event) => {
  event.preventDefault();
  searchQuery = String(new FormData(searchForm).get('search') || '').trim();
  load();
});

(async () => {
  const user = await initLayout({ active: 'users.html', adminOnly: true });
  if (!user) return;
  qs('#btn-new').addEventListener('click', openCreate);
  await load();
})();
