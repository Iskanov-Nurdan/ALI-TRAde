/** Карточка рейса: сведения, действия, расходы, комментарии, история. */
import { api } from '../api.js';
import { icon } from '../icons.js';
import { initLayout, isAdmin, queryParams } from '../layout.js';
import {
  clear,
  closeModal,
  confirmAction,
  el,
  formatDateTime,
  formatMinutes,
  formatMoney,
  formatConverted,
  formatTotals,
  fromLocalInputValue,
  openModal,
  qs,
  renderEmpty,
  renderError,
  renderLoading,
  setupModal,
  showApiError,
  statusBadge,
  toast,
  toLocalInputValue,
  userName,
} from '../ui.js';

const root = qs('#delivery-root');
const actionsBox = qs('#actions');
const expenseModal = setupModal(qs('#expense-modal'));
const actionModal = setupModal(qs('#action-modal'));
const expenseForm = qs('#expense-form');
const actionForm = qs('#action-form');

const deliveryId = Number(queryParams().id);
let delivery = null;
let dictionaries = { currencies: [], payers: [] };
let expenseTypes = [];
let expenseSettings = null;
let currentAction = null;

const EVENT_MODIFIERS = {
  DEADLINE_PASSED: 'timeline__item--danger',
  EXPENSE_ADDED: 'timeline__item--warning',
  EXPENSE_UPDATED: 'timeline__item--warning',
  EXPENSE_DELETED: 'timeline__item--warning',
  RECEIVED: 'timeline__item--success',
  CANCELLED: 'timeline__item--danger',
};

/* ------------------------------- Отрисовка ------------------------------- */

function infoItem(label, value) {
  return el('div', { class: 'info-list__item' }, [
    el('span', { class: 'info-list__label', text: label }),
    el('span', { class: 'info-list__value' }, [value instanceof Node ? value : String(value)]),
  ]);
}

function renderInfoCard() {
  const lateText =
    delivery.status === 'ARRIVED' && delivery.arrived_late
      ? `Опоздание: ${formatMinutes(delivery.late_minutes)}`
      : delivery.is_overdue
        ? `Просрочка: ${formatMinutes(delivery.late_minutes)}`
        : 'Без опоздания';

  return el('section', { class: 'card' }, [
    el('div', { class: 'card__title' }, [
      el('h2', { text: `Машина ${delivery.vehicle_number}` }),
      statusBadge(delivery),
    ]),
    el('div', { class: 'info-list' }, [
      infoItem(
        'Маршрут',
        el(
          'span',
          { class: 'route' },
          (delivery.route_points || [delivery.point_from.name, delivery.point_to.name]).flatMap(
            (name, index) => [
              index ? el('span', { class: 'route__arrow', text: '→' }) : null,
              el('span', { text: name }),
            ]
          ).filter(Boolean)
        )
      ),
      infoItem('Номер рейса', `#${delivery.id}`),
      infoItem('Отправлена', formatDateTime(delivery.dispatched_at)),
      infoItem('Плановое прибытие', formatDateTime(delivery.deadline_at)),
      infoItem('Фактическое прибытие', delivery.received_at ? formatDateTime(delivery.received_at) : '—'),
      infoItem('Опоздание', lateText),
      infoItem('Создал', userName(delivery.created_by)),
      infoItem('Отправил', userName(delivery.dispatched_by)),
      infoItem('Принял', userName(delivery.received_by)),
      infoItem(
        'Сумма расходов',
        el('span', {}, [
          el('span', { text: formatTotals(delivery.expense_totals) }),
          formatConverted(delivery.expense_total_converted)
            ? el('div', {
                class: 'total-row__converted',
                text: formatConverted(delivery.expense_total_converted),
              })
            : null,
        ])
      ),
      delivery.dispatch_comment ? infoItem('Комментарий при отправлении', delivery.dispatch_comment) : null,
      delivery.receive_comment ? infoItem('Комментарий при приёме', delivery.receive_comment) : null,
      delivery.cancel_comment ? infoItem('Причина отмены', delivery.cancel_comment) : null,
    ].filter(Boolean)),
  ]);
}

