from django import forms
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django.core.validators import MinValueValidator, MaxValueValidator
from .models import Property, Booking, Review, PropertyCategory, Amenity, Favorite, User


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    first_name = forms.CharField(max_length=30, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=30, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    # Убираем выбор администратора при регистрации
    user_type = forms.ChoiceField(
        choices=[('tenant', 'Арендатор'), ('landlord', 'Арендодатель')],
        initial='tenant',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    company_name = forms.CharField(max_length=200, required=False,
                                   widget=forms.TextInput(attrs={'class': 'form-control'}))
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={
        'class': 'form-control',
        'rows': 2,
        'placeholder': 'Введите ваш адрес'
    }))

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2',
                  'user_type', 'phone', 'company_name', 'address')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']

        # Явно устанавливаем значения для обычных пользователей
        if user.user_type != 'admin':
            user.is_staff = False
            user.is_superuser = False

        if commit:
            user.save()
        return user


class ProfileEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'company_name', 'address', 'avatar']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'avatar': forms.FileInput(attrs={'class': 'form-control'}),
        }


class AdminUserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'user_type', 'phone', 'company_name', 'address',
            'is_active', 'is_staff', 'is_superuser', 'is_verified'
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'user_type': forms.Select(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_superuser': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_verified': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AdminPropertyEditForm(forms.ModelForm):
    class Meta:
        model = Property
        exclude = ['created_at', 'updated_at']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'slug': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'property_type': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'landlord': forms.Select(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-control'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-control'}),
            'area': forms.NumberInput(attrs={'class': 'form-control'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control'}),
            'floor': forms.NumberInput(attrs={'class': 'form-control'}),
            'amenities': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'price_per_hour': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_day': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_week': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_month': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class PropertyForm(forms.ModelForm):
    """Форма для добавления/редактирования помещения (для арендодателя)"""

    class Meta:
        model = Property
        fields = [
            'title', 'description', 'property_type', 'category',
            'address', 'city', 'latitude', 'longitude',
            'area', 'capacity', 'floor', 'amenities',
            'price_per_hour', 'price_per_day', 'price_per_week', 'price_per_month',
            'status'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'property_type': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-control'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-control'}),
            'area': forms.NumberInput(attrs={'class': 'form-control'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control'}),
            'floor': forms.NumberInput(attrs={'class': 'form-control'}),
            'amenities': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'price_per_hour': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_day': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_week': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_month': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }


class AdminBookingEditForm(forms.ModelForm):
    class Meta:
        model = Booking
        exclude = ['created_at', 'updated_at', 'booking_id']
        widgets = {
            'property': forms.Select(attrs={'class': 'form-control'}),
            'tenant': forms.Select(attrs={'class': 'form-control'}),
            'start_datetime': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'end_datetime': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'guests': forms.NumberInput(attrs={'class': 'form-control'}),
            'special_requests': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'total_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }


class BookingForm(forms.ModelForm):
    start_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
                'id': 'id_start_datetime'
            }
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%d.%m.%Y %H:%M']
    )
    end_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
                'id': 'id_end_datetime'
            }
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%d.%m.%Y %H:%M']
    )

    class Meta:
        model = Booking
        fields = ['start_datetime', 'end_datetime', 'guests', 'special_requests']
        widgets = {
            'guests': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 100,
                'id': 'id_guests'
            }),
            'special_requests': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': 'Дополнительные пожелания',
                'id': 'id_special_requests'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Устанавливаем минимальное значение для даты (сегодня)
        from django.utils import timezone
        import datetime
        today = timezone.now().strftime('%Y-%m-%dT%H:%M')
        tomorrow = (timezone.now() + datetime.timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')

        self.fields['start_datetime'].widget.attrs['min'] = today
        self.fields['end_datetime'].widget.attrs['min'] = tomorrow


class PasswordChangeFormCustom(forms.Form):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Текущий пароль"
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Новый пароль"
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Подтвердите новый пароль"
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')

        if new_password1 and new_password2 and new_password1 != new_password2:
            raise forms.ValidationError("Пароли не совпадают")

        return cleaned_data

    def save(self, commit=True):
        self.user.set_password(self.cleaned_data['new_password1'])
        if commit:
            self.user.save()
        return self.user


class ReviewForm(forms.ModelForm):
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
                'rows': 4,
                'class': 'form-control',
                'placeholder': 'Оставьте ваш отзыв...'
            }),
        }


class SearchForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Property
        self.fields['property_type'].choices = [('', 'Все типы')] + list(Property.PROPERTY_TYPE_CHOICES)

    city = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Город'
        })
    )
    property_type = forms.ChoiceField(
        choices=[],  # Будет заполнено в __init__
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    category = forms.ModelChoiceField(
        queryset=PropertyCategory.objects.all(),
        required=False,
        empty_label="Все категории",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    min_price = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Мин. цена'
        })
    )
    max_price = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Макс. цена'
        })
    )


class PropertyImageForm(forms.ModelForm):
    class Meta:
        from .models import PropertyImage
        model = PropertyImage
        fields = ['image', 'is_main']
        widgets = {
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'is_main': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }