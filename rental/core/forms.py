from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, PasswordChangeForm
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, timedelta
import re
from .models import User, Property, Booking, Review, Favorite, Category, Amenity


class CustomUserCreationForm(UserCreationForm):
    """Форма регистрации пользователя"""
    USER_TYPE_CHOICES_REGISTRATION = [
        ('tenant', 'Арендатор'),
        ('landlord', 'Арендодатель'),
    ]

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'example@email.com'
        })
    )
    first_name = forms.CharField(
        required=True,
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Иван'
        })
    )
    last_name = forms.CharField(
        required=True,
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Иванов'
        })
    )
    phone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+7 (999) 999-99-99',
            'id': 'phone'
        })
    )
    company_name = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Название вашей компании'
        })
    )
    user_type = forms.ChoiceField(
        choices=USER_TYPE_CHOICES_REGISTRATION,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone',
                  'company_name', 'user_type', 'password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ivan_ivanov'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control'})

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError('Пользователь с таким email уже существует.')
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not phone:
            return phone

        phone_digits = re.sub(r'\D', '', phone)
        if len(phone_digits) < 10:
            raise ValidationError('Номер телефона должен содержать не менее 10 цифр.')
        if phone_digits[0] not in ['7', '8']:
            raise ValidationError('Номер телефона должен начинаться с 7 или 8.')

        if User.objects.filter(phone__endswith=phone_digits[-10:]).exists():
            raise ValidationError('Пользователь с таким телефоном уже существует.')

        if len(phone_digits) == 11:
            phone_digits = phone_digits[1:]

        phone_digits = phone_digits[:10]
        formatted_phone = f"+7 ({phone_digits[:3]}) {phone_digits[3:6]}-{phone_digits[6:8]}-{phone_digits[8:10]}"

        return formatted_phone

    def save(self, commit=True):
        user = super().save(commit=False)
        if user.user_type == 'admin':
            user.user_type = 'tenant'
        if commit:
            user.save()
        return user


class CustomUserChangeForm(UserChangeForm):
    """Форма редактирования профиля пользователя"""
    phone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+7 (999) 999-99-99',
            'id': 'phone'
        })
    )

    class Meta:
        model = User
        fields = ['avatar', 'first_name', 'last_name', 'email', 'phone', 'company_name']
        widgets = {
            'avatar': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control'
            }),
            'company_name': forms.TextInput(attrs={
                'class': 'form-control'
            }),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not phone:
            return phone

        phone_digits = re.sub(r'\D', '', phone)
        if len(phone_digits) < 10:
            raise ValidationError('Номер телефона должен содержать не менее 10 цифр.')
        if phone_digits[0] not in ['7', '8']:
            raise ValidationError('Номер телефона должен начинаться с 7 или 8.')

        if len(phone_digits) == 11:
            phone_digits = phone_digits[1:]

        phone_digits = phone_digits[:10]
        formatted_phone = f"+7 ({phone_digits[:3]}) {phone_digits[3:6]}-{phone_digits[6:8]}-{phone_digits[8:10]}"

        return formatted_phone


class MultipleFileInput(forms.ClearableFileInput):
    """Кастомный виджет для множественной загрузки файлов"""
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Кастомное поле для множественной загрузки файлов"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result


