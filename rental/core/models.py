from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid
from datetime import timedelta


class User(AbstractUser):
    USER_TYPE_CHOICES = (
        ('tenant', 'Арендатор'),
        ('landlord', 'Арендодатель'),
        ('admin', 'Администратор'),
    )

    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='tenant')
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to='users/avatars/', blank=True, null=True)
    company_name = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'
        db_table = 'custom_user'

    def __str__(self):
        return f'{self.get_full_name()} ({self.get_user_type_display()})'

    def save(self, *args, **kwargs):
        # ВАЖНО: Удаляем или комментируем старую логику!
        # Эта логика была неверной и сбрасывала права администратора

        # Новая правильная логика:
        # Если пользователь - администратор, даем ему все права
        if self.user_type == 'admin':
            self.is_staff = True
            self.is_superuser = True
        else:
            # Для обычных пользователей снимаем права администратора
            self.is_staff = False
            self.is_superuser = False

        super().save(*args, **kwargs)


class PropertyCategory(models.Model):
    name = models.CharField(max_length=100, verbose_name='Название')
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, verbose_name='Описание')
    icon = models.CharField(max_length=50, blank=True, default='building')

    class Meta:
        verbose_name = 'Категория помещения'
        verbose_name_plural = 'Категории помещений'

    def __str__(self):
        return self.name


class Amenity(models.Model):
    name = models.CharField(max_length=100, verbose_name='Название')
    icon = models.CharField(max_length=50, blank=True, default='check-circle')

    class Meta:
        verbose_name = 'Удобство'
        verbose_name_plural = 'Удобства'

    def __str__(self):
        return self.name


class Property(models.Model):
    PROPERTY_TYPE_CHOICES = (
        ('office', 'Офис'),
        ('coworking', 'Коворкинг'),
        ('conference_room', 'Конференц-зал'),
        ('retail', 'Торговая площадь'),
        ('warehouse', 'Склад'),
        ('industrial', 'Производственное помещение'),
        ('other', 'Другое'),
    )

    STATUS_CHOICES = (
        ('active', 'Активно'),
        ('inactive', 'Неактивно'),
        ('under_maintenance', 'На обслуживании'),
    )

    # Основная информация
    title = models.CharField(max_length=200, verbose_name='Название')
    slug = models.SlugField(unique=True)
    description = models.TextField(verbose_name='Описание')
    property_type = models.CharField(max_length=50, choices=PROPERTY_TYPE_CHOICES, verbose_name='Тип помещения')
    category = models.ForeignKey(PropertyCategory, on_delete=models.SET_NULL, null=True, verbose_name='Категория')

    # Владелец
    landlord = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'user_type': 'landlord'},
                                 verbose_name='Владелец')

    # Локация
    address = models.TextField(verbose_name='Адрес')
    city = models.CharField(max_length=100, verbose_name='Город')
    latitude = models.FloatField(verbose_name='Широта', null=True, blank=True)
    longitude = models.FloatField(verbose_name='Долгота', null=True, blank=True)

    # Характеристики
    area = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Площадь (м²)')
    capacity = models.IntegerField(verbose_name='Вместимость', default=1)
    floor = models.IntegerField(verbose_name='Этаж', null=True, blank=True)

    # Удобства
    amenities = models.ManyToManyField(Amenity, blank=True, verbose_name='Удобства')

    # Цены
    price_per_hour = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена за час', null=True,
                                         blank=True)
    price_per_day = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена за день', null=True,
                                        blank=True)
    price_per_week = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена за неделю', null=True,
                                         blank=True)
    price_per_month = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена за месяц', null=True,
                                          blank=True)

    # Статус
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name='Статус')
    is_featured = models.BooleanField(default=False, verbose_name='Рекомендуемое')

    # Метаданные
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Помещение'
        verbose_name_plural = 'Помещения'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_main_image(self):
        return self.images.filter(is_main=True).first() or self.images.first()

    def get_available_price(self):
        if self.price_per_hour:
            return self.price_per_hour
        elif self.price_per_day:
            return self.price_per_day
        elif self.price_per_week:
            return self.price_per_week
        elif self.price_per_month:
            return self.price_per_month
        return 0


class PropertyImage(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='properties/images/')
    is_main = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Изображение помещения'
        verbose_name_plural = 'Изображения помещений'

    def __str__(self):
        return f'Image for {self.property.title}'


class Booking(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Ожидание'),
        ('confirmed', 'Подтверждено'),
        ('cancelled', 'Отменено'),
        ('completed', 'Завершено'),
    )

    # Идентификаторы
    booking_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='bookings', verbose_name='Помещение')
    tenant = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'user_type': 'tenant'},
                               verbose_name='Арендатор')

    # Даты и время
    start_datetime = models.DateTimeField(verbose_name='Начало аренды')
    end_datetime = models.DateTimeField(verbose_name='Окончание аренды')

    # Информация о бронировании
    guests = models.IntegerField(default=1, verbose_name='Количество гостей')
    special_requests = models.TextField(blank=True, verbose_name='Особые пожелания')

    # Цены и оплата
    total_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Общая стоимость')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='Статус')

    # Метаданные
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Бронирование'
        verbose_name_plural = 'Бронирования'
        ordering = ['-created_at']

    def __str__(self):
        return f'Бронирование #{self.booking_id} - {self.property.title}'

    def get_duration_hours(self):
        duration = self.end_datetime - self.start_datetime
        return duration.total_seconds() / 3600

    def is_active(self):
        now = timezone.now()
        return self.start_datetime <= now <= self.end_datetime and self.status == 'confirmed'


class Review(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='review')
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Отзыв'
        verbose_name_plural = 'Отзывы'
        unique_together = ['property', 'user', 'booking']

    def __str__(self):
        return f'Отзыв от {self.user} на {self.property}'


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Избранное'
        verbose_name_plural = 'Избранные'
        unique_together = ['user', 'property']

    def __str__(self):
        return f'{self.user} → {self.property}'


class Notification(models.Model):
    TYPE_CHOICES = (
        ('booking_created', 'Новое бронирование'),
        ('booking_confirmed', 'Бронирование подтверждено'),
        ('booking_cancelled', 'Бронирование отменено'),
        ('review_added', 'Добавлен отзыв'),
        ('system', 'Системное уведомление'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_content_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} для {self.user}'