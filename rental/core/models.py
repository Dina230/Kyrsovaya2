# core/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
import uuid
from datetime import timedelta


class User(AbstractUser):
    """Модель пользователя"""
    USER_TYPE_CHOICES = [
        ('tenant', 'Арендатор'),
        ('landlord', 'Арендодатель'),
        ('admin', 'Администратор'),
    ]

    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPE_CHOICES,
        default='tenant',
        verbose_name='Тип пользователя'
    )
    avatar = models.ImageField(
        upload_to='avatars/',
        null=True,
        blank=True,
        verbose_name='Аватар'
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name='Телефон'
    )
    company_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Название компании'
    )
    email_verified = models.BooleanField(
        default=False,
        verbose_name='Email подтвержден'
    )
    phone_verified = models.BooleanField(
        default=False,
        verbose_name='Телефон подтвержден'
    )

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'

    def __str__(self):
        return self.username

    def get_full_name_or_username(self):
        """Получить полное имя или имя пользователя"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username


class Category(models.Model):
    """Модель категории помещений"""
    name = models.CharField(
        max_length=100,
        verbose_name='Название категории'
    )
    slug = models.SlugField(
        unique=True,
        verbose_name='Slug'
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name='Описание'
    )
    icon = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='Иконка'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Amenity(models.Model):
    """Модель удобств"""
    name = models.CharField(
        max_length=100,
        verbose_name='Название'
    )
    icon = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='Иконка'
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name='Описание'
    )

    class Meta:
        verbose_name = 'Удобство'
        verbose_name_plural = 'Удобства'
        ordering = ['name']

    def __str__(self):
        return self.name


class Property(models.Model):
    """Модель помещения"""
    PROPERTY_TYPE_CHOICES = [
        ('office', 'Офис'),
        ('conference', 'Конференц-зал'),
        ('coworking', 'Коворкинг'),
        ('shop', 'Торговая площадь'),
        ('warehouse', 'Склад'),
        ('studio', 'Студия'),
        ('other', 'Другое'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('pending', 'На модерации'),
        ('active', 'Активно'),
        ('inactive', 'Неактивно'),
    ]

    landlord = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='properties',
        verbose_name='Владелец'
    )
    title = models.CharField(
        max_length=200,
        verbose_name='Название'
    )
    slug = models.SlugField(
        unique=True,
        verbose_name='Slug'
    )
    description = models.TextField(
        verbose_name='Описание'
    )
    property_type = models.CharField(
        max_length=20,
        choices=PROPERTY_TYPE_CHOICES,
        default='office',
        verbose_name='Тип помещения'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='properties',
        verbose_name='Категория'
    )
    city = models.CharField(
        max_length=100,
        default='Москва',
        verbose_name='Город'
    )
    address = models.CharField(
        max_length=200,
        default='Не указан',
        verbose_name='Адрес'
    )
    latitude = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Широта'
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Долгота'
    )
    price_per_hour = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1000.00,
        verbose_name='Цена за час'
    )
    price_per_day = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Цена за день'
    )
    price_per_week = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Цена за неделю'
    )
    price_per_month = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Цена за месяц'
    )
    capacity = models.PositiveIntegerField(
        default=1,
        verbose_name='Вместимость'
    )
    area = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=10.00,
        verbose_name='Площадь (м²)'
    )
    floor = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Этаж'
    )
    amenities = models.ManyToManyField(
        Amenity,
        blank=True,
        related_name='properties',
        verbose_name='Удобства'
    )
    is_featured = models.BooleanField(
        default=False,
        verbose_name='Рекомендуемое'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        verbose_name='Статус'
    )
    views_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Количество просмотров'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )

    class Meta:
        verbose_name = 'Помещение'
        verbose_name_plural = 'Помещения'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            unique_slug = f"{base_slug}-{uuid.uuid4().hex[:8]}"
            self.slug = unique_slug
        super().save(*args, **kwargs)

    def get_main_image(self):
        """Получить главное изображение"""
        return self.images.filter(is_main=True).first() or self.images.first()


class PropertyImage(models.Model):
    """Модель изображений помещения"""
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Помещение'
    )
    image = models.ImageField(
        upload_to='properties/',
        verbose_name='Изображение'
    )
    is_main = models.BooleanField(
        default=False,
        verbose_name='Главное изображение'
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата загрузки'
    )

    class Meta:
        verbose_name = 'Изображение помещения'
        verbose_name_plural = 'Изображения помещений'

    def __str__(self):
        return f"Изображение {self.property.title}"


class Booking(models.Model):
    """Модель бронирования"""
    STATUS_CHOICES = [
        ('pending', 'Ожидание'),
        ('confirmed', 'Подтверждено'),
        ('cancelled', 'Отменено'),
        ('completed', 'Завершено'),
    ]

    booking_id = models.CharField(
        max_length=20,
        unique=True,
        verbose_name='ID бронирования'
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='bookings',
        verbose_name='Помещение'
    )
    tenant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='bookings_as_tenant',
        verbose_name='Арендатор'
    )
    start_datetime = models.DateTimeField(
        verbose_name='Начало бронирования'
    )
    end_datetime = models.DateTimeField(
        verbose_name='Окончание бронирования'
    )
    guests = models.PositiveIntegerField(
        default=1,
        verbose_name='Количество гостей'
    )
    special_requests = models.TextField(
        blank=True,
        null=True,
        verbose_name='Особые пожелания'
    )
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Итоговая стоимость'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='Статус'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )

    class Meta:
        verbose_name = 'Бронирование'
        verbose_name_plural = 'Бронирования'
        ordering = ['-created_at']

    def __str__(self):
        return f"Бронирование #{self.booking_id}"

    def save(self, *args, **kwargs):
        if not self.booking_id:
            self.booking_id = f"B{self.property.id:04d}-{uuid.uuid4().hex[:6].upper()}"

        # Расчет стоимости
        if self.start_datetime and self.end_datetime:
            duration_hours = (self.end_datetime - self.start_datetime).total_seconds() / 3600
            self.total_price = round(float(self.property.price_per_hour) * duration_hours, 2)

        super().save(*args, **kwargs)

    def get_duration(self):
        """Получить длительность бронирования"""
        if self.start_datetime and self.end_datetime:
            duration = self.end_datetime - self.start_datetime
            hours = duration.seconds // 3600
            minutes = (duration.seconds % 3600) // 60
            return {'hours': hours, 'minutes': minutes, 'total_hours': duration.total_seconds() / 3600}
        return {'hours': 0, 'minutes': 0, 'total_hours': 0}


class Review(models.Model):
    """Модель отзыва"""
    REVIEW_STATUS_CHOICES = [
        ('pending', 'На модерации'),
        ('approved', 'Одобрено'),
        ('rejected', 'Отклонено'),
    ]

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='Помещение'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='Пользователь'
    )
    rating = models.PositiveIntegerField(
        verbose_name='Рейтинг',
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        default=5
    )
    comment = models.TextField(
        verbose_name='Комментарий',
        max_length=1000,
        default='Без комментария'
    )
    status = models.CharField(
        max_length=20,
        choices=REVIEW_STATUS_CHOICES,
        default='pending',
        verbose_name='Статус отзыва'
    )
    admin_comment = models.TextField(
        verbose_name='Комментарий администратора',
        blank=True,
        null=True,
        max_length=500
    )
    is_verified = models.BooleanField(
        default=False,
        verbose_name='Подтвержденный отзыв'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )

    class Meta:
        verbose_name = 'Отзыв'
        verbose_name_plural = 'Отзывы'
        ordering = ['-created_at']
        unique_together = ['property', 'user']

    def __str__(self):
        return f'Отзыв от {self.user} на {self.property} ({self.rating}/5)'


class Favorite(models.Model):
    """Модель избранного"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name='Пользователь'
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='favorited_by',
        verbose_name='Помещение'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата добавления'
    )

    class Meta:
        verbose_name = 'Избранное'
        verbose_name_plural = 'Избранное'
        unique_together = ['user', 'property']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} -> {self.property}"


