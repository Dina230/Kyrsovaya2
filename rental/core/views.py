# views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, update_session_auth_hash
from django.contrib import messages
from django.db.models import Count, Sum, Avg, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import datetime, timedelta
from django.utils import timezone
from functools import wraps
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from decimal import Decimal
from urllib.parse import urlencode
from django.urls import reverse
import csv

from .models import *
from .forms import *


# Проверка является ли пользователь администратором
def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            messages.error(request, 'У вас нет прав для доступа к этой странице.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


def home(request):
    """Главная страница сайта"""
    featured_properties = Property.objects.filter(
        is_featured=True,
        status='active'
    ).select_related('landlord', 'category')[:6]

    recent_properties = Property.objects.filter(
        status='active'
    ).select_related('landlord', 'category').order_by('-created_at')[:6]

    stats = {
        'total_properties': Property.objects.filter(status='active').count(),
        'total_bookings': Booking.objects.filter(status='completed').count(),
        'total_landlords': User.objects.filter(user_type='landlord', is_active=True).count(),
    }

    context = {
        'featured_properties': featured_properties,
        'recent_properties': recent_properties,
        'stats': stats,
    }
    return render(request, 'core/home.html', context)


def register(request):
    """Регистрация нового пользователя"""
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f'Добро пожаловать, {user.username}! Регистрация успешна.')
            return redirect('dashboard')
    else:
        form = CustomUserCreationForm()
    return render(request, 'core/register.html', {'form': form})


@login_required
def dashboard(request):
    """Личный кабинет для всех пользователей"""
    context = {}

    if request.user.user_type == 'tenant':
        # Для арендатора
        active_bookings = Booking.objects.filter(
            tenant=request.user,
            status__in=['pending', 'confirmed'],
            end_datetime__gte=timezone.now()
        ).select_related('property').order_by('start_datetime')[:5]

        booking_history = Booking.objects.filter(
            tenant=request.user
        ).exclude(status__in=['pending', 'confirmed']).select_related('property').order_by('-created_at')[:5]

        favorites = Favorite.objects.filter(
            user=request.user
        ).select_related('property')[:4]
        favorite_properties = [fav.property for fav in favorites]

        stats = {
            'total_bookings': Booking.objects.filter(tenant=request.user).count(),
            'active_bookings': Booking.objects.filter(
                tenant=request.user,
                status__in=['pending', 'confirmed'],
                end_datetime__gte=timezone.now()
            ).count(),
            'completed_bookings': Booking.objects.filter(
                tenant=request.user,
                status='completed'
            ).count(),
            'total_spent': Booking.objects.filter(
                tenant=request.user,
                status='completed'
            ).aggregate(total=Sum('total_price'))['total'] or Decimal('0'),
        }

        context.update({
            'active_bookings': active_bookings,
            'booking_history': booking_history,
            'favorite_properties': favorite_properties,
            'stats': stats,
        })

    elif request.user.user_type == 'landlord':
        # Для арендодателя
        properties = Property.objects.filter(landlord=request.user)

        active_bookings = Booking.objects.filter(
            property__in=properties,
            status__in=['pending', 'confirmed'],
            end_datetime__gte=timezone.now()
        ).select_related('property', 'tenant').order_by('start_datetime')[:5]

        new_bookings = Booking.objects.filter(
            property__in=properties,
            status='pending'
        ).select_related('property', 'tenant').order_by('-created_at')[:5]

        thirty_days_ago = timezone.now() - timedelta(days=30)

        monthly_stats = Booking.objects.filter(
            property__in=properties,
            status='completed',
            created_at__gte=thirty_days_ago
        ).aggregate(
            total_revenue=Sum('total_price'),
            total_bookings=Count('id'),
            avg_booking=Avg('total_price')
        )

        stats = {
            'total_properties': properties.count(),
            'active_properties': properties.filter(status='active').count(),
            'total_bookings': Booking.objects.filter(property__in=properties).count(),
            'pending_bookings': Booking.objects.filter(
                property__in=properties,
                status='pending'
            ).count(),
            'monthly_revenue': monthly_stats['total_revenue'] or Decimal('0'),
        }

        popular_properties = Property.objects.filter(
            landlord=request.user
        ).annotate(
            booking_count=Count('bookings')
        ).order_by('-booking_count')[:4]

        context.update({
            'properties': properties[:5],
            'active_bookings': active_bookings,
            'new_bookings': new_bookings,
            'stats': stats,
            'monthly_stats': monthly_stats,
            'popular_properties': popular_properties,
        })

    elif request.user.is_staff:
        # Для администратора - редирект в кастомную админку
        return redirect('custom_admin_dashboard')

    return render(request, 'core/dashboard.html', context)


@login_required
def edit_profile(request):
    """Редактирование профиля пользователя"""
    if request.method == 'POST':
        form = ProfileEditForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Профиль успешно обновлен.')
            return redirect('dashboard')
    else:
        form = ProfileEditForm(instance=request.user)
    return render(request, 'core/edit_profile.html', {'form': form})


