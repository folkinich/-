(() => {
  const demoKey = 'sobralis.demo';
  const registrationKey = 'sobralis.demo.registrations.v1';
  const params = new URLSearchParams(location.search);
  if (params.get('demo') === '1') {
    sessionStorage.setItem(demoKey, '1');
    history.replaceState(null, '', location.pathname + location.hash);
  }
  const demo = sessionStorage.getItem(demoKey) === '1';
  let events = [], activities = [], registrations = [];
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const fail = (message) => { throw new Error(message); };
  function readDemoRegistrations() {
    let saved;
    try { saved = localStorage.getItem(registrationKey); }
    catch { return fail('Браузер запретил локальное хранилище. Разреши его для демоверсии.'); }
    if (saved === null) {
      const initial = ['a11', 'a31'];
      localStorage.setItem(registrationKey, JSON.stringify(initial));
      return initial;
    }
    try {
      const value = JSON.parse(saved);
      if (!Array.isArray(value) || value.some((id) => typeof id !== 'string')) throw new Error();
      return [...new Set(value)].filter((id) => activities.some((activity) => activity.id === id));
    } catch { return fail('Данные демоверсии повреждены. Удали ключ sobralis.demo.registrations.v1 в хранилище браузера.'); }
  }
  function saveDemo(next) {
    try { localStorage.setItem(registrationKey, JSON.stringify(next)); }
    catch { return fail('Не получилось сохранить запись в браузере. Проверь доступ к хранилищу.'); }
    registrations = next;
  }
  async function refreshRegistrations() {
    if (demo) registrations = readDemoRegistrations();
    else {
      const result = await apiRequest('/api/registrations');
      if (!Array.isArray(result.registrations)) return fail('Сервер вернул некорректное расписание.');
      registrations = result.registrations.map((item) => String(item.activityId));
    }
  }
  async function load() {
    let user;
    if (demo) {
      ({ events, activities } = clone(window.EVENTFLOW_DEMO_DATA));
      user = clone(window.EVENTFLOW_DEMO_DATA.user);
    } else {
      const profile = await apiRequest('/api/auth/me');
      user = profile.user;
      const [eventData, activityData] = await Promise.all([apiRequest('/api/events'), apiRequest('/api/activities')]);
      if (!Array.isArray(eventData.events) || !Array.isArray(activityData.activities)) return fail('Сервер вернул некорректную программу.');
      events = eventData.events.map((event) => ({ ...event, id: String(event.id) }));
      activities = activityData.activities.map((activity) => ({ ...activity, id: String(activity.id), eventId: String(activity.eventId) }));
    }
    if (!user || typeof user.name !== 'string') return fail('Не удалось прочитать профиль пользователя.');
    await refreshRegistrations();
    return user;
  }
  const enrolled = (id) => registrations.includes(String(id));
  function freeSeats(activity) {
    // taken includes other demo participants; the real API returns current available seats.
    return Math.max(0, demo ? activity.capacity - activity.taken - Number(enrolled(activity.id)) : activity.availableSeats);
  }
  function conflict(activity) {
    return activities.find((other) => other.id !== activity.id && enrolled(other.id)
      && Date.parse(activity.start) < Date.parse(other.end) && Date.parse(other.start) < Date.parse(activity.end));
  }
  async function register(id) {
    const activity = activities.find((item) => item.id === id);
    if (!activity) return fail('Активность не найдена.');
    if (demo) {
      registrations = readDemoRegistrations();
      if (enrolled(id)) return fail('Эта активность уже в твоём расписании.');
      if (!freeSeats(activity)) return fail('Свободные места закончились.');
      const overlap = conflict(activity);
      if (overlap) return fail(`В это время у тебя «${overlap.title}». Выбери другую активность или отмени прежнюю запись.`);
      saveDemo([...registrations, id]);
    } else {
      await apiRequest(`/api/activities/${encodeURIComponent(id)}/registrations`, { method: 'POST', body: {} });
      await load();
    }
  }
  async function cancel(id) {
    if (demo) {
      registrations = readDemoRegistrations();
      saveDemo(registrations.filter((item) => item !== id));
    } else {
      await apiRequest(`/api/activities/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: {} });
      await load();
    }
  }
  async function logout() {
    if (demo) sessionStorage.removeItem(demoKey);
    else await apiRequest('/api/auth/logout', { method: 'POST', body: {} });
  }
  window.EventFlowStore = { demo, load, register, cancel, logout, enrolled, freeSeats, conflict, refreshRegistrations,
    get events() { return events; }, get activities() { return activities; },
    get selected() { return activities.filter((activity) => enrolled(activity.id)).sort((a, b) => Date.parse(a.start) - Date.parse(b.start)); } };
})();
