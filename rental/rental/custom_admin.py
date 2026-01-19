"""
Кастомная админка для платформы аренды
"""
from django.contrib import admin
from django.urls import path
from django.shortcuts import render
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Sum, Avg
from datetime import datetime, timedelta
from django.utils import timezone


def staff_required(view_func):
    """
    Декоратор для проверки прав администратора
    """
    decorated_view_func = user_passes_test(
        lambda u: u.is_active and u.is_staff,
        login_url='/admin/login/'
    )(view_func)
    return decorated_view_func


@staff_required
def custom_admin_dashboard(request):
    """
    Кастомная админ-панель
    """
    from core.models import User, Property, Booking, Review

    # Основная статистика
    total_users = User.objects.count()
    total_properties = Property.objects.filter(status='active').count()
    total_bookings = Booking.objects.count()

    # Активные бронирования
    active_bookings = Booking.objects.filter(
        status__in=['pending', 'confirmed'],
        end_datetime__gte=timezone.now()
    ).count()

    # Статистика по бронированиям за последние 30 дней
    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_bookings = Booking.objects.filter(created_at__gte=thirty_days_ago)

    booking_stats = {
        'total': recent_bookings.count(),
        'confirmed': recent_bookings.filter(status='confirmed').count(),
        'cancelled': recent_bookings.filter(status='cancelled').count(),
        'completed': recent_bookings.filter(status='completed').count(),
        'total_revenue': recent_bookings.filter(status='completed').aggregate(
            total=Sum('total_price')
        )['total'] or 0,
        'avg_booking_value': recent_bookings.filter(status='completed').aggregate(
            avg=Avg('total_price')
        )['avg'] or 0,
        'confirmed_percentage': int((recent_bookings.filter(status='confirmed').count() /
                                     max(recent_bookings.count(), 1)) * 100)
    }

    # Недавние бронирования
    recent_bookings_list = Booking.objects.select_related(
        'property', 'tenant'
    ).order_by('-created_at')[:10]

    # Недавние пользователи
    recent_users = User.objects.order_by('-date_joined')[:10]

    # Распределение пользователей по типам
    user_types = User.objects.values('user_type').annotate(
        count=Count('id')
    )

    context = {
        'total_users': total_users,
        'total_properties': total_properties,
        'total_bookings': total_bookings,
        'active_bookings': active_bookings,
        'booking_stats': booking_stats,
        'recent_bookings': recent_bookings_list,
        'recent_users': recent_users,
        'user_types': user_types,
    }

    return render(request, 'admin/dashboard.html', context)


class CustomAdminSite(admin.AdminSite):
    """
    Кастомный админ-сайт
    """
    site_header = 'Администрирование SpaceRent'
    site_title = 'SpaceRent Admin'
    index_title = 'Панель управления'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('dashboard/', self.admin_view(custom_admin_dashboard), name='custom_dashboard'),
        ]
        return custom_urls + urls