/** Маршрут рейса: точки по порядку, отметка прохождения промежуточных. */
function renderRouteCard() {
  const stops = [
    { name: delivery.point_from.name, role: 'Отправление', passed: true, at: delivery.dispatched_at },
    ...delivery.waypoints.map((waypoint) => ({
      name: waypoint.point.name,
      role: 'Промежуточная точка',
      passed: waypoint.is_passed,
      at: waypoint.passed_at,
      by: waypoint.passed_by,
      waypoint,
    })),
    {
      name: delivery.point_to.name,
      role: 'Прибытие',
      passed: delivery.status === 'ARRIVED',
      at: delivery.received_at,
      by: delivery.received_by,
    },
  ];

  const canPass = delivery.status === 'IN_TRANSIT';

  const items = stops.map((stop, index) =>
    el('li', { class: `stops__item ${stop.passed ? 'stops__item--passed' : ''}` }, [
      el('span', { class: 'stops__marker', text: String(index + 1) }),
      el('span', { class: 'stops__body' }, [
        el('span', { class: 'stops__name', text: stop.name }),
        el('span', { class: 'stops__meta', text: stop.role }),
        stop.passed && stop.at
          ? el('span', {
              class: 'stops__meta',
              text: `${formatDateTime(stop.at)}${stop.by ? ` · ${userName(stop.by)}` : ''}`,
            })
          : null,
      ]),
      stop.waypoint && !stop.passed && canPass
        ? actionButton({
            label: 'Отметить прохождение',
            iconName: 'check',
            className: 'btn btn--sm',
            onClick: () => passWaypoint(stop.waypoint),
          })
        : stop.passed
          ? el('span', { class: 'badge badge--success', text: 'Пройдена' })
          : el('span', { class: 'badge', text: 'Ожидается' }),
    ])
  );

  return el('section', { class: 'card' }, [
    el('div', { class: 'card__title' }, [
      el('h2', { text: 'Маршрут' }),
      el('span', { class: 'cell-muted', text: `Точек: ${stops.length}` }),
    ]),
    el('ol', { class: 'stops' }, items),
  ]);
}

async function passWaypoint(waypoint) {
  try {
    await api.passWaypoint(delivery.id, waypoint.id, {});
    toast(`Точка «${waypoint.point.name}» отмечена как пройденная.`, 'success');
    await load();
  } catch (error) {
    showApiError(error);
  }
}

