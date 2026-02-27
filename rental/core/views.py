from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.http import JsonResponse, HttpResponse, FileResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg, Sum, F
from django.urls import reverse_lazy
from django.conf import settings
import json
from datetime import datetime, timedelta
import csv
import io
import os
import logging

# Импорты моделей
from .models import (
    User, Property, Booking, Review, Favorite,
    Category, Amenity, Notification, Message, Cart, Contract
)
# Импорты форм
from .forms import (
    CustomUserCreationForm, CustomUserChangeForm,
    PropertyForm, BookingForm, ReviewForm,
    ContactForm, CartBookingForm, CheckoutForm,
    AdminUserEditForm, AdminPropertyEditForm,
    AdminBookingEditForm, AdminReviewEditForm,
    SearchForm, PaymentCardForm
)

# Настройка логирования
logger = logging.getLogger(__name__)


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def get_time_ago(dt):
    """Возвращает красивое представление времени для AJAX-превью"""
    if not dt:
        return 'только что'

    now = timezone.now()
    diff = now - dt

    if diff < timedelta(minutes=1):
        return 'только что'
    elif diff < timedelta(hours=1):
        return f'{diff.seconds // 60} мин. назад'
    elif diff < timedelta(days=1):
        return f'{diff.seconds // 3600} ч. назад'
    elif diff < timedelta(days=7):
        return f'{diff.days} дн. назад'
    else:
        return dt.strftime('%d.%m.%Y')


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
    elif notification_type in ['booking_paid', 'booking_confirmed', 'booking_cancelled']:
        user = booking.tenant
    elif notification_type == 'booking_completed':
        user = booking.property.landlord
    else:
        return None

    title_map = {
        'booking_created': 'Новое бронирование',
        'booking_paid': 'Бронирование оплачено',
        'booking_confirmed': 'Бронирование подтверждено',
        'booking_cancelled': 'Бронирование отменено',
        'booking_completed': 'Бронирование завершено',
    }
    message_map = {
        'booking_created': f'Новый запрос на бронирование помещения "{booking.property.title}" на {booking.start_datetime.strftime("%d.%m.%Y %H:%M")}',
        'booking_paid': f'Бронирование #{booking.booking_id} оплачено. Ожидает подтверждения владельцем.',
        'booking_confirmed': f'Ваше бронирование #{booking.booking_id} подтверждено',
        'booking_cancelled': f'Бронирование #{booking.booking_id} отменено',
        'booking_completed': f'Бронирование #{booking.booking_id} завершено. Пожалуйста, оставьте отзыв.',
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


def generate_contract_pdf(booking):
    """
    Генерация PDF договора для бронирования
    Требуется установка: pip install reportlab
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from django.core.files.base import ContentFile

        # Создаем буфер
        buffer = io.BytesIO()
        # Создаем PDF документ
        doc = SimpleDocTemplate(buffer, pagesize=A4)

        # === РЕГИСТРАЦИЯ ШРИФТА С КИРИЛЛИЦЕЙ ===
        # Путь к шрифту в корне проекта
        font_path = os.path.join(settings.BASE_DIR, 'dejavu-sans-book.ttf')

        if os.path.exists(font_path):
            # Регистрируем шрифт
            pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
            font_name = 'DejaVuSans'
        else:
            logger.error(f"Шрифт не найден: {font_path}")
            font_name = 'Helvetica'  # Запасной вариант (без кириллицы)

        # Создаем стили с кириллическим шрифтом
        styles = getSampleStyleSheet()

        # Добавляем свои стили с правильным шрифтом
        styles.add(ParagraphStyle(
            name='NormalCyrillic',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10,
            leading=12,
            alignment=0
        ))

        styles.add(ParagraphStyle(
            name='Heading2Cyrillic',
            parent=styles['Heading2'],
            fontName=font_name,
            fontSize=12,
            leading=14,
            spaceBefore=12,
            spaceAfter=6,
            alignment=0
        ))

        styles.add(ParagraphStyle(
            name='TitleCyrillic',
            parent=styles['Title'],
            fontName=font_name,
            fontSize=14,
            leading=16,
            spaceAfter=12,
            alignment=1  # По центру
        ))
        # ===========================================

        elements = []

        # Заголовок
        elements.append(Paragraph(f"ДОГОВОР АРЕНДЫ №{booking.booking_id}", styles['TitleCyrillic']))
        elements.append(Spacer(1, 12))

        # Дата
        elements.append(Paragraph(f"г. Москва, {timezone.now().strftime('%d.%m.%Y')}", styles['NormalCyrillic']))
        elements.append(Spacer(1, 24))

        # Информация о сторонах
        landlord = booking.property.landlord
        tenant = booking.tenant
        landlord_info = f"Арендодатель: {landlord.get_full_name_or_username()}, {landlord.email or 'Email не указан'}, {landlord.phone or 'Тел. не указан'}"
        tenant_info = f"Арендатор: {tenant.get_full_name_or_username()}, {tenant.email or 'Email не указан'}, {tenant.phone or 'Тел. не указан'}"

        elements.append(Paragraph("1. СТОРОНЫ ДОГОВОРА", styles['Heading2Cyrillic']))
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(landlord_info, styles['NormalCyrillic']))
        elements.append(Paragraph(tenant_info, styles['NormalCyrillic']))
        elements.append(Spacer(1, 12))

        # Предмет договора
        elements.append(Paragraph("2. ПРЕДМЕТ ДОГОВОРА", styles['Heading2Cyrillic']))
        elements.append(Spacer(1, 6))
        elements.append(
            Paragraph(f"Арендодатель передает, а Арендатор принимает во временное владение и пользование помещение:",
                      styles['NormalCyrillic']))
        elements.append(Paragraph(f"Название: {booking.property.title}", styles['NormalCyrillic']))
        elements.append(
            Paragraph(f"Адрес: {booking.property.address}, {booking.property.city}", styles['NormalCyrillic']))
        elements.append(
            Paragraph(f"Площадь: {booking.property.area} кв.м., вместимость: {booking.property.capacity} чел.",
                      styles['NormalCyrillic']))
        elements.append(Spacer(1, 12))

        # Срок аренды
        elements.append(Paragraph("3. СРОК АРЕНДЫ", styles['Heading2Cyrillic']))
        elements.append(Spacer(1, 6))
        start_str = booking.start_datetime.strftime('%d.%m.%Y %H:%M')
        end_str = booking.end_datetime.strftime('%d.%m.%Y %H:%M')
        elements.append(Paragraph(f"Начало: {start_str}", styles['NormalCyrillic']))
        elements.append(Paragraph(f"Окончание: {end_str}", styles['NormalCyrillic']))
        elements.append(Spacer(1, 12))

        # Платежи
        elements.append(Paragraph("4. ПЛАТЕЖИ", styles['Heading2Cyrillic']))
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(f"Общая стоимость аренды: {booking.total_price} рублей", styles['NormalCyrillic']))
        elements.append(
            Paragraph(f"Статус оплаты: {'Оплачено' if booking.is_paid else 'Ожидает оплаты'}",
                      styles['NormalCyrillic']))
        elements.append(Spacer(1, 12))

        # Подписи - ИСПРАВЛЕННАЯ ТАБЛИЦА
        elements.append(Paragraph("5. ПОДПИСИ СТОРОН", styles['Heading2Cyrillic']))
        elements.append(Spacer(1, 30))

        # Создаем таблицу с правильными отступами
        data = [
            ['Арендодатель:', '______________________', 'Арендатор:', '______________________'],
            ['', f'({landlord.get_full_name_or_username()})', '', f'({tenant.get_full_name_or_username()})']
        ]
        table = Table(data, colWidths=[50 * mm, 55 * mm, 50 * mm, 55 * mm])
        table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('ALIGN', (3, 0), (3, 0), 'CENTER'),
            ('ALIGN', (1, 1), (1, 1), 'CENTER'),
            ('ALIGN', (3, 1), (3, 1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONT', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(table)

        # Сборка PDF
        doc.build(elements)
        buffer.seek(0)

        # Сохраняем в модель
        contract, created = Contract.objects.get_or_create(booking=booking)
        if not created and contract.pdf_file:
            contract.pdf_file.delete(save=False)

        filename = f"contract_{booking.booking_id}.pdf"
        contract.pdf_file.save(filename, ContentFile(buffer.getvalue()), save=True)

        return contract

    except ImportError:
        # Если reportlab не установлен, создаем текстовый файл
        contract, created = Contract.objects.get_or_create(booking=booking)
        landlord = booking.property.landlord
        tenant = booking.tenant
        content = f"""
ДОГОВОР АРЕНДЫ №{booking.booking_id}
Дата: {timezone.now().strftime('%d.%m.%Y')}

1. СТОРОНЫ ДОГОВОРА
Арендодатель: {landlord.get_full_name_or_username()}, {landlord.email}, {landlord.phone}
Арендатор: {tenant.get_full_name_or_username()}, {tenant.email}, {tenant.phone}

2. ПРЕДМЕТ ДОГОВОРА
Помещение: {booking.property.title}
Адрес: {booking.property.address}, {booking.property.city}

3. СРОК АРЕНДЫ
С {booking.start_datetime.strftime('%d.%m.%Y %H:%M')} по {booking.end_datetime.strftime('%d.%m.%Y %H:%M')}

4. ПЛАТЕЖИ
Стоимость: {booking.total_price} рублей

5. ПОДПИСИ СТОРОН
Арендодатель: ______________________
Арендатор: ______________________
"""
        from django.core.files.base import ContentFile
        filename = f"contract_{booking.booking_id}.txt"
        contract.pdf_file.save(filename, ContentFile(content.encode('utf-8')), save=True)
        return contract


def auto_cancel_expired_bookings():
    """
    Автоматически отменяет бронирования, не оплаченные в течение 30 минут
    """
    expiration_time = timezone.now() - timedelta(minutes=30)
    expired_bookings = Booking.objects.filter(
        status='pending',
        created_at__lte=expiration_time
    )
    count = expired_bookings.count()
    for booking in expired_bookings:
        booking.status = 'cancelled'
        booking.save()
        # Создаем уведомление для арендатора
        create_notification(
            user=booking.tenant,
            notification_type='booking_cancelled',
            title='Бронирование отменено',
            message=f'Бронирование #{booking.booking_id} автоматически отменено из-за истечения времени оплаты.',
            related_object_id=booking.id,
            related_object_type='booking'
        )
        logger.info(f"Booking #{booking.booking_id} auto-cancelled (created at {booking.created_at})")

    if count > 0:
        logger.info(f"Auto-cancelled {count} expired bookings")
    return count


# ============================================================================
# ПУБЛИЧНЫЕ СТРАНИЦЫ
# ============================================================================

def home(request):
    """Главная страница"""
    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    properties = Property.objects.filter(
        status='active',
        is_featured=True
    ).select_related('landlord', 'category')[:5]

    context = {
        'properties': properties,
        'title': 'Аренда коммерческих помещений'
    }
    return render(request, 'core/home.html', context)


def property_list(request):
    """Список всех помещений с пагинацией (5 на странице)"""
    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    properties = Property.objects.filter(status='active').select_related('landlord', 'category')

    # Фильтрация по параметрам
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

    # Фильтр "Только доступные"
    show_available_only = request.GET.get('available_only') == 'on'
    selected_date = request.GET.get('date')
    selected_time = request.GET.get('time')

    if show_available_only:
        # Если дата не указана, используем сегодня
        if not selected_date:
            selected_date = timezone.now().date().isoformat()
        # Если время не указано, используем текущее + 1 час
        if not selected_time:
            now = timezone.now()
            start_dt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            selected_time = start_dt.strftime('%H:%M')

        try:
            start_datetime = timezone.make_aware(datetime.strptime(
                f"{selected_date} {selected_time}", "%Y-%m-%d %H:%M"
            ))
            end_datetime = start_datetime + timedelta(hours=1)

            booked_property_ids = Booking.objects.filter(
                status__in=['pending', 'paid', 'confirmed'],
                start_datetime__lt=end_datetime,
                end_datetime__gt=start_datetime
            ).values_list('property_id', flat=True)
            properties = properties.exclude(id__in=booked_property_ids)
        except ValueError:
            pass

    # Пагинация - 5 элементов на странице
    paginator = Paginator(properties, 6)
    page = request.GET.get('page')
    properties_page = paginator.get_page(page)

    context = {
        'properties': properties_page,
        'property_types': dict(Property.PROPERTY_TYPE_CHOICES),
        'categories': Category.objects.all(),
        'title': 'Все помещения для аренды',
        'today': timezone.now().date().isoformat(),
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

    # Получаем только одобренные отзывы с пагинацией (5 на странице)
    reviews = Review.objects.filter(
        property=property_obj,
        status='approved'
    ).select_related('user').order_by('-created_at')

    # Пагинация для отзывов - 5 на странице
    reviews_paginator = Paginator(reviews, 5)
    reviews_page = request.GET.get('reviews_page')
    reviews_page_obj = reviews_paginator.get_page(reviews_page)

    # Проверяем, добавлено ли помещение в избранное
    is_favorite = False
    if request.user.is_authenticated:
        is_favorite = Favorite.objects.filter(
            user=request.user,
            property=property_obj
        ).exists()

    # Проверяем, есть ли в корзине
    in_cart = False
    if request.user.is_authenticated:
        in_cart = Cart.objects.filter(
            user=request.user,
            property=property_obj
        ).exists()

    # Готовим данные календаря на 30 дней
    today = timezone.now().date()
    calendar_data = []
    booked_dates = []

    bookings = property_obj.bookings.filter(
        status__in=['pending', 'paid', 'confirmed'],
        start_datetime__date__gte=today,
        start_datetime__date__lte=today + timedelta(days=30)
    )

    for booking in bookings:
        booking_date = booking.start_datetime.date()
        if booking_date not in booked_dates:
            booked_dates.append(booking_date)

    for i in range(30):
        current_date = today + timedelta(days=i)
        calendar_data.append({
            'date': current_date,
            'bookings': bookings.filter(start_datetime__date=current_date).exists()
        })

    # Похожие помещения (максимум 5)
    similar_properties = Property.objects.filter(
        status='active',
        property_type=property_obj.property_type,
        city=property_obj.city
    ).exclude(id=property_obj.id).select_related('landlord')[:5]

    context = {
        'property': property_obj,
        'reviews': reviews_page_obj,
        'is_favorite': is_favorite,
        'in_cart': in_cart,
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
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, 'Регистрация успешно завершена!')
                return redirect('dashboard')
            else:
                messages.error(request, 'Ошибка аутентификации.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = CustomUserCreationForm()

    return render(request, 'core/register.html', {'form': form, 'title': 'Регистрация'})


# ============================================================================
# ЛИЧНЫЙ КАБИНЕТ
# ============================================================================

@login_required
def dashboard(request):
    """Личный кабинет"""
    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    context = {'title': 'Личный кабинет'}
    user = request.user

    if user.user_type == 'tenant':
        # Для арендатора
        bookings = user.bookings_as_tenant.select_related('property').order_by('-created_at')
        active_bookings = bookings.filter(status__in=['pending', 'paid', 'confirmed'])

        # Статистика
        stats = {
            'total_bookings': bookings.count(),
            'active_bookings': active_bookings.count(),
            'completed_bookings': bookings.filter(status='completed').count(),
            'total_spent': bookings.filter(status='completed').aggregate(
                total=Sum('total_price')
            )['total'] or 0,
            'favorite_count': user.favorites.count(),
            'cart_count': Cart.objects.filter(user=user).count(),
        }

        # Избранные помещения (максимум 5)
        favorite_properties = list(user.favorites.select_related('property').all()[:5])
        # Активные бронирования (максимум 5)
        safe_active_bookings = list(active_bookings[:5])

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
            status__in=['paid', 'confirmed', 'completed'],
            updated_at__gte=timezone.now() - timedelta(days=30)
        ).aggregate(total=Sum('total_price'))['total'] or 0

        stats = {
            'total_properties': len(properties),
            'active_properties': len([p for p in properties if p.status == 'active']),
            'pending_properties': len([p for p in properties if p.status == 'pending']),
            'total_bookings': bookings.count(),
            'pending_bookings': bookings.filter(status='pending').count(),
            'paid_bookings': bookings.filter(status='paid').count(),
            'monthly_revenue': monthly_revenue,
            'avg_rating': Review.objects.filter(
                property__landlord=user,
                status='approved'
            ).aggregate(avg=Avg('rating'))['avg'] or 0,
            'reviews_count': Review.objects.filter(
                property__landlord=user,
                status='approved'
            ).count(),
        }

        # Мои помещения (максимум 5)
        safe_properties = properties[:5]
        # Новые бронирования (максимум 5)
        new_bookings = list(bookings.filter(status='pending').order_by('-created_at')[:5])
        # Активные бронирования (максимум 5)
        active_bookings = list(bookings.filter(
            status__in=['paid', 'confirmed'],
            start_datetime__gte=timezone.now()
        ).order_by('start_datetime')[:5])

        context.update({
            'stats': stats,
            'properties': safe_properties,
            'new_bookings': new_bookings,
            'active_bookings': active_bookings,
            'has_new_bookings': len(new_bookings) > 0,
            'has_active_bookings': len(active_bookings) > 0,
        })

    elif user.user_type == 'admin' or user.is_staff:
        # Для администратора
        stats = {
            'total_users': User.objects.count(),
            'new_users_today': User.objects.filter(date_joined__date=timezone.now().date()).count(),
            'total_properties': Property.objects.count(),
            'active_properties': Property.objects.filter(status='active').count(),
            'pending_properties': Property.objects.filter(status='pending').count(),
            'total_bookings': Booking.objects.count(),
            'pending_bookings': Booking.objects.filter(status='pending').count(),
            'paid_bookings': Booking.objects.filter(status='paid').count(),
            'today_bookings': Booking.objects.filter(start_datetime__date=timezone.now().date()).count(),
            'month_revenue': Booking.objects.filter(
                status__in=['paid', 'confirmed', 'completed'],
                updated_at__gte=timezone.now() - timedelta(days=30)
            ).aggregate(total=Sum('total_price'))['total'] or 0,
        }

        # Последние записи (максимум 5)
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
            login(request, user)
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
    """Мои бронирования с пагинацией (5 на странице)"""
    if request.user.user_type != 'tenant':
        messages.error(request, 'Эта страница доступна только арендаторам.')
        return redirect('dashboard')

    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    bookings = request.user.bookings_as_tenant.select_related('property').order_by('-created_at')

    # Фильтрация по статусу
    status_filter = request.GET.get('status')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    # Пагинация - 5 элементов на странице
    paginator = Paginator(bookings, 5)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    # Статистика по статусам для фильтра
    status_stats = {
        'total': bookings.count(),
        'pending': bookings.filter(status='pending').count(),
        'paid': bookings.filter(status='paid').count(),
        'confirmed': bookings.filter(status='confirmed').count(),
        'completed': bookings.filter(status='completed').count(),
        'cancelled': bookings.filter(status='cancelled').count(),
    }

    return render(request, 'core/my_bookings.html', {
        'bookings': bookings_page,
        'status_stats': status_stats,
        'current_status': status_filter,
        'title': 'Мои бронирования'
    })


@login_required
def my_favorites(request):
    """Избранные помещения с пагинацией (5 на странице)"""
    favorites = request.user.favorites.select_related('property').all().order_by('-created_at')

    # Пагинация - 5 элементов на странице
    paginator = Paginator(favorites, 5)
    page = request.GET.get('page')
    favorites_page = paginator.get_page(page)

    return render(request, 'core/my_favorites.html', {
        'favorites': favorites_page,
        'title': 'Избранное'
    })


@login_required
def my_properties(request):
    """Мои помещения (для арендодателей) с пагинацией (5 на странице)"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Эта страница доступна только арендодателям.')
        return redirect('dashboard')

    properties = request.user.properties.select_related('category').all().order_by('-created_at')

    # Фильтрация по статусу
    status_filter = request.GET.get('status')
    if status_filter:
        properties = properties.filter(status=status_filter)

    # Статистика
    stats = {
        'active_count': properties.filter(status='active').count(),
        'pending_count': properties.filter(status='pending').count(),
        'featured_count': properties.filter(is_featured=True).count(),
        'booked_count': Booking.objects.filter(
            property__in=properties,
            status__in=['paid', 'confirmed']
        ).count(),
    }

    # Пагинация - 5 элементов на странице
    paginator = Paginator(properties, 5)
    page = request.GET.get('page')
    properties_page = paginator.get_page(page)

    return render(request, 'core/my_properties.html', {
        'properties': properties_page,
        'stats': stats,
        'current_status': status_filter,
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
    property_obj = get_object_or_404(Property, id=property_id, status='active')

    if request.user.user_type != 'tenant':
        messages.error(request, 'Только арендаторы могут создавать бронирования.')
        return redirect('property_detail', slug=property_obj.slug)

    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    if request.method == 'POST':
        form = BookingForm(request.POST, property_obj=property_obj)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.property = property_obj
            booking.tenant = request.user
            booking.status = 'pending'
            booking.save()

            create_booking_notification(booking, 'booking_created')
            messages.success(request, 'Бронирование создано. Перейдите к оплате в течение 30 минут.')
            return redirect('payment', booking_id=booking.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{error}')
    else:
        form = BookingForm(property_obj=property_obj)

    context = {
        'form': form,
        'property': property_obj,
        'title': 'Бронирование помещения'
    }
    return render(request, 'core/create_booking.html', context)


@login_required
def booking_detail(request, booking_id):
    """Детали бронирования"""
    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    booking = get_object_or_404(
        Booking.objects.select_related('property', 'property__landlord', 'tenant'),
        id=booking_id
    )

    if request.user != booking.tenant and request.user != booking.property.landlord:
        messages.error(request, 'У вас нет доступа к этому бронированию.')
        return redirect('dashboard')

    can_cancel = (
            request.user == booking.tenant and
            booking.status in ['pending', 'paid'] and
            booking.start_datetime > timezone.now()
    )

    can_review = (
            request.user == booking.tenant and
            booking.status == 'completed' and
            not Review.objects.filter(property=booking.property, user=request.user).exists()
    )

    can_pay = (
            request.user == booking.tenant and
            booking.status == 'pending'
    )

    can_download_contract = (
            booking.status in ['paid', 'confirmed', 'completed'] and
            (request.user == booking.tenant or request.user == booking.property.landlord)
    )

    has_contract = Contract.objects.filter(booking=booking).exists()

    days_count = (booking.end_datetime.date() - booking.start_datetime.date()).days + 1
    hours_count = (booking.end_datetime - booking.start_datetime).total_seconds() / 3600

    # Рассчитываем оставшееся время для оплаты
    time_left = None
    if booking.status == 'pending':
        time_elapsed = timezone.now() - booking.created_at
        time_left = max(0, 30 - time_elapsed.total_seconds() / 60)

    return render(request, 'core/booking_detail.html', {
        'booking': booking,
        'can_cancel': can_cancel,
        'can_review': can_review,
        'can_pay': can_pay,
        'can_download_contract': can_download_contract,
        'has_contract': has_contract,
        'days_count': days_count,
        'hours_count': hours_count,
        'time_left': time_left,
        'title': f'Бронирование #{booking.booking_id}'
    })


@login_required
def cancel_booking(request, booking_id):
    """Отмена бронирования"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'Вы не можете отменить это бронирование.')
        return redirect('dashboard')

    if booking.status not in ['pending', 'paid']:
        messages.error(request, 'Это бронирование нельзя отменить.')
        return redirect('booking_detail', booking_id=booking_id)

    if booking.start_datetime <= timezone.now():
        messages.error(request, 'Нельзя отменить начавшееся бронирование.')
        return redirect('booking_detail', booking_id=booking_id)

    booking.status = 'cancelled'
    booking.save()

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
            review.booking = booking
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
# КОРЗИНА
# ============================================================================

@login_required
def cart_add(request, property_id):
    """Добавление помещения в корзину"""
    property_obj = get_object_or_404(Property, id=property_id, status='active')

    if request.user.user_type != 'tenant':
        messages.error(request, 'Только арендаторы могут добавлять в корзину.')
        return redirect('property_detail', slug=property_obj.slug)

    if request.method == 'POST':
        form = CartBookingForm(request.POST, property_obj=property_obj)
        if form.is_valid():
            start_datetime = form.cleaned_data['start_datetime']
            end_datetime = form.cleaned_data['end_datetime']
            guests = form.cleaned_data['guests']
            special_requests = form.cleaned_data.get('special_requests', '')

            # Проверяем, нет ли уже такого в корзине
            cart_item, created = Cart.objects.get_or_create(
                user=request.user,
                property=property_obj,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                defaults={
                    'guests': guests,
                    'special_requests': special_requests
                }
            )

            if created:
                messages.success(request, f'Помещение "{property_obj.title}" добавлено в корзину.')
            else:
                messages.info(request, f'Это помещение уже есть в корзине с такими же датами.')

            return redirect('cart_detail')
    else:
        form = CartBookingForm(property_obj=property_obj)

    context = {
        'form': form,
        'property': property_obj,
        'title': 'Добавление в корзину'
    }
    return render(request, 'core/cart_add.html', context)


@login_required
def cart_remove(request, item_id):
    """Удаление элемента из корзины"""
    cart_item = get_object_or_404(Cart, id=item_id, user=request.user)
    property_title = cart_item.property.title
    cart_item.delete()
    messages.success(request, f'Помещение "{property_title}" удалено из корзины.')
    return redirect('cart_detail')


@login_required
def cart_detail(request):
    """Просмотр корзины"""
    cart_items = Cart.objects.filter(user=request.user).select_related('property')
    total_amount = sum(item.get_total_price() for item in cart_items)

    context = {
        'cart_items': cart_items,
        'total_amount': total_amount,
        'title': 'Корзина'
    }
    return render(request, 'core/cart_detail.html', context)


@login_required
def checkout(request):
    """Оформление заказа (создание нескольких бронирований)"""
    if request.user.user_type != 'tenant':
        messages.error(request, 'Только арендаторы могут оформлять заказы.')
        return redirect('cart_detail')

    cart_items = Cart.objects.filter(user=request.user).select_related('property')

    if not cart_items.exists():
        messages.warning(request, 'Ваша корзина пуста.')
        return redirect('cart_detail')

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            # Создаем бронирования для каждого элемента корзины
            bookings_created = []
            for item in cart_items:
                booking = Booking.objects.create(
                    property=item.property,
                    tenant=request.user,
                    start_datetime=item.start_datetime,
                    end_datetime=item.end_datetime,
                    guests=item.guests,
                    special_requests=item.special_requests,
                    total_price=item.get_total_price(),
                    status='pending'
                )
                bookings_created.append(booking)
                create_booking_notification(booking, 'booking_created')

            # Очищаем корзину
            cart_items.delete()

            if len(bookings_created) == 1:
                messages.success(request,
                                 f'Бронирование #{bookings_created[0].booking_id} создано. Перейдите к оплате.')
                return redirect('payment', booking_id=bookings_created[0].id)
            else:
                messages.success(request, f'Создано {len(bookings_created)} бронирований. Перейдите к оплате.')
                return redirect('my_bookings')
    else:
        form = CheckoutForm()

    total_price = sum(item.get_total_price() for item in cart_items)

    context = {
        'form': form,
        'cart_items': cart_items,
        'total_price': total_price,
        'title': 'Оформление заказа'
    }
    return render(request, 'core/checkout.html', context)


# ============================================================================
# ОПЛАТА
# ============================================================================

@login_required
def payment(request, booking_id):
    """Страница оплаты бронирования"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'У вас нет доступа к этому бронированию.')
        return redirect('dashboard')

    if booking.status != 'pending':
        messages.warning(request, 'Это бронирование уже оплачено или обработано.')
        return redirect('booking_detail', booking_id=booking.id)

    # Проверка времени (30 минут) - только для оплаты картой
    time_elapsed = timezone.now() - booking.created_at
    time_left = timedelta(minutes=30) - time_elapsed

    if request.method == 'POST':
        form = PaymentCardForm(request.POST)
        if form.is_valid():
            payment_method = form.cleaned_data['payment_method']

            if payment_method == 'card':
                # Проверка времени только для карты
                if time_elapsed > timedelta(minutes=30):
                    booking.status = 'cancelled'
                    booking.save()
                    messages.error(request, 'Время для оплаты истекло. Бронирование автоматически отменено.')
                    return redirect('booking_detail', booking_id=booking.id)

                # Оплата картой
                booking.status = 'paid'
                booking.is_paid = True
                booking.payment_date = timezone.now()
                booking.save()

                create_booking_notification(booking, 'booking_paid')
                create_notification(
                    user=booking.property.landlord,
                    notification_type='booking_paid',
                    title='Бронирование оплачено',
                    message=f'Бронирование #{booking.booking_id} для помещения "{booking.property.title}" оплачено картой и ожидает подтверждения.',
                    related_object_id=booking.id,
                    related_object_type='booking'
                )

                try:
                    generate_contract_pdf(booking)
                except Exception as e:
                    logger.error(f"Error generating contract: {e}")

                messages.success(request,
                                 'Оплата прошла успешно! Договор будет доступен после подтверждения бронирования владельцем.')
                return redirect('payment_success', booking_id=booking.id)

            elif payment_method == 'cash':
                # Оплата наличными при встрече - таймер не проверяем
                # Просто создаем бронирование без оплаты

                # Уведомление владельцу
                create_notification(
                    user=booking.property.landlord,
                    notification_type='booking_created',
                    title='Новое бронирование (оплата наличными)',
                    message=f'Новое бронирование #{booking.booking_id} для помещения "{booking.property.title}". Клиент оплатит наличными при встрече.',
                    related_object_id=booking.id,
                    related_object_type='booking'
                )
                # Уведомление арендатору
                create_notification(
                    user=booking.tenant,
                    notification_type='booking_created',
                    title='Бронирование создано (оплата наличными)',
                    message=f'Ваше бронирование #{booking.booking_id} создано. Статус: ожидает оплаты при встрече. Свяжитесь с владельцем для подтверждения.',
                    related_object_id=booking.id,
                    related_object_type='booking'
                )

                messages.success(request,
                                 'Бронирование создано! Статус: ожидает оплаты при встрече. Свяжитесь с владельцем для подтверждения.')
                return redirect('booking_detail', booking_id=booking.id)
            else:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f'{error}')
    else:
        form = PaymentCardForm()

    # Для GET запроса показываем таймер только если не истекло время
    if time_elapsed > timedelta(minutes=30):
        booking.status = 'cancelled'
        booking.save()
        messages.error(request, 'Время для оплаты истекло. Бронирование автоматически отменено.')
        return redirect('booking_detail', booking_id=booking.id)

    time_left_seconds = max(0, int(time_left.total_seconds()))
    minutes_left = time_left_seconds // 60
    seconds_left = time_left_seconds % 60

    context = {
        'booking': booking,
        'form': form,
        'time_left_minutes': minutes_left,
        'time_left_seconds': seconds_left,
        'time_left_total': time_left_seconds,
        'title': f'Оплата бронирования #{booking.booking_id}'
    }
    return render(request, 'core/payment.html', context)


@login_required
def payment_success(request, booking_id):
    """Страница успешной оплаты"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'У вас нет доступа к этому бронированию.')
        return redirect('dashboard')

    return render(request, 'core/payment_success.html', {
        'booking': booking,
        'title': 'Оплата прошла успешно'
    })


# ============================================================================
# ДОГОВОРЫ
# ============================================================================

@login_required
def download_contract(request, booking_id):
    """Скачивание договора"""
    booking = get_object_or_404(Booking, id=booking_id)

    if not (request.user == booking.tenant or request.user == booking.property.landlord or request.user.is_staff):
        messages.error(request, 'У вас нет прав для скачивания этого договора.')
        return redirect('dashboard')

    if booking.status not in ['paid', 'confirmed', 'completed']:
        messages.error(request, 'Договор доступен только для оплаченных бронирований.')
        return redirect('booking_detail', booking_id=booking.id)

    # Получаем или генерируем договор
    try:
        contract = Contract.objects.get(booking=booking)
    except Contract.DoesNotExist:
        contract = generate_contract_pdf(booking)

    if contract.pdf_file:
        response = FileResponse(contract.pdf_file.open('rb'), as_attachment=True)
        filename = f"contract_{booking.booking_id}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    else:
        messages.error(request, 'Файл договора не найден.')
        return redirect('booking_detail', booking_id=booking.id)


# ============================================================================
# УВЕДОМЛЕНИЯ (ИСПРАВЛЕНО ДЛЯ AJAX)
# ============================================================================

@login_required
def notifications_list(request):
    """Страница со списком уведомлений с пагинацией (5 на странице)"""
    notifications = request.user.notifications.all().order_by('-created_at')

    # === AJAX ОБРАБОТКА ДЛЯ ПРЕВЬЮ В DROPDOWN ===
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        limit = int(request.GET.get('limit', 5))
        notifications_qs = notifications[:limit]

        notifications_data = []
        for notif in notifications_qs:
            # Определяем URL для перехода
            url = '#'
            if notif.related_object_type == 'booking' and notif.related_object_id:
                url = reverse_lazy('booking_detail', args=[notif.related_object_id])
            elif notif.related_object_type == 'message' and notif.related_object_id:
                url = reverse_lazy('messages_list')
            elif notif.notification_type == 'system':
                url = reverse_lazy('dashboard')

            notifications_data.append({
                'id': notif.id,
                'title': notif.title or 'Уведомление',
                'message': notif.message or '',
                'is_read': notif.is_read,
                'url': url,
                'time_ago': get_time_ago(notif.created_at),
                'notification_type': notif.notification_type,
            })

        return JsonResponse({
            'notifications': notifications_data,
            'unread_count': notifications.filter(is_read=False).count()
        })
    # === КОНЕЦ AJAX ОБРАБОТКИ ===

    # Пагинация - 5 элементов на странице (для HTML-страницы)
    paginator = Paginator(notifications, 5)
    page = request.GET.get('page')
    notifications_page = paginator.get_page(page)

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


@login_required
def get_unread_messages_count(request):
    """Получить количество непрочитанных сообщений (AJAX)"""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        count = Message.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        return JsonResponse({'count': count})
    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# СООБЩЕНИЯ (ИСПРАВЛЕНО ДЛЯ AJAX)
# ============================================================================

@login_required
def messages_list(request):
    """Страница со списком сообщений/диалогов с пагинацией (5 на странице)"""

    # === AJAX ОБРАБОТКА ДЛЯ ПРЕВЬЮ В DROPDOWN ===
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        limit = int(request.GET.get('limit', 5))

        # Получаем последние сообщения пользователя
        messages_qs = Message.objects.filter(
            Q(sender=request.user) | Q(recipient=request.user)
        ).select_related('sender', 'recipient', 'property').order_by('-created_at')[:limit]

        messages_data = []
        for msg in messages_qs:
            # Определяем отправителя для отображения
            sender = msg.sender if msg.sender != request.user else msg.recipient

            # Определяем URL для перехода
            url = reverse_lazy('messages_list')
            if msg.property:
                url = reverse_lazy('property_detail', args=[msg.property.slug])

            # Обрезаем текст сообщения для превью
            preview_text = msg.message[:100] + '...' if len(msg.message) > 100 else msg.message

            messages_data.append({
                'id': msg.id,
                'sender': sender.get_full_name_or_username() if sender else 'Пользователь',
                'message': preview_text,
                'is_read': msg.is_read if msg.recipient == request.user else True,
                'url': url,
                'time_ago': get_time_ago(msg.created_at),
                'subject': msg.subject or '',
            })

        unread_count = Message.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()

        return JsonResponse({
            'messages': messages_data,
            'unread_count': unread_count
        })
    # === КОНЕЦ AJAX ОБРАБОТКИ ===

    # Обычная логика для HTML-страницы
    sent_messages = Message.objects.filter(sender=request.user).values('recipient').distinct()
    received_messages = Message.objects.filter(recipient=request.user).values('sender').distinct()

    user_ids = set()
    for msg in sent_messages:
        user_ids.add(msg['recipient'])
    for msg in received_messages:
        user_ids.add(msg['sender'])

    conversations = []
    for user_id in user_ids:
        other_user = User.objects.get(id=user_id)
        last_message = Message.objects.filter(
            Q(sender=request.user, recipient=other_user) |
            Q(sender=other_user, recipient=request.user)
        ).order_by('-created_at').first()

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

    conversations.sort(
        key=lambda x: x['last_message'].created_at if x['last_message'] else timezone.make_aware(datetime.min),
        reverse=True
    )

    # Пагинация для диалогов - 5 на странице
    paginator = Paginator(conversations, 5)
    page = request.GET.get('page')
    conversations_page = paginator.get_page(page)

    context = {
        'conversations': conversations_page,
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

    conversation = Message.objects.filter(
        Q(sender=request.user, recipient=recipient) |
        Q(sender=recipient, recipient=request.user)
    ).order_by('created_at')

    # Помечаем сообщения как прочитанные
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
# УПРАВЛЕНИЕ ПОМЕЩЕНИЯМИ (ДЛЯ АРЕНДОДАТЕЛЕЙ)
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
            property_obj.status = 'pending'  # Отправляем на модерацию
            property_obj.save()
            form.save_m2m()

            images = request.FILES.getlist('images')
            for image in images:
                property_obj.images.create(image=image)

            # Уведомление администраторам
            admins = User.objects.filter(user_type='admin', is_active=True)
            for admin in admins:
                create_notification(
                    user=admin,
                    notification_type='system',
                    title='Новое помещение на модерации',
                    message=f'Помещение "{property_obj.title}" от {request.user.get_full_name_or_username()} требует проверки.',
                    related_object_id=property_obj.id,
                    related_object_type='property'
                )

            messages.success(request,
                             'Помещение отправлено на модерацию. После проверки оно станет доступным для бронирования.')
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


@login_required
def landlord_bookings(request):
    """Бронирования для арендодателя с пагинацией (5 на странице)"""
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

    # Пагинация - 5 элементов на странице
    paginator = Paginator(bookings, 5)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    context = {
        'bookings': bookings_page,
        'current_status': status_filter,
        'title': 'Бронирования моих помещений'
    }
    return render(request, 'core/landlord_bookings.html', context)


@login_required
def update_booking_status(request, booking_id, status):
    """Обновление статуса бронирования (для арендодателя)"""
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

    if old_status != status and status in ['confirmed', 'cancelled', 'completed']:
        notification_type = f'booking_{status}'
        create_booking_notification(booking, notification_type)

        # Если бронирование подтверждено, генерируем договор
        if status == 'confirmed':
            generate_contract_pdf(booking)

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
        from .models import PropertyImage
        PropertyImage.objects.create(property=property_obj, image=request.FILES['image'])
        messages.success(request, 'Изображение успешно добавлено.')
        return redirect('edit_property', property_id=property_id)


# ============================================================================
# АДМИН-ПАНЕЛЬ
# ============================================================================

@login_required
def custom_admin_dashboard(request):
    """Кастомная админ-панель"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    stats = {
        'total_users': User.objects.count(),
        'new_users_today': User.objects.filter(date_joined__date=today).count(),
        'new_users_week': User.objects.filter(date_joined__date__gte=week_ago).count(),
        'total_properties': Property.objects.count(),
        'active_properties': Property.objects.filter(status='active').count(),
        'pending_properties': Property.objects.filter(status='pending').count(),
        'total_bookings': Booking.objects.count(),
        'pending_bookings': Booking.objects.filter(status='pending').count(),
        'paid_bookings': Booking.objects.filter(status='paid').count(),
        'today_bookings': Booking.objects.filter(start_datetime__date=today).count(),
        'month_revenue': Booking.objects.filter(
            status__in=['paid', 'confirmed', 'completed'],
            updated_at__gte=month_ago
        ).aggregate(total=Sum('total_price'))['total'] or 0,
        'admin_count': User.objects.filter(user_type='admin').count(),
        'landlord_count': User.objects.filter(user_type='landlord').count(),
        'tenant_count': User.objects.filter(user_type='tenant').count(),
    }

    # Данные для графика
    chart_labels = []
    chart_paid = []
    chart_pending = []
    chart_cancelled = []

    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        chart_labels.append(date.strftime('%d.%m'))
        day_bookings = Booking.objects.filter(created_at__date=date)
        chart_paid.append(day_bookings.filter(status='paid').count())
        chart_pending.append(day_bookings.filter(status='pending').count())
        chart_cancelled.append(day_bookings.filter(status='cancelled').count())

    property_types = Property.objects.values('property_type').annotate(
        count=Count('id')
    ).order_by('-count')

    property_labels = []
    property_data = []
    type_names = dict(Property.PROPERTY_TYPE_CHOICES)
    for item in property_types:
        property_labels.append(type_names.get(item['property_type'], item['property_type']))
        property_data.append(item['count'])

    recent_users = User.objects.order_by('-date_joined')[:5]
    recent_bookings = Booking.objects.select_related('property', 'tenant').order_by('-created_at')[:5]
    recent_reviews = Review.objects.select_related('property', 'user').order_by('-created_at')[:5]

    return render(request, 'admin/dashboard.html', {
        'stats': stats,
        'recent_users': recent_users,
        'recent_bookings': recent_bookings,
        'recent_reviews': recent_reviews,
        'chart_labels': json.dumps(chart_labels),
        'chart_paid': json.dumps(chart_paid),
        'chart_pending': json.dumps(chart_pending),
        'chart_cancelled': json.dumps(chart_cancelled),
        'property_labels': json.dumps(property_labels),
        'property_data': json.dumps(property_data),
        'title': 'Админ-панель'
    })


@login_required
def admin_user_management(request):
    """Управление пользователями с пагинацией (5 на странице)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    users = User.objects.all().order_by('-date_joined')

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

    stats = {
        'total_users': users.count(),
        'active_count': users.filter(is_active=True).count(),
        'inactive_count': users.filter(is_active=False).count(),
        'admin_count': users.filter(user_type='admin').count(),
        'landlord_count': users.filter(user_type='landlord').count(),
        'tenant_count': users.filter(user_type='tenant').count(),
    }

    # Пагинация - 5 элементов на странице
    paginator = Paginator(users, 5)
    page = request.GET.get('page')
    users_page = paginator.get_page(page)

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

    return render(request, 'admin/user_management.html', {
        'users': users_page,
        'stats': stats,
        'search_query': search_query,
        'user_type_filter': user_type_filter,
        'status_filter': status_filter,
        'title': 'Управление пользователями'
    })


@login_required
def admin_property_management(request):
    """Управление помещениями (админ) с пагинацией (5 на странице)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    properties = Property.objects.select_related('landlord', 'category').all().order_by('-created_at')

    status_filter = request.GET.get('status')
    city_filter = request.GET.get('city')
    type_filter = request.GET.get('type')

    if status_filter:
        properties = properties.filter(status=status_filter)
    if city_filter:
        properties = properties.filter(city__icontains=city_filter)
    if type_filter:
        properties = properties.filter(property_type=type_filter)

    # Пагинация - 5 элементов на странице
    paginator = Paginator(properties, 5)
    page = request.GET.get('page')
    properties_page = paginator.get_page(page)

    if request.method == 'POST':
        action = request.POST.get('action')
        property_id = request.POST.get('property_id')
        try:
            property_obj = Property.objects.get(id=property_id)
            if action == 'approve':
                property_obj.status = 'active'
                property_obj.save()
                # Уведомление владельцу
                create_notification(
                    user=property_obj.landlord,
                    notification_type='system',
                    title='Помещение одобрено',
                    message=f'Ваше помещение "{property_obj.title}" прошло модерацию и теперь доступно для бронирования.',
                    related_object_id=property_obj.id,
                    related_object_type='property'
                )
                messages.success(request, f'Помещение "{property_obj.title}" одобрено.')
            elif action == 'reject':
                property_obj.status = 'rejected'
                property_obj.save()
                messages.success(request, f'Помещение "{property_obj.title}" отклонено.')
            elif action == 'toggle_featured':
                property_obj.is_featured = not property_obj.is_featured
                property_obj.save()
                messages.success(request, f'Статус "Рекомендуемое" изменен.')
            elif action == 'delete':
                property_obj.delete()
                messages.success(request, f'Помещение удалено.')
        except Property.DoesNotExist:
            messages.error(request, 'Помещение не найдено.')
        return redirect('admin_property_management')

    return render(request, 'admin/property_management.html', {
        'properties': properties_page,
        'title': 'Управление помещениями'
    })


@login_required
def admin_booking_management(request):
    """Управление бронированиями (админ) с пагинацией (5 на странице)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    bookings = Booking.objects.select_related('property', 'tenant').all().order_by('-created_at')

    status_filter = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if date_from:
        bookings = bookings.filter(start_datetime__date__gte=date_from)
    if date_to:
        bookings = bookings.filter(start_datetime__date__lte=date_to)

    # Пагинация - 5 элементов на странице
    paginator = Paginator(bookings, 5)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    return render(request, 'admin/booking_management.html', {
        'bookings': bookings_page,
        'title': 'Управление бронированиями'
    })


@login_required
def admin_review_management(request):
    """Управление отзывами (админ) с пагинацией (5 на странице)"""
    if not request.user.is_staff:
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    reviews = Review.objects.select_related('property', 'user').all().order_by('-created_at')

    status_filter = request.GET.get('status')
    rating_filter = request.GET.get('rating')

    if status_filter:
        reviews = reviews.filter(status=status_filter)
    if rating_filter:
        reviews = reviews.filter(rating=rating_filter)

    # Пагинация - 5 элементов на странице
    paginator = Paginator(reviews, 5)
    page = request.GET.get('page')
    reviews_page = paginator.get_page(page)

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

    return render(request, 'admin/review_management.html', {
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

        conflicting_bookings = Booking.objects.filter(
            property=property_obj,
            status__in=['pending', 'paid', 'confirmed'],
            start_datetime__lt=end_datetime,
            end_datetime__gt=start_datetime
        )

        if conflicting_bookings.exists():
            return JsonResponse({'error': 'Выбранное время уже занято.'}, status=400)

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
            'message': 'Бронирование создано. Перейдите к оплате.',
            'booking_id': booking.id,
            'redirect_url': reverse_lazy('payment', args=[booking.id])
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def booking_calendar(request, property_id):
    """Календарь бронирований"""
    property_obj = get_object_or_404(Property, id=property_id)

    month_str = request.GET.get('month')
    if month_str:
        try:
            current_month = datetime.strptime(month_str, '%Y-%m').date()
        except ValueError:
            current_month = timezone.now().date().replace(day=1)
    else:
        current_month = timezone.now().date().replace(day=1)

    if current_month.month == 1:
        prev_month = current_month.replace(year=current_month.year - 1, month=12)
    else:
        prev_month = current_month.replace(month=current_month.month - 1)

    if current_month.month == 12:
        next_month = current_month.replace(year=current_month.year + 1, month=1)
    else:
        next_month = current_month.replace(month=current_month.month + 1)

    bookings = property_obj.bookings.filter(
        start_datetime__year=current_month.year,
        start_datetime__month=current_month.month,
        status__in=['pending', 'paid', 'confirmed']
    ).select_related('tenant')

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

    upcoming_bookings = property_obj.bookings.filter(
        start_datetime__gte=timezone.now(),
        status__in=['paid', 'confirmed']
    ).select_related('tenant').order_by('start_datetime')[:5]

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