class Notification(models.Model):
    """Модель уведомлений"""
    NOTIFICATION_TYPES = [
        ('booking_created', 'Новое бронирование'),
        ('booking_confirmed', 'Бронирование подтверждено'),
        ('booking_cancelled', 'Бронирование отменено'),
        ('review_added', 'Добавлен отзыв'),
        ('message_received', 'Новое сообщение'),
        ('system', 'Системное уведомление'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Пользователь'
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NOTIFICATION_TYPES,
        verbose_name='Тип уведомления'
    )
    title = models.CharField(
        max_length=200,
        verbose_name='Заголовок'
    )
    message = models.TextField(
        verbose_name='Сообщение'
    )
    is_read = models.BooleanField(
        default=False,
        verbose_name='Прочитано'
    )
    related_object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='ID связанного объекта'
    )
    related_object_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name='Тип связанного объекта'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )

    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.title}"


class Message(models.Model):
    """Модель сообщений"""
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_messages',
        verbose_name='Отправитель'
    )
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='received_messages',
        verbose_name='Получатель'
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='messages',
        verbose_name='Помещение'
    )
    subject = models.CharField(
        max_length=200,
        verbose_name='Тема'
    )
    message = models.TextField(
        verbose_name='Сообщение'
    )
    is_read = models.BooleanField(
        default=False,
        verbose_name='Прочитано'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )

    class Meta:
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.sender} -> {self.recipient}: {self.subject}"