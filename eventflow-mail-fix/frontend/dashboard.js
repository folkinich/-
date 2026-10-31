const slides = [...document.querySelectorAll('.welcome-slide')];
const dots = [...document.querySelectorAll('.slider-dot')];
const userName = document.querySelector('#user-name');
const userRole = document.querySelector('#user-role');
const userAvatar = document.querySelector('#user-avatar');
let currentSlide = 0;
let slideTimer;

function showSlide(index) {
  currentSlide = (index + slides.length) % slides.length;
  slides.forEach((slide, i) => {
    slide.classList.toggle('active', i === currentSlide);
    slide.setAttribute('aria-hidden', String(i !== currentSlide));
    dots[i].classList.toggle('active', i === currentSlide);
    dots[i].setAttribute('aria-selected', String(i === currentSlide));
  });
}

function restartTimer() {
  window.clearInterval(slideTimer);
  slideTimer = window.setInterval(() => showSlide(currentSlide + 1), 6500);
}

document.querySelector('#slide-prev').addEventListener('click', () => { showSlide(currentSlide - 1); restartTimer(); });
document.querySelector('#slide-next').addEventListener('click', () => { showSlide(currentSlide + 1); restartTimer(); });
dots.forEach((dot, index) => dot.addEventListener('click', () => { showSlide(index); restartTimer(); }));

const dashboardMessage = document.querySelector('#dashboard-message');
const profileRetry = document.querySelector('#profile-retry');
function loadProfile() {
  profileRetry.hidden = true;
  dashboardMessage.textContent = 'Загружаем профиль…';
  return apiRequest('/api/auth/me')
  .then(({ user }) => {
    userName.textContent = user.name;
    userAvatar.textContent = user.name.trim().slice(0, 1).toLocaleUpperCase('ru');
    userRole.textContent = user.role === 'organizer' ? 'Организатор' : 'Участник';
    document.querySelector('#welcome-title').textContent = `Поздравляем, ${user.name}!`;
    document.querySelector('#welcome-caption').textContent = 'Вы успешно вошли в свой аккаунт.';
    dashboardMessage.textContent = '';
  })
  .catch((error) => {
    if (error.status === 401) window.location.replace('login.html');
    else {
      dashboardMessage.textContent = error.message;
      profileRetry.hidden = false;
    }
  });
}
profileRetry.addEventListener('click', loadProfile);
loadProfile();

document.querySelector('#logout-button').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await apiRequest('/api/auth/logout', { method: 'POST', body: {} });
    window.location.replace('login.html');
  } catch (error) {
    dashboardMessage.textContent = error.message;
    button.disabled = false;
  }
});

restartTimer();
