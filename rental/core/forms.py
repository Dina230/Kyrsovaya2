# core/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, PasswordChangeForm
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, timedelta
from .models import User, Property, Booking, Review, Favorite, Category, Amenity


class CustomUserCreationForm(UserCreationForm):
    """Форма регистрации пользователя"""
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
            'placeholder': '+7 (XXX) XXX-XX-XX'
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
        choices=User.USER_TYPE_CHOICES,
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


class CustomUserChangeForm(UserChangeForm):
    """Форма редактирования профиля пользователя"""

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
            'phone': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'company_name': forms.TextInput(attrs={
                'class': 'form-control'
            }),
        }


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

    class Meta:
        model = Property
        fields = ['title', 'description', 'property_type', 'category', 'city',
                  'address', 'price_per_hour', 'capacity', 'area', 'floor',
                  'amenities', 'is_featured', 'status']
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
                'step': 100
            }),
            'capacity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1
            }),
            'area': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'step': 1
            }),
            'floor': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': -5,
                'max': 200
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


class BookingForm(forms.ModelForm):
    """Форма бронирования помещения"""

    class Meta:
        model = Booking
        fields = ['start_datetime', 'end_datetime', 'guests', 'special_requests']
        widgets = {
            'start_datetime': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control',
                'id': 'start_datetime'
            }),
            'end_datetime': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control',
                'id': 'end_datetime'
            }),
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
            'start_datetime': 'Начало бронирования',
            'end_datetime': 'Окончание бронирования',
            'guests': 'Количество гостей',
            'special_requests': 'Особые пожелания',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Устанавливаем минимальную дату - сегодня
        today = timezone.now().strftime('%Y-%m-%dT%H:%M')
        self.fields['start_datetime'].widget.attrs['min'] = today
        self.fields['end_datetime'].widget.attrs['min'] = today

        # Устанавливаем значения по умолчанию
        if not self.instance.pk:
            tomorrow = timezone.now() + timedelta(days=1)
            self.fields['start_datetime'].initial = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
            self.fields['end_datetime'].initial = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
            self.fields['guests'].initial = 1

    def clean(self):
        cleaned_data = super().clean()
        start_datetime = cleaned_data.get('start_datetime')
        end_datetime = cleaned_data.get('end_datetime')
        guests = cleaned_data.get('guests')

        if start_datetime and end_datetime:
            # Проверка на прошедшие даты
            if start_datetime < timezone.now():
                raise ValidationError({'start_datetime': 'Нельзя бронировать на прошедшие даты.'})

            # Проверка что окончание позже начала
            if end_datetime <= start_datetime:
                raise ValidationError({'end_datetime': 'Время окончания должно быть позже времени начала.'})

            # Проверка минимальной продолжительности (1 час)
            duration = end_datetime - start_datetime
            if duration < timedelta(hours=1):
                raise ValidationError({'end_datetime': 'Минимальное время бронирования - 1 час.'})

            # Проверка рабочего времени (9:00-22:00)
            if start_datetime.hour < 9 or start_datetime.hour >= 22:
                raise ValidationError({'start_datetime': 'Рабочее время с 9:00 до 22:00.'})

            if end_datetime.hour > 22 or (end_datetime.hour == 22 and end_datetime.minute > 0):
                raise ValidationError({'end_datetime': 'Рабочее время до 22:00.'})

            # Проверка на длительное бронирование (более 24 часов)
            if duration > timedelta(days=1):
                self.add_warning = True  # Добавляем флаг для предупреждения

        if guests:
            if guests < 1:
                raise ValidationError({'guests': 'Минимум 1 гость.'})

        return cleaned_data


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

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone',
                  'company_name', 'user_type', 'is_active', 'is_staff']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'user_type': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AdminPropertyEditForm(forms.ModelForm):
    """Форма редактирования помещения для администратора"""

    class Meta:
        model = Property
        fields = ['title', 'description', 'property_type', 'category', 'city',
                  'address', 'price_per_hour', 'capacity', 'area', 'floor',
                  'amenities', 'is_featured', 'status', 'landlord']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'property_type': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'price_per_hour': forms.NumberInput(attrs={'class': 'form-control'}),
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