@login_required
def change_password(request):
    """Изменение пароля"""
    if request.method == 'POST':
        form = PasswordChangeFormCustom(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, 'Пароль успешно изменен.')
            return redirect('dashboard')
    else:
        form = PasswordChangeFormCustom(request.user)
    return render(request, 'core/change_password.html', {'form': form})


@login_required
def my_bookings(request):
    """Мои бронирования (для арендатора)"""
    if request.user.user_type != 'tenant':
        messages.error(request, 'Эта страница доступна только арендаторам.')
        return redirect('dashboard')

    bookings = Booking.objects.filter(
        tenant=request.user
    ).select_related('property').order_by('-created_at')

    status_filter = request.GET.get('status')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    paginator = Paginator(bookings, 10)
    page = request.GET.get('page')
    try:
        bookings = paginator.page(page)
    except PageNotAnInteger:
        bookings = paginator.page(1)
    except EmptyPage:
        bookings = paginator.page(paginator.num_pages)

    return render(request, 'core/my_bookings.html', {'bookings': bookings})


@login_required
def my_favorites(request):
    """Избранные помещения (для арендатора)"""
    if request.user.user_type != 'tenant':
        messages.error(request, 'Эта страница доступна только арендаторам.')
        return redirect('dashboard')

    favorites = Favorite.objects.filter(user=request.user).select_related('property')
    properties = [favorite.property for favorite in favorites]

    paginator = Paginator(properties, 12)
    page = request.GET.get('page')
    try:
        properties = paginator.page(page)
    except PageNotAnInteger:
        properties = paginator.page(1)
    except EmptyPage:
        properties = paginator.page(paginator.num_pages)

    return render(request, 'core/my_favorites.html', {'properties': properties})


