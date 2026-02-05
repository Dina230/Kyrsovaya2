# core/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User, Category, Amenity, Property,
    PropertyImage, Booking, Review, Favorite,
    Notification, Message
)

# Кастомная админка для пользователя
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name',
                    'user_type', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('user_type', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Персональная информация', {'fields': ('first_name', 'last_name', 'email', 'phone', 'avatar', 'company_name')}),
        ('Тип пользователя', {'fields': ('user_type',)}),
        ('Разрешения', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Важные даты', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'user_type'),
        }),
    )


# Админка для категорий
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'created_at')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


# Админка для удобств
class AmenityAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon')
    search_fields = ('name',)


# Админка для изображений помещений (inline)
class PropertyImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 1
    fields = ('image', 'is_main')
    readonly_fields = ('uploaded_at',)


# Админка для помещений
class PropertyAdmin(admin.ModelAdmin):
    list_display = ('title', 'landlord', 'property_type', 'city',
                    'price_per_hour', 'status', 'is_featured', 'created_at')
    list_filter = ('property_type', 'status', 'is_featured', 'city')
    search_fields = ('title', 'description', 'address', 'city')
    readonly_fields = ('slug', 'views_count', 'created_at', 'updated_at')
    filter_horizontal = ('amenities',)
    inlines = [PropertyImageInline]
    fieldsets = (
        ('Основная информация', {
            'fields': ('title', 'slug', 'description', 'property_type', 'category', 'landlord')
        }),
        ('Локация', {
            'fields': ('city', 'address', 'latitude', 'longitude')
        }),
        ('Характеристики', {
            'fields': ('price_per_hour', 'price_per_day', 'price_per_week', 'price_per_month',
                       'capacity', 'area', 'floor', 'amenities')
        }),
        ('Статус и просмотры', {
            'fields': ('status', 'is_featured', 'views_count')
        }),
        ('Даты', {
            'fields': ('created_at', 'updated_at')
        }),
    )


# Админка для бронирований
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_id', 'property', 'tenant', 'start_datetime',
                    'end_datetime', 'status', 'total_price', 'created_at')
    list_filter = ('status', 'start_datetime')
    search_fields = ('booking_id', 'property__title', 'tenant__username')
    readonly_fields = ('booking_id', 'total_price', 'created_at', 'updated_at')
    date_hierarchy = 'start_datetime'


# Админка для отзывов
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('property', 'user', 'rating', 'status', 'is_verified', 'created_at')
    list_filter = ('status', 'rating', 'is_verified')
    search_fields = ('property__title', 'user__username', 'comment')
    readonly_fields = ('created_at', 'updated_at')


# Админка для избранного
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'property', 'created_at')
    search_fields = ('user__username', 'property__title')


# Админка для уведомлений
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'title', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('user__username', 'title', 'message')
    readonly_fields = ('created_at',)


# Админка для сообщений
class MessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'recipient', 'subject', 'is_read', 'created_at')
    list_filter = ('is_read',)
    search_fields = ('sender__username', 'recipient__username', 'subject', 'message')
    readonly_fields = ('created_at',)


# Регистрация всех моделей
admin.site.register(User, CustomUserAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Amenity, AmenityAdmin)
admin.site.register(Property, PropertyAdmin)
admin.site.register(Booking, BookingAdmin)
admin.site.register(Review, ReviewAdmin)
admin.site.register(Favorite, FavoriteAdmin)
admin.site.register(Notification, NotificationAdmin)
admin.site.register(Message, MessageAdmin)