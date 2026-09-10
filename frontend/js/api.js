/**
 * Клиент REST API: хранение токенов, автоматическое обновление access-токена,
 * единая обработка ошибок.
 */

const API_BASE = (window.APP_CONFIG && window.APP_CONFIG.apiBase) || '/api';
const STORAGE_KEYS = {
  access: 'delivery.access',
  refresh: 'delivery.refresh',
  user: 'delivery.user',
};

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload || {};
  }

  /** Ошибки валидации полей в виде «поле: сообщение». */
  get fieldErrors() {
    const errors = this.payload.errors;
    if (!errors || typeof errors !== 'object') return [];
    return Object.entries(errors).map(([field, messages]) => ({
      field,
      message: Array.isArray(messages) ? messages.join(' ') : String(messages),
    }));
  }
}

export const tokenStore = {
  get access() {
    return localStorage.getItem(STORAGE_KEYS.access);
  },
  get refresh() {
    return localStorage.getItem(STORAGE_KEYS.refresh);
  },
  get user() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEYS.user) || 'null');
    } catch (error) {
      return null;
    }
  },
  save({ access, refresh, user }) {
    if (access) localStorage.setItem(STORAGE_KEYS.access, access);
    if (refresh) localStorage.setItem(STORAGE_KEYS.refresh, refresh);
    if (user) localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(user));
  },
  clear() {
    Object.values(STORAGE_KEYS).forEach((key) => localStorage.removeItem(key));
  },
};

function buildUrl(path, params) {
  const url = `${API_BASE}${path}`;
  if (!params) return url;
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) {
      value.forEach((item) => query.append(key, item));
    } else {
      query.append(key, value);
    }
  });
  const queryString = query.toString();
  return queryString ? `${url}?${queryString}` : url;
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') || '';
  if (response.status === 204) return null;
  if (contentType.includes('application/json')) return response.json();
  return response.text();
}

async function refreshAccessToken() {
  const refresh = tokenStore.refresh;
  if (!refresh) return false;

  let response;
  try {
    response = await fetch(buildUrl('/auth/refresh/'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    });
  } catch (error) {
    // Связь пропала именно на обновлении токена. Без этой обёртки наружу
    // улетал системный TypeError: страницы показывали английский текст, а
    // initLayout не узнавал в нём ни 401, ни обрыв связи.
    throw new ApiError('Нет связи с сервером. Проверьте подключение.', 0, {});
  }
  if (!response.ok) return false;

  const data = await response.json();
  tokenStore.save({ access: data.access, refresh: data.refresh });
  return true;
}

export async function request(path, { method = 'GET', body, params, raw = false, retry = true } = {}) {
  const headers = {};
  const access = tokenStore.access;
  if (access) headers.Authorization = `Bearer ${access}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response;
  try {
    response = await fetch(buildUrl(path, params), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new ApiError('Нет связи с сервером. Проверьте подключение.', 0, {});
  }

  if (response.status === 401 && retry) {
    // Обновляем токен, только если есть чем. Во всех остальных случаях сессия
    // мертва: её нужно погасить и увести пользователя на вход, иначе он
    // останется на пустой странице с нерабочими токенами в хранилище.
    const refreshed = tokenStore.refresh ? await refreshAccessToken() : false;
    if (refreshed) {
      return request(path, { method, body, params, raw, retry: false });
    }
    tokenStore.clear();
    redirectToLogin();
    throw new ApiError('Сессия истекла. Войдите заново.', 401, {});
  }

  if (response.status === 401) {
    // Повторный запрос снова получил 401 — например, учётную запись
    // заблокировали, пока страница была открыта.
    tokenStore.clear();
    redirectToLogin();
    throw new ApiError('Сессия завершена. Войдите заново.', 401, {});
  }

  if (raw && response.ok) return response;

  const payload = await parseResponse(response);

  if (!response.ok) {
    const detail =
      (payload && payload.detail) ||
      (payload && payload.errors && 'Проверьте правильность заполнения полей.') ||
      'Не удалось выполнить операцию.';
    throw new ApiError(detail, response.status, payload || {});
  }

  return payload;
}

export function redirectToLogin() {
  const current = window.location.pathname.split('/').pop();
  if (current !== 'index.html' && current !== '') {
    window.location.href = 'index.html';
  }
}

/** Скачивание файла (CSV) с авторизацией. */
export async function downloadFile(path, params, filename) {
  const response = await request(path, { params, raw: true });
  // Сервер присылает имя файла с отметкой времени — используем его, если оно есть
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/);
  if (match) filename = match[1];
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  // Аутентификация
  login: (login, password) => request('/auth/login/', { method: 'POST', body: { login, password } }),
  me: () => request('/auth/me/'),
  changePassword: (body) => request('/auth/change-password/', { method: 'POST', body }),

  // Точки
  listPoints: (params) => request('/points/', { params }),
  createPoint: (body) => request('/points/', { method: 'POST', body }),
  updatePoint: (id, body) => request(`/points/${id}/`, { method: 'PATCH', body }),
  setPointActive: (id, isActive) =>
    request(`/points/${id}/set-active/`, { method: 'POST', body: { is_active: isActive } }),
  deletePoint: (id) => request(`/points/${id}/`, { method: 'DELETE' }),

  // Сотрудники
  listUsers: (params) => request('/users/', { params }),
  employeeDirectory: () => request('/users/directory/'),
  createUser: (body) => request('/users/', { method: 'POST', body }),
  updateUser: (id, body) => request(`/users/${id}/`, { method: 'PATCH', body }),
  setUserActive: (id, isActive) =>
    request(`/users/${id}/set-active/`, { method: 'POST', body: { is_active: isActive } }),
  deleteUser: (id) => request(`/users/${id}/`, { method: 'DELETE' }),

  // Рейсы
  listDeliveries: (params) => request('/deliveries/', { params }),
  dashboard: (params) => request('/deliveries/dashboard/', { params }),
  getDelivery: (id) => request(`/deliveries/${id}/`),
  createDelivery: (body) => request('/deliveries/', { method: 'POST', body }),
  updateDelivery: (id, body) => request(`/deliveries/${id}/`, { method: 'PATCH', body }),
  dispatchDelivery: (id, body) => request(`/deliveries/${id}/dispatch/`, { method: 'POST', body }),
  receiveDelivery: (id, body) => request(`/deliveries/${id}/receive/`, { method: 'POST', body }),
  cancelDelivery: (id, body) => request(`/deliveries/${id}/cancel/`, { method: 'POST', body }),
  passWaypoint: (deliveryId, waypointId, body) =>
    request(`/deliveries/${deliveryId}/waypoints/${waypointId}/pass/`, { method: 'POST', body }),
  listComments: (id) => request(`/deliveries/${id}/comments/`),
  addComment: (id, comment) => request(`/deliveries/${id}/comments/`, { method: 'POST', body: { comment } }),
  listEvents: (id) => request(`/deliveries/${id}/events/`),
  searchVehicles: (q) => request('/vehicles/search/', { params: { q } }),

  // Расходы
  listExpenses: (params) => request('/expenses/', { params }),
  expenseTotals: (params) => request('/expenses/totals/', { params }),
  deliveryExpenses: (deliveryId) => request(`/deliveries/${deliveryId}/expenses/`),
  addExpense: (deliveryId, body) =>
    request(`/deliveries/${deliveryId}/expenses/`, { method: 'POST', body }),
  updateExpense: (id, body) => request(`/expenses/${id}/`, { method: 'PATCH', body }),
  deleteExpense: (id) => request(`/expenses/${id}/`, { method: 'DELETE' }),
  listExpenseTypes: (params) => request('/expense-types/', { params }),
  createExpenseType: (body) => request('/expense-types/', { method: 'POST', body }),
  updateExpenseType: (id, body) => request(`/expense-types/${id}/`, { method: 'PATCH', body }),
  deleteExpenseType: (id) => request(`/expense-types/${id}/`, { method: 'DELETE' }),
  dictionaries: () => request('/expenses/dictionaries/'),
  currencyRates: () => request('/expenses/rates/'),
  updateCurrencyRates: (body) => request('/expenses/rates/', { method: 'PUT', body }),
  getExpenseSettings: () => request('/expenses/settings/'),
  updateExpenseSettings: (body) => request('/expenses/settings/', { method: 'PUT', body }),

  // Отчёты и аудит
  reportSummary: (params) => request('/reports/summary/', { params }),
  reportExpenses: (params) => request('/reports/expenses/', { params }),
  reportEmployees: (params) => request('/reports/employees/', { params }),
  listAudit: (params) => request('/audit/', { params }),
};
