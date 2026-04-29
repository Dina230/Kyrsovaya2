from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Основные пути
    path('', views.home, name='home'),
    path('help/', views.help_page, name='help'),
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),

    # Личный кабинет
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/expenses/', views.tenant_expenses, name='tenant_expenses'),
    path('dashboard/revenue/', views.landlord_revenue, name='landlord_revenue'),
    path('dashboard/platform-revenue/', views.admin_platform_revenue, name='admin_platform_revenue'),

    # Профиль
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/password/', views.change_password, name='change_password'),

    # Уведомления
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/<int:notification_id>/mark-read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('notifications/<int:notification_id>/delete/', views.delete_notification, name='delete_notification'),
    path('notifications/delete-all/', views.delete_all_notifications, name='delete_all_notifications'),
    path('notifications/unread-count/', views.get_unread_count, name='get_unread_count'),

    # Мессенджер
    path('messages/', views.messages_list, name='messages_list'),
    path('messages/send/<int:user_id>/', views.send_message, name='send_message'),
    path('messages/property/<int:property_id>/', views.send_message, name='send_message_property'),

    # Для арендатора
    path('my-bookings/export.csv', views.export_my_bookings_csv, name='export_my_bookings_csv'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('my-favorites/', views.my_favorites, name='my_favorites'),
    path('bookings/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('bookings/<int:booking_id>/cancel/', views.cancel_booking, name='cancel_booking'),
    path('bookings/<int:booking_id>/review/', views.add_review, name='add_review'),
    path('bookings/<int:booking_id>/payment/', views.payment, name='payment'),
    path('bookings/<int:booking_id>/payment/success/', views.payment_success, name='payment_success'),
    path('bookings/<int:booking_id>/contract/download/', views.download_contract, name='download_contract'),

    path('messages/unread-count/', views.get_unread_messages_count, name='get_unread_messages_count'),

    # Корзина (несколько бронирований подряд)
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:property_id>/', views.cart_add, name='cart_add'),
    path('cart/remove/<int:item_id>/', views.cart_remove, name='cart_remove'),
    path('cart/checkout/', views.checkout, name='checkout'),

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
    path('properties/<int:property_id>/calendar/', views.booking_calendar, name='booking_calendar'),
    path('properties/<int:property_id>/favorite/', views.toggle_favorite, name='toggle_favorite'),
    path('properties/<int:property_id>/book/', views.create_booking, name='create_booking'),
    path('api/properties/<int:property_id>/book-ajax/', views.ajax_create_booking, name='ajax_create_booking'),

    # Кастомная админка
    path('admin-panel/dashboard/', views.custom_admin_dashboard, name='custom_admin_dashboard'),
    path('admin-panel/users/', views.admin_user_management, name='admin_user_management'),
    path('admin-panel/users/export/', views.export_users_csv, name='export_users_csv'),
    path('admin-panel/properties/', views.admin_property_management, name='admin_property_management'),
    path('admin-panel/bookings/', views.admin_booking_management, name='admin_booking_management'),
    path('admin-panel/reviews/', views.admin_review_management, name='admin_review_management'),
    path('admin-panel/audit/', views.admin_audit_log, name='admin_audit_log'),
    path('admin-panel/user-audit/', views.admin_user_audit_log, name='admin_user_audit_log'),

    # Встроенные Django представления для сброса пароля
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='core/password_reset.html'),
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
