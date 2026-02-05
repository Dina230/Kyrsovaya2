from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg, Sum, F
from django.views.generic import CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
import json
from datetime import datetime, timedelta
import csv

from .models import User, Property, Booking, Review, Favorite, Category, Amenity, Notification, Message
from .forms import (
    CustomUserCreationForm, CustomUserChangeForm,
    PropertyForm, BookingForm, ReviewForm,
    ContactForm
)


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def has_valid_slug(obj):
    """Проверяет, имеет ли объект валидный slug"""
    return bool(obj and hasattr(obj, 'slug') and obj.slug and obj.slug.strip())


def filter_valid_properties(properties):
    """Фильтрует список объектов Property, оставляя только те, у которых есть валидный slug"""
    return [prop for prop in properties if has_valid_slug(prop)]


def filter_valid_bookings(bookings):
    """Фильтрует список объектов Booking, оставляя только те, у которых property имеет валидный slug"""
    return [booking for booking in bookings if booking.property and has_valid_slug(booking.property)]


def filter_valid_favorites(favorites):
    """Фильтрует список объектов Favorite, оставляя только те, у которых property имеет валидный slug"""
    return [fav for fav in favorites if fav.property and has_valid_slug(fav.property)]


def create_notification(user, notification_type, title, message,
                        related_object_id=None, related_object_type=None):
    """Создать уведомление для пользователя"""
    notification = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        related_object_id=related_object_id,
        related_object_type=related_object_type
    )
    return notification


def create_booking_notification(booking, notification_type):
    """Создать уведомление о бронировании"""
    if notification_type == 'booking_created':
        user = booking.property.landlord
    elif notification_type in ['booking_confirmed', 'booking_cancelled']:
        user = booking.tenant
    else:
        return None

    title_map = {
        'booking_created': 'Новое бронирование',
        'booking_confirmed': 'Бронирование подтверждено',
        'booking_cancelled': 'Бронирование отменено',
    }
    message_map = {
        'booking_created': f'Новый запрос на бронирование помещения "{booking.property.title}" на {booking.start_datetime.strftime("%d.%m.%Y %H:%M")}',
        'booking_confirmed': f'Ваше бронирование #{booking.booking_id} подтверждено',
        'booking_cancelled': f'Бронирование #{booking.booking_id} отменено',
    }

    return create_notification(
        user=user,
        notification_type=notification_type,
        title=title_map.get(notification_type, 'Уведомление'),
        message=message_map.get(notification_type, ''),
        related_object_id=booking.id,
        related_object_type='booking'
    )


def create_message_notification(message):
    """Создать уведомление о новом сообщении"""
    return create_notification(
        user=message.recipient,
        notification_type='message_received',
        title='Новое сообщение',
        message=f'Вам новое сообщение от {message.sender.get_full_name_or_username()}',
        related_object_id=message.id,
        related_object_type='message'
    )


# ============================================================================
# ПУБЛИЧНЫЕ СТРАНИЦЫ
# ============================================================================

def home(request):
    """Главная страница"""
    properties = Property.objects.filter(
        status='active',
        is_featured=True
    ).select_related('landlord', 'category')[:6]

    context = {
        'properties': properties,
        'title': 'Аренда коммерческих помещений'
    }
    return render(request, 'core/home.html', context)


def property_list(request):
    """Список всех помещений"""
    properties = Property.objects.filter(status='active').select_related('landlord', 'category')

    # Фильтрация
    property_type = request.GET.get('property_type')
    city = request.GET.get('city')
    category = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    if property_type:
        properties = properties.filter(property_type=property_type)
    if city:
        properties = properties.filter(city__icontains=city)
    if category:
        properties = properties.filter(category_id=category)
    if min_price:
        properties = properties.filter(price_per_hour__gte=float(min_price))
    if max_price:
        properties = properties.filter(price_per_hour__lte=float(max_price))

    # Пагинация
    paginator = Paginator(properties, 12)
    page = request.GET.get('page')
    properties_page = paginator.get_page(page)

    context = {
        'properties': properties_page,
        'property_types': Property.PROPERTY_TYPE_CHOICES,
        'categories': Category.objects.all(),
        'title': 'Все помещения для аренды'
    }
    return render(request, 'core/property_list.html', context)


def property_detail(request, slug):
    """Детальная страница помещения"""
    property_obj = get_object_or_404(
        Property.objects.select_related('landlord', 'category')
        .prefetch_related('amenities', 'images'),
        slug=slug,
        status='active'
    )

    # Увеличиваем счетчик просмотров
    property_obj.views_count = F('views_count') + 1
    property_obj.save()
    property_obj.refresh_from_db()

    # Получаем только одобренные отзывы
    reviews = Review.objects.filter(
        property=property_obj,
        status='approved'
    ).select_related('user').order_by('-created_at')

    # Проверяем, добавлено ли помещение в избранное
    is_favorite = False
    if request.user.is_authenticated:
        is_favorite = Favorite.objects.filter(
            user=request.user,
            property=property_obj
        ).exists()

    # Готовим данные календаря на 30 дней
    today = timezone.now().date()
    calendar_data = []
    booked_dates = []

    # Получаем бронирования на ближайшие 30 дней
    bookings = property_obj.bookings.filter(
        status__in=['confirmed', 'pending'],
        start_datetime__date__gte=today,
        start_datetime__date__lte=today + timedelta(days=30)
    )

    # Собираем забронированные даты
    for booking in bookings:
        booking_date = booking.start_datetime.date()
        if booking_date not in booked_dates:
            booked_dates.append(booking_date)

    # Создаем данные календаря
    for i in range(30):
        current_date = today + timedelta(days=i)
        calendar_data.append({
            'date': current_date,
            'bookings': bookings.filter(start_datetime__date=current_date).exists()
        })

    # Похожие помещения
    similar_properties = Property.objects.filter(
        status='active',
        property_type=property_obj.property_type,
        city=property_obj.city
    ).exclude(id=property_obj.id).select_related('landlord')[:4]

    context = {
        'property': property_obj,
        'reviews': reviews,
        'is_favorite': is_favorite,
        'calendar_data': calendar_data,
        'booked_dates_json': json.dumps([d.strftime('%Y-%m-%d') for d in booked_dates]),
        'similar_properties': similar_properties,
        'today': today.strftime('%Y-%m-%d'),
        'hours_range': range(9, 22),
        'title': property_obj.title
    }

    return render(request, 'core/property_detail.html', context)


