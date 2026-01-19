// Основной JavaScript файл для приложения

$(document).ready(function() {
    // Инициализация тултипов
    $('[data-bs-toggle="tooltip"]').tooltip();

    // Инициализация попапов
    $('[data-bs-toggle="popover"]').popover();

    // Автоматическое скрытие алертов через 5 секунд
    setTimeout(function() {
        $('.alert').alert('close');
    }, 5000);

    // Обновление цены при изменении дат бронирования
    $('#id_start_datetime, #id_end_datetime').on('change', function() {
        updateBookingPrice();
    });

    // Загрузка календаря через AJAX
    $('.calendar-month').on('click', function(e) {
        e.preventDefault();
        const propertyId = $(this).data('property-id');
        const month = $(this).data('month');

        $.ajax({
            url: `/api/calendar/${propertyId}/`,
            data: { month: month },
            success: function(data) {
                updateCalendar(data.calendar_data);
            }
        });
    });
});

function updateBookingPrice() {
    // Расчет стоимости бронирования
    const startDate = new Date($('#id_start_datetime').val());
    const endDate = new Date($('#id_end_datetime').val());

    if (startDate && endDate && startDate < endDate) {
        const durationHours = (endDate - startDate) / (1000 * 60 * 60);
        const pricePerHour = parseFloat($('#property-price').data('price-per-hour'));

        if (pricePerHour) {
            const totalPrice = durationHours * pricePerHour;
            $('#total-price').text(totalPrice.toFixed(2) + ' ₽');
            $('#duration').text(durationHours.toFixed(1) + ' часов');
        }
    }
}

function updateCalendar(calendarData) {
    // Обновление календаря с новыми данными
    const calendarContainer = $('.calendar-container');
    let calendarHtml = '';

    // Генерация HTML для календаря
    // ... реализация генерации календаря

    calendarContainer.html(calendarHtml);
}

// Функция для добавления в избранное
function toggleFavorite(propertyId) {
    $.ajax({
        url: `/properties/${propertyId}/toggle-favorite/`,
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken')
        },
        success: function(response) {
            const favoriteBtn = $(`.favorite-btn[data-property-id="${propertyId}"]`);
            if (response.is_favorite) {
                favoriteBtn.addClass('active').html('<i class="bi bi-heart-fill"></i>');
            } else {
                favoriteBtn.removeClass('active').html('<i class="bi bi-heart"></i>');
            }
        }
    });
}

// Функция для получения CSRF токена
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Инициализация карты
function initMap(latitude, longitude, propertyTitle) {
    const mapElement = document.getElementById('property-map');

    if (mapElement && latitude && longitude) {
        const map = L.map('property-map').setView([latitude, longitude], 15);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);

        L.marker([latitude, longitude])
            .addTo(map)
            .bindPopup(`<strong>${propertyTitle}</strong>`)
            .openPopup();
    }
}

// Валидация форм
function validateBookingForm() {
    const startDate = new Date($('#id_start_datetime').val());
    const endDate = new Date($('#id_end_datetime').val());
    const now = new Date();

    if (startDate < now) {
        alert('Нельзя выбрать прошедшую дату');
        return false;
    }

    if (startDate >= endDate) {
        alert('Дата окончания должна быть позже даты начала');
        return false;
    }

    return true;
}