function renderExpensesCard() {
  const card = el('section', { class: 'card' }, [
    el('div', { class: 'card__title' }, [
      el('h2', { text: `Расходы (${delivery.expenses.length})` }),
      actionButton({ label: 'Добавить расход', iconName: 'plus', className: 'btn btn--primary btn--sm', onClick: openExpenseModal }),
    ]),
  ]);

  if (!delivery.expenses.length) {
    const empty = el('div', {});
    renderEmpty(empty, 'Расходов нет', 'Расход можно добавить на любом этапе рейса, в том числе после прибытия.');
    card.append(empty);
    return card;
  }

  const rows = delivery.expenses.map((expense) =>
    el('tr', {}, [
      el('td', { text: expense.expense_type_name }),
      el('td', { class: 'cell-num cell-strong', text: formatMoney(expense.amount, expense.currency) }),
      el('td', {}, [
        el('span', { text: expense.payer_display }),
        expense.payer_auto_assigned ? el('div', { class: 'cell-muted', text: 'определён правилом' }) : null,
      ]),
      el('td', {}, [
        el('div', { text: expense.description }),
        expense.comment ? el('div', { class: 'cell-muted', text: expense.comment }) : null,
      ]),
      el('td', { text: userName(expense.created_by) }),
      el('td', { class: 'cell-nowrap', text: formatDateTime(expense.created_at) }),
      isAdmin()
        ? el('td', {}, [
            el('button', {
              class: 'btn btn--sm btn--danger',
              type: 'button',
              text: 'Удалить',
              onClick: () => removeExpense(expense),
            }),
          ])
        : el('td', {}),
    ])
  );

  card.append(
    el('div', { class: 'table-wrapper' }, [
      el('table', {}, [
        el('thead', {}, [
          el(
            'tr',
            {},
            ['Тип', 'Сумма', 'Плательщик', 'Описание', 'Добавил', 'Дата', ''].map((label) =>
              el('th', { scope: 'col', class: label === 'Сумма' ? 'cell-num' : null, text: label })
            )
          ),
        ]),
        el('tbody', {}, rows),
      ]),
    ]),
    el('div', { class: 'total-row' }, [
      el('span', { text: 'Общая сумма расходов' }),
      el('span', {}, [
        el('span', { text: formatTotals(delivery.expense_totals) }),
        formatConverted(delivery.expense_total_converted)
          ? el('div', {
              class: 'total-row__converted',
              text: formatConverted(delivery.expense_total_converted),
            })
          : null,
      ]),
    ])
  );
  return card;
}

function renderCommentsCard() {
  const list = delivery.comments.length
    ? el(
        'ul',
        { class: 'comment-list' },
        delivery.comments.map((comment) =>
          el('li', { class: 'comment' }, [
            el('div', { class: 'comment__meta', text: `${userName(comment.user)} · ${formatDateTime(comment.event_time)}` }),
            el('div', { text: comment.comment }),
          ])
        )
      )
    : el('p', { class: 'cell-muted', text: 'Комментариев пока нет.' });

  const form = el('form', { class: 'form-grid' }, [
    el('div', { class: 'field' }, [
      el('label', { class: 'field__label', for: 'new-comment', text: 'Новый комментарий' }),
      el('textarea', { id: 'new-comment', name: 'comment', rows: '2', required: true }),
    ]),
    el('button', { class: 'btn btn--primary', type: 'submit', text: 'Добавить комментарий' }),
  ]);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const value = String(new FormData(form).get('comment') || '').trim();
    if (!value) {
      toast('Комментарий не может быть пустым.', 'error');
      return;
    }
    try {
      await api.addComment(delivery.id, value);
      toast('Комментарий добавлен.', 'success');
      await load();
    } catch (error) {
      showApiError(error);
    }
  });

  return el('section', { class: 'card' }, [el('div', { class: 'card__title' }, [el('h2', { text: 'Комментарии' })]), list, form]);
}

function eventTitle(event) {
  if (event.event_type === 'EXPENSE_ADDED' && event.metadata) {
    return `${event.event_type_display}: ${event.metadata.type} ${event.metadata.amount} ${event.metadata.currency}`;
  }
  if (event.event_type === 'RECEIVED' && event.metadata && event.metadata.late_minutes) {
    return `${event.event_type_display} (опоздание ${formatMinutes(event.metadata.late_minutes)})`;
  }
  return event.event_type_display;
}

function renderHistoryCard() {
  const items = delivery.events.map((event) =>
    el('li', { class: `timeline__item ${EVENT_MODIFIERS[event.event_type] || ''}` }, [
      el('div', { class: 'timeline__time', text: formatDateTime(event.event_time) }),
      el('div', { class: 'timeline__title', text: eventTitle(event) }),
      el('div', { class: 'timeline__text', text: event.user ? userName(event.user) : 'Система' }),
      event.comment ? el('div', { class: 'timeline__text', text: event.comment }) : null,
    ])
  );

  return el('section', { class: 'card' }, [
    el('div', { class: 'card__title' }, [el('h2', { text: 'История действий' })]),
    items.length ? el('ol', { class: 'timeline' }, items) : el('p', { class: 'cell-muted', text: 'Событий нет.' }),
  ]);
}