@login_required
def my_properties(request):
    """Мои помещения (для арендодателя)"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Эта страница доступна только арендодателям.')
        return redirect('dashboard')

    properties = Property.objects.filter(landlord=request.user).order_by('-created_at')

    status_filter = request.GET.get('status')
    if status_filter:
        properties = properties.filter(status=status_filter)

    paginator = Paginator(properties, 10)
    page = request.GET.get('page')
    try:
        properties = paginator.page(page)
    except PageNotAnInteger:
        properties = paginator.page(1)
    except EmptyPage:
        properties = paginator.page(paginator.num_pages)

    return render(request, 'core/my_properties.html', {'properties': properties})


def property_list(request):
    """Список всех помещений"""
    properties = Property.objects.filter(status='active').select_related('landlord', 'category')

    property_type = request.GET.get('type')
    category_id = request.GET.get('category')
    city = request.GET.get('city')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    if property_type:
        properties = properties.filter(property_type=property_type)
    if category_id:
        properties = properties.filter(category_id=category_id)
    if city:
        properties = properties.filter(city__icontains=city)
    if min_price:
        properties = properties.filter(price_per_hour__gte=min_price)
    if max_price:
        properties = properties.filter(price_per_hour__lte=max_price)

    paginator = Paginator(properties, 12)
    page = request.GET.get('page')
    try:
        properties = paginator.page(page)
    except PageNotAnInteger:
        properties = paginator.page(1)
    except EmptyPage:
        properties = paginator.page(paginator.num_pages)

    categories = PropertyCategory.objects.all()

    context = {
        'properties': properties,
        'categories': categories,
        'property_types': Property.PROPERTY_TYPE_CHOICES,
    }
    return render(request, 'core/property_list.html', context)


def property_detail(request, slug):
    """Детальная страница помещения"""
    property_obj = get_object_or_404(
        Property.objects.select_related('landlord', 'category')
        .prefetch_related('amenities', 'images', 'reviews__user'),
        slug=slug,
        status='active'
    )

    is_favorite = False
    if request.user.is_authenticated:
        is_favorite = Favorite.objects.filter(
            user=request.user,
            property=property_obj
        ).exists()

    reviews = property_obj.reviews.all()

    similar_properties = Property.objects.filter(
        category=property_obj.category,
        status='active'
    ).exclude(id=property_obj.id)[:4]

    today = datetime.now().date()
    next_month = today + timedelta(days=30)

    booked_dates = Booking.objects.filter(
        property=property_obj,
        start_datetime__date__lte=next_month,
        end_datetime__date__gte=today,
        status__in=['confirmed', 'pending']
    ).values_list('start_datetime__date', flat=True).distinct()

    booked_dates_json = json.dumps([date.strftime('%Y-%m-%d') for date in booked_dates])

    hours_range = list(range(9, 23))

    calendar_data = []
    for i in range(30):
        date = today + timedelta(days=i)
        has_bookings = date in booked_dates
        calendar_data.append({
            'date': date,
            'bookings': has_bookings
        })

    context = {
        'property': property_obj,
        'is_favorite': is_favorite,
        'reviews': reviews,
        'similar_properties': similar_properties,
        'today': today.strftime('%Y-%m-%d'),
        'booked_dates_json': booked_dates_json,
        'hours_range': hours_range,
        'calendar_data': calendar_data,
    }
    return render(request, 'core/property_detail.html', context)


@login_required
def toggle_favorite(request, property_id):
    """Добавление/удаление из избранного"""
    property_obj = get_object_or_404(Property, id=property_id)

    favorite, created = Favorite.objects.get_or_create(
        user=request.user,
        property=property_obj
    )

    if not created:
        favorite.delete()
        messages.success(request, 'Помещение удалено из избранного.')
    else:
        messages.success(request, 'Помещение добавлено в избранное.')

    return redirect(request.META.get('HTTP_REFERER', 'property_list'))


@login_required
def create_booking(request, property_id):
    """Создание бронирования"""
    property_obj = get_object_or_404(Property, id=property_id, status='active')

    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.property = property_obj
            booking.tenant = request.user

            conflicting_bookings = Booking.objects.filter(
                property=property_obj,
                status__in=['pending', 'confirmed'],
                start_datetime__lt=booking.end_datetime,
                end_datetime__gt=booking.start_datetime
            )

            if conflicting_bookings.exists():
                messages.error(request, 'Помещение уже забронировано на выбранные даты.')
            else:
                # Исправлено: преобразуем timedelta в Decimal для умножения на Decimal
                duration_hours = Decimal((booking.end_datetime - booking.start_datetime).total_seconds()) / Decimal(
                    '3600')
                booking.total_price = property_obj.price_per_hour * duration_hours
                booking.save()
                messages.success(request, 'Бронирование создано! Ожидайте подтверждения от владельца.')
                return redirect('my_bookings')
    else:
        form = BookingForm()

    return render(request, 'core/create_booking.html', {
        'form': form,
        'property': property_obj
    })


@csrf_exempt
@require_POST
@login_required
def ajax_create_booking(request, property_id):
    """AJAX создание бронирования"""
    try:
        property_obj = Property.objects.get(id=property_id, status='active')

        if request.user.user_type != 'tenant':
            return JsonResponse({
                'success': False,
                'error': 'Только арендаторы могут создавать бронирования'
            }, status=403)

        data = json.loads(request.body)

        booking_date = datetime.strptime(data['booking_date'], '%Y-%m-%d').date()
        start_time = data['start_time']
        end_time = data['end_time']
        guests = int(data['guests'])

        start_datetime = timezone.make_aware(
            datetime.combine(booking_date, datetime.strptime(start_time, '%H:%M').time())
        )
        end_datetime = timezone.make_aware(
            datetime.combine(booking_date, datetime.strptime(end_time, '%H:%M').time())
        )

        if end_datetime <= start_datetime:
            return JsonResponse({
                'success': False,
                'error': 'Время окончания должно быть позже времени начала'
            }, status=400)

        duration = (end_datetime - start_datetime).total_seconds() / 3600
        if duration < 1:
            return JsonResponse({
                'success': False,
                'error': 'Минимальное время бронирования - 1 час'
            }, status=400)

        conflicting_bookings = Booking.objects.filter(
            property=property_obj,
            status__in=['confirmed', 'pending'],
            start_datetime__lt=end_datetime,
            end_datetime__gt=start_datetime
        ).exists()

        if conflicting_bookings:
            return JsonResponse({
                'success': False,
                'error': 'Помещение уже забронировано на выбранное время'
            }, status=400)

        if guests > property_obj.capacity:
            return JsonResponse({
                'success': False,
                'error': f'Максимальная вместимость: {property_obj.capacity} человек'
            }, status=400)

        # Исправлено: преобразуем duration в Decimal перед умножением
        duration_decimal = Decimal(str(duration))
        total_price = property_obj.price_per_hour * duration_decimal

        booking = Booking.objects.create(
            property=property_obj,
            tenant=request.user,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            guests=guests,
            special_requests=data.get('special_requests', ''),
            total_price=total_price,
            status='pending'
        )

        return JsonResponse({
            'success': True,
            'booking_id': booking.id,
            'booking_uuid': str(booking.booking_id),
            'message': 'Бронирование успешно создано! Ожидайте подтверждения от владельца.',
            'redirect_url': f'/bookings/{booking.id}/'
        })

    except Property.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Помещение не найдено'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
def booking_detail(request, booking_id):
    """Детальная страница бронирования"""
    booking = get_object_or_404(
        Booking.objects.select_related('property', 'tenant'),
        id=booking_id
    )

    if request.user != booking.tenant and request.user != booking.property.landlord:
        if not request.user.is_staff:
            messages.error(request, 'У вас нет прав для просмотра этого бронирования.')
            return redirect('dashboard')

    context = {
        'booking': booking,
        'can_cancel': booking.status in ['pending', 'confirmed'] and request.user == booking.tenant,
        'can_review': booking.status == 'completed' and request.user == booking.tenant and not hasattr(booking,
                                                                                                       'review'),
    }
    return render(request, 'core/booking_detail.html', context)


@login_required
def add_property(request):
    """Добавление нового помещения (для арендодателя)"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Только арендодатели могут добавлять помещения.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES)
        if form.is_valid():
            property_obj = form.save(commit=False)
            property_obj.landlord = request.user
            property_obj.save()
            form.save_m2m()
            messages.success(request, 'Помещение успешно добавлено!')
            return redirect('my_properties')
    else:
        form = PropertyForm()

    return render(request, 'core/add_property.html', {'form': form})


