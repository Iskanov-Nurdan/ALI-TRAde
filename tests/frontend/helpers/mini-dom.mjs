/**
 * Минимальный DOM для запуска настоящих модулей фронтенда в Node без зависимостей.
 * Реализовано ровно то, что использует код в frontend/js: создание узлов,
 * подмножество CSS-селекторов, классы, dataset, события с всплытием,
 * MutationObserver (микрозадача), IntersectionObserver (управляется тестом),
 * localStorage, matchMedia, FormData, Image.
 *
 * Важно: семантика <select> смоделирована как в браузере — присваивание
 * select.value меняет только IDL-свойства (selectedIndex, option.selected)
 * и НЕ порождает мутаций атрибутов/детей. Это ключевой момент для теста 03.
 */

/* --------------------------- Разбор селекторов --------------------------- */

function parseCompound(text) {
  const part = { tag: null, id: null, classes: [], attrs: [], not: [] };
  let rest = text;
  while (rest.length) {
    let m;
    if ((m = rest.match(/^:not\(([^()]*)\)/))) {
      part.not.push(parseCompound(m[1].trim()));
    } else if ((m = rest.match(/^#([\w-]+)/))) {
      part.id = m[1];
    } else if ((m = rest.match(/^\.([\w-]+)/))) {
      part.classes.push(m[1]);
    } else if ((m = rest.match(/^\[([\w-]+)(?:([~^$*|]?=)"?([^\]"]*)"?)?\]/))) {
      part.attrs.push({ name: m[1], op: m[2] || null, value: m[3] });
    } else if ((m = rest.match(/^\*/))) {
      part.tag = null;
    } else if ((m = rest.match(/^[\w-]+/))) {
      part.tag = m[0].toUpperCase();
    } else {
      throw new Error(`mini-dom: не поддерживается селектор "${text}"`);
    }
    rest = rest.slice(m[0].length);
  }
  return part;
}

/** "a b > c, d" -> [[{part,comb}], ...] */
function parseSelector(selector) {
  return selector.split(',').map((group) => {
    const tokens = group.trim().split(/\s*(>)\s*|\s+/).filter(Boolean);
    const steps = [];
    let comb = 'descendant';
    tokens.forEach((token) => {
      if (token === '>') {
        comb = 'child';
        return;
      }
      steps.push({ part: parseCompound(token), comb });
      comb = 'descendant';
    });
    return steps;
  });
}

function matchesCompound(node, part) {
  if (node.nodeType !== 1) return false;
  if (part.tag && node.tagName !== part.tag) return false;
  if (part.id && node.getAttribute('id') !== part.id) return false;
  for (const cls of part.classes) if (!node.classList.contains(cls)) return false;
  for (const attr of part.attrs) {
    if (!node.hasAttribute(attr.name)) return false;
    if (attr.op === '=' && node.getAttribute(attr.name) !== attr.value) return false;
  }
  for (const n of part.not) if (matchesCompound(node, n)) return false;
  return true;
}

function matchesSteps(node, steps) {
  let index = steps.length - 1;
  if (!matchesCompound(node, steps[index].part)) return false;
  let current = node;
  index -= 1;
  while (index >= 0) {
    const comb = steps[index + 1].comb;
    if (comb === 'child') {
      current = current.parentNode;
      if (!current || current.nodeType !== 1 || !matchesCompound(current, steps[index].part)) return false;
    } else {
      let found = null;
      let walker = current.parentNode;
      while (walker && walker.nodeType === 1) {
        if (matchesCompound(walker, steps[index].part)) {
          found = walker;
          break;
        }
        walker = walker.parentNode;
      }
      if (!found) return false;
      current = found;
    }
    index -= 1;
  }
  return true;
}

/* ------------------------------ MutationObserver -------------------------- */

const observers = new Set();

function isInside(target, root, subtree) {
  if (target === root) return true;
  if (!subtree) return target.parentNode === root;
  let node = target;
  while (node) {
    if (node === root) return true;
    node = node.parentNode;
  }
  return false;
}

function notify(type, target, extra = {}) {
  observers.forEach((obs) => {
    obs.entries.forEach((entry) => {
      if (type === 'childList' && !entry.options.childList) return;
      if (type === 'attributes' && !entry.options.attributes) return;
      const relevant =
        type === 'childList'
          ? isInside(target, entry.root, entry.options.subtree)
          : isInside(target, entry.root, entry.options.subtree);
      if (!relevant) return;
      obs.queue.push({ type, target, addedNodes: extra.added || [], removedNodes: extra.removed || [] });
      obs.schedule();
    });
  });
}

export class MutationObserver {
  constructor(callback) {
    this.callback = callback;
    this.entries = [];
    this.queue = [];
    this.pending = false;
    observers.add(this);
  }
  observe(root, options = {}) {
    this.entries.push({ root, options });
  }
  disconnect() {
    observers.delete(this);
  }
  schedule() {
    if (this.pending) return;
    this.pending = true;
    queueMicrotask(() => {
      this.pending = false;
      const records = this.queue;
      this.queue = [];
      if (records.length) this.callback(records, this);
    });
  }
}

/* ---------------------------------- Узлы ---------------------------------- */

let ownerDocument = null;

class DomNode {
  constructor(nodeType) {
    this.nodeType = nodeType;
    this.parentNode = null;
    this.childNodes = [];
    this._listeners = new Map();
  }
  get children() {
    return this.childNodes.filter((node) => node.nodeType === 1);
  }
  get firstChild() {
    return this.childNodes[0] || null;
  }
  contains(node) {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parentNode;
    }
    return false;
  }
  _insert(node, before = null) {
    if (node.parentNode) node.parentNode.removeChild(node, true);
    const index = before ? this.childNodes.indexOf(before) : this.childNodes.length;
    this.childNodes.splice(index < 0 ? this.childNodes.length : index, 0, node);
    node.parentNode = this;
    notify('childList', this, { added: [node] });
    return node;
  }
  appendChild(node) {
    return this._insert(node);
  }
  insertBefore(node, before) {
    return this._insert(node, before);
  }
  removeChild(node, silent = false) {
    const index = this.childNodes.indexOf(node);
    if (index >= 0) {
      this.childNodes.splice(index, 1);
      node.parentNode = null;
      if (!silent) notify('childList', this, { removed: [node] });
    }
    return node;
  }
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
  _coerce(child) {
    return typeof child === 'string' || typeof child === 'number'
      ? ownerDocument.createTextNode(String(child))
      : child;
  }
  append(...children) {
    children.forEach((child) => this._insert(this._coerce(child)));
  }
  prepend(...children) {
    const first = this.childNodes[0] || null;
    children.forEach((child) => this._insert(this._coerce(child), first));
  }
  replaceChildren(...children) {
    const removed = this.childNodes.slice();
    removed.forEach((node) => {
      node.parentNode = null;
    });
    this.childNodes = [];
    children.forEach((child) => {
      const node = this._coerce(child);
      if (node.parentNode) node.parentNode.removeChild(node, true);
      this.childNodes.push(node);
      node.parentNode = this;
    });
    notify('childList', this, { added: this.childNodes.slice(), removed });
  }
  _walk(out = []) {
    this.childNodes.forEach((child) => {
      out.push(child);
      if (child._walk) child._walk(out);
    });
    return out;
  }
  querySelectorAll(selector) {
    const groups = parseSelector(selector);
    return this._walk().filter(
      (node) => node.nodeType === 1 && groups.some((steps) => matchesSteps(node, steps))
    );
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  addEventListener(type, handler) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(handler);
  }
  removeEventListener(type, handler) {
    const list = this._listeners.get(type);
    if (list) this._listeners.set(type, list.filter((item) => item !== handler));
  }
  dispatchEvent(event) {
    event.target = event.target || this;
    const path = [];
    let node = this;
    while (node) {
      path.push(node);
      node = node.parentNode;
    }
    if (!path.includes(ownerDocument)) path.push(ownerDocument);
    path.forEach((current) => {
      if (event.cancelBubble && current !== this) return;
      (current._listeners.get(event.type) || []).slice().forEach((handler) => {
        event.currentTarget = current;
        handler.call(current, event);
      });
    });
    return !event.defaultPrevented;
  }
  get textContent() {
    return this.childNodes.map((node) => node.textContent).join('');
  }
  set textContent(value) {
    this.childNodes.forEach((node) => {
      node.parentNode = null;
    });
    this.childNodes = [];
    if (value !== '') this.childNodes.push(Object.assign(ownerDocument.createTextNode(String(value)), { parentNode: this }));
  }
}

class DomText extends DomNode {
  constructor(text) {
    super(3);
    this.data = String(text);
  }
  get textContent() {
    return this.data;
  }
  set textContent(value) {
    this.data = String(value);
  }
  querySelectorAll() {
    return [];
  }
}

const camel = (name) => name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
const dashed = (name) => name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);

class DomElement extends DomNode {
  constructor(tagName) {
    super(1);
    this.tagName = String(tagName).toUpperCase();
    this.attributes = new Map();
    this.style = {
      _props: new Map(),
      setProperty(name, value) {
        this._props.set(name, value);
      },
      getPropertyValue(name) {
        return this._props.get(name) || '';
      },
    };
    const self = this;
    this.classList = {
      contains: (name) => self._classes().includes(name),
      add: (...names) => self._setClasses([...new Set([...self._classes(), ...names])]),
      remove: (...names) => self._setClasses(self._classes().filter((item) => !names.includes(item))),
      toggle: (name, force) => {
        const has = self._classes().includes(name);
        const next = force === undefined ? !has : Boolean(force);
        if (next) self.classList.add(name);
        else self.classList.remove(name);
        return next;
      },
      get value() {
        return self.getAttribute('class') || '';
      },
    };
    this.dataset = new Proxy(
      {},
      {
        get: (_, key) => (typeof key === 'string' ? self.getAttribute(`data-${dashed(key)}`) ?? undefined : undefined),
        set: (_, key, value) => {
          self.setAttribute(`data-${dashed(key)}`, String(value));
          return true;
        },
        has: (_, key) => self.hasAttribute(`data-${dashed(key)}`),
        deleteProperty: (_, key) => {
          self.removeAttribute(`data-${dashed(key)}`);
          return true;
        },
        ownKeys: () =>
          [...self.attributes.keys()].filter((k) => k.startsWith('data-')).map((k) => camel(k.slice(5))),
        getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }),
      }
    );
  }
  _classes() {
    return (this.getAttribute('class') || '').split(/\s+/).filter(Boolean);
  }
  _setClasses(list) {
    this.setAttribute('class', list.join(' '));
  }
  get className() {
    return this.getAttribute('class') || '';
  }
  set className(value) {
    this.setAttribute('class', value);
  }
  get id() {
    return this.getAttribute('id') || '';
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    notify('attributes', this, {});
  }
  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }
  hasAttribute(name) {
    return this.attributes.has(name);
  }
  removeAttribute(name) {
    this.attributes.delete(name);
    notify('attributes', this, {});
  }
  get hidden() {
    return this.hasAttribute('hidden');
  }
  set hidden(value) {
    if (value) this.setAttribute('hidden', '');
    else this.removeAttribute('hidden');
  }
  set innerHTML(value) {
    this._innerHTML = String(value);
    this.childNodes.forEach((node) => {
      node.parentNode = null;
    });
    this.childNodes = [];
  }
  get innerHTML() {
    return this._innerHTML || '';
  }
  get outerHTML() {
    const attrs = [...this.attributes].map(([k, v]) => ` ${k}="${v}"`).join('');
    return `<${this.tagName.toLowerCase()}${attrs}>`;
  }
  closest(selector) {
    let node = this;
    const groups = parseSelector(selector);
    while (node && node.nodeType === 1) {
      if (groups.some((steps) => matchesSteps(node, steps))) return node;
      node = node.parentNode;
    }
    return null;
  }
  focus() {
    ownerDocument.activeElement = this;
  }
  blur() {
    if (ownerDocument.activeElement === this) ownerDocument.activeElement = ownerDocument.body;
  }
  getBoundingClientRect() {
    return { top: 0, left: 0, right: 100, bottom: 30, width: 100, height: 30 };
  }
  scrollIntoView() {}
  get disabled() {
    return this.hasAttribute('disabled');
  }
  set disabled(value) {
    if (value) this.setAttribute('disabled', '');
    else this.removeAttribute('disabled');
  }
  get checked() {
    return Boolean(this._checked);
  }
  set checked(value) {
    this._checked = Boolean(value);
  }
  /* --- select / option --- */
  get options() {
    return this.querySelectorAll('option');
  }
  get multiple() {
    return this.hasAttribute('multiple');
  }
  get selected() {
    if (this.tagName !== 'OPTION') return undefined;
    const select = this.closest('select');
    if (!select) return this.hasAttribute('selected');
    return select.options[select.selectedIndex] === this;
  }
  get selectedIndex() {
    if (this.tagName !== 'SELECT') return undefined;
    if (this._selectedIndex === undefined) return this.options.length ? 0 : -1;
    return this._selectedIndex;
  }
  set selectedIndex(index) {
    this._selectedIndex = index;
  }
  get value() {
    if (this.tagName === 'SELECT') {
      const option = this.options[this.selectedIndex];
      return option ? (option.hasAttribute('value') ? option.getAttribute('value') : option.textContent) : '';
    }
    if (this.tagName === 'OPTION') {
      return this.hasAttribute('value') ? this.getAttribute('value') : this.textContent;
    }
    return this._value === undefined ? this.getAttribute('value') || '' : this._value;
  }
  set value(next) {
    if (this.tagName === 'SELECT') {
      // Как в браузере: меняются только IDL-свойства, ни один атрибут не трогается,
      // событие change не отправляется, MutationObserver ничего не видит.
      const options = this.options;
      const index = options.findIndex((option) => option.value === String(next));
      this._selectedIndex = index;
      return;
    }
    this._value = String(next);
  }
  get elements() {
    if (this.tagName !== 'FORM') return undefined;
    const map = {};
    this.querySelectorAll('input, select, textarea, button').forEach((node) => {
      const name = node.getAttribute('name');
      const id = node.getAttribute('id');
      if (name && !map[name]) map[name] = node;
      if (id && !map[id]) map[id] = node;
    });
    return map;
  }
  reset() {}
}

/* ------------------------------ Разбор HTML ------------------------------- */

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);

function parseHtml(html, doc) {
  const root = doc.createElement('root');
  const stack = [root];
  let index = 0;
  const decode = (text) =>
    text.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)));

  while (index < html.length) {
    const lt = html.indexOf('<', index);
    if (lt < 0) break;
    if (lt > index) {
      const text = html.slice(index, lt);
      if (text.trim()) stack[stack.length - 1].append(doc.createTextNode(decode(text)));
    }
    if (html.startsWith('<!--', lt)) {
      index = html.indexOf('-->', lt) + 3;
      continue;
    }
    if (html.startsWith('<!', lt)) {
      index = html.indexOf('>', lt) + 1;
      continue;
    }
    const gt = html.indexOf('>', lt);
    if (gt < 0) break;
    const raw = html.slice(lt + 1, gt);
    if (raw.startsWith('/')) {
      const name = raw.slice(1).trim().toLowerCase();
      for (let i = stack.length - 1; i > 0; i -= 1) {
        if (stack[i].tagName.toLowerCase() === name) {
          stack.length = i;
          break;
        }
      }
      index = gt + 1;
      continue;
    }
    const nameMatch = raw.match(/^([\w:-]+)/);
    const tag = nameMatch[1].toLowerCase();
    const node = doc.createElement(tag);
    const attrRe = /([\w:@.-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
    let attrMatch;
    const attrSource = raw.slice(nameMatch[0].length);
    while ((attrMatch = attrRe.exec(attrSource))) {
      node.setAttribute(attrMatch[1], decode(attrMatch[2] ?? attrMatch[3] ?? attrMatch[4] ?? ''));
    }
    stack[stack.length - 1].append(node);
    index = gt + 1;
    if (tag === 'script' || tag === 'style') {
      const end = html.indexOf(`</${tag}`, index);
      if (end >= 0) index = html.indexOf('>', end) + 1;
      continue;
    }
    if (!VOID.has(tag) && !raw.endsWith('/')) stack.push(node);
  }
  return root;
}

/* -------------------------------- Документ -------------------------------- */

class DomDocument extends DomNode {
  constructor() {
    super(9);
    ownerDocument = this;
    this.documentElement = new DomElement('html');
    this.body = new DomElement('body');
    this.head = new DomElement('head');
    this.documentElement.append(this.head, this.body);
    this.append(this.documentElement);
    this.title = '';
    this.activeElement = this.body;
  }
  createElement(tag) {
    return new DomElement(tag);
  }
  createElementNS(_ns, tag) {
    return new DomElement(tag);
  }
  createTextNode(text) {
    return new DomText(text);
  }
}

/* ------------------------------ Прочие заглушки --------------------------- */

class FakeStorage {
  constructor(initial = {}) {
    this.map = new Map(Object.entries(initial));
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  setItem(key, value) {
    this.map.set(key, String(value));
  }
  removeItem(key) {
    this.map.delete(key);
  }
  clear() {
    this.map.clear();
  }
}

class FakeIntersectionObserver {
  constructor(callback) {
    this.callback = callback;
    this.targets = new Set();
    FakeIntersectionObserver.instances.push(this);
  }
  observe(node) {
    this.targets.add(node);
  }
  unobserve(node) {
    this.targets.delete(node);
  }
  disconnect() {
    this.targets.clear();
  }
  /** Тест сам решает, что попало в область видимости. */
  trigger(nodes = [...this.targets]) {
    this.callback(nodes.map((target) => ({ target, isIntersecting: true })), this);
  }
}
FakeIntersectionObserver.instances = [];

class FakeEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = Boolean(options.bubbles);
    this.defaultPrevented = false;
    this.cancelBubble = false;
    this.target = null;
  }
  preventDefault() {
    this.defaultPrevented = true;
  }
  stopPropagation() {
    this.cancelBubble = true;
  }
}

