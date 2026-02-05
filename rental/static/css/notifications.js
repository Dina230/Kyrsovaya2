/* static/css/notifications.css */
.notification-badge {
    position: absolute;
    top: -5px;
    right: -5px;
    min-width: 18px;
    height: 18px;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 9px;
    display: none;
}

.notification-item.unread {
    background-color: #f8f9fa;
    border-left: 3px solid #007bff;
}

.notification-item.read {
    opacity: 0.8;
    background-color: #fff;
}

.notification-time {
    font-size: 12px;
    color: #6c757d;
}

.notification-dropdown {
    min-width: 350px;
    max-width: 400px;
    max-height: 500px;
    overflow-y: auto;
}

.notification-dropdown .dropdown-item {
    white-space: normal;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid #f8f9fa;
}

.notification-dropdown .dropdown-item:last-child {
    border-bottom: none;
}

.notification-dropdown .dropdown-item:hover {
    background-color: #f8f9fa;
}

.notification-dropdown .notification-preview {
    display: flex;
    flex-direction: column;
}

.notification-dropdown .notification-title {
    font-weight: 600;
    margin-bottom: 0.25rem;
    color: #343a40;
}

.notification-dropdown .notification-message {
    font-size: 0.875rem;
    color: #6c757d;
    margin-bottom: 0.25rem;
}

.notification-dropdown .notification-time {
    font-size: 0.75rem;
    color: #adb5bd;
}