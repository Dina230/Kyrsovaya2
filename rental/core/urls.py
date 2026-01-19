from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Основные пути
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),

    # Личный кабинет
    path('dashboard/', views.dashboard, name='dashboard'),

    # Профиль
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/password/', views.change_password, name='change_password'),

    # Для арендатора
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('my-favorites/', views.my_favorites, name='my_favorites'),
    path('bookings/<int:booking_id>/', views.booking_detail, name='booking_detail'),  # Добавьте эту строку
    path('bookings/<int:booking_id>/cancel/', views.cancel_booking, name='cancel_booking'),
    path('bookings/<int:booking_id>/review/', views.add_review, name='add_review'),

    # Для арендодателя
    path('my-properties/', views.my_properties, name='my_properties'),
    path('properties/add/', views.add_property, name='add_property'),
    path('properties/<int:property_id>/edit/', views.edit_property, name='edit_property'),
    path('properties/<int:property_id>/delete/', views.delete_property, name='delete_property'),
    path('landlord/bookings/', views.landlord_bookings, name='landlord_bookings'),
    path('bookings/<int:booking_id>/<str:status>/', views.update_booking_status, name='update_booking_status'),
    path('properties/<int:property_id>/images/add/', views.add_property_image, name='add_property_image'),
    path('images/<int:image_id>/delete/', views.delete_property_image, name='delete_property_image'),

    # Помещения
    path('properties/', views.property_list, name='property_list'),
    path('properties/<slug:slug>/', views.property_detail, name='property_detail'),
    path('properties/<int:property_id>/favorite/', views.toggle_favorite, name='toggle_favorite'),
    path('properties/<int:property_id>/book/', views.create_booking, name='create_booking'),
    path('api/properties/<int:property_id>/book-ajax/', views.ajax_create_booking, name='ajax_create_booking'),  # Добавьте эту строку

    # Кастомная админка
    path('admin/dashboard/', views.custom_admin_dashboard, name='custom_admin_dashboard'),

    # Управление пользователями
    path('admin/users/', views.admin_user_management, name='admin_user_management'),
    path('admin/users/add/', views.admin_add_user, name='admin_add_user'),
    path('admin/users/edit/<int:user_id>/', views.admin_edit_user, name='admin_edit_user'),

    # Управление помещениями
    path('admin/properties/', views.admin_property_management, name='admin_property_management'),
    path('admin/properties/add/', views.admin_add_property, name='admin_add_property'),
    path('admin/properties/edit/<int:property_id>/', views.admin_edit_property, name='admin_edit_property'),

    # Управление бронированиями
    path('admin/bookings/', views.admin_booking_management, name='admin_booking_management'),
    path('admin/bookings/edit/<int:booking_id>/', views.admin_edit_booking, name='admin_edit_booking'),

    # Управление отзывами
    path('admin/reviews/', views.admin_review_management, name='admin_review_management'),

    # Настройки системы
    path('admin/settings/', views.admin_system_settings, name='admin_system_settings'),

    # Встроенные Django представления для сброса пароля
    path('password-reset/',
         auth_views.PasswordResetView.as_view(template_name='core/password_reset.html'),
         name='password_reset'),
    path('password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(template_name='core/password_reset_done.html'),
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(template_name='core/password_reset_confirm.html'),
         name='password_reset_confirm'),
    path('password-reset-complete/',
         auth_views.PasswordResetCompleteView.as_view(template_name='core/password_reset_complete.html'),
         name='password_reset_complete'),
]