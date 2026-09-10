/** Заглушка fetch: карта «URL -> ответ» плюс журнал вызовов. */
export function makeFetch(routes) {
  const calls = [];
  const fn = async (url, options = {}) => {
    calls.push({ url, options });
    const key = Object.keys(routes).find((route) => String(url).includes(route));
    if (!key) throw new TypeError(`fetch failed: нет маршрута для ${url}`);
    const route = routes[key];
    const result = typeof route === 'function' ? await route({ url, options, calls }) : route;
    if (result instanceof Error) throw result;
    const status = result.status ?? 200;
    const body = result.body ?? null;
    return {
      status,
      ok: status >= 200 && status < 300,
      headers: { get: (name) => (name.toLowerCase() === 'content-type' ? 'application/json' : null) },
      json: async () => body,
      text: async () => JSON.stringify(body),
      blob: async () => body,
    };
  };
  fn.calls = calls;
  return fn;
}

export const APP_CONFIG = { logo: 'assets/logo.png', appName: 'ALI trade', apiBase: '/api' };
