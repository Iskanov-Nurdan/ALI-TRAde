/** Справочник типов расходов и правило автоматического плательщика. */
import { api } from '../api.js';
import { initLayout } from '../layout.js';
import {
  clear,
  closeModal,
  confirmAction,
  el,
  openModal,
  qs,
  renderEmpty,
  renderError,
  renderLoading,
  setupModal,
  showApiError,
  toast,
} from '../ui.js';

const typesBox = qs('#types');
const typeModal = setupModal(qs('#type-modal'));
const typeForm = qs('#type-form');
const settingsForm = qs('#settings-form');

function renderTypes(types) {
  clear(typesBox);
  if (!types.length) {
    renderEmpty(typesBox, 'Типы расходов не заданы');
    return;
  }

  const rows = types.map((type) =>
    el('tr', {}, [
      el('td', { class: 'cell-strong', text: type.name }),
      el('td', { class: 'cell-muted', text: type.code }),
      el('td', { text: String(type.sort_order) }),
      el('td', {}, [
        type.is_active
          ? el('span', { class: 'badge badge--success', text: 'Активен' })
          : el('span', { class: 'badge', text: 'Отключён' }),
      ]),
      el('td', {}, [
        el('div', { class: 'btn-group' }, [
          el('button', { class: 'btn btn--sm', type: 'button', text: 'Изменить', onClick: () => openEdit(type) }),
          el('button', {
            class: 'btn btn--sm',
            type: 'button',
            text: type.is_active ? 'Отключить' : 'Включить',
            onClick: () => toggleActive(type),
          }),
          el('button', { class: 'btn btn--sm btn--danger', type: 'button', text: 'Удалить', onClick: () => remove(type) }),
        ]),
      ]),
    ])
  );

  typesBox.append(
    el('div', { class: 'table-wrapper' }, [
      el('table', {}, [
        el('thead', {}, [
          el('tr', {}, ['Название', 'Код', 'Порядок', 'Статус', 'Действия'].map((label) => el('th', { scope: 'col', text: label }))),
        ]),
        el('tbody', {}, rows),
      ]),
    ])
  );
}

async function loadTypes() {
  renderLoading(typesBox);
  try {
    const data = await api.listExpenseTypes();
    renderTypes(Array.isArray(data) ? data : data.results);
  } catch (error) {
    renderError(typesBox, error.message, loadTypes);
  }
}

function openCreate() {
  typeForm.reset();
  typeForm.elements.id.value = '';
  typeForm.elements.sort_order.value = '100';
  typeForm.elements.is_active.checked = true;
  qs('#type-modal-title').textContent = 'Новый тип расхода';
  openModal(typeModal);
}

function openEdit(type) {
  typeForm.reset();
  typeForm.elements.id.value = type.id;
  typeForm.elements.name.value = type.name;
  typeForm.elements.sort_order.value = type.sort_order;
  typeForm.elements.is_active.checked = type.is_active;
  qs('#type-modal-title').textContent = type.name;
  openModal(typeModal);
}

async function toggleActive(type) {
  try {
    await api.updateExpenseType(type.id, { is_active: !type.is_active });
    toast('Статус типа изменён.', 'success');
    await loadTypes();
  } catch (error) {
    showApiError(error);
  }
}

async function remove(type) {
  if (!confirmAction(`Удалить тип «${type.name}»?`)) return;
  try {
    await api.deleteExpenseType(type.id);
    toast('Тип расхода удалён.', 'success');
    await loadTypes();
  } catch (error) {
    showApiError(error);
  }
}

typeForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(typeForm).entries());
  const submit = qs('#type-submit');

  const payload = {
    name: String(data.name || '').trim(),
    sort_order: Number(data.sort_order) || 100,
    is_active: Boolean(data.is_active),
  };
  if (payload.name.length < 2) {
    toast('Укажите название типа расхода.', 'error');
    return;
  }

  submit.disabled = true;
  try {
    if (data.id) {
      await api.updateExpenseType(Number(data.id), payload);
      toast('Тип расхода обновлён.', 'success');
    } else {
      await api.createExpenseType(payload);
      toast('Тип расхода создан.', 'success');
    }
    closeModal(typeModal);
    await loadTypes();
  } catch (error) {
    showApiError(error);
  } finally {
    submit.disabled = false;
  }
});

async function loadSettings() {
  try {
    const [dicts, settings] = await Promise.all([api.dictionaries(), api.getExpenseSettings()]);

    const currencySelect = qs('#s-currency');
    clear(currencySelect);
    dicts.currencies.forEach((currency) => currencySelect.append(el('option', { value: currency.value, text: currency.value })));

    ['#s-above', '#s-below'].forEach((selector) => {
      const select = qs(selector);
      clear(select);
      dicts.payers.forEach((payer) => select.append(el('option', { value: payer.value, text: payer.label })));
    });

    settingsForm.elements.auto_payer_enabled.checked = settings.auto_payer_enabled;
    settingsForm.elements.threshold_amount.value = settings.threshold_amount;
    settingsForm.elements.threshold_currency.value = settings.threshold_currency;
    settingsForm.elements.payer_above.value = settings.payer_above;
    settingsForm.elements.payer_below.value = settings.payer_below;
  } catch (error) {
    toast('Не удалось загрузить настройки расходов.', 'error');
  }
}

settingsForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(settingsForm).entries());
  const submit = qs('#settings-submit');

  submit.disabled = true;
  try {
    await api.updateExpenseSettings({
      auto_payer_enabled: Boolean(data.auto_payer_enabled),
      threshold_amount: String(data.threshold_amount || '0'),
      threshold_currency: data.threshold_currency,
      payer_above: data.payer_above,
      payer_below: data.payer_below,
    });
    toast('Правило сохранено.', 'success');
  } catch (error) {
    showApiError(error);
  } finally {
    submit.disabled = false;
  }
});

(async () => {
  const user = await initLayout({ active: 'settings.html', adminOnly: true });
  if (!user) return;
  qs('#btn-new-type').addEventListener('click', openCreate);
  await Promise.all([loadTypes(), loadSettings()]);
})();
