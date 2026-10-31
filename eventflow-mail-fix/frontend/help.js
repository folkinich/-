const supportForm = document.querySelector('#support-form');
const supportFeedback = document.querySelector('#support-feedback');
let supportBusy = false;
supportForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (supportBusy || !supportForm.reportValidity()) return;
  supportBusy = true;
  const submit = supportForm.querySelector('[type="submit"]');
  submit.disabled = true;
  const values = new FormData(supportForm);
  supportFeedback.classList.remove('error');
  supportFeedback.textContent = 'Отправляем…';
  try {
    const result = await apiRequest('/api/support', { method: 'POST',
      body: { email: values.get('email'), message: values.get('message') } });
    supportFeedback.textContent = result.message;
    supportForm.reset();
  } catch (error) {
    supportFeedback.classList.add('error');
    supportFeedback.textContent = error.message;
  } finally {
    supportBusy = false;
    submit.disabled = false;
  }
});