class PropertyForm(forms.ModelForm):
    """Форма для добавления/редактирования помещения"""
    images = MultipleFileField(
        required=False,
        label='Изображения'
    )

    # Добавляем поля для цены за день, неделю, месяц
    price_per_day = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Автоматический расчет',
            'id': 'price_per_day'
        }),
        label='Цена за день (₽)'
    )

    price_per_week = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Автоматический расчет',
            'id': 'price_per_week'
        }),
        label='Цена за неделю (₽)'
    )

    price_per_month = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Автоматический расчет',
            'id': 'price_per_month'
        }),
        label='Цена за месяц (₽)'
    )

    class Meta:
        model = Property
        fields = ['title', 'description', 'property_type', 'category', 'city',
                  'address', 'price_per_hour', 'price_per_day', 'price_per_week',
                  'price_per_month', 'capacity', 'area', 'floor', 'amenities',
                  'is_featured', 'status']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Название помещения'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Подробное описание помещения'
            }),
            'property_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'category': forms.Select(attrs={
                'class': 'form-select'
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Москва'
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ул. Примерная, д. 1'
            }),
            'price_per_hour': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'step': 100,
                'id': 'price_per_hour'
            }),
            'capacity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1
            }),
            'area': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'step': 0.01
            }),
            'floor': forms.NumberInput(attrs={
                'class': 'form-control'
            }),
            'amenities': forms.CheckboxSelectMultiple(attrs={
                'class': 'form-check-input'
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['amenities'].queryset = Amenity.objects.all()

        # Делаем некоторые поля необязательными
        self.fields['category'].required = False
        self.fields['area'].required = False
        self.fields['floor'].required = False
        self.fields['price_per_day'].required = False
        self.fields['price_per_week'].required = False
        self.fields['price_per_month'].required = False

        # Устанавливаем начальные значения для цен при редактировании
        if self.instance and self.instance.pk:
            if not self.initial.get('price_per_day') and self.instance.price_per_hour:
                # Автоматический расчет если нет цены за день
                self.initial['price_per_day'] = self.instance.price_per_hour * 8

            if not self.initial.get('price_per_week') and self.instance.price_per_hour:
                # Автоматический расчет если нет цены за неделю
                self.initial['price_per_week'] = self.instance.price_per_hour * 8 * 5  # 5 рабочих дней

            if not self.initial.get('price_per_month') and self.instance.price_per_hour:
                # Автоматический расчет если нет цены за месяц
                self.initial['price_per_month'] = self.instance.price_per_hour * 8 * 20  # 20 рабочих дней


class BookingForm(forms.ModelForm):
    """Форма бронирования помещения"""
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'start_date'
        }),
        label='Дата начала'
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'end_date'
        }),
        label='Дата окончания'
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={
            'type': 'time',
            'class': 'form-control',
            'id': 'start_time'
        }),
        label='Время начала',
        initial='09:00'
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={
            'type': 'time',
            'class': 'form-control',
            'id': 'end_time'
        }),
        label='Время окончания',
        initial='18:00'
    )
    booking_type = forms.ChoiceField(
        choices=[('hourly', 'Почасовое'), ('daily', 'Посуточное'),
                 ('weekly', 'Понедельное'), ('monthly', 'Помесячное')],
        widget=forms.RadioSelect(attrs={
            'class': 'form-check-input booking-type'
        }),
        initial='hourly',
        label='Тип бронирования'
    )
    days_count = forms.IntegerField(
        min_value=1,
        max_value=365,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'id': 'days_count',
            'min': '1',
            'max': '365'
        }),
        required=False,
        label='Количество дней'
    )

    class Meta:
        model = Booking
        fields = ['guests', 'special_requests']
        widgets = {
            'guests': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'id': 'guests'
            }),
            'special_requests': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Особые пожелания (необязательно)',
                'id': 'special_requests'
            }),
        }
        labels = {
            'guests': 'Количество гостей',
            'special_requests': 'Особые пожелания',
        }

    def __init__(self, *args, **kwargs):
        self.property_obj = kwargs.pop('property_obj', None)
        super().__init__(*args, **kwargs)

        # Устанавливаем минимальную дату - сегодня
        today = timezone.now().date().strftime('%Y-%m-%d')
        self.fields['start_date'].widget.attrs['min'] = today
        self.fields['end_date'].widget.attrs['min'] = today

        # Устанавливаем начальные значения
        tomorrow = timezone.now() + timedelta(days=1)
        self.fields['start_date'].initial = tomorrow.date()
        self.fields['end_date'].initial = tomorrow.date()

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        booking_type = cleaned_data.get('booking_type')
        days_count = cleaned_data.get('days_count', 1)
        guests = cleaned_data.get('guests')

        if not all([start_date, end_date, start_time, end_time]):
            raise ValidationError('Все даты и времена должны быть заполнены.')

        # Создаем полные datetime объекты
        start_datetime = datetime.combine(start_date, start_time)
        end_datetime = datetime.combine(end_date, end_time)

        # Конвертируем в aware datetime
        start_datetime = timezone.make_aware(start_datetime)
        end_datetime = timezone.make_aware(end_datetime)

        # Для посуточного, недельного и месячного бронирования
        if booking_type in ['daily', 'weekly', 'monthly']:
            end_datetime = end_datetime.replace(hour=23, minute=59)

        # Проверка на прошедшие даты
        if start_datetime < timezone.now():
            raise ValidationError({'start_date': 'Нельзя бронировать на прошедшие даты.'})

        # Проверка что окончание позже начала
        if end_datetime <= start_datetime:
            raise ValidationError({'end_date': 'Дата окончания должна быть позже даты начала.'})

        # Проверка минимальной продолжительности
        duration = end_datetime - start_datetime
        if booking_type == 'hourly' and duration < timedelta(hours=1):
            raise ValidationError({'end_time': 'Минимальное время бронирования - 1 час.'})
        if booking_type == 'daily' and duration < timedelta(days=1):
            raise ValidationError({'end_date': 'Минимальное время бронирования - 1 день.'})
        if booking_type == 'weekly' and duration < timedelta(days=7):
            raise ValidationError({'end_date': 'Минимальное время бронирования - 7 дней.'})
        if booking_type == 'monthly' and duration < timedelta(days=28):
            raise ValidationError({'end_date': 'Минимальное время бронирования - 28 дней.'})

        # Проверка рабочего времени для почасового бронирования
        if booking_type == 'hourly':
            if start_datetime.hour < 9 or start_datetime.hour >= 22:
                raise ValidationError({'start_time': 'Рабочее время с 9:00 до 22:00.'})
            if end_datetime.hour > 22 or (end_datetime.hour == 22 and end_datetime.minute > 0):
                raise ValidationError({'end_time': 'Рабочее время до 22:00.'})

        # Проверка доступности помещения
        if self.property_obj:
            conflicting_bookings = Booking.objects.filter(
                property=self.property_obj,
                status__in=['confirmed', 'pending'],
                start_datetime__lt=end_datetime,
                end_datetime__gt=start_datetime
            ).exclude(id=self.instance.id if self.instance else None)

            if conflicting_bookings.exists():
                raise ValidationError('Выбранное время уже занято другим бронированием.')

        # Проверка количества гостей
        if guests:
            if guests < 1:
                raise ValidationError({'guests': 'Минимум 1 гость.'})
            if self.property_obj and guests > self.property_obj.capacity:
                raise ValidationError(
                    {'guests': f'Превышена вместимость помещения. Максимум: {self.property_obj.capacity} человек.'})

        # Сохраняем рассчитанные datetime
        cleaned_data['calculated_start_datetime'] = start_datetime
        cleaned_data['calculated_end_datetime'] = end_datetime

        # Рассчитываем стоимость
        if self.property_obj:
            duration_days = (end_date - start_date).days + 1

            if booking_type == 'hourly':
                hours = duration.total_seconds() / 3600
                price = float(self.property_obj.price_per_hour) * hours
            elif booking_type == 'daily':
                if self.property_obj.price_per_day:
                    price = float(self.property_obj.price_per_day) * duration_days
                else:
                    price = float(self.property_obj.price_per_hour) * 8 * duration_days
            elif booking_type == 'weekly':
                weeks = max(1, duration_days // 7 + (1 if duration_days % 7 > 0 else 0))
                if self.property_obj.price_per_week:
                    price = float(self.property_obj.price_per_week) * weeks
                elif self.property_obj.price_per_day:
                    price = float(self.property_obj.price_per_day) * 5 * weeks  # 5 рабочих дней в неделю
                else:
                    price = float(self.property_obj.price_per_hour) * 8 * 5 * weeks
            elif booking_type == 'monthly':
                months = max(1, duration_days // 30 + (1 if duration_days % 30 > 0 else 0))
                if self.property_obj.price_per_month:
                    price = float(self.property_obj.price_per_month) * months
                elif self.property_obj.price_per_week:
                    price = float(self.property_obj.price_per_week) * 4 * months  # 4 недели в месяц
                elif self.property_obj.price_per_day:
                    price = float(self.property_obj.price_per_day) * 20 * months  # 20 рабочих дней в месяц
                else:
                    price = float(self.property_obj.price_per_hour) * 8 * 20 * months

            cleaned_data['calculated_price'] = round(price, 2)

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.start_datetime = self.cleaned_data['calculated_start_datetime']
        instance.end_datetime = self.cleaned_data['calculated_end_datetime']

        if 'calculated_price' in self.cleaned_data:
            instance.total_price = self.cleaned_data['calculated_price']

        if commit:
            instance.save()
        return instance


class ReviewForm(forms.ModelForm):
    """Форма добавления отзыва"""

    class Meta:
        model = Review
        fields = ['rating', 'comment']
        widgets = {
            'rating': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 5
            }),
            'comment': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Оставьте ваш отзыв о помещении...'
            }),
        }
        labels = {
            'rating': 'Оценка (1-5)',
            'comment': 'Комментарий'
        }


