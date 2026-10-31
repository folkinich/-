const store = window.EventFlowStore;
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
// Reuse ICU formatters: constructing one for every time/date delays opening the dialog.
const formatters = new Map();
const format = (value, options) => {
  const key = JSON.stringify(options);
  if (!formatters.has(key)) formatters.set(key, new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', ...options }));
  return formatters.get(key).format(new Date(value));
};
const time = (value) => format(value, { hour: '2-digit', minute: '2-digit' });
const dayFormatter = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' });
const dayKey = (value) => {
  const parts = dayFormatter.formatToParts(new Date(value));
  return ['year', 'month', 'day'].map((name) => parts.find((part) => part.type === name).value).join('-');
};
const dateValue = (date) => `${date}T12:00:00+03:00`;
const dateLabel = (date) => format(dateValue(date), { day: 'numeric', month: 'long' });
const safeColor = (value, fallback) => /^#[0-9a-f]{6}$/i.test(value || '') ? value : fallback;
let category = 'Все события';
let scheduleDay = 'all';
let currentEvent = null;
let pendingCancel = null;
let actionBusy = false;
let toastTimer;
const dialog = $('#event-dialog');
const cancelDialog = $('#cancel-dialog');

function syncModalState() {
  document.documentElement.classList.toggle('modal-open', Boolean(document.querySelector('dialog[open]')));
}
function showDialog(modal) {
  if (!modal.open) modal.showModal();
  syncModalState();
}
for (const modal of [dialog, cancelDialog]) modal.addEventListener('close', syncModalState);

function notify(message) {
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500);
}
function eventById(id) { return store.events.find((event) => event.id === id); }
function eventActivities(id) { return store.activities.filter((activity) => activity.eventId === id).sort((a, b) => Date.parse(a.start) - Date.parse(b.start)); }
function cover(event, extraClass = '') {
  const art = ['rings', 'spark', 'blocks'].includes(event.art) ? event.art : 'rings';
  return `<div class="event-cover ${extraClass}" style="--cover:${safeColor(event.color, '#dfebd5')};--cover-ink:${safeColor(event.ink, '#4c7444')}"><span class="cover-label">${esc(event.coverLabel || event.category)}</span><div class="cover-heading">${esc(event.coverTitle || event.title).replace(/\n/g, '<br>')}</div><span class="cover-art ${art}" aria-hidden="true">${art === 'spark' ? '✳' : ''}</span><span class="cover-index">СОБРАЛИСЬ · 2026</span></div>`;
}
function renderCategories() {
  const categories = ['Все события', ...new Set(store.events.map((event) => event.category))];
  if (!categories.includes(category)) category = categories[0];
  $('#category-filters').innerHTML = categories.map((name) => `<button type="button" class="chip ${name === category ? 'active' : ''}" data-category="${esc(name)}" aria-pressed="${name === category}">${esc(name)}</button>`).join('');
}
function renderEvents() {
  const query = $('#event-search').value.trim().toLocaleLowerCase('ru');
  let events = store.events.filter((event) => (category === 'Все события' || event.category === category)
    && [event.title, event.description, event.location].join(' ').toLocaleLowerCase('ru').includes(query));
  events.sort($('#event-sort').value === 'name' ? (a, b) => a.title.localeCompare(b.title, 'ru') : (a, b) => a.date.localeCompare(b.date));
  $('#event-count').textContent = events.length;
  $('#events-empty').hidden = events.length !== 0;
  $('#events-grid').innerHTML = events.map((event) => {
    const activities = eventActivities(event.id);
    const hasPlaces = activities.some((activity) => store.freeSeats(activity) > 0);
    const own = activities.some((activity) => store.enrolled(activity.id));
    return `<article class="event-card">${cover(event)}<div class="event-card-body"><div class="event-category-row"><span class="category-tag">${esc(event.category)}</span><span class="event-day">${esc(dateLabel(event.date))}</span></div><h3>${esc(event.title)}</h3><p class="event-description">${esc(event.description)}</p><span class="event-location">${icon('pin')}${esc(event.location)}</span><div class="event-card-footer"><button type="button" class="card-program" data-event="${esc(event.id)}" aria-label="Программа: ${esc(event.title)}">Программа события <span><span class="arrow-glyph" aria-hidden="true"></span></span></button><span class="card-status ${!hasPlaces && !own ? 'full-status' : ''}">${own ? icon('check') + 'Ты участвуешь' : hasPlaces ? '<i class="status-dot"></i>Есть места' : 'Мест пока нет'}</span></div></div></article>`;
  }).join('');
}
function renderNext() {
  const activity = store.selected.find((item) => Date.parse(item.end) > Date.now());
  if (!activity) {
    $('#next-activity').innerHTML = '<div class="next-no-plan"><span class="small-spark">✳</span><p>Впереди столько интересного.<br>Добавь первый план в расписание.</p></div>';
    return;
  }
  $('#next-activity').innerHTML = `<div class="next-date"><span class="date-square">${esc(format(activity.start, { day: '2-digit' }))}</span><span>${esc(format(activity.start, { month: 'long' }))}<br>${esc(format(activity.start, { weekday: 'long' }))}</span></div><h3>${esc(activity.title)}</h3><p class="next-meta">${icon('clock')}${esc(time(activity.start))}–${esc(time(activity.end))}</p><p class="next-meta">${icon('pin')}${esc(activity.room)}</p>`;
}
function renderSchedule() {
  const selected = store.selected;
  $('#schedule-count').textContent = selected.length;
  $('#summary-count').textContent = selected.length;
  const dates = [...new Set(selected.map((activity) => dayKey(activity.start)))].sort();
  if (scheduleDay !== 'all' && !dates.includes(scheduleDay)) scheduleDay = 'all';
  $('#schedule-days').innerHTML = [{ id: 'all', title: 'Все дни' }, ...dates.map((date) => ({ id: date, title: dateLabel(date) }))].map((day) => `<button type="button" class="chip ${scheduleDay === day.id ? 'active' : ''}" data-day="${esc(day.id)}" aria-pressed="${scheduleDay === day.id}">${esc(day.title)}</button>`).join('');
  const visible = selected.filter((activity) => scheduleDay === 'all' || dayKey(activity.start) === scheduleDay);
  $('#schedule-empty').hidden = visible.length !== 0;
  let previousDay = '';
  $('#schedule-list').innerHTML = visible.map((activity) => {
    const event = eventById(activity.eventId);
    const date = dayKey(activity.start);
    let heading = '';
    if (date !== previousDay) heading = `<h2 class="schedule-day-heading">${esc(format(activity.start, { day: 'numeric', month: 'long', weekday: 'long' }))}</h2>`;
    previousDay = date;
    return `${heading}<article class="schedule-item" data-schedule-activity="${esc(activity.id)}"><div class="schedule-time"><b>${esc(time(activity.start))}</b><small>до ${esc(time(activity.end))}</small></div><div class="schedule-stripe" style="--stripe:${safeColor(event?.ink, '#94ba79')}"></div><div><h3>${esc(activity.title)}</h3><button type="button" class="schedule-event-link" data-event="${esc(activity.eventId)}">${esc(event?.title || 'Программа события')} <span class="arrow-glyph" aria-hidden="true"></span></button><div class="schedule-location">${icon('pin')}${esc(activity.room)}</div></div><div class="schedule-item-actions"><span class="registered-badge">${icon('check')}Ты записан</span><button type="button" class="cancel-button" data-cancel="${esc(activity.id)}">Отменить запись</button></div></article>`;
  }).join('');
}
function renderAll() {
  renderCategories(); renderEvents(); renderSchedule(); renderNext();
}
function navigate() {
  const schedule = location.hash === '#schedule';
  $('#events-view').hidden = schedule;
  $('#schedule-view').hidden = !schedule;
  for (const [id, active] of [['events', !schedule], ['schedule', schedule]]) {
    $(`#nav-${id}`).classList.toggle('active', active);
    if (active) $(`#nav-${id}`).setAttribute('aria-current', 'page');
    else $(`#nav-${id}`).removeAttribute('aria-current');
  }
  $('#breadcrumb-current').textContent = schedule ? 'Моё расписание' : 'События';
  document.title = `${schedule ? 'Моё расписание' : 'События'} — Собрались`;
  if (dialog.open) dialog.close();
  if (cancelDialog.open) cancelDialog.close();
  if (location.hash === '#catalog') requestAnimationFrame(() => $('#catalog').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }));
  else window.scrollTo(0, 0);
}
function renderDialog() {
  const event = eventById(currentEvent);
  if (!event) return;
  $('#dialog-content').innerHTML = `${cover(event, 'dialog-cover')}<span class="category-tag">${esc(event.category)}</span><h2 id="dialog-title" class="dialog-title">${esc(event.title)}</h2><p class="dialog-description">${esc(event.description)}</p><div class="dialog-meta"><span>${icon('calendar')}${esc(dateLabel(event.date))}</span><span>${icon('pin')}${esc(event.location)}</span></div><h3 class="dialog-program-title">Программа</h3><p class="dialog-program-hint">Запишись на отдельные активности. Время указано по Москве.</p>${eventActivities(event.id).map((activity) => {
    const mine = store.enrolled(activity.id);
    const free = store.freeSeats(activity);
    const overlap = !mine && store.conflict(activity);
    return `<article class="activity-card" data-activity="${esc(activity.id)}"><span class="activity-time">${esc(time(activity.start))}–${esc(time(activity.end))}</span><h4>${esc(activity.title)}</h4><p>${esc(activity.description)}</p><span class="next-meta">${icon('pin')}${esc(activity.room)}</span><div class="activity-footer"><span class="seats ${free <= 3 ? 'low' : ''}">${free} из ${esc(activity.capacity)} мест свободно</span><button type="button" data-register="${esc(activity.id)}" class="button ${mine ? 'registered' : free === 0 ? 'sold-out' : 'primary'}" ${mine || free === 0 ? 'disabled' : ''}>${mine ? '✓ Ты записан' : free === 0 ? 'Мест нет' : 'Записаться <span class="arrow-glyph" aria-hidden="true"></span>'}</button></div>${overlap ? `<div class="activity-conflict">Пересекается с твоим планом «${esc(overlap.title)}».</div>` : ''}</article>`;
  }).join('')}`;
}
function openEvent(id) {
  if (!eventById(id)) return;
  currentEvent = id;
  $('#dialog-message').textContent = '';
  renderDialog();
  showDialog(dialog);
}
function openCancel(id) {
  const activity = store.selected.find((item) => item.id === id);
  if (!activity) return;
  pendingCancel = id;
  $('#cancel-description').textContent = `«${activity.title}», ${dateLabel(dayKey(activity.start))}, ${time(activity.start)}.`;
  $('#cancel-message').textContent = '';
  showDialog(cancelDialog);
  $('#keep-registration').focus();
}
async function register(id, button) {
  if (actionBusy) return;
  actionBusy = true; button.disabled = true;
  $('#dialog-message').textContent = 'Сохраняем запись…';
  try {
    await store.register(id);
    renderAll(); renderDialog();
    $('#dialog-message').textContent = '';
    notify('Ты записан! Активность добавлена в расписание.');
  } catch (error) {
    $('#dialog-message').textContent = error.message;
    button.disabled = false;
    if (error.status === 401) location.href = 'login.html';
  } finally { actionBusy = false; }
}
async function cancelRegistration() {
  if (actionBusy || !pendingCancel) return;
  actionBusy = true;
  $('#confirm-cancel').disabled = $('#keep-registration').disabled = true;
  try {
    await store.cancel(pendingCancel);
    pendingCancel = null;
    cancelDialog.close(); renderAll();
    notify('Запись отменена. Место снова свободно.');
  } catch (error) {
    $('#cancel-message').textContent = error.message;
    if (error.status === 401) location.href = 'login.html';
  } finally {
    actionBusy = false;
    $('#confirm-cancel').disabled = $('#keep-registration').disabled = false;
  }
}
async function load() {
  $('#loading-state').hidden = false;
  $('#error-state').hidden = true;
  $('#app-content').hidden = true;
  try {
    const user = await store.load();
    $('#user-name').textContent = user.name;
    $('#user-avatar').textContent = user.name.trim().slice(0, 1).toLocaleUpperCase('ru') || 'У';
    $('#user-role').textContent = store.demo ? 'Демоверсия' : user.role === 'organizer' ? 'Организатор' : 'Участник';
    $('#demo-banner').hidden = !store.demo;
    const firstDate = [...store.events].sort((a, b) => a.date.localeCompare(b.date))[0]?.date;
    $('#month-label').textContent = firstDate ? format(dateValue(firstDate), { month: 'long', year: 'numeric' }) : 'События';
    if (firstDate) {
      $('.hero-ticket b').textContent = format(dateValue(firstDate), { day: '2-digit' });
      const ticketMonth = document.createElement('span');
      ticketMonth.textContent = format(dateValue(firstDate), { month: 'long' }).toLocaleUpperCase('ru');
      const ticketDay = document.createElement('span');
      ticketDay.textContent = format(dateValue(firstDate), { weekday: 'long' }).toLocaleUpperCase('ru');
      $('.hero-ticket small').replaceChildren(ticketMonth, document.createElement('br'), ticketDay);
    }
    renderAll(); navigate(); $('#app-content').hidden = false;
  } catch (error) {
    if (error.status === 401) location.replace('login.html');
    else { $('#load-error').textContent = error.message; $('#error-state').hidden = false; }
  } finally { $('#loading-state').hidden = true; }
}
document.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (button?.dataset.event) openEvent(button.dataset.event);
  if (button?.dataset.cancel) openCancel(button.dataset.cancel);
  if (button?.dataset.register) register(button.dataset.register, button);
  if (button?.dataset.category) { category = button.dataset.category; renderCategories(); renderEvents(); }
  if (button?.dataset.day) { scheduleDay = button.dataset.day; renderSchedule(); }
  const profile = $('.profile-menu');
  if (!profile.contains(event.target)) profile.open = false;
});
$('#event-search').addEventListener('input', renderEvents);
$('#event-sort').addEventListener('change', renderEvents);
$('#reset-filters').addEventListener('click', () => { category = 'Все события'; $('#event-search').value = ''; renderCategories(); renderEvents(); });
$('#close-dialog').addEventListener('click', () => dialog.close());
$('#keep-registration').addEventListener('click', () => cancelDialog.close());
$('#confirm-cancel').addEventListener('click', cancelRegistration);
for (const modal of [dialog, cancelDialog]) modal.addEventListener('click', (event) => {
  const rect = modal.getBoundingClientRect();
  if (!actionBusy && event.target === modal && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) modal.close();
});
$('#retry-load').addEventListener('click', load);
$('#logout-button').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try { await store.logout(); location.href = 'login.html'; }
  catch (error) { notify(error.message); button.disabled = false; }
});
window.addEventListener('hashchange', navigate);
window.addEventListener('storage', async (event) => {
  if (store.demo && event.key === 'sobralis.demo.registrations.v1') {
    try { await store.refreshRegistrations(); renderAll(); if (dialog.open) renderDialog(); }
    catch (error) { notify(error.message); }
  }
});
load();
