const form = document.querySelector('#login-form');
const message = document.querySelector('#login-message');
const submit = document.querySelector('#login-submit');
const password = document.querySelector('#password');
let busy = false;
document.querySelector('#password-toggle').addEventListener('click', (event) => {
  const show = password.type === 'password';
  password.type = show ? 'text' : 'password';
  event.currentTarget.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (busy || !form.reportValidity()) return;
  busy = true; submit.disabled = true; message.textContent = 'Входим…';
  try {
    await apiRequest('/api/auth/login', { method: 'POST', body: { login: form.elements.login.value.trim(), password: password.value } });
    sessionStorage.removeItem('sobralis.demo');
    password.value = '';
    location.href = 'dashboard.html';
  } catch (error) { message.textContent = error.message; }
  finally { busy = false; submit.disabled = false; }
});