@login_required
def edit_property(request, property_id):
    """Редактирование помещения (для арендодателя)"""
    property_obj = get_object_or_404(Property, id=property_id, landlord=request.user)

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES, instance=property_obj)
        if form.is_valid():
            # Устанавливаем landlord перед сохранением
            form.instance.landlord = request.user
            property_obj = form.save()
            messages.success(request, 'Помещение успешно обновлено!')
            return redirect('my_properties')
    else:
        form = PropertyForm(instance=property_obj)

    # Получаем существующие изображения для отображения
    existing_images = property_obj.images.all()

    context = {
        'form': form,
        'property': property_obj,
        'existing_images': existing_images,
    }

    return render(request, 'core/edit_property.html', context)


@login_required
def delete_property(request, property_id):
    """Удаление помещения (для арендодателя)"""
    property_obj = get_object_or_404(Property, id=property_id, landlord=request.user)

    if request.method == 'POST':
        property_obj.delete()
        messages.success(request, 'Помещение успешно удалено.')
        return redirect('my_properties')

    return render(request, 'core/confirm_delete.html', {
        'object': property_obj,
        'type': 'помещение'
    })


@login_required
def add_review(request, booking_id):
    """Добавление отзыва"""
    booking = get_object_or_404(Booking, id=booking_id, tenant=request.user)

    if booking.status != 'completed':
        messages.error(request, 'Отзыв можно оставить только после завершения бронирования.')
        return redirect('my_bookings')

    if hasattr(booking, 'review'):
        messages.error(request, 'Вы уже оставили отзыв на это бронирование.')
        return redirect('my_bookings')

    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.property = booking.property
            review.user = request.user
            review.booking = booking
            review.save()
            messages.success(request, 'Спасибо за ваш отзыв!')
            return redirect('my_bookings')
    else:
        form = ReviewForm()

    return render(request, 'core/add_review.html', {'form': form, 'booking': booking})


# --- АДМИН-ПАНЕЛЬ ---
@login_required
@admin_required
def custom_admin_dashboard(request):
    """Кастомная админ-панель"""
    total_users = User.objects.count()
    total_properties = Property.objects.count()
    total_bookings = Booking.objects.count()

    active_bookings = Booking.objects.filter(
        status__in=['pending', 'confirmed'],
        end_datetime__gte=timezone.now()
    ).count()

    thirty_days_ago = timezone.now() - timedelta(days=30)

    user_stats = User.objects.values('user_type').annotate(count=Count('id'))
    property_stats = Property.objects.values('property_type').annotate(count=Count('id'))
    booking_stats = Booking.objects.values('status').annotate(count=Count('id'))

    recent_users = User.objects.order_by('-date_joined')[:5]
    recent_bookings = Booking.objects.select_related('property', 'tenant').order_by('-created_at')[:5]
    recent_reviews = Review.objects.select_related('property', 'user').order_by('-created_at')[:5]

    revenue_stats = Booking.objects.filter(
        status='completed',
        created_at__gte=thirty_days_ago
    ).aggregate(
        total_revenue=Sum('total_price'),
        avg_booking=Avg('total_price')
    )

    context = {
        'total_users': total_users,
        'total_properties': total_properties,
        'total_bookings': total_bookings,
        'active_bookings': active_bookings,
        'user_stats': user_stats,
        'property_stats': property_stats,
        'booking_stats': booking_stats,
        'recent_users': recent_users,
        'recent_bookings': recent_bookings,
        'recent_reviews': recent_reviews,
        'revenue_stats': revenue_stats,
    }
    return render(request, 'admin/dashboard.html', context)


