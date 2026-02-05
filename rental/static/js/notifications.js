// static/js/notifications.js
class NotificationManager {
    constructor() {
        this.pollingInterval = 30000; // 30 секунд
        this.badgeElement = document.querySelector('.notification-badge');
        this.init();
    }

    init() {
        this.updateBadge();
        this.startPolling();
        this.setupEventListeners();
    }

    updateBadge() {
        fetch('/notifications/unread-count/', {
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        })
        .then(response => response.json())
        .then(data => {
            if (this.badgeElement) {
                if (data.count > 0) {
                    this.badgeElement.textContent = data.count;
                    this.badgeElement.style.display = 'inline-block';
                } else {
                    this.badgeElement.style.display = 'none';
                }
            }
        })
        .catch(error => console.error('Error updating notification count:', error));
    }

    startPolling() {
        setInterval(() => this.updateBadge(), this.pollingInterval);
    }

    setupEventListeners() {
        // Пометить все как прочитанные при клике на иконку колокольчика
        const bellIcon = document.querySelector('.notification-bell');
        if (bellIcon) {
            bellIcon.addEventListener('click', () => {
                setTimeout(() => this.updateBadge(), 1000);
            });
        }
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.notification-badge')) {
        new NotificationManager();
    }
});