from django.utils import timezone
from datetime import timedelta
from .models import Booking


class AutoCancelBookingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # Проверяем при каждом 10-м запросе (для оптимизации)
        self.counter = 0

    def __call__(self, request):
        # Пропускаем статические файлы и админку
        if not request.path.startswith('/static/') and not request.path.startswith('/admin/'):
            self.counter += 1
            # Проверяем каждый 10-й запрос
            if self.counter % 10 == 0:
                self.cancel_expired_bookings()

        response = self.get_response(request)
        return response

    def cancel_expired_bookings(self):
        """Отмена просроченных бронирований"""
        expiration_time = timezone.now() - timedelta(minutes=30)
        expired_bookings = Booking.objects.filter(
            status='pending',
            created_at__lte=expiration_time
        )

        for booking in expired_bookings:
            booking.status = 'cancelled'
            booking.save()

            # Импортируем здесь, чтобы избежать циклического импорта
            from .views import create_notification
            create_notification(
                user=booking.tenant,
                notification_type='booking_cancelled',
                title='Бронирование отменено',
                message=f'Бронирование #{booking.booking_id} автоматически отменено из-за истечения времени оплаты.',
                related_object_id=booking.id,
                related_object_type='booking'
            )