class FakeFormData {
  constructor(form) {
    this.map = new Map();
    if (form) {
      form.querySelectorAll('input, select, textarea').forEach((node) => {
        const name = node.getAttribute('name');
        if (!name) return;
        if (node.getAttribute('type') === 'checkbox' && !node.checked) return;
        this.map.set(name, node.value);
      });
    }
  }
  get(name) {
    return this.map.has(name) ? this.map.get(name) : null;
  }
  entries() {
    return this.map.entries();
  }
  [Symbol.iterator]() {
    return this.map.entries();
  }
}

/**
 * Ставит глобальное окружение. Возвращает ручки для управления из теста.
 * @param {{html?: string, storage?: object, media?: object}} options
 */
export function installDom({ html = '', storage = {}, media = {} } = {}) {
  const doc = new DomDocument();

  if (html) {
    const titleMatch = html.match(/<title>([\s\S]*?)<\/title>/i);
    if (titleMatch) doc.title = titleMatch[1].trim();
    const bodyMatch = html.match(/<body([^>]*)>([\s\S]*)<\/body>/i);
    const bodyHtml = bodyMatch ? bodyMatch[2] : html;
    if (bodyMatch) {
      const classMatch = bodyMatch[1].match(/class="([^"]*)"/);
      if (classMatch) doc.body.className = classMatch[1];
    }
    const parsed = parseHtml(bodyHtml, doc);
    parsed.childNodes.slice().forEach((node) => doc.body.append(node));
  }

  const mediaState = new Map(Object.entries(media));
  const mediaLists = new Map();

  const win = globalThis;
  win.window = win;
  win.document = doc;
  win.localStorage = new FakeStorage(storage);
  win.sessionStorage = new FakeStorage();
  win.MutationObserver = MutationObserver;
  win.IntersectionObserver = FakeIntersectionObserver;
  win.Event = FakeEvent;
  win.FormData = FakeFormData;
  win.Node = DomNode;
  win.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  win.cancelAnimationFrame = (id) => clearTimeout(id);
  win.innerHeight = 800;
  win.innerWidth = 1280;
  // Слушатели самого окна: select.js вешает сюда scroll и resize.
  // Фаза перехвата не моделируется — обработчик просто получает событие,
  // как получил бы в браузере, а разбор target остаётся на его совести.
  const winListeners = new Map();
  win.addEventListener = (type, handler) => {
    if (!winListeners.has(type)) winListeners.set(type, []);
    winListeners.get(type).push(handler);
  };
  win.removeEventListener = (type, handler) => {
    const list = winListeners.get(type);
    if (list) winListeners.set(type, list.filter((item) => item !== handler));
  };
  win.dispatchEvent = (event) => {
    (winListeners.get(event.type) || []).slice().forEach((handler) => handler(event));
    return true;
  };
  win.confirm = () => true;
  win.matchMedia = (query) => {
    if (mediaLists.has(query)) return mediaLists.get(query);
    const list = {
      media: query,
      get matches() {
        return Boolean(mediaState.get(query));
      },
      listeners: [],
      addEventListener(_type, handler) {
        this.listeners.push(handler);
      },
      removeEventListener(_type, handler) {
        this.listeners = this.listeners.filter((item) => item !== handler);
      },
      addListener(handler) {
        this.listeners.push(handler);
      },
    };
    mediaLists.set(query, list);
    return list;
  };
  win.location = {
    pathname: '/dashboard.html',
    search: '',
    href: 'http://localhost/dashboard.html',
    assign(url) {
      this.href = url;
    },
  };
  win.history = { replaceState() {} };
  win.URL = globalThis.URL;
  win.Image = class {
    constructor() {
      this._listeners = {};
    }
    addEventListener(type, handler) {
      (this._listeners[type] = this._listeners[type] || []).push(handler);
    }
    set src(value) {
      this._src = value;
    }
    get src() {
      return this._src;
    }
    fire(type) {
      (this._listeners[type] || []).forEach((handler) => handler());
    }
  };

  return {
    document: doc,
    window: win,
    storage: win.localStorage,
    setMedia(query, value) {
      mediaState.set(query, value);
      const list = mediaLists.get(query);
      if (list) list.listeners.forEach((handler) => handler({ matches: value, media: query }));
    },
    intersectionObservers: FakeIntersectionObserver.instances,
    flush: () => new Promise((resolve) => setTimeout(resolve, 0)),
  };
}

export const FRONTEND = new URL('../../../frontend/', import.meta.url).href;