@login_required
@admin_required
def admin_user_management(request):
    """Управление пользователями"""
    users = User.objects.all().order_by('-date_joined')

    # Обработка поиска
    search_query = request.GET.get('search', '')
    user_type_filter = request.GET.get('user_type', '')
    status_filter = request.GET.get('status', '')

    # Статистика для быстрых фильтров
    active_count = User.objects.filter(is_active=True).count()
    inactive_count = User.objects.filter(is_active=False).count()
    admin_count = User.objects.filter(user_type='admin').count()
    landlord_count = User.objects.filter(user_type='landlord').count()
    tenant_count = User.objects.filter(user_type='tenant').count()
    total_users = User.objects.count()

    # Сохраняем параметры поиска для пагинации
    query_params = {}

    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
        query_params['search'] = search_query

    if user_type_filter:
        users = users.filter(user_type=user_type_filter)
        query_params['user_type'] = user_type_filter

    if status_filter:
        if status_filter == 'active':
            users = users.filter(is_active=True)
        elif status_filter == 'inactive':
            users = users.filter(is_active=False)
        query_params['status'] = status_filter

    # Пагинация
    paginator = Paginator(users, 5)  # 5 пользователей на страницу
    page_number = request.GET.get('page')

    try:
        users_page = paginator.page(page_number)
    except PageNotAnInteger:
        users_page = paginator.page(1)
    except EmptyPage:
        users_page = paginator.page(paginator.num_pages)

    # Обработка POST запросов для действий
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        action = request.POST.get('action')

        if user_id and action:
            try:
                user = get_object_or_404(User, id=user_id)

                if action == 'delete':
                    user.delete()
                    messages.success(request, f'Пользователь {user.username} удален.')
                elif action == 'toggle_active':
                    user.is_active = not user.is_active
                    user.save()
                    status = 'активирован' if user.is_active else 'деактивирован'
                    messages.success(request, f'Пользователь {user.username} {status}.')
                elif action == 'toggle_staff':
                    user.is_staff = not user.is_staff
                    user.save()
                    status = 'назначен администратором' if user.is_staff else 'снят с администратора'
                    messages.success(request, f'Пользователь {user.username} {status}.')

                # Редирект с сохранением параметров поиска
                redirect_url = reverse('admin_user_management')
                if query_params:
                    params = urlencode(query_params)
                    redirect_url = f"{redirect_url}?{params}"

                # Добавляем параметр страницы, если он был
                if page_number and page_number != '1':
                    redirect_url += f"&page={page_number}" if '?' in redirect_url else f"?page={page_number}"

                return redirect(redirect_url)

            except Exception as e:
                messages.error(request, f'Ошибка при выполнении действия: {str(e)}')
                redirect_url = reverse('admin_user_management')
                if query_params:
                    params = urlencode(query_params)
                    redirect_url = f"{redirect_url}?{params}"
                return redirect(redirect_url)

    context = {
        'users': users_page,
        'search_query': search_query,
        'user_type_filter': user_type_filter,
        'status_filter': status_filter,
        'active_count': active_count,
        'inactive_count': inactive_count,
        'admin_count': admin_count,
        'landlord_count': landlord_count,
        'tenant_count': tenant_count,
        'total_users': total_users,
        'query_params': query_params,
    }

    return render(request, 'admin/user_management.html', context)


def export_users_csv(request):
    """Экспорт пользователей в CSV"""
    # Проверяем, авторизован ли пользователь и является ли администратором
    if not request.user.is_authenticated or not request.user.is_staff:
        return HttpResponse('Доступ запрещен', status=403)

    users = User.objects.all().order_by('-date_joined')

    # Применяем те же фильтры, что и в основном представлении
    search_query = request.GET.get('search', '')
    user_type_filter = request.GET.get('user_type', '')
    status_filter = request.GET.get('status', '')

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

    # Создаем HTTP ответ с CSV заголовками
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response[
        'Content-Disposition'] = f'attachment; filename="users_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

    # Создаем CSV writer с правильной кодировкой
    writer = csv.writer(response, delimiter=';')

    # Заголовки CSV
    writer.writerow([
        'ID', 'Логин', 'Email', 'Имя', 'Фамилия', 'Телефон',
        'Тип пользователя', 'Активен', 'Администратор', 'Подтвержден',
        'Дата регистрации', 'Последний вход'
    ])

    # Данные
    for user in users:
        writer.writerow([
            user.id,
            user.username,
            user.email,
            user.first_name or '',
            user.last_name or '',
            user.phone or '',
            user.get_user_type_display(),
            'Да' if user.is_active else 'Нет',
            'Да' if user.is_staff else 'Нет',
            'Да' if user.is_verified else 'Нет',
            user.date_joined.strftime('%d.%m.%Y %H:%M') if user.date_joined else '',
            user.last_login.strftime('%d.%m.%Y %H:%M') if user.last_login else ''
        ])

    return response


