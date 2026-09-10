/** Переиспользуемая таблица рейсов с цветовой индикацией. */
import { el, clear, formatDateTime, formatTotals, renderEmpty, rowClass, statusBadge, userName } from '../ui.js';

/**
 * Цепочка маршрута. Длинные маршруты сворачиваются: Бишкек → +2 → Достук,
 * пройденные промежуточные точки отмечаются приглушённым цветом.
 */
function routeChain(delivery) {
  const waypoints = delivery.waypoints || [];
  const node = el('div', { class: 'route' });
  node.append(el('span', { text: delivery.point_from.name }));

  if (waypoints.length > 2) {
    node.append(
      el('span', { class: 'route__arrow', text: '→' }),
      el('span', {
        class: 'route__more',
        text: `+${waypoints.length}`,
        title: waypoints.map((item) => item.point.name).join(' → '),
      })
    );
  } else {
    waypoints.forEach((item) => {
      node.append(
        el('span', { class: 'route__arrow', text: '→' }),
        el('span', {
          class: item.is_passed ? 'route__stop route__stop--passed' : 'route__stop',
          text: item.point.name,
          title: item.is_passed ? 'Точка пройдена' : 'Точка не пройдена',
        })
      );
    });
  }

  node.append(el('span', { class: 'route__arrow', text: '→' }), el('span', { text: delivery.point_to.name }));
  return el('td', {}, [node]);
}

const COLUMNS = [
  { key: 'vehicle', label: 'Машина' },
  { key: 'route', label: 'Маршрут' },
  { key: 'dispatched', label: 'Отправлена' },
  { key: 'deadline', label: 'Дедлайн' },
  { key: 'received', label: 'Прибыла' },
  { key: 'status', label: 'Статус' },
  { key: 'people', label: 'Сотрудники' },
  { key: 'expenses', label: 'Расход' },
  { key: 'actions', label: '' },
];

export function renderDeliveryTable(container, deliveries, { emptyTitle = 'Рейсов нет', emptyHint = '' } = {}) {
  clear(container);

  if (!deliveries.length) {
    renderEmpty(container, emptyTitle, emptyHint);
    return;
  }

  const head = el('thead', {}, [el('tr', {}, COLUMNS.map((column) => el('th', { scope: 'col', text: column.label })))]);

  const body = el(
    'tbody',
    {},
    deliveries.map((delivery) =>
      el('tr', { class: rowClass(delivery) }, [
        el('td', {}, [
          el('a', { class: 'cell-strong', href: `delivery.html?id=${delivery.id}`, text: delivery.vehicle_number }),
          el('div', { class: 'cell-muted', text: `Рейс #${delivery.id}` }),
        ]),
        routeChain(delivery),
        el('td', { class: 'cell-nowrap', text: formatDateTime(delivery.dispatched_at) }),
        el('td', { class: 'cell-nowrap', text: formatDateTime(delivery.deadline_at) }),
        el('td', { class: 'cell-nowrap', text: delivery.received_at ? formatDateTime(delivery.received_at) : '—' }),
        el('td', {}, [statusBadge(delivery)]),
        el('td', {}, [
          el('div', { class: 'cell-muted', text: `Отправил: ${userName(delivery.dispatched_by)}` }),
          el('div', { class: 'cell-muted', text: `Принял: ${userName(delivery.received_by)}` }),
        ]),
        el('td', {}, [
          delivery.has_expenses
            ? el('span', { class: 'badge badge--warning', text: formatTotals(delivery.expense_totals) })
            : el('span', { class: 'cell-muted', text: '—' }),
        ]),
        el('td', {}, [el('a', { class: 'btn btn--sm', href: `delivery.html?id=${delivery.id}`, text: 'Открыть' })]),
      ])
    )
  );

  container.append(el('div', { class: 'table-wrapper' }, [el('table', {}, [head, body])]));
}
