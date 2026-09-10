/** Главная панель: сводные показатели и оперативные списки рейсов. */
import { api } from '../api.js';
import { initLayout } from '../layout.js';
import { clear, el, formatConverted, formatTotals, renderError, renderLoading } from '../ui.js';
import { renderDeliveryTable } from '../components/delivery-table.js';

const statsBox = document.querySelector('#stats');
const activeBox = document.querySelector('#active-deliveries');
const recentBox = document.querySelector('#recent-deliveries');

function statCard({ label, value, hint, modifier }) {
  return el('article', { class: `stat ${modifier || ''}` }, [
    el('span', { class: 'stat__label', text: label }),
    el('strong', { class: 'stat__value', text: String(value) }),
    hint ? el('span', { class: 'stat__hint', text: hint }) : null,
  ]);
}

function renderStats(summary) {
  clear(statsBox).append(
    statCard({ label: 'Машин в пути', value: summary.in_transit, modifier: 'stat--primary' }),
    statCard({ label: 'Просрочено', value: summary.overdue, modifier: 'stat--danger', hint: 'Срок истёк, прибытие не подтверждено' }),
    statCard({ label: 'Прибыло', value: summary.arrived, modifier: 'stat--success' }),
    statCard({ label: 'С опозданием', value: summary.arrived_late, modifier: 'stat--warning' }),
    statCard({ label: 'Рейсов с расходами', value: summary.with_expenses, modifier: 'stat--warning' }),
    statCard({
      label: 'Сумма расходов',
      value: formatTotals(summary.expense_totals),
      hint: formatConverted(summary.expense_total_converted),
      modifier: 'stat--primary',
    }),
    statCard({ label: 'Ожидают отправления', value: summary.created }),
    statCard({ label: 'Всего рейсов', value: summary.total })
  );
}

async function loadDashboard() {
  renderLoading(statsBox, 'Считаем показатели…');
  renderLoading(activeBox);
  renderLoading(recentBox);

  try {
    const [summary, active, recent] = await Promise.all([
      api.dashboard(),
      api.listDeliveries({ state: 'active', ordering: 'deadline_at', page_size: 50 }),
      api.listDeliveries({ state: 'arrived', ordering: '-received_at', page_size: 10 }),
    ]);

    renderStats(summary);
    renderDeliveryTable(activeBox, active.results, {
      emptyTitle: 'Машин в пути нет',
      emptyHint: 'Все рейсы завершены либо ещё не отправлены.',
    });
    renderDeliveryTable(recentBox, recent.results, { emptyTitle: 'Прибытий пока нет' });
  } catch (error) {
    renderError(statsBox, error.message, loadDashboard);
    clear(activeBox);
    clear(recentBox);
  }
}

(async () => {
  const user = await initLayout({ active: 'dashboard.html' });
  if (!user) return;
  await loadDashboard();
})();