@login_required
@admin_required
def admin_property_management(request):
    """Управление помещениями"""
    # Получаем все уникальные города для фильтра
    unique_cities = Property.objects.values_list('city', flat=True).distinct().order_by('city')

    # Начинаем с всех свойств
    properties = Property.objects.all().select_related('landlord', 'category').order_by('-created_at')

    # Применяем фильтры
    search_query = request.GET.get('search', '')
    property_type = request.GET.get('property_type', '')
    status = request.GET.get('status', '')
    city = request.GET.get('city', '')

    if search_query:
        properties = properties.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(city__icontains=search_query) |
            Q(address__icontains=search_query)
        )

    if property_type:
        properties = properties.filter(property_type=property_type)

    if status:
        properties = properties.filter(status=status)

    if city:
        properties = properties.filter(city=city)

    # Обработка POST запросов для действий
    if request.method == 'POST':
        property_id = request.POST.get('property_id')
        action = request.POST.get('action')

        if property_id and action:
            property_obj = get_object_or_404(Property, id=property_id)

            if action == 'delete':
                property_obj.delete()
                messages.success(request, f'Помещение "{property_obj.title}" удалено.')
            elif action == 'toggle_featured':
                property_obj.is_featured = not property_obj.is_featured
                property_obj.save()
                status_msg = 'добавлено в рекомендуемые' if property_obj.is_featured else 'убрано из рекомендуемых'
                messages.success(request, f'Помещение "{property_obj.title}" {status_msg}.')
            elif action == 'toggle_status':
                if property_obj.status == 'active':
                    property_obj.status = 'inactive'
                else:
                    property_obj.status = 'active'
                property_obj.save()
                status_msg = 'активировано' if property_obj.status == 'active' else 'деактивировано'
                messages.success(request, f'Помещение "{property_obj.title}" {status_msg}.')

            # Редирект с сохранением параметров фильтрации
            query_params = {}
            if search_query:
                query_params['search'] = search_query
            if property_type:
                query_params['property_type'] = property_type
            if status:
                query_params['status'] = status
            if city:
                query_params['city'] = city

            redirect_url = reverse('admin_property_management')
            if query_params:
                params = urlencode(query_params)
                redirect_url = f"{redirect_url}?{params}"

            # Добавляем номер страницы, если он был
            page_number = request.GET.get('page')
            if page_number and page_number != '1':
                redirect_url += f"&page={page_number}" if '?' in redirect_url else f"?page={page_number}"

            return redirect(redirect_url)

    # Пагинация
    paginator = Paginator(properties, 10)  # 10 элементов на странице
    page_number = request.GET.get('page')

    try:
        properties_page = paginator.page(page_number)
    except PageNotAnInteger:
        properties_page = paginator.page(1)
    except EmptyPage:
        properties_page = paginator.page(paginator.num_pages)

    # Статистика для карточек
    total_properties = Property.objects.count()
    active_properties = Property.objects.filter(status='active').count()
    featured_properties = Property.objects.filter(is_featured=True).count()

    # Помещения с активными бронированиями
    booked_properties = Property.objects.filter(
        bookings__status__in=['confirmed', 'pending'],
        bookings__start_datetime__gte=timezone.now()
    ).distinct().count()

    # Общая статистика для сайдбара
    total_users = User.objects.count()
    total_bookings = Booking.objects.count()

    context = {
        'properties': properties_page,
        'cities': unique_cities,
        'search_query': search_query,
        'property_type_filter': property_type,
        'status_filter': status,
        'city_filter': city,
        'total_properties': total_properties,
        'active_properties': active_properties,
        'featured_properties': featured_properties,
        'booked_properties': booked_properties,
        'total_users': total_users,
        'total_bookings': total_bookings,
    }

    return render(request, 'admin/property_management.html', context)


