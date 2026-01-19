# core/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import *

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'user_type', 'is_staff']
    list_filter = ['user_type', 'is_staff', 'is_active']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Дополнительная информация', {
            'fields': ('user_type', 'phone', 'company_name')
        }),
    )

@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ['title', 'landlord', 'property_type', 'city', 'price_per_hour', 'status']
    list_filter = ['property_type', 'status', 'city']
    search_fields = ['title', 'description', 'address']

admin.site.register(PropertyCategory)
admin.site.register(Amenity)
admin.site.register(PropertyImage)
admin.site.register(Booking)
admin.site.register(Review)
admin.site.register(Favorite)