def register(request):
    """Регистрация нового пользователя"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()

            # Аутентификация и вход пользователя
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)

            if user is not None:
                login(request, user)
                messages.success(request, 'Регистрация успешно завершена!')
                return redirect('dashboard')
    else:
        form = CustomUserCreationForm()

    return render(request, 'core/register.html', {'form': form, 'title': 'Регистрация'})


# ============================================================================
# ЛИЧНЫЙ КАБИНЕТ
# ============================================================================

@login_required
def dashboard(request):
    """Личный кабинет"""
    context = {'title': 'Личный кабинет'}
    user = request.user

    if user.user_type == 'tenant':
        # Для арендатора
        bookings = user.bookings_as_tenant.select_related('property').order_by('-created_at')
        active_bookings = bookings.filter(status__in=['pending', 'confirmed'])

        # Статистика
        stats = {
            'total_bookings': bookings.count(),
            'active_bookings': active_bookings.count(),
            'completed_bookings': bookings.filter(status='completed').count(),
            'total_spent': bookings.filter(status='completed').aggregate(
                total=Sum('total_price')
            )['total'] or 0,
            'favorite_count': user.favorites.count(),
            'bookings_trend': 12,  # Примерный тренд
            'spending_trend': 8,
            'favorites_trend': 15,
            'completion_rate': bookings.filter(status='completed').count() * 100 // max(bookings.count(), 1)
        }

        # Получаем избранные помещения с валидным slug
        all_favorites = list(user.favorites.select_related('property').all()[:4])
        favorite_properties = filter_valid_favorites(all_favorites)

        # Получаем активные бронирования с валидным slug
        all_active_bookings = list(active_bookings[:5])
        safe_active_bookings = filter_valid_bookings(all_active_bookings)

        context.update({
            'stats': stats,
            'active_bookings': safe_active_bookings,
            'favorite_properties': favorite_properties,
            'has_favorites': len(favorite_properties) > 0,
            'has_active_bookings': len(safe_active_bookings) > 0
        })

    elif user.user_type == 'landlord':
        # Для арендодателя
        properties = list(user.properties.select_related('category').all())
        bookings = Booking.objects.filter(
            property__landlord=user
        ).select_related('property', 'tenant')

        # Статистика
        monthly_revenue = bookings.filter(
            status='completed',
            updated_at__gte=timezone.now() - timedelta(days=30)
        ).aggregate(total=Sum('total_price'))['total'] or 0

        stats = {
            'total_properties': len(properties),
            'active_properties': len([p for p in properties if p.status == 'active']),
            'total_bookings': bookings.count(),
            'pending_bookings': bookings.filter(status='pending').count(),
            'monthly_revenue': monthly_revenue,
            'avg_rating': Review.objects.filter(
                property__landlord=user,
                status='approved'
            ).aggregate(avg=Avg('rating'))['avg'] or 0,
            'reviews_count': Review.objects.filter(
                property__landlord=user,
                status='approved'
            ).count(),
            'revenue_trend': 18,  # Примерный тренд
        }

        # Фильтруем только помещения с валидным slug
        safe_properties = filter_valid_properties(properties[:6])

        # Популярные помещения с валидным slug
        properties_with_stats = [p for p in properties if hasattr(p, 'id')]
        popular_properties = []
        for prop in properties_with_stats:
            if has_valid_slug(prop):
                prop.booking_count = prop.bookings.count()
                popular_properties.append(prop)

        popular_properties.sort(key=lambda x: x.booking_count, reverse=True)
        popular_properties = popular_properties[:5]

        # Новые бронирования с валидным slug
        all_new_bookings = list(bookings.filter(status='pending').order_by('-created_at')[:10])
        new_bookings = filter_valid_bookings(all_new_bookings)

        # Активные бронирования с валидным slug
        all_active_bookings = list(bookings.filter(
            status='confirmed',
            start_datetime__gte=timezone.now()
        ).order_by('start_datetime')[:10])
        active_bookings = filter_valid_bookings(all_active_bookings)

        # Статистика за месяц
        monthly_stats = {
            'total_revenue': monthly_revenue,
            'total_bookings': bookings.filter(
                status='completed',
                updated_at__gte=timezone.now() - timedelta(days=30)
            ).count(),
            'avg_booking': bookings.filter(
                status='completed',
                updated_at__gte=timezone.now() - timedelta(days=30)
            ).aggregate(avg=Avg('total_price'))['avg'] or 0,
        }

        context.update({
            'stats': stats,
            'properties': safe_properties,
            'new_bookings': new_bookings,
            'active_bookings': active_bookings,
            'popular_properties': popular_properties,
            'monthly_stats': monthly_stats,
            'has_new_bookings': len(new_bookings) > 0,
            'has_active_bookings': len(active_bookings) > 0,
            'has_popular_properties': len(popular_properties) > 0
        })

    elif user.user_type == 'admin' or user.is_staff:
        # Для администратора
        stats = {
            'total_users': User.objects.count(),
            'new_users_today': User.objects.filter(date_joined__date=timezone.now().date()).count(),
            'total_properties': Property.objects.count(),
            'active_properties': Property.objects.filter(status='active').count(),
            'total_bookings': Booking.objects.count(),
            'pending_bookings': Booking.objects.filter(status='pending').count(),
            'today_bookings': Booking.objects.filter(start_datetime__date=timezone.now().date()).count(),
            'month_revenue': Booking.objects.filter(
                status='completed',
                updated_at__gte=timezone.now() - timedelta(days=30)
            ).aggregate(total=Sum('total_price'))['total'] or 0,
        }

        # Последние действия
        recent_users = User.objects.order_by('-date_joined')[:5]
        recent_bookings = Booking.objects.select_related('property', 'tenant').order_by('-created_at')[:5]
        recent_reviews = Review.objects.select_related('property', 'user').order_by('-created_at')[:5]

        context.update({
            'stats': stats,
            'recent_users': recent_users,
            'recent_bookings': recent_bookings,
            'recent_reviews': recent_reviews,
            'is_admin_dashboard': True,
        })

    return render(request, 'core/dashboard.html', context)


@login_required
def edit_profile(request):
    """Редактирование профиля"""
    if request.method == 'POST':
        form = CustomUserChangeForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Профиль успешно обновлен.')
            return redirect('dashboard')
    else:
        form = CustomUserChangeForm(instance=request.user)

    return render(request, 'core/edit_profile.html', {
        'form': form,
        'title': 'Редактирование профиля'
    })


@login_required
def change_password(request):
    """Смена пароля"""
    from django.contrib.auth.forms import PasswordChangeForm

    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Перезагружаем сессию
            messages.success(request, 'Пароль успешно изменен.')
            return redirect('dashboard')
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'core/change_password.html', {
        'form': form,
        'title': 'Смена пароля'
    })


@login_required
def my_bookings(request):
    """Мои бронирования"""
    if request.user.user_type != 'tenant':
        messages.error(request, 'Эта страница доступна только арендаторам.')
        return redirect('dashboard')

    bookings = request.user.bookings_as_tenant.select_related('property').order_by('-created_at')

    # Фильтрация по статусу
    status_filter = request.GET.get('status')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    # Пагинация
    paginator = Paginator(bookings, 10)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    return render(request, 'core/my_bookings.html', {
        'bookings': bookings_page,
        'title': 'Мои бронирования'
    })


@login_required
def my_favorites(request):
    """Избранные помещения"""
    favorites = request.user.favorites.select_related('property').all()

    return render(request, 'core/my_favorites.html', {
        'favorites': favorites,
        'title': 'Избранное'
    })


@login_required
def my_properties(request):
    """Мои помещения (для арендодателей)"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Эта страница доступна только арендодателям.')
        return redirect('dashboard')

    properties = request.user.properties.select_related('category').all()

    # Фильтрация по статусу
    status_filter = request.GET.get('status')
    if status_filter:
        properties = properties.filter(status=status_filter)

    # Статистика
    stats = {
        'active_count': properties.filter(status='active').count(),
        'featured_count': properties.filter(is_featured=True).count(),
        'booked_count': Booking.objects.filter(
            property__in=properties,
            status__in=['confirmed', 'pending']
        ).count(),
    }

    # Пагинация
    paginator = Paginator(properties, 10)
    page = request.GET.get('page')
    properties_page = paginator.get_page(page)

    return render(request, 'core/my_properties.html', {
        'properties': properties_page,
        'stats': stats,
        'title': 'Мои помещения'
    })


