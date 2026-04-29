from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import UserAuditLog


def _extract_ip(request):
    if request is None:
        return None
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _extract_user_agent(request):
    if request is None:
        return ''
    return (request.META.get('HTTP_USER_AGENT') or '')[:255]


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    UserAuditLog.objects.create(
        user=user,
        username_snapshot=getattr(user, 'username', ''),
        event_type='login_success',
        details='Пользователь успешно вошел в систему',
        ip_address=_extract_ip(request),
        user_agent=_extract_user_agent(request),
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    username = getattr(user, 'username', '') if user is not None else ''
    UserAuditLog.objects.create(
        user=user if user is not None else None,
        username_snapshot=username,
        event_type='logout',
        details='Пользователь вышел из системы',
        ip_address=_extract_ip(request),
        user_agent=_extract_user_agent(request),
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get('username', '') if credentials else ''
    UserAuditLog.objects.create(
        user=None,
        username_snapshot=username,
        event_type='login_failed',
        details='Неуспешная попытка входа',
        ip_address=_extract_ip(request),
        user_agent=_extract_user_agent(request),
    )