/** Кнопка с иконкой слева от подписи. */
function actionButton({ label, iconName, className = 'btn', onClick, href }) {
  const node = href
    ? el('a', { class: className, href })
    : el('button', { class: className, type: 'button', onClick });
  node.append(icon(iconName, { size: 15 }), el('span', { text: label }));
  return node;
}

function renderActions() {
  clear(actionsBox);
  actionsBox.append(actionButton({ label: 'К списку', iconName: 'back', href: 'deliveries.html' }));

  if (delivery.status === 'CREATED') {
    actionsBox.append(
      actionButton({
        label: 'Подтвердить отправление',
        iconName: 'truck',
        className: 'btn btn--primary',
        onClick: () => openActionModal('dispatch'),
      })
    );
  }
  if (delivery.status === 'IN_TRANSIT') {
    actionsBox.append(
      actionButton({
        label: 'Подтвердить прибытие',
        iconName: 'check',
        className: 'btn btn--success',
        onClick: () => openActionModal('receive'),
      })
    );
  }
  if (delivery.status !== 'ARRIVED' && delivery.status !== 'CANCELLED') {
    actionsBox.append(
      actionButton({
        label: 'Отменить рейс',
        iconName: 'ban',
        className: 'btn btn--danger',
        onClick: () => openActionModal('cancel'),
      })
    );
  }
  actionsBox.append(
    actionButton({ label: 'Добавить расход', iconName: 'plus', onClick: openExpenseModal })
  );
}

function render() {
  qs('#page-title').textContent = `Рейс #${delivery.id} — ${delivery.vehicle_number}`;
  document.title = `Рейс #${delivery.id} — ${delivery.vehicle_number}`;

  clear(root).append(
    el('div', { class: 'detail-grid' }, [
      el('div', {}, [renderInfoCard(), renderRouteCard(), renderExpensesCard(), renderCommentsCard()]),
      el('div', {}, [renderHistoryCard()]),
    ])
  );
  renderActions();
}

/* -------------------------------- Действия ------------------------------- */

function openActionModal(action) {
  currentAction = action;
  const titles = {
    dispatch: 'Подтверждение отправления',
    receive: 'Подтверждение прибытия',
    cancel: 'Отмена рейса',
  };
  const timeLabels = { dispatch: 'Время отправления', receive: 'Время прибытия' };

  qs('#action-modal-title').textContent = titles[action];
  actionForm.reset();

  const timeField = qs('#action-time-field');
  timeField.hidden = action === 'cancel';
  if (action !== 'cancel') {
    qs('#a-time').value = toLocalInputValue();
    timeField.querySelector('label').textContent = timeLabels[action];
  }
  qs('#action-submit').textContent = action === 'cancel' ? 'Отменить рейс' : 'Подтвердить';
  openModal(actionModal);
}

actionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(actionForm).entries());
  const comment = String(data.comment || '').trim();
  const time = data.time ? fromLocalInputValue(data.time) : null;
  const submit = qs('#action-submit');

  if (currentAction === 'cancel' && !comment) {
    toast('Укажите причину отмены рейса.', 'error');
    return;
  }

  submit.disabled = true;
  try {
    if (currentAction === 'dispatch') {
      await api.dispatchDelivery(delivery.id, { dispatched_at: time, comment });
      toast('Отправление подтверждено.', 'success');
    } else if (currentAction === 'receive') {
      const updated = await api.receiveDelivery(delivery.id, { received_at: time, comment });
      toast(
        updated.arrived_late
          ? `Прибытие подтверждено. Опоздание: ${formatMinutes(updated.late_minutes)}.`
          : 'Прибытие подтверждено вовремя.',
        'success'
      );
    } else {
      await api.cancelDelivery(delivery.id, { comment });
      toast('Рейс отменён.', 'success');
    }
    closeModal(actionModal);
    await load();
  } catch (error) {
    showApiError(error);
  } finally {
    submit.disabled = false;
  }
});