@login_required
def toggle_favorite(request, property_id):
    """Добавить/удалить помещение из избранного"""
    property_obj = get_object_or_404(Property, id=property_id)

    favorite, created = Favorite.objects.get_or_create(
        user=request.user,
        property=property_obj
    )

    if not created:
        favorite.delete()
        messages.success(request, 'Удалено из избранного')
    else:
        messages.success(request, 'Добавлено в избранное')

    return redirect('property_detail', slug=property_obj.slug)


@login_required
def create_booking(request, property_id):
    """Создание бронирования"""
    property_obj = get_object_or_404(Property, id=property_id)

    if request.user.user_type != 'tenant':
        messages.error(request, 'Только арендаторы могут создавать бронирования.')
        return redirect('property_detail', slug=property_obj.slug)

    if request.method == 'POST':
        form = BookingForm(request.POST, property_obj=property_obj)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.property = property_obj
            booking.tenant = request.user
            booking.status = 'pending'
            booking.save()

            # Создаем уведомление для владельца
            create_booking_notification(booking, 'booking_created')

            messages.success(request, 'Бронирование отправлено на подтверждение.')
            return redirect('my_bookings')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{error}')
    else:
        form = BookingForm(property_obj=property_obj)

    # Рассчитываем стоимость
    price_per_hour = property_obj.price_per_hour
    price_per_day = property_obj.price_per_day or float(price_per_hour) * 8

    context = {
        'form': form,
        'property': property_obj,
        'price_per_hour': price_per_hour,
        'price_per_day': price_per_day,
        'title': 'Бронирование помещения'
    }
    return render(request, 'core/create_booking.html', context)