@login_required
@admin_required
def admin_booking_management(request):
    """Управление бронированиями"""
    # Получаем все бронирования
    bookings = Booking.objects.all().select_related('property', 'tenant').order_by('-created_at')

    # Применяем фильтры
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    date_filter = request.GET.get('date', '')

    if search_query:
        bookings = bookings.filter(
            Q(booking_id__icontains=search_query) |
            Q(property__title__icontains=search_query) |
            Q(tenant__username__icontains=search_query) |
            Q(tenant__email__icontains=search_query)
        )

    if status_filter:
        bookings = bookings.filter(status=status_filter)

    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            bookings = bookings.filter(
                start_datetime__date=filter_date
            )
        except ValueError:
            pass

    # Статистика для карточек
    total_bookings = Booking.objects.count()
    pending_bookings = Booking.objects.filter(status='pending').count()
    confirmed_bookings = Booking.objects.filter(status='confirmed').count()
    completed_bookings = Booking.objects.filter(status='completed').count()
    cancelled_bookings = Booking.objects.filter(status='cancelled').count()

    # Выручка
    total_revenue = Booking.objects.filter(status='completed').aggregate(
        total=Sum('total_price')
    )['total'] or Decimal('0')

    # Обработка POST запросов для действий
    if request.method == 'POST':
        booking_id = request.POST.get('booking_id')
        action = request.POST.get('action')

        if booking_id and action:
            try:
                booking = get_object_or_404(Booking, id=booking_id)

                if action == 'confirm':
                    if booking.status == 'pending':
                        booking.status = 'confirmed'
                        booking.save()
                        messages.success(request, f'Бронирование #{booking.booking_id} подтверждено.')
                    else:
                        messages.warning(request,
                                         f'Бронирование #{booking.booking_id} уже имеет статус {booking.get_status_display()}.')

                elif action == 'cancel':
                    if booking.status in ['pending', 'confirmed']:
                        booking.status = 'cancelled'
                        booking.save()
                        messages.success(request, f'Бронирование #{booking.booking_id} отменено.')
                    else:
                        messages.warning(request,
                                         f'Бронирование #{booking.booking_id} уже имеет статус {booking.get_status_display()}.')

                elif action == 'complete':
                    if booking.status == 'confirmed':
                        booking.status = 'completed'
                        booking.save()
                        messages.success(request, f'Бронирование #{booking.booking_id} завершено.')
                    elif booking.status == 'completed':
                        messages.warning(request, f'Бронирование #{booking.booking_id} уже завершено.')
                    else:
                        messages.warning(request,
                                         f'Бронирование #{booking.booking_id} должно быть подтверждено перед завершением.')

                elif action == 'delete':
                    booking.delete()
                    messages.success(request, f'Бронирование #{booking.booking_id} удалено.')

                # Редирект с сохранением параметров фильтрации
                query_params = {}
                if search_query:
                    query_params['search'] = search_query
                if status_filter:
                    query_params['status'] = status_filter
                if date_filter:
                    query_params['date'] = date_filter

                redirect_url = reverse('admin_booking_management')
                if query_params:
                    params = urlencode(query_params)
                    redirect_url = f"{redirect_url}?{params}"

                # Добавляем параметр страницы, если он был
                page_number = request.GET.get('page')
                if page_number and page_number != '1':
                    redirect_url += f"&page={page_number}" if '?' in redirect_url else f"?page={page_number}"

                return redirect(redirect_url)

            except Exception as e:
                messages.error(request, f'Ошибка при выполнении действия: {str(e)}')
                # Редирект с сохранением параметров фильтрации
                query_params = {}
                if search_query:
                    query_params['search'] = search_query
                if status_filter:
                    query_params['status'] = status_filter
                if date_filter:
                    query_params['date'] = date_filter

                redirect_url = reverse('admin_booking_management')
                if query_params:
                    params = urlencode(query_params)
                    redirect_url = f"{redirect_url}?{params}"
                return redirect(redirect_url)

    # Пагинация
    paginator = Paginator(bookings, 10)  # 10 элементов на странице
    page_number = request.GET.get('page')

    try:
        bookings_page = paginator.page(page_number)
    except PageNotAnInteger:
        bookings_page = paginator.page(1)
    except EmptyPage:
        bookings_page = paginator.page(paginator.num_pages)

    # Общая статистика для сайдбара
    total_users = User.objects.count()
    total_properties = Property.objects.count()

    # Добавляем вычисление часов для каждого бронирования
    for booking in bookings_page:
        duration = booking.end_datetime - booking.start_datetime
        booking.hours = round(duration.total_seconds() / 3600, 1)

    context = {
        'bookings': bookings_page,
        'search_query': search_query,
        'status_filter': status_filter,
        'date_filter': date_filter,
        'total_bookings': total_bookings,
        'pending_bookings': pending_bookings,
        'confirmed_bookings': confirmed_bookings,
        'completed_bookings': completed_bookings,
        'cancelled_bookings': cancelled_bookings,
        'total_revenue': total_revenue,
        'total_users': total_users,
        'total_properties': total_properties,
    }

    return render(request, 'admin/booking_management.html', context)


@login_required
@admin_required
def admin_review_management(request):
    """Управление отзывами"""
    reviews = Review.objects.all().select_related('property', 'user').order_by('-created_at')

    if request.method == 'POST':
        review_id = request.POST.get('review_id')
        action = request.POST.get('action')

        if review_id and action:
            review = get_object_or_404(Review, id=review_id)

            if action == 'delete':
                review.delete()
                messages.success(request, f'Отзыв от {review.user} удален.')

    # Статистика для карточек
    total_reviews = Review.objects.count()
    avg_rating = Review.objects.aggregate(avg=Avg('rating'))['avg'] or 0

    # Количество отзывов по рейтингам
    rating_5 = Review.objects.filter(rating=5).count()
    rating_low = Review.objects.filter(rating__in=[1, 2]).count()

    # Пагинация
    paginator = Paginator(reviews, 10)
    page = request.GET.get('page')

    try:
        reviews_page = paginator.page(page)
    except PageNotAnInteger:
        reviews_page = paginator.page(1)
    except EmptyPage:
        reviews_page = paginator.page(paginator.num_pages)

    context = {
        'reviews': reviews_page,
        'total_reviews': total_reviews,
        'avg_rating': avg_rating,
        'rating_5': rating_5,
        'rating_low': rating_low,
    }

    return render(request, 'admin/review_management.html', context)


@login_required
@admin_required
def admin_edit_user(request, user_id):
    """Редактирование пользователя"""
    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        form = AdminUserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Пользователь {user.username} обновлен.')
            return redirect('admin_user_management')
    else:
        form = AdminUserEditForm(instance=user)

    return render(request, 'admin/edit_user.html', {'form': form, 'user': user})


@login_required
@admin_required
def admin_edit_property(request, property_id):
    """Редактирование помещения"""
    property_obj = get_object_or_404(Property, id=property_id)

    if request.method == 'POST':
        form = AdminPropertyEditForm(request.POST, request.FILES, instance=property_obj)
        if form.is_valid():
            form.save()
            messages.success(request, f'Помещение "{property_obj.title}" обновлено.')
            return redirect('admin_property_management')
    else:
        form = AdminPropertyEditForm(instance=property_obj)

    return render(request, 'admin/edit_property.html', {'form': form, 'property': property_obj})


