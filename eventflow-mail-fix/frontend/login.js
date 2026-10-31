const loginForm = document.querySelector('#login-form');
const loginMessage = document.querySelector('#login-message');
const loginPassword = document.querySelector('#login-password');
const loginPasswordToggle = document.querySelector('.login-password-toggle');
const resendButton = document.querySelector('#resend-verification');
let authBusy = false;
if (new URLSearchParams(location.search).get('verified') === '1') {
  loginMessage.textContent = 'Почта подтверждена. Теперь можно войти.';
  history.replaceState(null, '', location.pathname);
}
loginPasswordToggle.addEventListener('click', () => {
  const show = loginPassword.type === 'password';
  loginPassword.type = show ? 'text' : 'password';
  loginPasswordToggle.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
});
async function authenticate(resend) {
  if (authBusy || !loginForm.reportValidity()) return;
  authBusy = true;
  const submit = loginForm.querySelector('[type="submit"]');
  submit.disabled = resendButton.disabled = true;
  const values = new FormData(loginForm);
  loginMessage.classList.remove('error');
  loginMessage.textContent = resend ? 'Отправляем письмо…' : 'Входим…';
  try {
    const result = await apiRequest(resend ? '/api/auth/resend-verification' : '/api/auth/login', {
      method: 'POST', body: { email: values.get('email'), password: values.get('password') },
    });
    if (resend) loginMessage.textContent = result.message;
    else window.location.href = 'dashboard.html';
  } catch (error) {
    loginMessage.classList.add('error');
    loginMessage.textContent = error.message;
  } finally {
    authBusy = false;
    submit.disabled = resendButton.disabled = false;
  }
}
loginForm.addEventListener('submit', (event) => { event.preventDefault(); authenticate(false); });
resendButton.addEventListener('click', () => authenticate(true));