@login_required
def booking_detail(request, booking_id):
    """Детали бронирования"""
    booking = get_object_or_404(
        Booking.objects.select_related('property', 'tenant'),
        id=booking_id
    )

    # Проверка прав доступа
    if request.user != booking.tenant and request.user != booking.property.landlord:
        messages.error(request, 'У вас нет доступа к этому бронированию.')
        return redirect('dashboard')

    can_cancel = (
            request.user == booking.tenant and
            booking.status in ['pending', 'confirmed'] and
            booking.start_datetime > timezone.now()
    )

    can_review = (
            request.user == booking.tenant and
            booking.status == 'completed' and
            not Review.objects.filter(property=booking.property, user=request.user).exists()
    )

    # Рассчитываем количество дней
    if booking.start_datetime and booking.end_datetime:
        days_count = (booking.end_datetime.date() - booking.start_datetime.date()).days + 1
        hours_count = (booking.end_datetime - booking.start_datetime).total_seconds() / 3600
    else:
        days_count = 0
        hours_count = 0

    return render(request, 'core/booking_detail.html', {
        'booking': booking,
        'can_cancel': can_cancel,
        'can_review': can_review,
        'days_count': days_count,
        'hours_count': hours_count,
        'title': f'Бронирование #{booking.booking_id}'
    })


@login_required
def cancel_booking(request, booking_id):
    """Отмена бронирования"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'Вы не можете отменить это бронирование.')
        return redirect('dashboard')

    if booking.status not in ['pending', 'confirmed']:
        messages.error(request, 'Это бронирование нельзя отменить.')
        return redirect('booking_detail', booking_id=booking_id)

    if booking.start_datetime <= timezone.now():
        messages.error(request, 'Нельзя отменить начавшееся бронирование.')
        return redirect('booking_detail', booking_id=booking_id)

    booking.status = 'cancelled'
    booking.save()

    # Создаем уведомление для владельца
    create_booking_notification(booking, 'booking_cancelled')

    messages.success(request, 'Бронирование успешно отменено.')
    return redirect('my_bookings')


@login_required
def add_review(request, booking_id):
    """Добавление отзыва"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'Вы не можете оставить отзыв на это бронирование.')
        return redirect('dashboard')

    if booking.status != 'completed':
        messages.error(request, 'Отзыв можно оставить только на завершенное бронирование.')
        return redirect('booking_detail', booking_id=booking_id)

    if Review.objects.filter(property=booking.property, user=request.user).exists():
        messages.error(request, 'Вы уже оставляли отзыв на это помещение.')
        return redirect('booking_detail', booking_id=booking_id)

    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.property = booking.property
            review.user = request.user
            review.save()

            messages.success(request, 'Отзыв успешно добавлен и отправлен на модерацию.')
            return redirect('property_detail', slug=booking.property.slug)
    else:
        form = ReviewForm()

    return render(request, 'core/add_review.html', {
        'form': form,
        'booking': booking,
        'title': 'Добавление отзыва'
    })


# ============================================================================
# УВЕДОМЛЕНИЯ
# ============================================================================

@login_required
def notifications_list(request):
    """Страница со списком уведомлений"""
    notifications = request.user.notifications.all().order_by('-created_at')

    # Пагинация
    paginator = Paginator(notifications, 20)
    page = request.GET.get('page')
    notifications_page = paginator.get_page(page)

    # Пометить как прочитанные при открытии страницы
    if request.GET.get('mark_read'):
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return redirect('notifications_list')

    return render(request, 'core/notifications_list.html', {
        'notifications': notifications_page,
        'title': 'Мои уведомления'
    })


@login_required
def mark_notification_read(request, notification_id):
    """Пометить уведомление как прочитанное"""
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user
    )
    notification.is_read = True
    notification.save()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


@login_required
def mark_all_notifications_read(request):
    """Пометить все уведомления как прочитанные"""
    request.user.notifications.filter(is_read=False).update(is_read=True)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('notifications_list')


@login_required
def delete_notification(request, notification_id):
    """Удалить уведомление"""
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user
    )
    notification.delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('notifications_list')


@login_required
def delete_all_notifications(request):
    """Удалить все уведомления"""
    if request.method == 'POST':
        request.user.notifications.all().delete()
        messages.success(request, 'Все уведомления удалены.')

    return redirect('notifications_list')


@login_required
def get_unread_count(request):
    """Получить количество непрочитанных уведомлений (AJAX)"""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        count = request.user.notifications.filter(is_read=False).count()
        return JsonResponse({'count': count})

    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# СООБЩЕНИЯ
# ============================================================================

@login_required
def messages_list(request):
    """Страница со списком сообщений/диалогов"""
    # Получаем всех собеседников
    sent_messages = Message.objects.filter(sender=request.user).values('recipient').distinct()
    received_messages = Message.objects.filter(recipient=request.user).values('sender').distinct()

    # Объединяем ID собеседников
    user_ids = set()
    for msg in sent_messages:
        user_ids.add(msg['recipient'])
    for msg in received_messages:
        user_ids.add(msg['sender'])

    # Получаем пользователей и последние сообщения
    conversations = []
    for user_id in user_ids:
        other_user = User.objects.get(id=user_id)

        # Получаем последнее сообщение
        last_message = Message.objects.filter(
            Q(sender=request.user, recipient=other_user) |
            Q(sender=other_user, recipient=request.user)
        ).order_by('-created_at').first()

        # Считаем непрочитанные сообщения
        unread_count = Message.objects.filter(
            sender=other_user,
            recipient=request.user,
            is_read=False
        ).count()

        conversations.append({
            'user': other_user,
            'last_message': last_message,
            'unread_count': unread_count,
        })

    # Сортируем диалоги
    conversations.sort(
        key=lambda x: x['last_message'].created_at if x['last_message'] else timezone.make_aware(datetime.min),
        reverse=True)

    context = {
        'conversations': conversations,
        'title': 'Мои сообщения'
    }
    return render(request, 'core/messages_list.html', context)


@login_required
def send_message(request, user_id=None, property_id=None):
    """Отправка сообщения пользователю или владельцу помещения"""
    recipient = None
    property_obj = None

    if property_id:
        property_obj = get_object_or_404(Property, id=property_id)
        recipient = property_obj.landlord

        if request.user == recipient:
            messages.error(request, 'Вы не можете отправить сообщение самому себе.')
            return redirect('property_detail', slug=property_obj.slug)
    elif user_id:
        recipient = get_object_or_404(User, id=user_id)

        if request.user == recipient:
            messages.error(request, 'Вы не можете отправить сообщение самому себе.')
            return redirect('messages_list')
    else:
        messages.error(request, 'Не указан получатель.')
        return redirect('home')

    if request.method == 'POST':
        subject = request.POST.get('subject', '')
        message_text = request.POST.get('message', '')

        if not message_text:
            messages.error(request, 'Сообщение не может быть пустым.')
        else:
            if not subject and property_obj:
                subject = f'Вопрос по помещению: {property_obj.title}'

            message = Message.objects.create(
                sender=request.user,
                recipient=recipient,
                property=property_obj,
                subject=subject,
                message=message_text
            )

            create_message_notification(message)
            messages.success(request, 'Сообщение отправлено.')

            if property_obj:
                return redirect('property_detail', slug=property_obj.slug)
            else:
                return redirect('messages_list')

    # Получаем историю переписки
    conversation = Message.objects.filter(
        Q(sender=request.user, recipient=recipient) |
        Q(sender=recipient, recipient=request.user)
    ).order_by('created_at')

    # Помечаем входящие сообщения как прочитанные
    Message.objects.filter(
        sender=recipient,
        recipient=request.user,
        is_read=False
    ).update(is_read=True)

    context = {
        'recipient': recipient,
        'property': property_obj,
        'conversation': conversation,
        'title': f'Сообщение для {recipient.get_full_name_or_username()}' if recipient else 'Новое сообщение'
    }
    return render(request, 'core/send_message.html', context)


# ============================================================================
# УПРАВЛЕНИЕ ПОМЕЩЕНИЯМИ
# ============================================================================

@login_required
def add_property(request):
    """Добавление нового помещения"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Только арендодатели могут добавлять помещения.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES)
        if form.is_valid():
            property_obj = form.save(commit=False)
            property_obj.landlord = request.user

            # Генерация slug
            from django.utils.text import slugify
            import uuid
            base_slug = slugify(property_obj.title)
            unique_slug = f"{base_slug}-{uuid.uuid4().hex[:8]}"
            property_obj.slug = unique_slug

            property_obj.save()
            form.save_m2m()  # Сохраняем ManyToMany поля

            # Сохраняем изображения
            images = request.FILES.getlist('images')
            for image in images:
                property_obj.images.create(image=image)

            messages.success(request, 'Помещение успешно добавлено.')
            return redirect('my_properties')
    else:
        form = PropertyForm()

    return render(request, 'core/add_property.html', {
        'form': form,
        'title': 'Добавление помещения'
    })


@login_required
def edit_property(request, property_id):
    """Редактирование помещения"""
    property_obj = get_object_or_404(Property, id=property_id)

    if request.user != property_obj.landlord:
        messages.error(request, 'Вы не можете редактировать это помещение.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES, instance=property_obj)
        if form.is_valid():
            property_obj = form.save()

            # Обновляем изображения
            images = request.FILES.getlist('images')
            for image in images:
                property_obj.images.create(image=image)

            messages.success(request, 'Помещение успешно обновлено.')
            return redirect('my_properties')
    else:
        form = PropertyForm(instance=property_obj)

    return render(request, 'core/edit_property.html', {
        'form': form,
        'property': property_obj,
        'existing_images': property_obj.images.all(),
        'title': 'Редактирование помещения'
    })


@login_required
def delete_property(request, property_id):
    """Удаление помещения"""
    property_obj = get_object_or_404(Property, id=property_id)

    if request.user != property_obj.landlord:
        messages.error(request, 'Вы не можете удалить это помещение.')
        return redirect('dashboard')

    if request.method == 'POST':
        property_obj.delete()
        messages.success(request, 'Помещение успешно удалено.')
        return redirect('my_properties')

    return render(request, 'core/confirm_delete.html', {
        'object': property_obj,
        'type': 'помещение',
        'title': 'Удаление помещения'
    })


@login_required
def delete_property_image(request, image_id):
    """Удаление изображения помещения"""
    from .models import PropertyImage
    image = get_object_or_404(PropertyImage, id=image_id)

    if request.user != image.property.landlord:
        messages.error(request, 'Вы не можете удалить это изображение.')
        return redirect('dashboard')

    image.delete()
    messages.success(request, 'Изображение успешно удалено.')
    return redirect('edit_property', property_id=image.property.id)


# ============================================================================
# ДЛЯ АРЕНДОДАТЕЛЕЙ
# ============================================================================

@login_required
def landlord_bookings(request):
    """Бронирования для арендодателя"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Эта страница доступна только арендодателям.')
        return redirect('dashboard')

    bookings = Booking.objects.filter(
        property__landlord=request.user
    ).select_related('property', 'tenant').order_by('-created_at')

    # Фильтрация по статусу
    status_filter = request.GET.get('status')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    # Пагинация
    paginator = Paginator(bookings, 10)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    context = {
        'bookings': bookings_page,
        'title': 'Бронирования моих помещений'
    }
    return render(request, 'core/landlord_bookings.html', context)