@login_required
@admin_required
def admin_edit_booking(request, booking_id):
    """Редактирование бронирования"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.method == 'POST':
        form = AdminBookingEditForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            messages.success(request, f'Бронирование #{booking.booking_id} обновлено.')
            return redirect('admin_booking_management')
    else:
        form = AdminBookingEditForm(instance=booking)

    return render(request, 'admin/edit_booking.html', {'form': form, 'booking': booking})


@login_required
@admin_required
def admin_add_property(request):
    """Добавление нового помещения"""
    if request.method == 'POST':
        form = AdminPropertyEditForm(request.POST, request.FILES)
        if form.is_valid():
            property_obj = form.save()
            messages.success(request, f'Помещение "{property_obj.title}" добавлено.')
            return redirect('admin_property_management')
    else:
        form = AdminPropertyEditForm()

    return render(request, 'admin/add_property.html', {'form': form})


@login_required
@admin_required
def admin_add_user(request):
    """Добавление нового пользователя"""
    if request.method == 'POST':
        form = AdminUserEditForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Пользователь {user.username} добавлен.')
            return redirect('admin_user_management')
    else:
        form = AdminUserEditForm()

    return render(request, 'admin/add_user.html', {'form': form})


@login_required
@admin_required
def admin_system_settings(request):
    """Настройки системы"""
    if request.method == 'POST':
        messages.success(request, 'Настройки системы обновлены.')
        return redirect('admin_system_settings')

    # Статистика для отображения
    total_users = User.objects.count()
    total_properties = Property.objects.count()
    total_bookings = Booking.objects.count()

    context = {
        'total_users': total_users,
        'total_properties': total_properties,
        'total_bookings': total_bookings,
        'uptime': '24/7',  # Можно добавить реальное время работы
    }

    return render(request, 'admin/system_settings.html', context)


# Дополнительные функции для арендодателя
@login_required
def landlord_bookings(request):
    """Бронирования арендодателя"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Эта страница доступна только арендодателям.')
        return redirect('dashboard')

    properties = Property.objects.filter(landlord=request.user)
    bookings = Booking.objects.filter(
        property__in=properties
    ).select_related('property', 'tenant').order_by('-created_at')

    status_filter = request.GET.get('status')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    paginator = Paginator(bookings, 10)
    page = request.GET.get('page')
    try:
        bookings = paginator.page(page)
    except PageNotAnInteger:
        bookings = paginator.page(1)
    except EmptyPage:
        bookings = paginator.page(paginator.num_pages)

    return render(request, 'core/landlord_bookings.html', {'bookings': bookings})


@login_required
def update_booking_status(request, booking_id, status):
    """Изменение статуса бронирования (для арендодателя)"""
    booking = get_object_or_404(Booking, id=booking_id, property__landlord=request.user)

    if status in ['confirmed', 'cancelled', 'completed']:
        booking.status = status
        booking.save()

        status_display = {
            'confirmed': 'подтверждено',
            'cancelled': 'отменено',
            'completed': 'завершено'
        }

        messages.success(request, f'Бронирование #{booking.booking_id} {status_display.get(status, "обновлено")}.')

    return redirect('landlord_bookings')


@login_required
def cancel_booking(request, booking_id):
    """Отмена бронирования (для арендатора)"""
    booking = get_object_or_404(Booking, id=booking_id, tenant=request.user)

    if booking.status in ['pending', 'confirmed']:
        booking.status = 'cancelled'
        booking.save()
        messages.success(request, f'Бронирование #{booking.booking_id} отменено.')

    return redirect('my_bookings')


@login_required
def add_property_image(request, property_id):
    """Добавление изображений к помещению"""
    property_obj = get_object_or_404(Property, id=property_id, landlord=request.user)

    if request.method == 'POST':
        form = PropertyImageForm(request.POST, request.FILES)
        if form.is_valid():
            image = form.save(commit=False)
            image.property = property_obj
            image.save()

            if image.is_main:
                PropertyImage.objects.filter(property=property_obj).exclude(id=image.id).update(is_main=False)

            messages.success(request, 'Изображение успешно добавлено.')
            return redirect('edit_property', property_id=property_id)
    else:
        form = PropertyImageForm()

    return render(request, 'core/add_property_image.html', {'form': form, 'property': property_obj})


@login_required
def delete_property_image(request, image_id):
    """Удаление изображения помещения"""
    image = get_object_or_404(PropertyImage, id=image_id, property__landlord=request.user)

    if request.method == 'POST':
        image.delete()
        messages.success(request, 'Изображение удалено.')
        return redirect('edit_property', property_id=image.property.id)

    return render(request, 'core/confirm_delete.html', {
        'object': image,
        'type': 'изображение'
    })