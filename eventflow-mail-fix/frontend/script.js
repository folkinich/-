const roleOptions = document.querySelectorAll('.role-option');
const passwordInput = document.querySelector('#password');
const passwordToggle = document.querySelector('.toggle-password');
const signupForm = document.querySelector('#signup-form');
const formMessage = document.querySelector('#form-message');
let signupBusy = false;
function updateRole() {
  roleOptions.forEach((item) => item.classList.toggle('selected', item.querySelector('input').checked));
}
roleOptions.forEach((option) => option.addEventListener('change', updateRole));
passwordToggle.addEventListener('click', () => {
  const show = passwordInput.type === 'password';
  passwordInput.type = show ? 'text' : 'password';
  passwordToggle.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
});
function addLoginLink() {
  const link = document.createElement('a');
  link.href = 'login.html';
  link.className = 'login-link';
  link.textContent = ' Перейти ко входу';
  formMessage.append(link);
}
signupForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (signupBusy || !signupForm.reportValidity()) return;
  signupBusy = true;
  const submit = signupForm.querySelector('[type="submit"]');
  submit.disabled = true;
  const values = new FormData(signupForm);
  formMessage.classList.remove('error');
  formMessage.textContent = 'Создаём аккаунт и отправляем письмо…';
  try {
    const result = await apiRequest('/api/auth/register', {
      method: 'POST',
      body: { name: values.get('name'), email: values.get('email'), password: values.get('password'),
        role: values.get('role'), consent: values.get('consent') === 'on' },
    });
    formMessage.textContent = result.message;
    addLoginLink();
    signupForm.reset();
    passwordInput.type = 'password';
    passwordToggle.setAttribute('aria-label', 'Показать пароль');
    updateRole();
  } catch (error) {
    formMessage.classList.add('error');
    formMessage.textContent = error.message;
    if (error.code === 'verification_delivery_failed' || error.status === 409) addLoginLink();
  } finally {
    signupBusy = false;
    submit.disabled = false;
  }
});