@login_required
def update_booking_status(request, booking_id, status):
    """Обновление статуса бронирования"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.property.landlord:
        messages.error(request, 'Вы не можете изменить статус этого бронирования.')
        return redirect('dashboard')

    valid_statuses = ['confirmed', 'cancelled', 'completed']
    if status not in valid_statuses:
        messages.error(request, 'Недопустимый статус.')
        return redirect('landlord_bookings')

    old_status = booking.status
    booking.status = status
    booking.save()

    if old_status != status and status in ['confirmed', 'cancelled']:
        notification_type = f'booking_{status}'
        create_booking_notification(booking, notification_type)

    status_names = {
        'confirmed': 'подтверждено',
        'cancelled': 'отменено',
        'completed': 'завершено'
    }

    messages.success(request, f'Бронирование успешно {status_names[status]}.')
    return redirect('landlord_bookings')


@login_required
def add_property_image(request, property_id):
    """Добавление изображения к помещению"""
    property_obj = get_object_or_404(Property, id=property_id)

    if request.user != property_obj.landlord:
        messages.error(request, 'Вы не можете добавлять изображения к этому помещению.')
        return redirect('dashboard')

    if request.method == 'POST' and request.FILES.get('image'):
        image = request.FILES['image']
        from .models import PropertyImage
        PropertyImage.objects.create(property=property_obj, image=image)
        messages.success(request, 'Изображение успешно добавлено.')

    return redirect('edit_property', property_id=property_id)


# ============================================================================
# API ЭНДПОИНТЫ
# ============================================================================

@login_required
def ajax_create_booking(request, property_id):
    """AJAX бронирование"""
    if request.method != 'POST' or not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    property_obj = get_object_or_404(Property, id=property_id)

    try:
        data = json.loads(request.body)
        start_datetime = datetime.fromisoformat(f"{data['booking_date']} {data['start_time']}")
        end_datetime = datetime.fromisoformat(f"{data['booking_date']} {data['end_time']}")

        # Проверка доступности
        conflicting_bookings = Booking.objects.filter(
            property=property_obj,
            status__in=['confirmed', 'pending'],
            start_datetime__lt=end_datetime,
            end_datetime__gt=start_datetime
        )

        if conflicting_bookings.exists():
            return JsonResponse({'error': 'Выбранное время уже занято.'}, status=400)

        # Создание бронирования
        booking = Booking.objects.create(
            property=property_obj,
            tenant=request.user,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            guests=data.get('guests', 1),
            special_requests=data.get('special_requests', ''),
            status='pending'
        )

        create_booking_notification(booking, 'booking_created')

        return JsonResponse({
            'success': True,
            'message': 'Бронирование отправлено на подтверждение.',
            'booking_id': booking.id,
            'redirect_url': reverse_lazy('booking_detail', args=[booking.id])
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def booking_calendar(request, property_id):
    """Календарь бронирований"""
    property_obj = get_object_or_404(Property, id=property_id)

    # Получаем месяц из запроса
    month_str = request.GET.get('month')
    if month_str:
        try:
            current_month = datetime.strptime(month_str, '%Y-%m').date()
        except ValueError:
            current_month = timezone.now().date().replace(day=1)
    else:
        current_month = timezone.now().date().replace(day=1)

    # Рассчитываем предыдущий и следующий месяцы
    if current_month.month == 1:
        prev_month = current_month.replace(year=current_month.year - 1, month=12)
    else:
        prev_month = current_month.replace(month=current_month.month - 1)

    if current_month.month == 12:
        next_month = current_month.replace(year=current_month.year + 1, month=1)
    else:
        next_month = current_month.replace(month=current_month.month + 1)

    # Получаем бронирования на месяц
    bookings = property_obj.bookings.filter(
        start_datetime__year=current_month.year,
        start_datetime__month=current_month.month,
        status__in=['confirmed', 'pending']
    ).select_related('tenant')

    # Генерируем календарь
    import calendar
    cal = calendar.Calendar()
    calendar_weeks = []

    for week in cal.monthdatescalendar(current_month.year, current_month.month):
        week_days = []
        for day in week:
            day_bookings = bookings.filter(start_datetime__date=day)
            week_days.append({
                'date': day,
                'is_today': day == timezone.now().date(),
                'has_bookings': day_bookings.exists(),
                'bookings': [{
                    'tenant': b.tenant.get_full_name_or_username(),
                    'start_time': b.start_datetime.time().strftime('%H:%M'),
                    'end_time': b.end_datetime.time().strftime('%H:%M')
                } for b in day_bookings]
            })
        calendar_weeks.append(week_days)

    # Ближайшие бронирования
    upcoming_bookings = property_obj.bookings.filter(
        start_datetime__gte=timezone.now(),
        status__in=['confirmed', 'pending']
    ).select_related('tenant').order_by('start_datetime')[:10]

    # Статистика
    month_start = current_month
    month_end = month_start + timedelta(days=calendar.monthrange(current_month.year, current_month.month)[1])

    bookings_count = bookings.count()
    total_days = (month_end - month_start).days
    booked_days = bookings.values('start_datetime__date').distinct().count()
    occupancy_rate = round((booked_days / total_days) * 100) if total_days > 0 else 0

    return render(request, 'core/booking_calendar.html', {
        'property': property_obj,
        'current_month': current_month,
        'prev_month': prev_month,
        'next_month': next_month,
        'calendar_weeks': calendar_weeks,
        'upcoming_bookings': upcoming_bookings,
        'bookings_count': bookings_count,
        'occupancy_rate': occupancy_rate,
        'title': f'Календарь бронирований - {property_obj.title}'
    })


# ============================================================================
# АДМИН-ПАНЕЛЬ
# ============================================================================

@login_required
def custom_admin_dashboard(request):
    """Кастомная админ-панель"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    # Статистика
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    stats = {
        'total_users': User.objects.count(),
        'new_users_today': User.objects.filter(date_joined__date=today).count(),
        'new_users_week': User.objects.filter(date_joined__date__gte=week_ago).count(),
        'total_properties': Property.objects.count(),
        'active_properties': Property.objects.filter(status='active').count(),
        'total_bookings': Booking.objects.count(),
        'pending_bookings': Booking.objects.filter(status='pending').count(),
        'today_bookings': Booking.objects.filter(start_datetime__date=today).count(),
        'month_revenue': Booking.objects.filter(
            status='completed',
            updated_at__gte=month_ago
        ).aggregate(total=Sum('total_price'))['total'] or 0,
    }

    # Последние действия
    recent_users = User.objects.order_by('-date_joined')[:5]
    recent_bookings = Booking.objects.select_related('property', 'tenant').order_by('-created_at')[:5]
    recent_reviews = Review.objects.select_related('property', 'user').order_by('-created_at')[:5]

    return render(request, 'core/admin/dashboard.html', {
        'stats': stats,
        'recent_users': recent_users,
        'recent_bookings': recent_bookings,
        'recent_reviews': recent_reviews,
        'title': 'Админ-панель'
    })