class ContactForm(forms.Form):
    """Форма обратной связи"""
    subject = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Тема сообщения'
        })
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 5,
            'placeholder': 'Ваше сообщение...'
        })
    )


class PasswordChangeCustomForm(PasswordChangeForm):
    """Кастомная форма смены пароля"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].widget.attrs.update({'class': 'form-control'})
        self.fields['new_password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['new_password2'].widget.attrs.update({'class': 'form-control'})


class AdminUserEditForm(UserChangeForm):
    """Форма редактирования пользователя для администратора"""
    phone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+7 (999) 999-99-99',
            'id': 'phone'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone',
                  'company_name', 'user_type', 'is_active', 'is_staff']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'user_type': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not phone:
            return phone

        phone_digits = re.sub(r'\D', '', phone)
        if len(phone_digits) < 10:
            raise ValidationError('Номер телефона должен содержать не менее 10 цифр.')
        if phone_digits[0] not in ['7', '8']:
            raise ValidationError('Номер телефона должен начинаться с 7 или 8.')

        if len(phone_digits) == 11:
            phone_digits = phone_digits[1:]

        phone_digits = phone_digits[:10]
        formatted_phone = f"+7 ({phone_digits[:3]}) {phone_digits[3:6]}-{phone_digits[6:8]}-{phone_digits[8:10]}"

        return formatted_phone


class AdminPropertyEditForm(forms.ModelForm):
    """Форма редактирования помещения для администратора"""

    class Meta:
        model = Property
        fields = ['title', 'description', 'property_type', 'category', 'city',
                  'address', 'price_per_hour', 'price_per_day', 'price_per_week',
                  'price_per_month', 'capacity', 'area', 'floor', 'amenities',
                  'is_featured', 'status', 'landlord']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'property_type': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'price_per_hour': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_day': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_week': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_month': forms.NumberInput(attrs={'class': 'form-control'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control'}),
            'area': forms.NumberInput(attrs={'class': 'form-control'}),
            'floor': forms.NumberInput(attrs={'class': 'form-control'}),
            'amenities': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'landlord': forms.Select(attrs={'class': 'form-select'}),
        }


class AdminBookingEditForm(forms.ModelForm):
    """Форма редактирования бронирования для администратора"""

    class Meta:
        model = Booking
        fields = ['property', 'tenant', 'start_datetime', 'end_datetime',
                  'guests', 'special_requests', 'total_price', 'status']
        widgets = {
            'property': forms.Select(attrs={'class': 'form-select'}),
            'tenant': forms.Select(attrs={'class': 'form-select'}),
            'start_datetime': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'end_datetime': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'guests': forms.NumberInput(attrs={'class': 'form-control'}),
            'special_requests': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3
            }),
            'total_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }


class AdminReviewEditForm(forms.ModelForm):
    """Форма редактирования отзыва для администратора"""

    class Meta:
        model = Review
        fields = ['status', 'admin_comment', 'is_verified']
        widgets = {
            'status': forms.Select(attrs={
                'class': 'form-select',
            }),
            'admin_comment': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Комментарий администратора'
            }),
            'is_verified': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
        labels = {
            'status': 'Статус отзыва',
            'admin_comment': 'Комментарий администратора',
            'is_verified': 'Подтвержденный отзыв'
        }


class SearchForm(forms.Form):
    """Форма поиска"""
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Поиск...'
        })
    )
    property_type = forms.ChoiceField(
        required=False,
        choices=[('', 'Все типы')] + list(Property.PROPERTY_TYPE_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    city = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Город'
        })
    )
    min_price = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Мин. цена'
        })
    )
    max_price = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Макс. цена'
        })
    )


class FilterForm(forms.Form):
    """Форма фильтрации"""
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'Все статусы'), ('active', 'Активные'), ('inactive', 'Неактивные')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    user_type = forms.ChoiceField(
        required=False,
        choices=[('', 'Все типы')] + list(User.USER_TYPE_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )