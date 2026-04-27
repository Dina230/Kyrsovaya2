(function () {
  'use strict';

  function toggle(button) {
    var group = button.closest('.input-group.password-toggle');
    if (!group) return;
    var input = group.querySelector('input');
    if (!input || (input.type !== 'password' && input.type !== 'text')) return;
    var show = input.getAttribute('type') === 'password';
    input.setAttribute('type', show ? 'text' : 'password');
    var icon = button.querySelector('i');
    if (icon) {
      icon.className = show ? 'bi bi-eye-slash' : 'bi bi-eye';
    }
    button.setAttribute('aria-label', show ? 'Скрыть' : 'Показать');
    if (button.title !== undefined) {
      button.title = show ? 'Скрыть' : 'Показать';
    }
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-password-toggle]');
    if (!btn) return;
    e.preventDefault();
    toggle(btn);
  });
})();