@login_required
def admin_user_management(request):
    """Управление пользователями"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    users = User.objects.all().order_by('-date_joined')

    # Фильтрация
    search_query = request.GET.get('search')
    user_type_filter = request.GET.get('user_type')
    status_filter = request.GET.get('status')

    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    if user_type_filter:
        users = users.filter(user_type=user_type_filter)

    if status_filter:
        if status_filter == 'active':
            users = users.filter(is_active=True)
        elif status_filter == 'inactive':
            users = users.filter(is_active=False)

    # Статистика
    stats = {
        'total_users': users.count(),
        'active_count': users.filter(is_active=True).count(),
        'inactive_count': users.filter(is_active=False).count(),
        'admin_count': users.filter(user_type='admin').count(),
        'landlord_count': users.filter(user_type='landlord').count(),
        'tenant_count': users.filter(user_type='tenant').count(),
    }

    # Пагинация
    paginator = Paginator(users, 20)
    page = request.GET.get('page')
    users_page = paginator.get_page(page)

    # Обработка действий
    if request.method == 'POST':
        action = request.POST.get('action')
        user_id = request.POST.get('user_id')

        try:
            user = User.objects.get(id=user_id)

            if action == 'toggle_active':
                user.is_active = not user.is_active
                user.save()
                status = 'активирован' if user.is_active else 'деактивирован'
                messages.success(request, f'Пользователь {user.username} {status}.')

            elif action == 'delete':
                if user == request.user:
                    messages.error(request, 'Вы не можете удалить свой аккаунт.')
                else:
                    user.delete()
                    messages.success(request, f'Пользователь {user.username} удален.')

        except User.DoesNotExist:
            messages.error(request, 'Пользователь не найден.')

        return redirect('admin_user_management')

    return render(request, 'core/admin/user_management.html', {
        'users': users_page,
        'stats': stats,
        'search_query': search_query,
        'user_type_filter': user_type_filter,
        'status_filter': status_filter,
        'title': 'Управление пользователями'
    })


@login_required
def admin_add_user(request):
    """Добавление пользователя (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Пользователь {user.username} успешно создан.')
            return redirect('admin_user_management')
    else:
        form = CustomUserCreationForm()

    return render(request, 'core/admin/add_user.html', {
        'form': form,
        'title': 'Добавление пользователя'
    })


@login_required
def admin_edit_user(request, user_id):
    """Редактирование пользователя (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        form = CustomUserChangeForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Пользователь {user.username} успешно обновлен.')
            return redirect('admin_user_management')
    else:
        form = CustomUserChangeForm(instance=user)

    return render(request, 'core/admin/edit_user.html', {
        'form': form,
        'user_obj': user,
        'title': 'Редактирование пользователя'
    })


@login_required
def admin_property_management(request):
    """Управление помещениями (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    properties = Property.objects.select_related('landlord', 'category').all().order_by('-created_at')

    # Фильтрация
    status_filter = request.GET.get('status')
    city_filter = request.GET.get('city')
    type_filter = request.GET.get('type')

    if status_filter:
        properties = properties.filter(status=status_filter)
    if city_filter:
        properties = properties.filter(city__icontains=city_filter)
    if type_filter:
        properties = properties.filter(property_type=type_filter)

    # Пагинация
    paginator = Paginator(properties, 20)
    page = request.GET.get('page')
    properties_page = paginator.get_page(page)

    return render(request, 'core/admin/property_management.html', {
        'properties': properties_page,
        'title': 'Управление помещениями'
    })


@login_required
def admin_booking_management(request):
    """Управление бронированиями (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    bookings = Booking.objects.select_related('property', 'tenant').all().order_by('-created_at')

    # Фильтрация по статусу
    status_filter = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if date_from:
        bookings = bookings.filter(start_datetime__date__gte=date_from)
    if date_to:
        bookings = bookings.filter(start_datetime__date__lte=date_to)

    # Пагинация
    paginator = Paginator(bookings, 20)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    return render(request, 'core/admin/booking_management.html', {
        'bookings': bookings_page,
        'title': 'Управление бронированиями'
    })


@login_required
def admin_review_management(request):
    """Управление отзывами (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    reviews = Review.objects.select_related('property', 'user').all().order_by('-created_at')

    # Фильтрация
    status_filter = request.GET.get('status')
    rating_filter = request.GET.get('rating')

    if status_filter:
        reviews = reviews.filter(status=status_filter)
    if rating_filter:
        reviews = reviews.filter(rating=rating_filter)

    # Пагинация
    paginator = Paginator(reviews, 20)
    page = request.GET.get('page')
    reviews_page = paginator.get_page(page)

    # Обработка действий
    if request.method == 'POST':
        action = request.POST.get('action')
        review_id = request.POST.get('review_id')

        try:
            review = Review.objects.get(id=review_id)

            if action == 'approve':
                review.status = 'approved'
                review.save()
                messages.success(request, 'Отзыв одобрен.')

            elif action == 'reject':
                review.status = 'rejected'
                review.save()
                messages.success(request, 'Отзыв отклонен.')

            elif action == 'delete':
                review.delete()
                messages.success(request, 'Отзыв удален.')

        except Review.DoesNotExist:
            messages.error(request, 'Отзыв не найден.')

        return redirect('admin_review_management')

    return render(request, 'core/admin/review_management.html', {
        'reviews': reviews_page,
        'title': 'Управление отзывами'
    })


@login_required
def export_users_csv(request):
    """Экспорт пользователей в CSV"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Имя пользователя', 'Email', 'Имя', 'Фамилия', 'Тип', 'Статус', 'Дата регистрации'])

    users = User.objects.all().order_by('-date_joined')
    for user in users:
        writer.writerow([
            user.id,
            user.username,
            user.email,
            user.first_name or '',
            user.last_name or '',
            user.get_user_type_display(),
            'Активен' if user.is_active else 'Неактивен',
            user.date_joined.strftime('%Y-%m-%d %H:%M')
        ])

    return response


# ============================================================================
# ДОПОЛНИТЕЛЬНЫЕ АДМИН-ФУНКЦИИ
# ============================================================================

@login_required
def admin_add_property(request):
    """Добавление помещения (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES)
        if form.is_valid():
            property_obj = form.save()

            # Сохраняем изображения
            images = request.FILES.getlist('images')
            for image in images:
                property_obj.images.create(image=image)

            messages.success(request, 'Помещение успешно добавлено.')
            return redirect('admin_property_management')
    else:
        form = PropertyForm()

    return render(request, 'core/admin/add_property.html', {
        'form': form,
        'title': 'Добавление помещения'
    })


@login_required
def admin_edit_property(request, property_id):
    """Редактирование помещения (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    property_obj = get_object_or_404(Property, id=property_id)

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES, instance=property_obj)
        if form.is_valid():
            property_obj = form.save()

            # Обновляем изображения
            images = request.FILES.getlist('images')
            for image in images:
                property_obj.images.create(image=image)

            messages.success(request, 'Помещение успешно обновлено.')
            return redirect('admin_property_management')
    else:
        form = PropertyForm(instance=property_obj)

    return render(request, 'core/admin/edit_property.html', {
        'form': form,
        'property': property_obj,
        'existing_images': property_obj.images.all(),
        'title': 'Редактирование помещения'
    })


@login_required
def admin_edit_booking(request, booking_id):
    """Редактирование бронирования (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    booking = get_object_or_404(Booking, id=booking_id)

    if request.method == 'POST':
        from .forms import BookingForm
        form = BookingForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            messages.success(request, 'Бронирование успешно обновлено.')
            return redirect('admin_booking_management')
    else:
        from .forms import BookingForm
        form = BookingForm(instance=booking)

    return render(request, 'core/admin/edit_booking.html', {
        'form': form,
        'booking': booking,
        'title': 'Редактирование бронирования'
    })


@login_required
def admin_edit_review(request, review_id):
    """Редактирование отзыва (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    review = get_object_or_404(Review, id=review_id)

    if request.method == 'POST':
        from .forms import ReviewForm
        form = ReviewForm(request.POST, instance=review)
        if form.is_valid():
            form.save()
            messages.success(request, 'Отзыв успешно обновлен.')
            return redirect('admin_review_management')
    else:
        from .forms import ReviewForm
        form = ReviewForm(instance=review)

    return render(request, 'core/admin/edit_review.html', {
        'form': form,
        'review': review,
        'title': 'Редактирование отзыва'
    })


@login_required
def admin_system_settings(request):
    """Настройки системы (админ)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    return render(request, 'core/admin/system_settings.html', {
        'title': 'Настройки системы'
    })