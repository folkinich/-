async function apiRequest(path, { method = 'GET', body } = {}) {
  const base = (window.EVENTFLOW_API_BASE_URL || '').replace(/\/$/, '');
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 25000);
  let response;
  let result;
  try {
    response = await fetch(`${base}${path}`, {
      method, credentials: 'include',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    try { result = text ? JSON.parse(text) : {}; }
    catch { throw new Error('Сервер вернул неожиданный ответ. Попробуйте позже.'); }
    if (!result || typeof result !== 'object' || Array.isArray(result)) {
      throw new Error('Сервер вернул неожиданный ответ. Попробуйте позже.');
    }
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Сервер долго не отвечает. Попробуйте ещё раз.');
    if (error instanceof TypeError) throw new Error('Не удалось связаться с сервером. Проверьте подключение и адрес API.');
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
  if (!response.ok) {
    const error = new Error(typeof result.error === 'string' ? result.error : 'Не удалось выполнить запрос.');
    error.status = response.status;
    error.code = result.code;
    throw error;
  }
  return result;
}