/* --------------------------------- Расходы -------------------------------- */

function openExpenseModal() {
  expenseForm.reset();
  const hint = qs('#payer-hint');
  if (expenseSettings && expenseSettings.auto_payer_enabled) {
    hint.textContent = `Если не выбрать: свыше ${expenseSettings.threshold_amount} ${expenseSettings.threshold_currency} — плательщик определяется правилом.`;
  } else {
    hint.textContent = 'Если не выбрать — будет указана наша компания.';
  }
  openModal(expenseModal);
}

expenseForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(expenseForm).entries());
  const submit = qs('#expense-submit');

  const payload = {
    expense_type_id: Number(data.expense_type_id),
    amount: String(data.amount || '').trim(),
    currency: data.currency,
    description: String(data.description || '').trim(),
    comment: String(data.comment || '').trim(),
  };
  if (data.payer) payload.payer = data.payer;

  if (!payload.expense_type_id) {
    toast('Выберите тип расхода.', 'error');
    return;
  }
  if (!payload.amount || Number(payload.amount) <= 0) {
    toast('Укажите сумму расхода.', 'error');
    return;
  }
  if (payload.description.length < 2) {
    toast('Опишите расход.', 'error');
    return;
  }

  submit.disabled = true;
  submit.textContent = 'Сохранение…';
  try {
    await api.addExpense(delivery.id, payload);
    closeModal(expenseModal);
    toast('Расход добавлен.', 'success');
    await load();
  } catch (error) {
    showApiError(error);
  } finally {
    submit.disabled = false;
    submit.textContent = 'Сохранить расход';
  }
});

async function removeExpense(expense) {
  if (!confirmAction(`Удалить расход «${expense.description}» на ${formatMoney(expense.amount, expense.currency)}?`)) {
    return;
  }
  try {
    await api.deleteExpense(expense.id);
    toast('Расход удалён.', 'success');
    await load();
  } catch (error) {
    showApiError(error);
  }
}

/* -------------------------------- Загрузка -------------------------------- */

async function loadDictionaries() {
  const [types, dicts] = await Promise.all([api.listExpenseTypes({ is_active: true }), api.dictionaries()]);
  expenseTypes = Array.isArray(types) ? types : types.results;
  dictionaries = dicts;

  const typeSelect = qs('#e-type');
  clear(typeSelect).append(el('option', { value: '', text: '— выберите тип —' }));
  expenseTypes.forEach((type) => typeSelect.append(el('option', { value: type.id, text: type.name })));

  const currencySelect = qs('#e-currency');
  clear(currencySelect);
  dictionaries.currencies.forEach((currency) =>
    currencySelect.append(el('option', { value: currency.value, text: `${currency.value} — ${currency.label}` }))
  );

  const payerSelect = qs('#e-payer');
  clear(payerSelect).append(el('option', { value: '', text: 'Определить автоматически' }));
  dictionaries.payers.forEach((payer) => payerSelect.append(el('option', { value: payer.value, text: payer.label })));

  try {
    expenseSettings = await api.getExpenseSettings();
  } catch (error) {
    expenseSettings = null;
  }
}

async function load() {
  renderLoading(root, 'Загружаем карточку рейса…');
  try {
    delivery = await api.getDelivery(deliveryId);
    render();
  } catch (error) {
    renderError(root, error.status === 404 ? 'Рейс не найден.' : error.message, load);
  }
}

(async () => {
  const user = await initLayout({ active: 'deliveries.html' });
  if (!user) return;

  if (!deliveryId) {
    renderError(root, 'Не указан номер рейса.');
    return;
  }

  try {
    await loadDictionaries();
  } catch (error) {
    toast('Не удалось загрузить справочники расходов.', 'error');
  }
  await load();
})();
