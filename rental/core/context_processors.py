# core/context_processors.py
from .models import Notification, Cart, Message


def tenant_cart(request):
    """Количество позиций в корзине (арендатор)."""
    if request.user.is_authenticated and getattr(request.user, 'user_type', None) == 'tenant':
        return {'cart_items_count': Cart.objects.filter(user=request.user).count()}
    return {'cart_items_count': 0}


def notifications_context(request):
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).count()
        unread_messages_count = Message.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count()
        recent_notifications = Notification.objects.filter(
            user=request.user
        ).order_by('-created_at')[:5]
        return {
            'unread_notifications_count': unread_count,
            'unread_messages_count': unread_messages_count,
            'recent_notifications': recent_notifications,
        }
    return {
        'unread_notifications_count': 0,
        'unread_messages_count': 0,
        'recent_notifications': [],
    }