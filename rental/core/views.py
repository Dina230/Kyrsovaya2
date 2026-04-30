from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.http import JsonResponse, HttpResponse, FileResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg, Sum, F, DateTimeField
from django.db.models.functions import TruncMonth, Coalesce
from django.urls import reverse, reverse_lazy
from django.conf import settings
import json
from datetime import datetime, timedelta, time as dt_time
import calendar
import csv
import io
import os
import re
import logging
from itertools import groupby
from xml.sax.saxutils import escape

# Импорты моделей
from .models import (
    User, Property, Booking, Review, Favorite,
    Category, Amenity, Notification, Message, Cart, Contract, AdminAuditLog, UserAuditLog
)
# Импорты форм
from .forms import (
    CustomUserCreationForm, CustomUserChangeForm,
    PasswordChangeCustomForm,
    PropertyForm, BookingForm, ReviewForm,
    ContactForm, CartBookingForm, CheckoutForm,
    AdminUserEditForm, AdminPropertyEditForm,
    AdminBookingEditForm, AdminReviewEditForm,
    SearchForm, PaymentCardForm
)

# Настройка логирования
logger = logging.getLogger(__name__)


def add_calendar_months(d, months):
    """Сдвиг даты на N месяцев (для календаря)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return datetime(y, m, day).date()


def booking_overlaps_calendar_day(booking, day):
    """Пересекается ли бронирование с календарным днём (локальная дата)."""
    day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    day_end = day_start + timedelta(days=1)
    return booking.end_datetime > day_start and booking.start_datetime < day_end


def build_property_occupancy(property_obj, start_date, num_days, bookings_qs=None):
    """
    Занятость по дням и по часам для интервала [start_date, start_date + num_days).
    bookings_qs — необязательный список/QuerySet бронирований (уже отфильтрованный).
    """
    if bookings_qs is None:
        end_d = start_date + timedelta(days=num_days)
        range_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        range_end = timezone.make_aware(datetime.combine(end_d, datetime.min.time()))
        bookings_qs = property_obj.bookings.filter(
            status__in=['pending', 'paid', 'confirmed'],
            end_datetime__gt=range_start,
            start_datetime__lt=range_end,
        ).select_related('tenant')
    bookings_list = list(bookings_qs)
    today = timezone.now().date()
    occupancy_days = []
    hourly_by_date = {}
    for i in range(num_days):
        d = start_date + timedelta(days=i)
        overlapping = [b for b in bookings_list if booking_overlaps_calendar_day(b, d)]
        count = len(overlapping)
        level = min(3, count)
        occupancy_days.append({
            'date': d,
            'count': count,
            'level': level,
            'is_past': d < today,
            'is_today': d == today,
        })
        busy_hours = []
        for h in range(24):
            slot_start = timezone.make_aware(datetime.combine(d, dt_time(h, 0)))
            slot_end = slot_start + timedelta(hours=1)
            if any(b.end_datetime > slot_start and b.start_datetime < slot_end for b in overlapping):
                busy_hours.append(h)
        hourly_by_date[d.isoformat()] = busy_hours
    return occupancy_days, hourly_by_date, bookings_list


def occupancy_days_to_month_blocks(occupancy_days):
    """
    Группирует плоский список дней занятости в блоки по календарным месяцам
    с сеткой 7×N (дни недели Пн–Вс) для компактного отображения на карточке.
    """
    if not occupancy_days:
        return []
    month_names = [
        '', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
        'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
    ]
    blocks = []
    for (y, m), iterator in groupby(
        occupancy_days, key=lambda x: (x['date'].year, x['date'].month)
    ):
        days = list(iterator)
        first = days[0]['date']
        cells = [None] * first.weekday()
        cells.extend(days)
        while len(cells) % 7 != 0:
            cells.append(None)
        weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]
        blocks.append({
            'title': f'{month_names[m]} {y}',
            'weeks': weeks,
        })
    return blocks


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def get_time_ago(dt):
    """Возвращает красивое представление времени для AJAX-превью"""
    if not dt:
        return 'только что'

    now = timezone.now()
    diff = now - dt

    if diff < timedelta(minutes=1):
        return 'только что'
    elif diff < timedelta(hours=1):
        return f'{diff.seconds // 60} мин. назад'
    elif diff < timedelta(days=1):
        return f'{diff.seconds // 3600} ч. назад'
    elif diff < timedelta(days=7):
        return f'{diff.days} дн. назад'
    else:
        return dt.strftime('%d.%m.%Y')


def create_notification(user, notification_type, title, message,
                        related_object_id=None, related_object_type=None):
    """Создать уведомление для пользователя"""
    notification = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        related_object_id=related_object_id,
        related_object_type=related_object_type
    )
    return notification


def create_booking_notification(booking, notification_type):
    """Создать уведомление о бронировании"""
    if notification_type == 'booking_created':
        user = booking.property.landlord
    elif notification_type in ['booking_paid', 'booking_confirmed', 'booking_cancelled']:
        user = booking.tenant
    elif notification_type == 'booking_completed':
        user = booking.property.landlord
    else:
        return None

    title_map = {
        'booking_created': 'Новое бронирование',
        'booking_paid': 'Бронирование оплачено',
        'booking_confirmed': 'Бронирование подтверждено',
        'booking_cancelled': 'Бронирование отменено',
        'booking_completed': 'Бронирование завершено',
    }
    message_map = {
        'booking_created': f'Новый запрос на бронирование помещения "{booking.property.title}" на {booking.start_datetime.strftime("%d.%m.%Y %H:%M")}',
        'booking_paid': f'Бронирование #{booking.booking_id} оплачено. Ожидает подтверждения владельцем.',
        'booking_confirmed': f'Ваше бронирование #{booking.booking_id} подтверждено',
        'booking_cancelled': f'Бронирование #{booking.booking_id} отменено',
        'booking_completed': f'Бронирование #{booking.booking_id} завершено. Пожалуйста, оставьте отзыв.',
    }

    return create_notification(
        user=user,
        notification_type=notification_type,
        title=title_map.get(notification_type, 'Уведомление'),
        message=message_map.get(notification_type, ''),
        related_object_id=booking.id,
        related_object_type='booking'
    )


def create_message_notification(message):
    """Создать уведомление о новом сообщении"""
    return create_notification(
        user=message.recipient,
        notification_type='message_received',
        title='Новое сообщение',
        message=f'Вам новое сообщение от {message.sender.get_full_name_or_username()}',
        related_object_id=message.id,
        related_object_type='message'
    )


_CONTRACT_PDF_FONT_REGISTERED = None  # кэш: имя шрифта ReportLab для кириллицы


def _get_contract_pdf_font_name():
    """
    Подключает TTF с кириллицей для reportlab (один раз).
    Порядок: DejaVu в проекте → Arial (Windows) → системные DejaVu/Liberation (Linux).
    Если ничего не найдено — Helvetica (кириллица может отображаться некорректно).
    """
    global _CONTRACT_PDF_FONT_REGISTERED
    if _CONTRACT_PDF_FONT_REGISTERED is not None:
        return _CONTRACT_PDF_FONT_REGISTERED

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    base = settings.BASE_DIR
    candidates = [
        os.path.join(base, 'dejavu-sans-book.ttf'),
        os.path.join(base, 'fonts', 'DejaVuSans.ttf'),
    ]
    windir = os.environ.get('WINDIR', '') or os.environ.get('SystemRoot', '')
    if windir:
        candidates.extend([
            os.path.join(windir, 'Fonts', 'arial.ttf'),
            os.path.join(windir, 'Fonts', 'Arial.ttf'),
        ])
    candidates.extend([
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ])

    name = 'Helvetica'
    for font_path in candidates:
        if not font_path or not os.path.isfile(font_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont('ContractPdfSans', font_path))
            name = 'ContractPdfSans'
            logger.info('PDF договор: используется шрифт %s', font_path)
            break
        except Exception as err:
            logger.warning('Не удалось подключить шрифт %s: %s', font_path, err)

    if name == 'Helvetica':
        logger.warning(
            'Для корректной кириллицы в PDF положите DejaVuSans.ttf в папку fonts/ у проекта '
            'или используйте систему с Arial/DejaVu (см. документацию DejaVu).'
        )

    _CONTRACT_PDF_FONT_REGISTERED = name
    return name


def _contract_party_block(user, party_label):
    """Текст стороны для шапки договора (физ./юр. лицо упрощённо)."""
    name = user.get_full_name_or_username()
    company = (user.company_name or '').strip()
    doc_basis = 'Устава / свидетельства о регистрации' if company else 'паспорта гражданина РФ'
    rep = f'{name} (самостоятельно)' if not company else f'{name}, представитель организации'
    org_line = f'{company}, ' if company else ''
    return (
        f'{escape(org_line)}именуем__ в дальнейшем «{party_label}», в лице {escape(rep)}, '
        f'действующ___ на основании {escape(doc_basis)}'
    )


def generate_contract_pdf(booking):
    """
    PDF договора аренды нежилого помещения (структура по ГОСТ Р 7.0.97-2016, сокращённый текст).
    Данные подставляются из бронирования и профилей; реквизиты ИНН/КПП и кадастр — под заполнение вручную.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from django.core.files.base import ContentFile

        contract, _ = Contract.objects.get_or_create(booking=booking)
        contract.save()
        contract_number = contract.contract_number

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
        )

        font_name = _get_contract_pdf_font_name()

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name='NormalCyrillic',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=9,
            leading=11,
            alignment=0,
        ))
        styles.add(ParagraphStyle(
            name='Heading2Cyrillic',
            parent=styles['Heading2'],
            fontName=font_name,
            fontSize=11,
            leading=13,
            spaceBefore=10,
            spaceAfter=4,
            alignment=0,
        ))
        styles.add(ParagraphStyle(
            name='TitleCyrillic',
            parent=styles['Title'],
            fontName=font_name,
            fontSize=13,
            leading=15,
            spaceAfter=8,
            alignment=1,
        ))
        styles.add(ParagraphStyle(
            name='SmallCyrillic',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=8,
            leading=10,
            alignment=4,  # justify
        ))

        def P(text):
            return Paragraph(escape(str(text)), styles['NormalCyrillic'])

        prop = booking.property
        landlord = prop.landlord
        tenant = booking.tenant

        type_labels = dict(Property.PROPERTY_TYPE_CHOICES)
        purpose = type_labels.get(prop.property_type, prop.property_type)
        amenities_qs = prop.amenities.all()[:20]
        amenities_txt = ', '.join(a.name for a in amenities_qs) if amenities_qs.exists() else 'согласно описанию объекта на платформе «Простор»'
        floor_txt = str(prop.floor) if prop.floor is not None else '_______'
        payment_labels = dict(Booking._meta.get_field('payment_method').choices)
        pay_method = payment_labels.get(booking.payment_method, booking.payment_method)

        now_local = timezone.localtime(timezone.now())

        start_l = timezone.localtime(booking.start_datetime)
        end_l = timezone.localtime(booking.end_datetime)

        elements = []
        elements.append(Paragraph(
            escape(f'ДОГОВОР АРЕНДЫ НЕЖИЛОГО ПОМЕЩЕНИЯ № {contract_number}'),
            styles['TitleCyrillic'],
        ))
        elements.append(Spacer(1, 4))
        elements.append(P(f'г. {prop.city or "_______________"}'))
        elements.append(P(
            f'«{now_local.day:02d}» {_contract_month_name(now_local.month)} {now_local.year} г.'
        ))
        elements.append(Spacer(1, 8))

        intro = (
            f'{_contract_party_block(landlord, "Арендодатель")}, с одной стороны, и '
            f'<br/>{_contract_party_block(tenant, "Арендатор")}, с другой стороны, '
            f'совместно именуемые «Стороны», заключили настоящий Договор о нижеследующем:'
        )
        elements.append(Paragraph(intro, styles['NormalCyrillic']))
        elements.append(Spacer(1, 8))

        # --- 1. Предмет ---
        elements.append(Paragraph('<b>1. ПРЕДМЕТ ДОГОВОРА</b>', styles['Heading2Cyrillic']))
        elements.append(P(
            f'1.1. Арендодатель передает, а Арендатор принимает во временное владение и пользование '
            f'нежилое помещение (далее — «Помещение»), расположенное по адресу: {prop.address}, '
            f'{prop.city}, общей площадью {prop.area} кв. м, этаж {floor_txt}, '
            f'кадастровый номер ________________________ (при наличии).'
        ))
        elements.append(P(
            f'1.2. Помещение предоставляется для использования в целях: {purpose} '
            f'(коммерческая аренда через платформу «Простор»).'
        ))
        elements.append(P(
            f'1.3. Характеристики: назначение — {purpose}; состояние — пригодно для использования по назначению '
            f'(по данным карточки объекта); оснащение — {amenities_txt}.'
        ))
        elements.append(P(
            '1.4. Передача Помещения оформляется Актом приема-передачи (Приложение № 1), '
            'являющимся неотъемлемой частью настоящего Договора.'
        ))

        # --- 2. Срок ---
        elements.append(Paragraph('<b>2. СРОК ДЕЙСТВИЯ ДОГОВОРА</b>', styles['Heading2Cyrillic']))
        elements.append(P(
            '2.1. Договор заключен на срок фактического пользования Помещением в интервале, указанном в п. 2.3.'
        ))
        elements.append(P('2.2. Договор вступает в силу с даты подписания Сторонами (в т. ч. путём акцепта на платформе).'))
        elements.append(P(
            f'2.3. Срок аренды: начало — «{start_l.day:02d}» {_contract_month_name(start_l.month)} {start_l.year} г. '
            f'с {start_l.strftime("%H")} ч. {start_l.strftime("%M")} мин.; '
            f'окончание — «{end_l.day:02d}» {_contract_month_name(end_l.month)} {end_l.year} г. '
            f'до {end_l.strftime("%H")} ч. {end_l.strftime("%M")} мин.'
        ))
        elements.append(P('2.4. По окончании срока Арендатор обязан освободить Помещение в день окончания аренды.'))

        # --- 3. Плата ---
        elements.append(Paragraph('<b>3. АРЕНДНАЯ ПЛАТА И ПОРЯДОК РАСЧЁТОВ</b>', styles['Heading2Cyrillic']))
        ph = prop.price_per_hour
        pd_ = prop.price_per_day
        pw = prop.price_per_week
        pm = prop.price_per_month
        elements.append(P(
            f'3.1. Ориентировочные тарифы: за 1 час — {ph} руб.; '
            f'за 1 день — {pd_ if pd_ is not None else "—"}; '
            f'за 1 неделю — {pw if pw is not None else "—"}; '
            f'за 1 месяц — {pm if pm is not None else "—"} (при указании в карточке объекта).'
        ))
        elements.append(P(
            f'3.2. Общая стоимость аренды по настоящему Договору (бронирование № {booking.booking_id}): '
            f'{booking.total_price} руб. (сумма прописью: ________________________________).'
        ))
        elements.append(P(
            f'3.3. Расчёты: предоплата в размере 100% до начала использования Помещения (если иное не согласовано). '
            f'Способ оплаты: {pay_method}.'
        ))
        elements.append(P('3.4. Датой оплаты считается дата поступления денежных средств Арендодателю.'))
        elements.append(P(
            '3.5–3.6. Коммунальные услуги и дополнительные расходы определяются соглашением Сторон / '
            'условиями объекта; при отсутствии особых условий — по фактическому потреблению и тарифам поставщиков.'
        ))

        # --- 4. Права и обязанности (сжато) ---
        elements.append(Paragraph('<b>4. ПРАВА И ОБЯЗАННОСТИ СТОРОН</b>', styles['Heading2Cyrillic']))
        elements.append(P(
            '4.1. Арендодатель обязуется: передать Помещение в состоянии, пригодном для использования; '
            'обеспечить доступ; не чинить неправомерных препятствий; информировать о правах третьих лиц (при наличии).'
        ))
        elements.append(P(
            '4.2. Арендодатель вправе: проверять состояние Помещения с предварительным уведомлением; '
            'расторгнуть Договор при существенном нарушении условий Арендатором.'
        ))
        elements.append(P(
            '4.3. Арендатор обязуется: использовать Помещение по назначению; своевременно вносить плату; '
            'соблюдать правила пожарной безопасности и санитарные нормы; не производить перепланировку без согласия; '
            'возместить ущерб при порче; вернуть Помещение с учётом нормального износа.'
        ))
        elements.append(P(
            '4.4. Арендатор вправе: пользоваться Помещением в соответствии с Договором; '
            'субаренда — только с письменного согласия Арендодателя.'
        ))

        # --- 5–9 сокращённо ---
        elements.append(Paragraph('<b>5. ОТВЕТСТВЕННОСТЬ СТОРОН</b>', styles['Heading2Cyrillic']))
        elements.append(P(
            '5.1. За просрочку арендной платы может взиматься пеня в размере _____ % в день от просроченной суммы '
            '(конкретный размер определяется дополнительным соглашением).'
        ))
        elements.append(P('5.2–5.4. Иные случаи ответственности — в соответствии с законодательством РФ и настоящим Договором.'))

        elements.append(Paragraph('<b>6. ФОРС-МАЖОР</b>', styles['Heading2Cyrillic']))
        elements.append(P(
            '6.1–6.3. Стороны освобождаются от ответственности при обстоятельствах непреодолимой силы при условии '
            'уведомления другой Стороны в разумный срок; сроки исполнения сдвигаются соразмерно.'
        ))

        elements.append(Paragraph('<b>7. ИЗМЕНЕНИЕ И РАСТОРЖЕНИЕ</b>', styles['Heading2Cyrillic']))
        elements.append(P(
            '7.1. Изменения — по письменным дополнительным соглашениям. 7.2. Досрочное расторжение — по соглашению Сторон, '
            'а также по основаниям, предусмотренным ГК РФ и настоящим Договором (существенные нарушения, неисполнение оплаты и др.).'
        ))
        elements.append(P('7.3. Уведомление о расторжении направляется за _____ календарных дней (подлежит согласованию Сторонами).'))

        elements.append(Paragraph('<b>8. СПОРЫ</b>', styles['Heading2Cyrillic']))
        elements.append(P(
            '8.1–8.3. Споры разрешаются путём переговоров; при недостижении согласия — в суде по месту нахождения Помещения '
            'после соблюдения претензионного порядка (срок ответа на претензию _____ дней).'
        ))

        elements.append(Paragraph('<b>9. ЗАКЛЮЧИТЕЛЬНЫЕ ПОЛОЖЕНИЯ</b>', styles['Heading2Cyrillic']))
        elements.append(P(
            '9.1. Договор составлен в двух экземплярах. 9.2. Во всём, что не урегулировано, применяется законодательство РФ '
            '(гл. 34 ГК РФ «Аренда»). 9.3. Приложения являются неотъемлемой частью Договора.'
        ))

        # --- 10. Реквизиты (таблица) ---
        elements.append(Paragraph('<b>10. АДРЕСА, РЕКВИЗИТЫ И ПОДПИСИ СТОРОН</b>', styles['Heading2Cyrillic']))
        elements.append(Spacer(1, 4))

        def cell(txt):
            return Paragraph(escape(str(txt)), styles['NormalCyrillic'])

        req_data = [
            [cell('<b>Арендодатель</b>'), cell('<b>Арендатор</b>')],
            [cell(f'ФИО / наименование: {landlord.get_full_name_or_username()}'
                  + (f', {landlord.company_name}' if landlord.company_name else '')),
             cell(f'ФИО / наименование: {tenant.get_full_name_or_username()}'
                  + (f', {tenant.company_name}' if tenant.company_name else ''))],
            [cell(f'Тел.: {landlord.phone or "________________"}'),
             cell(f'Тел.: {tenant.phone or "________________"}')],
            [cell(f'Email: {landlord.email or "________________"}'),
             cell(f'Email: {tenant.email or "________________"}')],
            [cell('ИНН: ____________  КПП: ____________  ОГРН: ____________'),
             cell('ИНН: ____________  КПП: ____________  ОГРН: ____________')],
            [cell('Банк / БИК / р/с / к/с: ________________________________'),
             cell('Банк / БИК / р/с / к/с: ________________________________')],
        ]
        req_tbl = Table(req_data, colWidths=[87 * mm, 87 * mm])
        req_tbl.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOX', (0, 0), (-1, -1), 0.5, (0.75, 0.75, 0.75)),
            ('INNERGRID', (0, 0), (-1, -1), 0.25, (0.85, 0.85, 0.85)),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(req_tbl)
        elements.append(Spacer(1, 12))

        sig_data = [
            [cell('_________________ / _____________ /'), cell('_________________ / _____________ /')],
            [cell('М.П.'), cell('М.П.')],
        ]
        sig_tbl = Table(sig_data, colWidths=[87 * mm, 87 * mm])
        sig_tbl.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONT', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(sig_tbl)

        # --- Приложение 1 ---
        elements.append(PageBreak())
        elements.append(Paragraph(escape('Приложение № 1'), styles['Heading2Cyrillic']))
        elements.append(Paragraph(escape('АКТ ПРИЕМА-ПЕРЕДАЧИ ПОМЕЩЕНИЯ'), styles['TitleCyrillic']))
        elements.append(Spacer(1, 6))
        elements.append(P(f'г. {prop.city or "_______________"}'))
        elements.append(P(
            f'«{now_local.day:02d}» {_contract_month_name(now_local.month)} {now_local.year} г.'
        ))
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(
            f'{_contract_party_block(landlord, "Арендодатель")}, с одной стороны, и '
            f'<br/>{_contract_party_block(tenant, "Арендатор")}, с другой стороны, составили настоящий Акт о нижеследующем:',
            styles['NormalCyrillic'],
        ))
        elements.append(Spacer(1, 6))
        elements.append(P(
            f'1. Арендодатель передал, а Арендатор принял нежилое помещение по адресу: {prop.address}, {prop.city}.'
        ))
        elements.append(P('2. Техническое состояние на момент передачи: пригодно для использования по назначению (осмотр Сторон).'))
        elements.append(P(f'3. Оснащение (по данным объекта): {amenities_txt}.'))
        elements.append(P('4. Недостатки при осмотре: ________________________________________________.'))
        elements.append(P('5. Показания приборов учёта: электроэнергия _____; вода _____; тепло _____ (при наличии).'))
        elements.append(P('6. Претензий к состоянию Помещения Стороны не имеют / имеют (нужное подчеркнуть вручную).'))
        elements.append(Spacer(1, 16))
        app_sig = Table([
            [cell('Арендодатель: _________________ / _____________ /'),
             cell('Арендатор: _________________ / _____________ /')],
            [cell('М.П.'), cell('М.П.')],
        ], colWidths=[87 * mm, 87 * mm])
        app_sig.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(app_sig)

        elements.append(Spacer(1, 14))
        elements.append(Paragraph(
            escape(
                'Примечание: текст договора ориентирован на требования к оформлению организационно-распорядительной '
                'документации (ГОСТ Р 7.0.97-2016) и общие положения главы 34 ГК РФ «Аренда». '
                'Юридически значимые реквизиты и суммы прописью Стороны дополняют вручную.'
            ),
            styles['SmallCyrillic'],
        ))

        doc.build(elements)
        buffer.seek(0)

        if contract.pdf_file:
            contract.pdf_file.delete(save=False)

        safe_id = re.sub(r'[^\w\-]', '_', str(booking.booking_id))
        filename = f"contract_{safe_id}.pdf"
        contract.pdf_file.save(filename, ContentFile(buffer.getvalue()), save=True)

        return contract

    except ImportError as e:
        raise RuntimeError(
            'Для договора в формате PDF установите пакет: pip install reportlab'
        ) from e


def _contract_month_name(m):
    months = (
        '', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
    )
    return months[m] if 1 <= m <= 12 else str(m)


def auto_cancel_expired_bookings():
    """
    Автоматически отменяет бронирования, не оплаченные в течение 30 минут
    """
    expiration_time = timezone.now() - timedelta(minutes=30)
    expired_bookings = Booking.objects.filter(
        status='pending',
        created_at__lte=expiration_time
    )
    count = expired_bookings.count()
    for booking in expired_bookings:
        booking.status = 'cancelled'
        booking.save()
        # Создаем уведомление для арендатора
        create_notification(
            user=booking.tenant,
            notification_type='booking_cancelled',
            title='Бронирование отменено',
            message=f'Бронирование #{booking.booking_id} автоматически отменено из-за истечения времени оплаты.',
            related_object_id=booking.id,
            related_object_type='booking'
        )
        logger.info(f"Booking #{booking.booking_id} auto-cancelled (created at {booking.created_at})")

    if count > 0:
        logger.info(f"Auto-cancelled {count} expired bookings")
    return count


def _preserve_get_query(request, exclude_page=True, exclude_keys=None):
    q = request.GET.copy()
    if exclude_page:
        q.pop('page', None)
    if exclude_keys:
        for k in exclude_keys:
            q.pop(k, None)
    return q.urlencode()


def _filter_tenant_bookings_queryset(request, base_qs):
    """Фильтры страницы «Мои бронирования» (список и экспорт CSV)."""
    bookings = base_qs.order_by('-created_at')
    status_filter = request.GET.get('status')
    if status_filter:
        bookings = bookings.filter(status=status_filter)
    q = (request.GET.get('q') or '').strip()
    if q:
        bookings = _filter_icase_contains(
            bookings,
            ['booking_id', 'property__title', 'property__city'],
            q,
            prefix='mbq',
        )
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        bookings = bookings.filter(start_datetime__date__gte=date_from)
    if date_to:
        bookings = bookings.filter(start_datetime__date__lte=date_to)
    sort = request.GET.get('sort') or 'newest'
    if sort == 'oldest':
        bookings = bookings.order_by('start_datetime')
    elif sort == 'price_desc':
        bookings = bookings.order_by('-total_price')
    elif sort == 'price_asc':
        bookings = bookings.order_by('total_price')
    else:
        bookings = bookings.order_by('-created_at')
    return bookings


# Статусы бронирований, по которым учитываются расходы арендатора / доход арендодателя
def _paid_like_statuses():
    return ['paid', 'confirmed', 'completed']


def _is_platform_admin(user):
    """Доступ к кастомной админке: staff или тип пользователя «Администратор»."""
    return bool(getattr(user, 'is_staff', False) or getattr(user, 'user_type', None) == 'admin')


def _get_client_ip(request):
    """Получить IP клиента с учетом прокси."""
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_admin_action(request, action, target_model, target_obj=None, details=''):
    """Записать действие администратора в аудит-лог."""
    target_id = None
    target_repr = ''
    if target_obj is not None:
        target_id = getattr(target_obj, 'pk', None)
        target_repr = str(target_obj)

    AdminAuditLog.objects.create(
        admin_user=request.user if request.user.is_authenticated else None,
        action=action,
        target_model=target_model,
        target_id=target_id,
        target_repr=target_repr,
        details=details or '',
        ip_address=_get_client_ip(request),
    )


def log_user_event(request, event_type, user=None, details=''):
    """Записать событие пользователя в аудит-лог."""
    actor = user or (request.user if getattr(request, 'user', None) and request.user.is_authenticated else None)
    username_snapshot = getattr(actor, 'username', '')
    user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:255] if request is not None else ''
    UserAuditLog.objects.create(
        user=actor,
        username_snapshot=username_snapshot,
        event_type=event_type,
        details=details or '',
        ip_address=_get_client_ip(request) if request is not None else None,
        user_agent=user_agent,
    )


def _unicode_case_variants(s):
    """
    Набор вариантов регистра для поиска (кириллица и латиница).
    Нужен потому что в SQLite функция LOWER() в SQL не меняет регистр кириллицы,
    а LIKE с кириллицей остаётся чувствительным к регистру.
    """
    s = (s or '').strip()
    if not s:
        return []
    variants = {
        s,
        s.lower(),
        s.upper(),
        s.title(),
        s.capitalize(),
    }
    if len(s) > 1:
        variants.add(s[0].upper() + s[1:].lower())
        variants.add(s[0].lower() + s[1:].upper())
    return list({v for v in variants if v})


def _filter_icase_contains(queryset, field_paths, q, prefix='ic'):
    """
    Поиск подстроки без учёта регистра (в т.ч. кириллица на SQLite).
    Строит OR из __icontains по нескольким вариантам строки (title/lower/upper…).
    prefix оставлен для совместимости вызовов, не используется.
    """
    _ = prefix
    q = (q or '').strip()
    if not q or not field_paths:
        return queryset
    cond = Q()
    for v in _unicode_case_variants(q):
        for path in field_paths:
            cond |= Q(**{f'{path}__icontains': v})
    return queryset.filter(cond)


def _month_range(year, month):
    """Начало месяца и первый момент следующего месяца (для __lt)."""
    start = datetime(year, month, 1, tzinfo=timezone.get_current_timezone())
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.get_current_timezone())
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.get_current_timezone())
    return start, end


def _calendar_month_bounds(dt):
    """Границы календарного месяца для aware datetime dt."""
    return _month_range(dt.year, dt.month)


# ============================================================================
# ПУБЛИЧНЫЕ СТРАНИЦЫ
# ============================================================================

def home(request):
    """Главная страница"""
    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    properties = Property.objects.filter(
        status='active',
        is_featured=True
    ).select_related('landlord', 'category')[:5]

    recently_viewed = []
    raw_ids = request.session.get('recently_viewed_properties') or []
    if isinstance(raw_ids, list) and raw_ids:
        qs = Property.objects.filter(
            id__in=raw_ids[:12],
            status='active',
        ).select_related('landlord', 'category').prefetch_related('images')
        order_map = {pid: i for i, pid in enumerate(raw_ids)}
        recently_viewed = sorted(qs, key=lambda p: order_map.get(p.id, 999))[:8]

    context = {
        'properties': properties,
        'recently_viewed': recently_viewed,
        'title': 'Аренда коммерческих помещений'
    }
    return render(request, 'core/home.html', context)


def help_page(request):
    """Справка и ответы на частые вопросы."""
    return render(request, 'core/help.html', {'title': 'Справка'})


def terms_of_use(request):
    """Условия использования сервиса."""
    return render(request, 'core/terms_of_use.html', {'title': 'Условия использования'})


def privacy_policy(request):
    """Политика конфиденциальности сервиса."""
    return render(request, 'core/privacy_policy.html', {'title': 'Политика конфиденциальности'})


def property_list(request):
    """Список всех помещений с пагинацией (5 на странице)"""
    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    properties = Property.objects.filter(status='active').select_related('landlord', 'category')

    # Фильтрация по параметрам
    property_type = request.GET.get('property_type')
    city = request.GET.get('city')
    category = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    q = (request.GET.get('q') or '').strip()
    min_area = request.GET.get('min_area')
    max_area = request.GET.get('max_area')
    min_capacity = request.GET.get('min_capacity')
    sort = request.GET.get('sort') or 'newest'

    if q:
        properties = _filter_icase_contains(
            properties,
            ['title', 'description', 'address', 'city'],
            q,
            prefix='plq',
        )
    if property_type:
        properties = properties.filter(property_type=property_type)
    if city:
        properties = _filter_icase_contains(properties, ['city'], city, prefix='plc')
    if category:
        properties = properties.filter(category_id=category)
    if min_price:
        try:
            properties = properties.filter(price_per_hour__gte=float(min_price))
        except ValueError:
            pass
    if max_price:
        try:
            properties = properties.filter(price_per_hour__lte=float(max_price))
        except ValueError:
            pass
    if min_area:
        try:
            properties = properties.filter(area__gte=float(min_area))
        except ValueError:
            pass
    if max_area:
        try:
            properties = properties.filter(area__lte=float(max_area))
        except ValueError:
            pass
    if min_capacity:
        try:
            properties = properties.filter(capacity__gte=int(min_capacity))
        except ValueError:
            pass

    sort_map = {
        'price_asc': 'price_per_hour',
        'price_desc': '-price_per_hour',
        'area_asc': 'area',
        'area_desc': '-area',
        'newest': '-created_at',
        'popular': '-views_count',
    }
    properties = properties.order_by(sort_map.get(sort, sort_map['newest']))

    # Фильтр "Только доступные"
    show_available_only = request.GET.get('available_only') == 'on'
    selected_date = request.GET.get('date')
    selected_time = request.GET.get('time')

    if show_available_only:
        # Если дата не указана, используем сегодня
        if not selected_date:
            selected_date = timezone.now().date().isoformat()
        # Если время не указано, используем текущее + 1 час
        if not selected_time:
            now = timezone.now()
            start_dt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            selected_time = start_dt.strftime('%H:%M')

        try:
            start_datetime = timezone.make_aware(datetime.strptime(
                f"{selected_date} {selected_time}", "%Y-%m-%d %H:%M"
            ))
            end_datetime = start_datetime + timedelta(hours=1)

            booked_property_ids = Booking.objects.filter(
                status__in=['pending', 'paid', 'confirmed'],
                start_datetime__lt=end_datetime,
                end_datetime__gt=start_datetime
            ).values_list('property_id', flat=True)
            properties = properties.exclude(id__in=booked_property_ids)
        except ValueError:
            pass

    # Пагинация - 5 элементов на странице
    paginator = Paginator(properties, 6)
    page = request.GET.get('page')
    properties_page = paginator.get_page(page)

    context = {
        'properties': properties_page,
        'property_types': dict(Property.PROPERTY_TYPE_CHOICES),
        'categories': Category.objects.all(),
        'title': 'Все помещения для аренды',
        'today': timezone.now().date().isoformat(),
        'current_sort': sort,
    }
    return render(request, 'core/property_list.html', context)


def property_detail(request, slug):
    """Детальная страница помещения"""
    property_obj = get_object_or_404(
        Property.objects.select_related('landlord', 'category')
        .prefetch_related('amenities', 'images'),
        slug=slug,
        status='active'
    )

    Property.objects.filter(pk=property_obj.pk).update(views_count=F('views_count') + 1)
    property_obj.refresh_from_db()

    # Недавно просмотренные (сессия)
    rid = property_obj.id
    visited = request.session.get('recently_viewed_properties', [])
    if not isinstance(visited, list):
        visited = []
    if rid in visited:
        visited.remove(rid)
    visited.insert(0, rid)
    request.session['recently_viewed_properties'] = visited[:15]

    # Получаем только одобренные отзывы с пагинацией (5 на странице)
    reviews = Review.objects.filter(
        property=property_obj,
        status='approved'
    ).select_related('user').order_by('-created_at')

    # Пагинация для отзывов - 5 на странице
    reviews_paginator = Paginator(reviews, 5)
    reviews_page = request.GET.get('reviews_page')
    reviews_page_obj = reviews_paginator.get_page(reviews_page)

    # Проверяем, добавлено ли помещение в избранное
    is_favorite = False
    if request.user.is_authenticated:
        is_favorite = Favorite.objects.filter(
            user=request.user,
            property=property_obj
        ).exists()

    # Проверяем, есть ли в корзине
    in_cart = False
    if request.user.is_authenticated:
        in_cart = Cart.objects.filter(
            user=request.user,
            property=property_obj
        ).exists()

    today = timezone.now().date()
    occupancy_days, hourly_by_date, _ = build_property_occupancy(property_obj, today, 90)
    occupancy_month_blocks = occupancy_days_to_month_blocks(occupancy_days)

    # Похожие помещения (максимум 5)
    similar_properties = Property.objects.filter(
        status='active',
        property_type=property_obj.property_type,
        city=property_obj.city
    ).exclude(id=property_obj.id).select_related('landlord')[:5]

    context = {
        'property': property_obj,
        'reviews': reviews_page_obj,
        'is_favorite': is_favorite,
        'in_cart': in_cart,
        'occupancy_days': occupancy_days,
        'occupancy_month_blocks': occupancy_month_blocks,
        'hourly_occupancy_json': json.dumps(hourly_by_date),
        'similar_properties': similar_properties,
        'today': today.strftime('%Y-%m-%d'),
        'title': property_obj.title
    }
    return render(request, 'core/property_detail.html', context)


def register(request):
    """Регистрация нового пользователя"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_user_event(
                request,
                event_type='register',
                user=user,
                details='Создан новый аккаунт'
            )
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, 'Регистрация успешно завершена!')
                return redirect('dashboard')
            else:
                messages.error(request, 'Ошибка аутентификации.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = CustomUserCreationForm()

    return render(request, 'core/register.html', {'form': form, 'title': 'Регистрация'})


# ============================================================================
# ЛИЧНЫЙ КАБИНЕТ
# ============================================================================

@login_required
def dashboard(request):
    """Личный кабинет"""
    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    context = {'title': 'Личный кабинет'}
    user = request.user

    if user.user_type == 'tenant':
        # Для арендатора
        bookings = user.bookings_as_tenant.select_related('property').order_by('-created_at')
        active_bookings = bookings.filter(status__in=['pending', 'paid', 'confirmed'])
        paid_like = _paid_like_statuses()
        expense_qs = bookings.filter(status__in=paid_like)
        ref_expr = Coalesce('payment_date', 'created_at', output_field=DateTimeField())

        total_spent = expense_qs.aggregate(t=Sum('total_price'))['t'] or 0

        now = timezone.localtime()
        cur_start, cur_end = _calendar_month_bounds(now)
        prev_anchor = cur_start - timedelta(days=1)
        prev_start, prev_end = _calendar_month_bounds(prev_anchor)

        spent_this_month = (
            expense_qs.annotate(ref_date=ref_expr)
            .filter(ref_date__gte=cur_start, ref_date__lt=cur_end)
            .aggregate(t=Sum('total_price'))['t'] or 0
        )
        spent_prev_month = (
            expense_qs.annotate(ref_date=ref_expr)
            .filter(ref_date__gte=prev_start, ref_date__lt=prev_end)
            .aggregate(t=Sum('total_price'))['t'] or 0
        )
        spending_trend = 0
        if spent_prev_month and spent_prev_month > 0:
            spending_trend = round(
                float((spent_this_month - spent_prev_month) / spent_prev_month * 100), 1
            )

        by_status_spent = {
            row['status']: row['total']
            for row in expense_qs.values('status').annotate(total=Sum('total_price'))
        }

        # Статистика
        stats = {
            'total_bookings': bookings.count(),
            'active_bookings': active_bookings.count(),
            'completed_bookings': bookings.filter(status='completed').count(),
            'total_spent': total_spent,
            'spent_this_month': spent_this_month,
            'spent_prev_month': spent_prev_month,
            'spending_trend': spending_trend,
            'by_status_spent': by_status_spent,
            'favorite_count': user.favorites.count(),
            'cart_count': Cart.objects.filter(user=user).count(),
        }

        # Избранные помещения (максимум 5)
        favorite_properties = list(user.favorites.select_related('property').all()[:5])
        # Активные бронирования (максимум 5)
        safe_active_bookings = list(active_bookings[:5])

        context.update({
            'stats': stats,
            'active_bookings': safe_active_bookings,
            'favorite_properties': favorite_properties,
            'has_favorites': len(favorite_properties) > 0,
            'has_active_bookings': len(safe_active_bookings) > 0,
            'dashboard_role': 'tenant',
        })

    elif user.user_type == 'landlord':
        # Для арендодателя
        properties = list(user.properties.select_related('category').all())
        bookings = Booking.objects.filter(
            property__landlord=user
        ).select_related('property', 'tenant')

        # Статистика
        monthly_revenue = bookings.filter(
            status__in=['paid', 'confirmed', 'completed'],
            updated_at__gte=timezone.now() - timedelta(days=30)
        ).aggregate(total=Sum('total_price'))['total'] or 0

        stats = {
            'total_properties': len(properties),
            'active_properties': len([p for p in properties if p.status == 'active']),
            'pending_properties': len([p for p in properties if p.status == 'pending']),
            'total_bookings': bookings.count(),
            'pending_bookings': bookings.filter(status='pending').count(),
            'paid_bookings': bookings.filter(status='paid').count(),
            'monthly_revenue': monthly_revenue,
            'avg_rating': Review.objects.filter(
                property__landlord=user,
                status='approved'
            ).aggregate(avg=Avg('rating'))['avg'] or 0,
            'reviews_count': Review.objects.filter(
                property__landlord=user,
                status='approved'
            ).count(),
        }

        # Мои помещения (максимум 5)
        safe_properties = properties[:5]
        # Новые бронирования (максимум 5)
        new_bookings = list(bookings.filter(status='pending').order_by('-created_at')[:5])
        # Активные бронирования (максимум 5)
        active_bookings = list(bookings.filter(
            status__in=['paid', 'confirmed'],
            start_datetime__gte=timezone.now()
        ).order_by('start_datetime')[:5])

        ref_l = Coalesce('payment_date', 'updated_at', 'created_at', output_field=DateTimeField())
        rev_now = timezone.localtime()
        rs, re = _calendar_month_bounds(rev_now)
        revenue_this_month = (
            bookings.filter(status__in=_paid_like_statuses())
            .annotate(ref_date=ref_l)
            .filter(ref_date__gte=rs, ref_date__lt=re)
            .aggregate(t=Sum('total_price'))['t'] or 0
        )
        stats['revenue_this_month'] = revenue_this_month

        # Данные для диаграмм арендодателя
        revenue_qs = bookings.filter(status__in=_paid_like_statuses()).annotate(ref_date=ref_l)
        month_labels = []
        month_revenue_values = []
        month_bookings_values = []
        chart_anchor = timezone.localtime()
        for i in range(5, -1, -1):
            d = chart_anchor - timedelta(days=30 * i)
            month_start, month_end = _calendar_month_bounds(d)
            month_labels.append(month_start.strftime('%m.%Y'))
            month_slice = revenue_qs.filter(ref_date__gte=month_start, ref_date__lt=month_end)
            month_revenue_values.append(float(month_slice.aggregate(t=Sum('total_price'))['t'] or 0))
            month_bookings_values.append(month_slice.count())

        booking_status_order = ['pending', 'paid', 'confirmed', 'completed', 'cancelled']
        booking_status_labels_map = {
            'pending': 'Ожидают',
            'paid': 'Оплачены',
            'confirmed': 'Подтверждены',
            'completed': 'Завершены',
            'cancelled': 'Отменены',
        }
        booking_status_counts = {
            item['status']: item['count']
            for item in bookings.values('status').annotate(count=Count('id'))
        }
        status_labels = [booking_status_labels_map[s] for s in booking_status_order]
        status_values = [booking_status_counts.get(s, 0) for s in booking_status_order]

        context.update({
            'stats': stats,
            'properties': safe_properties,
            'new_bookings': new_bookings,
            'active_bookings': active_bookings,
            'landlord_chart_month_labels': json.dumps(month_labels),
            'landlord_chart_month_revenue': json.dumps(month_revenue_values),
            'landlord_chart_month_bookings': json.dumps(month_bookings_values),
            'landlord_chart_status_labels': json.dumps(status_labels),
            'landlord_chart_status_values': json.dumps(status_values),
            'has_new_bookings': len(new_bookings) > 0,
            'has_active_bookings': len(active_bookings) > 0,
            'dashboard_role': 'landlord',
        })

    elif user.user_type == 'admin' or user.is_staff:
        # Для администратора
        paid_like_admin = _paid_like_statuses()
        ref_admin = Coalesce('payment_date', 'updated_at', 'created_at', output_field=DateTimeField())
        rev_all = Booking.objects.filter(status__in=paid_like_admin)
        total_platform_revenue = rev_all.aggregate(t=Sum('total_price'))['t'] or 0

        now_ad = timezone.localtime()
        cur_s, cur_e = _calendar_month_bounds(now_ad)
        prev_anchor_ad = cur_s - timedelta(days=1)
        prev_s, prev_e = _calendar_month_bounds(prev_anchor_ad)

        revenue_this_month = (
            rev_all.annotate(ref_date=ref_admin)
            .filter(ref_date__gte=cur_s, ref_date__lt=cur_e)
            .aggregate(t=Sum('total_price'))['t'] or 0
        )
        revenue_prev_month = (
            rev_all.annotate(ref_date=ref_admin)
            .filter(ref_date__gte=prev_s, ref_date__lt=prev_e)
            .aggregate(t=Sum('total_price'))['t'] or 0
        )
        platform_revenue_trend = 0
        if revenue_prev_month and revenue_prev_month > 0:
            platform_revenue_trend = round(
                float((revenue_this_month - revenue_prev_month) / revenue_prev_month * 100), 1
            )

        stats = {
            'total_users': User.objects.count(),
            'new_users_today': User.objects.filter(date_joined__date=timezone.now().date()).count(),
            'total_properties': Property.objects.count(),
            'active_properties': Property.objects.filter(status='active').count(),
            'pending_properties': Property.objects.filter(status='pending').count(),
            'total_bookings': Booking.objects.count(),
            'pending_bookings': Booking.objects.filter(status='pending').count(),
            'paid_bookings': Booking.objects.filter(status='paid').count(),
            'today_bookings': Booking.objects.filter(start_datetime__date=timezone.now().date()).count(),
            'month_revenue': Booking.objects.filter(
                status__in=['paid', 'confirmed', 'completed'],
                updated_at__gte=timezone.now() - timedelta(days=30)
            ).aggregate(total=Sum('total_price'))['total'] or 0,
            'total_platform_revenue': total_platform_revenue,
            'revenue_this_month': revenue_this_month,
            'revenue_prev_month': revenue_prev_month,
            'platform_revenue_trend': platform_revenue_trend,
        }

        # Последние записи (максимум 5)
        recent_users = User.objects.order_by('-date_joined')[:5]
        recent_bookings = Booking.objects.select_related('property', 'tenant').order_by('-created_at')[:5]
        recent_reviews = Review.objects.select_related('property', 'user').order_by('-created_at')[:5]

        context.update({
            'stats': stats,
            'recent_users': recent_users,
            'recent_bookings': recent_bookings,
            'recent_reviews': recent_reviews,
            'is_admin_dashboard': True,
            'dashboard_role': 'admin',
        })

    return render(request, 'core/dashboard.html', context)


@login_required
def tenant_expenses(request):
    """Детализация расходов арендатора по месяцам и статусам."""
    if request.user.user_type != 'tenant':
        messages.info(request, 'Раздел доступен арендаторам.')
        return redirect('dashboard')

    auto_cancel_expired_bookings()
    bookings = request.user.bookings_as_tenant.select_related('property')
    paid_like = _paid_like_statuses()
    expense_qs = bookings.filter(status__in=paid_like)
    ref_expr = Coalesce('payment_date', 'created_at', output_field=DateTimeField())

    total = expense_qs.aggregate(t=Sum('total_price'))['t'] or 0

    monthly = list(
        expense_qs.annotate(ref_date=ref_expr)
        .annotate(month=TruncMonth('ref_date'))
        .values('month')
        .annotate(total=Sum('total_price'))
        .order_by('-month')[:24]
    )

    by_status = list(
        expense_qs.values('status').annotate(total=Sum('total_price'), cnt=Count('id')).order_by('-total')
    )

    recent_lines = list(
        expense_qs.select_related('property')
        .annotate(ref_date=Coalesce('payment_date', 'created_at', output_field=DateTimeField()))
        .order_by('-ref_date')[:50]
    )

    now = timezone.localtime()
    cur_start, cur_end = _calendar_month_bounds(now)
    prev_anchor = cur_start - timedelta(days=1)
    prev_start, prev_end = _calendar_month_bounds(prev_anchor)

    spent_this_month = (
        expense_qs.annotate(ref_date=ref_expr)
        .filter(ref_date__gte=cur_start, ref_date__lt=cur_end)
        .aggregate(t=Sum('total_price'))['t'] or 0
    )
    spent_prev_month = (
        expense_qs.annotate(ref_date=ref_expr)
        .filter(ref_date__gte=prev_start, ref_date__lt=prev_end)
        .aggregate(t=Sum('total_price'))['t'] or 0
    )

    return render(request, 'core/tenant_expenses.html', {
        'title': 'Мои расходы',
        'total_spent': total,
        'monthly_rows': monthly,
        'by_status': by_status,
        'recent_lines': recent_lines,
        'spent_this_month': spent_this_month,
        'spent_prev_month': spent_prev_month,
    })


@login_required
def landlord_revenue(request):
    """Доход арендодателя по месяцам (по оплаченным и завершённым бронированиям)."""
    if request.user.user_type != 'landlord':
        messages.info(request, 'Раздел доступен арендодателям.')
        return redirect('dashboard')

    auto_cancel_expired_bookings()
    bookings = Booking.objects.filter(property__landlord=request.user).select_related('property', 'tenant')
    paid_like = _paid_like_statuses()
    rev_qs = bookings.filter(status__in=paid_like)
    ref_expr = Coalesce('payment_date', 'updated_at', 'created_at', output_field=DateTimeField())

    total = rev_qs.aggregate(t=Sum('total_price'))['t'] or 0

    monthly = list(
        rev_qs.annotate(ref_date=ref_expr)
        .annotate(month=TruncMonth('ref_date'))
        .values('month')
        .annotate(total=Sum('total_price'))
        .order_by('-month')[:24]
    )

    by_status = list(
        rev_qs.values('status').annotate(total=Sum('total_price'), cnt=Count('id')).order_by('-total')
    )

    recent_lines = list(
        rev_qs.select_related('property', 'tenant')
        .annotate(ref_date=Coalesce('payment_date', 'updated_at', 'created_at', output_field=DateTimeField()))
        .order_by('-ref_date')[:50]
    )

    now = timezone.localtime()
    cur_start, cur_end = _calendar_month_bounds(now)
    revenue_this_month = (
        rev_qs.annotate(ref_date=ref_expr)
        .filter(ref_date__gte=cur_start, ref_date__lt=cur_end)
        .aggregate(t=Sum('total_price'))['t'] or 0
    )

    return render(request, 'core/landlord_revenue.html', {
        'title': 'Выручка',
        'total_revenue': total,
        'monthly_rows': monthly,
        'by_status': by_status,
        'recent_lines': recent_lines,
        'revenue_this_month': revenue_this_month,
    })


@login_required
def admin_platform_revenue(request):
    """Агрегированная выручка платформы по всем бронированиям (оплачено / подтверждено / завершено)."""
    if not (request.user.user_type == 'admin' or request.user.is_staff):
        messages.info(request, 'Раздел доступен администраторам.')
        return redirect('dashboard')

    auto_cancel_expired_bookings()
    paid_like = _paid_like_statuses()
    rev_qs = Booking.objects.filter(status__in=paid_like).select_related('property', 'tenant')
    ref_expr = Coalesce('payment_date', 'updated_at', 'created_at', output_field=DateTimeField())

    total = rev_qs.aggregate(t=Sum('total_price'))['t'] or 0

    monthly = list(
        rev_qs.annotate(ref_date=ref_expr)
        .annotate(month=TruncMonth('ref_date'))
        .values('month')
        .annotate(total=Sum('total_price'))
        .order_by('-month')[:24]
    )

    by_status = list(
        rev_qs.values('status').annotate(total=Sum('total_price'), cnt=Count('id')).order_by('-total')
    )

    recent_lines = list(
        rev_qs.select_related('property', 'tenant')
        .annotate(ref_date=Coalesce('payment_date', 'updated_at', 'created_at', output_field=DateTimeField()))
        .order_by('-ref_date')[:50]
    )

    now = timezone.localtime()
    cur_start, cur_end = _calendar_month_bounds(now)
    revenue_this_month = (
        rev_qs.annotate(ref_date=ref_expr)
        .filter(ref_date__gte=cur_start, ref_date__lt=cur_end)
        .aggregate(t=Sum('total_price'))['t'] or 0
    )

    return render(request, 'core/admin_platform_revenue.html', {
        'title': 'Оборот платформы',
        'total_revenue': total,
        'monthly_rows': monthly,
        'by_status': by_status,
        'recent_lines': recent_lines,
        'revenue_this_month': revenue_this_month,
    })


@login_required
def edit_profile(request):
    """Редактирование профиля"""
    if request.method == 'POST':
        form = CustomUserChangeForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            log_user_event(
                request,
                event_type='profile_update',
                details='Пользователь обновил профиль'
            )
            messages.success(request, 'Профиль успешно обновлен.')
            return redirect('dashboard')
    else:
        form = CustomUserChangeForm(instance=request.user)

    return render(request, 'core/edit_profile.html', {
        'form': form,
        'title': 'Редактирование профиля'
    })


@login_required
def change_password(request):
    """Смена пароля"""
    if request.method == 'POST':
        form = PasswordChangeCustomForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            log_user_event(
                request,
                event_type='password_change',
                user=user,
                details='Пользователь сменил пароль'
            )
            messages.success(request, 'Пароль успешно изменен.')
            return redirect('dashboard')
    else:
        form = PasswordChangeCustomForm(request.user)

    return render(request, 'core/change_password.html', {
        'form': form,
        'title': 'Смена пароля'
    })


@login_required
def my_bookings(request):
    """Мои бронирования с пагинацией (5 на странице)"""
    if request.user.user_type != 'tenant':
        messages.error(request, 'Эта страница доступна только арендаторам.')
        return redirect('dashboard')

    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    base_qs = request.user.bookings_as_tenant.select_related('property')
    status_stats = {
        'total': base_qs.count(),
        'pending': base_qs.filter(status='pending').count(),
        'paid': base_qs.filter(status='paid').count(),
        'confirmed': base_qs.filter(status='confirmed').count(),
        'completed': base_qs.filter(status='completed').count(),
        'cancelled': base_qs.filter(status='cancelled').count(),
    }

    status_filter = request.GET.get('status')
    sort = request.GET.get('sort') or 'newest'
    q = (request.GET.get('q') or '').strip()
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    bookings = _filter_tenant_bookings_queryset(request, base_qs)

    paginator = Paginator(bookings, 5)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    return render(request, 'core/my_bookings.html', {
        'bookings': bookings_page,
        'status_stats': status_stats,
        'current_status': status_filter,
        'current_sort': sort,
        'preserved_query': _preserve_get_query(request),
        'preserved_no_status': _preserve_get_query(request, exclude_keys=('status',)),
        'search_query': q,
        'date_from_val': date_from or '',
        'date_to_val': date_to or '',
        'title': 'Мои бронирования'
    })


@login_required
def export_my_bookings_csv(request):
    """Экспорт отфильтрованных бронирований арендатора в CSV (UTF-8 с BOM для Excel)."""
    if request.user.user_type != 'tenant':
        messages.error(request, 'Экспорт доступен только арендаторам.')
        return redirect('dashboard')
    auto_cancel_expired_bookings()
    base_qs = request.user.bookings_as_tenant.select_related('property')
    bookings = _filter_tenant_bookings_queryset(request, base_qs)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="moi_bronirovaniya.csv"'
    response.write('\ufeff')
    w = csv.writer(response, delimiter=';')
    w.writerow([
        'Номер бронирования', 'Помещение', 'Город', 'Начало', 'Окончание',
        'Сумма ₽', 'Статус', 'Создано',
    ])
    status_labels = dict(Booking.STATUS_CHOICES)
    for b in bookings:
        w.writerow([
            b.booking_id,
            b.property.title,
            b.property.city,
            timezone.localtime(b.start_datetime).strftime('%d.%m.%Y %H:%M'),
            timezone.localtime(b.end_datetime).strftime('%d.%m.%Y %H:%M'),
            str(b.total_price).replace('.', ','),
            status_labels.get(b.status, b.status),
            timezone.localtime(b.created_at).strftime('%d.%m.%Y %H:%M'),
        ])
    return response


@login_required
def my_favorites(request):
    """Избранные помещения с пагинацией (5 на странице)"""
    favorites = request.user.favorites.select_related('property').all().order_by('-created_at')

    # Пагинация - 5 элементов на странице
    paginator = Paginator(favorites, 5)
    page = request.GET.get('page')
    favorites_page = paginator.get_page(page)

    return render(request, 'core/my_favorites.html', {
        'favorites': favorites_page,
        'title': 'Избранное'
    })


@login_required
def my_properties(request):
    """Мои помещения (арендодатель): фильтры, поиск, сортировка, пагинация."""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Эта страница доступна только арендодателям.')
        return redirect('dashboard')

    base_qs = request.user.properties.select_related('category').all()

    stats = {
        'total_count': base_qs.count(),
        'active_count': base_qs.filter(status='active').count(),
        'pending_count': base_qs.filter(status='pending').count(),
        'featured_count': base_qs.filter(is_featured=True).count(),
        'booked_count': Booking.objects.filter(
            property__landlord=request.user,
            status__in=['paid', 'confirmed'],
        ).count(),
    }

    properties = base_qs
    status_filter = request.GET.get('status')
    if status_filter:
        properties = properties.filter(status=status_filter)

    q = (request.GET.get('q') or '').strip()
    if q:
        properties = _filter_icase_contains(
            properties,
            ['title', 'description', 'address', 'city'],
            q,
            prefix='mpq',
        )

    property_type = request.GET.get('property_type')
    if property_type:
        properties = properties.filter(property_type=property_type)

    city_filter = (request.GET.get('city') or '').strip()
    if city_filter:
        properties = _filter_icase_contains(properties, ['city'], city_filter, prefix='mpc')

    featured = request.GET.get('featured')
    if featured == '1':
        properties = properties.filter(is_featured=True)
    elif featured == '0':
        properties = properties.filter(is_featured=False)

    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        try:
            properties = properties.filter(price_per_hour__gte=float(min_price))
        except ValueError:
            pass
    if max_price:
        try:
            properties = properties.filter(price_per_hour__lte=float(max_price))
        except ValueError:
            pass

    sort = request.GET.get('sort') or 'newest'
    sort_map = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'price_asc': 'price_per_hour',
        'price_desc': '-price_per_hour',
        'title': 'title',
        'views': '-views_count',
    }
    properties = properties.order_by(sort_map.get(sort, sort_map['newest']))
    properties = properties.prefetch_related('images')

    paginator = Paginator(properties, 5)
    properties_page = paginator.get_page(request.GET.get('page'))

    owner_cities = sorted({c for c in base_qs.values_list('city', flat=True) if c})

    return render(request, 'core/my_properties.html', {
        'properties': properties_page,
        'stats': stats,
        'current_status': status_filter,
        'search_query': q,
        'current_type': property_type or '',
        'current_city': city_filter,
        'current_featured': featured or '',
        'min_price_val': min_price or '',
        'max_price_val': max_price or '',
        'current_sort': sort,
        'preserved_query': _preserve_get_query(request),
        'property_types': Property.PROPERTY_TYPE_CHOICES,
        'status_choices': Property.STATUS_CHOICES,
        'owner_cities': owner_cities,
        'title': 'Мои помещения',
    })


@login_required
def toggle_favorite(request, property_id):
    """Добавить/удалить помещение из избранного"""
    property_obj = get_object_or_404(Property, id=property_id)

    favorite, created = Favorite.objects.get_or_create(
        user=request.user,
        property=property_obj
    )

    if not created:
        favorite.delete()
        messages.success(request, 'Удалено из избранного')
    else:
        messages.success(request, 'Добавлено в избранное')

    return redirect('property_detail', slug=property_obj.slug)


@login_required
def create_booking(request, property_id):
    """Создание бронирования"""
    property_obj = get_object_or_404(Property, id=property_id, status='active')

    if request.user.user_type != 'tenant':
        messages.error(request, 'Только арендаторы могут создавать бронирования.')
        return redirect('property_detail', slug=property_obj.slug)

    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    initial = {}
    if request.method != 'POST':
        date_str = request.GET.get('date')
        if date_str:
            try:
                picked = datetime.strptime(date_str, '%Y-%m-%d').date()
                if picked >= timezone.now().date():
                    initial['start_date'] = picked
                    initial['end_date'] = picked
            except ValueError:
                pass

    if request.method == 'POST':
        form = BookingForm(request.POST, property_obj=property_obj)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.property = property_obj
            booking.tenant = request.user
            booking.status = 'pending'
            booking.save()

            create_booking_notification(booking, 'booking_created')
            messages.success(request, 'Бронирование создано. Перейдите к оплате в течение 30 минут.')
            return redirect('payment', booking_id=booking.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{error}')
    else:
        form = BookingForm(property_obj=property_obj, initial=initial)

    context = {
        'form': form,
        'property': property_obj,
        'title': 'Бронирование помещения'
    }
    return render(request, 'core/create_booking.html', context)


@login_required
def booking_detail(request, booking_id):
    """Детали бронирования"""
    # Проверяем просроченные бронирования
    auto_cancel_expired_bookings()

    booking = get_object_or_404(
        Booking.objects.select_related('property', 'property__landlord', 'tenant'),
        id=booking_id
    )

    if request.user != booking.tenant and request.user != booking.property.landlord:
        messages.error(request, 'У вас нет доступа к этому бронированию.')
        return redirect('dashboard')

    can_cancel = (
            request.user == booking.tenant and
            booking.status in ['pending', 'paid'] and
            booking.start_datetime > timezone.now()
    )

    can_review = (
            request.user == booking.tenant and
            booking.status == 'completed' and
            not Review.objects.filter(property=booking.property, user=request.user).exists()
    )

    can_pay = (
            request.user == booking.tenant and
            booking.status == 'pending'
    )

    can_download_contract = (
            booking.status in ['paid', 'confirmed', 'completed'] and
            (request.user == booking.tenant or request.user == booking.property.landlord)
    )

    has_contract = Contract.objects.filter(booking=booking).exists()

    days_count = (booking.end_datetime.date() - booking.start_datetime.date()).days + 1
    hours_count = (booking.end_datetime - booking.start_datetime).total_seconds() / 3600

    # Оставшееся время оплаты картой (как на странице payment — от created_at, не от загрузки страницы)
    time_left_minutes = 0
    time_left_seconds = 0
    time_left_total = 0
    if (
        booking.status == 'pending'
        and not booking.is_paid
        and booking.payment_method == 'card'
    ):
        elapsed = timezone.now() - booking.created_at
        remaining = timedelta(minutes=30) - elapsed
        time_left_total = max(0, int(remaining.total_seconds()))
        time_left_minutes = time_left_total // 60
        time_left_seconds = time_left_total % 60

    return render(request, 'core/booking_detail.html', {
        'booking': booking,
        'can_cancel': can_cancel,
        'can_review': can_review,
        'can_pay': can_pay,
        'can_download_contract': can_download_contract,
        'has_contract': has_contract,
        'days_count': days_count,
        'hours_count': hours_count,
        'time_left_minutes': time_left_minutes,
        'time_left_seconds': time_left_seconds,
        'time_left_total': time_left_total,
        'title': f'Бронирование #{booking.booking_id}'
    })


@login_required
def cancel_booking(request, booking_id):
    """Отмена бронирования"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'Вы не можете отменить это бронирование.')
        return redirect('dashboard')

    if booking.status not in ['pending', 'paid']:
        messages.error(request, 'Это бронирование нельзя отменить.')
        return redirect('booking_detail', booking_id=booking_id)

    if booking.start_datetime <= timezone.now():
        messages.error(request, 'Нельзя отменить начавшееся бронирование.')
        return redirect('booking_detail', booking_id=booking_id)

    was_paid = booking.is_paid or booking.status == 'paid'
    booking.status = 'cancelled'
    if was_paid:
        # Откат признаков оплаты при отмене, чтобы состояние брони было консистентным.
        booking.is_paid = False
        booking.payment_date = None
    booking.save()

    create_booking_notification(booking, 'booking_cancelled')
    messages.success(request, 'Бронирование успешно отменено.')
    return redirect('my_bookings')


@login_required
def add_review(request, booking_id):
    """Добавление отзыва"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'Вы не можете оставить отзыв на это бронирование.')
        return redirect('dashboard')

    if booking.status != 'completed':
        messages.error(request, 'Отзыв можно оставить только на завершенное бронирование.')
        return redirect('booking_detail', booking_id=booking_id)

    if Review.objects.filter(property=booking.property, user=request.user).exists():
        messages.error(request, 'Вы уже оставляли отзыв на это помещение.')
        return redirect('booking_detail', booking_id=booking_id)

    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.property = booking.property
            review.user = request.user
            review.booking = booking
            review.save()
            messages.success(request, 'Отзыв успешно добавлен и отправлен на модерацию.')
            return redirect('property_detail', slug=booking.property.slug)
    else:
        form = ReviewForm()

    return render(request, 'core/add_review.html', {
        'form': form,
        'booking': booking,
        'title': 'Добавление отзыва'
    })


# ============================================================================
# КОРЗИНА
# ============================================================================

@login_required
def cart_add(request, property_id):
    """Добавление помещения в корзину"""
    property_obj = get_object_or_404(Property, id=property_id, status='active')

    if request.user.user_type != 'tenant':
        messages.error(request, 'Только арендаторы могут добавлять в корзину.')
        return redirect('property_detail', slug=property_obj.slug)

    if request.method == 'POST':
        form = CartBookingForm(request.POST, property_obj=property_obj)
        if form.is_valid():
            start_datetime = form.cleaned_data['start_datetime']
            end_datetime = form.cleaned_data['end_datetime']
            guests = form.cleaned_data['guests']
            special_requests = form.cleaned_data.get('special_requests', '')

            # Проверяем, нет ли уже такого в корзине
            cart_item, created = Cart.objects.get_or_create(
                user=request.user,
                property=property_obj,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                defaults={
                    'guests': guests,
                    'special_requests': special_requests
                }
            )

            if created:
                messages.success(request, f'Помещение "{property_obj.title}" добавлено в корзину.')
            else:
                messages.info(request, f'Это помещение уже есть в корзине с такими же датами.')

            return redirect('cart_detail')
    else:
        form = CartBookingForm(property_obj=property_obj)

    context = {
        'form': form,
        'property': property_obj,
        'title': 'Добавление в корзину'
    }
    return render(request, 'core/cart_add.html', context)


@login_required
def cart_remove(request, item_id):
    """Удаление элемента из корзины"""
    cart_item = get_object_or_404(Cart, id=item_id, user=request.user)
    property_title = cart_item.property.title
    cart_item.delete()
    messages.success(request, f'Помещение "{property_title}" удалено из корзины.')
    return redirect('cart_detail')


@login_required
def cart_detail(request):
    """Просмотр корзины"""
    cart_items = Cart.objects.filter(user=request.user).select_related('property')
    total_amount = sum(item.get_total_price() for item in cart_items)

    context = {
        'cart_items': cart_items,
        'total_amount': total_amount,
        'title': 'Корзина'
    }
    return render(request, 'core/cart_detail.html', context)


@login_required
def checkout(request):
    """Оформление заказа (создание нескольких бронирований)"""
    if request.user.user_type != 'tenant':
        messages.error(request, 'Только арендаторы могут оформлять заказы.')
        return redirect('cart_detail')

    cart_items = Cart.objects.filter(user=request.user).select_related('property')

    if not cart_items.exists():
        messages.warning(request, 'Ваша корзина пуста.')
        return redirect('cart_detail')

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            # Создаем бронирования для каждого элемента корзины
            bookings_created = []
            for item in cart_items:
                booking = Booking.objects.create(
                    property=item.property,
                    tenant=request.user,
                    start_datetime=item.start_datetime,
                    end_datetime=item.end_datetime,
                    guests=item.guests,
                    special_requests=item.special_requests,
                    total_price=item.get_total_price(),
                    status='pending'
                )
                bookings_created.append(booking)
                create_booking_notification(booking, 'booking_created')

            # Очищаем корзину
            cart_items.delete()

            if len(bookings_created) == 1:
                messages.success(request,
                                 f'Бронирование #{bookings_created[0].booking_id} создано. Перейдите к оплате.')
                return redirect('payment', booking_id=bookings_created[0].id)
            else:
                messages.success(request, f'Создано {len(bookings_created)} бронирований. Перейдите к оплате.')
                return redirect('my_bookings')
    else:
        form = CheckoutForm()

    total_price = sum(item.get_total_price() for item in cart_items)

    context = {
        'form': form,
        'cart_items': cart_items,
        'total_price': total_price,
        'title': 'Оформление заказа'
    }
    return render(request, 'core/checkout.html', context)


# ============================================================================
# ОПЛАТА
# ============================================================================
@login_required
def payment(request, booking_id):
    """Страница оплаты бронирования"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'У вас нет доступа к этому бронированию.')
        return redirect('dashboard')

    if booking.status != 'pending':
        messages.warning(request, 'Это бронирование уже оплачено или обработано.')
        return redirect('booking_detail', booking_id=booking.id)

    # Проверка времени (30 минут) - только для оплаты картой
    time_elapsed = timezone.now() - booking.created_at
    time_left = timedelta(minutes=30) - time_elapsed

    if request.method == 'POST':
        form = PaymentCardForm(request.POST)

        if form.is_valid():
            payment_method = form.cleaned_data['payment_method']
            booking.payment_method = payment_method
            booking.save()

            if payment_method == 'card':
                contract, _ = Contract.objects.get_or_create(booking=booking)
                if not (contract.signed_by_tenant and contract.signed_by_landlord):
                    messages.error(
                        request,
                        'Перед оплатой договор должен быть подписан арендатором и арендодателем.'
                    )
                    return redirect('booking_detail', booking_id=booking.id)

                # Проверка времени только для карты
                if time_elapsed > timedelta(minutes=30):
                    booking.status = 'cancelled'
                    booking.save()
                    messages.error(request, 'Время для оплаты истекло. Бронирование автоматически отменено.')
                    return redirect('booking_detail', booking_id=booking.id)

                # Оплата картой
                booking.status = 'paid'
                booking.is_paid = True
                booking.payment_date = timezone.now()
                booking.save()

                create_booking_notification(booking, 'booking_paid')

                create_notification(
                    user=booking.property.landlord,
                    notification_type='booking_paid',
                    title='Бронирование оплачено',
                    message=f'Бронирование #{booking.booking_id} для помещения "{booking.property.title}" оплачено картой и ожидает подтверждения.',
                    related_object_id=booking.id,
                    related_object_type='booking'
                )

                try:
                    generate_contract_pdf(booking)
                except Exception as e:
                    logger.error(f"Error generating contract: {e}")

                messages.success(request,
                                 'Оплата прошла успешно! Договор будет доступен после подтверждения бронирования владельцем.')
                return redirect('payment_success', booking_id=booking.id)

            elif payment_method == 'cash':
                # Оплата наличными при встрече - таймер не проверяем
                # Просто создаем бронирование без оплаты

                # Уведомление владельцу
                create_notification(
                    user=booking.property.landlord,
                    notification_type='booking_created',
                    title='Новое бронирование (оплата наличными)',
                    message=f'Новое бронирование #{booking.booking_id} для помещения "{booking.property.title}". Клиент оплатит наличными при встрече.',
                    related_object_id=booking.id,
                    related_object_type='booking'
                )

                # Уведомление арендатору
                create_notification(
                    user=booking.tenant,
                    notification_type='booking_created',
                    title='Бронирование создано (оплата наличными)',
                    message=f'Ваше бронирование #{booking.booking_id} создано. Статус: ожидает оплаты при встрече. Свяжитесь с владельцем для подтверждения.',
                    related_object_id=booking.id,
                    related_object_type='booking'
                )

                messages.success(request,
                                 'Бронирование создано! Статус: ожидает оплаты при встрече. Свяжитесь с владельцем для подтверждения.')
                return redirect('booking_detail', booking_id=booking.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{error}')
    else:
        form = PaymentCardForm()

    # Для GET запроса показываем таймер только если не истекло время
    if time_elapsed > timedelta(minutes=30):
        booking.status = 'cancelled'
        booking.save()
        messages.error(request, 'Время для оплаты истекло. Бронирование автоматически отменено.')
        return redirect('booking_detail', booking_id=booking.id)

    time_left_seconds = max(0, int(time_left.total_seconds()))
    minutes_left = time_left_seconds // 60
    seconds_left = time_left_seconds % 60

    context = {
        'booking': booking,
        'form': form,
        'time_left_minutes': minutes_left,
        'time_left_seconds': seconds_left,
        'time_left_total': time_left_seconds,
        'title': f'Оплата бронирования #{booking.booking_id}'
    }
    return render(request, 'core/payment.html', context)


@login_required
def payment_success(request, booking_id):
    """Страница успешной оплаты"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.tenant:
        messages.error(request, 'У вас нет доступа к этому бронированию.')
        return redirect('dashboard')

    return render(request, 'core/payment_success.html', {
        'booking': booking,
        'title': 'Оплата прошла успешно'
    })


# ============================================================================
# ДОГОВОРЫ
# ============================================================================

@login_required
def download_contract(request, booking_id):
    """Скачивание договора только в формате PDF."""
    booking = get_object_or_404(
        Booking.objects.select_related('property', 'property__landlord', 'tenant'),
        id=booking_id
    )

    if not (request.user == booking.tenant or request.user == booking.property.landlord or request.user.is_staff):
        messages.error(request, 'У вас нет прав для скачивания этого договора.')
        return redirect('dashboard')

    if booking.status not in ['paid', 'confirmed', 'completed']:
        messages.error(request, 'Договор доступен только для оплаченных бронирований.')
        return redirect('booking_detail', booking_id=booking.id)

    contract, _ = Contract.objects.get_or_create(booking=booking)

    def _regenerate_pdf():
        if contract.pdf_file:
            contract.pdf_file.delete(save=False)
            contract.refresh_from_db()
        generate_contract_pdf(booking)
        contract.refresh_from_db()

    def _need_pdf():
        if not contract.pdf_file or not contract.pdf_file.name:
            return True
        if not contract.pdf_file.name.lower().endswith('.pdf'):
            return True
        try:
            return not contract.pdf_file.storage.exists(contract.pdf_file.name)
        except NotImplementedError:
            return False

    if _need_pdf():
        try:
            _regenerate_pdf()
        except RuntimeError as e:
            messages.error(request, str(e))
            return redirect('booking_detail', booking_id=booking.id)
        except Exception:
            logger.exception('Не удалось сгенерировать PDF договора')
            messages.error(
                request,
                'Не удалось сформировать PDF. Установите reportlab (pip install reportlab) и повторите попытку.'
            )
            return redirect('booking_detail', booking_id=booking.id)

    if not contract.pdf_file or not contract.pdf_file.name or not contract.pdf_file.name.lower().endswith('.pdf'):
        messages.error(request, 'Файл договора PDF не найден.')
        return redirect('booking_detail', booking_id=booking.id)

    safe_id = re.sub(r'[^\w\-]', '_', str(booking.booking_id))
    download_name = f'dogovor_{safe_id}.pdf'

    try:
        file_obj = contract.pdf_file.open('rb')
    except (FileNotFoundError, OSError):
        try:
            _regenerate_pdf()
            file_obj = contract.pdf_file.open('rb')
        except Exception:
            messages.error(request, 'Не удалось открыть или пересоздать PDF договора.')
            return redirect('booking_detail', booking_id=booking.id)

    return FileResponse(
        file_obj,
        as_attachment=True,
        filename=download_name,
        content_type='application/pdf',
    )


# ============================================================================
# УВЕДОМЛЕНИЯ (ИСПРАВЛЕНО ДЛЯ AJAX)
# ============================================================================

@login_required
def notifications_list(request):
    """Страница со списком уведомлений с пагинацией (5 на странице)"""
    notifications = request.user.notifications.all().order_by('-created_at')

    # === AJAX ОБРАБОТКА ДЛЯ ПРЕВЬЮ В DROPDOWN ===
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        limit = int(request.GET.get('limit', 5))
        notifications_qs = notifications[:limit]

        notifications_data = []
        for notif in notifications_qs:
            # Определяем URL для перехода
            url = '#'
            if notif.related_object_type == 'booking' and notif.related_object_id:
                url = reverse_lazy('booking_detail', args=[notif.related_object_id])
            elif notif.related_object_type == 'message' and notif.related_object_id:
                url = reverse_lazy('messages_list')
            elif notif.notification_type == 'system':
                url = reverse_lazy('dashboard')

            notifications_data.append({
                'id': notif.id,
                'title': notif.title or 'Уведомление',
                'message': notif.message or '',
                'is_read': notif.is_read,
                'url': url,
                'time_ago': get_time_ago(notif.created_at),
                'notification_type': notif.notification_type,
            })

        return JsonResponse({
            'notifications': notifications_data,
            'unread_count': notifications.filter(is_read=False).count()
        })
    # === КОНЕЦ AJAX ОБРАБОТКИ ===

    # Пагинация - 5 элементов на странице (для HTML-страницы)
    paginator = Paginator(notifications, 5)
    page = request.GET.get('page')
    notifications_page = paginator.get_page(page)

    if request.GET.get('mark_read'):
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return redirect('notifications_list')

    return render(request, 'core/notifications_list.html', {
        'notifications': notifications_page,
        'title': 'Мои уведомления'
    })


@login_required
def mark_notification_read(request, notification_id):
    """Пометить уведомление как прочитанное"""
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user
    )
    notification.is_read = True
    notification.save()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


@login_required
def mark_all_notifications_read(request):
    """Пометить все уведомления как прочитанные"""
    request.user.notifications.filter(is_read=False).update(is_read=True)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    return redirect('notifications_list')


@login_required
def delete_notification(request, notification_id):
    """Удалить уведомление"""
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user
    )
    notification.delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    return redirect('notifications_list')


@login_required
def delete_all_notifications(request):
    """Удалить все уведомления"""
    if request.method == 'POST':
        request.user.notifications.all().delete()
        messages.success(request, 'Все уведомления удалены.')
        return redirect('notifications_list')


@login_required
def get_unread_count(request):
    """Получить количество непрочитанных уведомлений (AJAX)"""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        count = request.user.notifications.filter(is_read=False).count()
        return JsonResponse({'count': count})
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def get_unread_messages_count(request):
    """Получить количество непрочитанных сообщений (AJAX)"""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        count = Message.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        return JsonResponse({'count': count})
    return JsonResponse({'error': 'Invalid request'}, status=400)


# ============================================================================
# СООБЩЕНИЯ (ИСПРАВЛЕНО ДЛЯ AJAX)
# ============================================================================

@login_required
def messages_list(request):
    """Страница со списком сообщений/диалогов с пагинацией (5 на странице)"""

    # === AJAX ОБРАБОТКА ДЛЯ ПРЕВЬЮ В DROPDOWN ===
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax'):
        limit = int(request.GET.get('limit', 5))

        # Получаем последние сообщения пользователя
        messages_qs = Message.objects.filter(
            Q(sender=request.user) | Q(recipient=request.user)
        ).select_related('sender', 'recipient', 'property').order_by('-created_at')[:limit]

        messages_data = []
        for msg in messages_qs:
            # Определяем отправителя для отображения
            sender = msg.sender if msg.sender != request.user else msg.recipient

            # Определяем URL для перехода
            url = reverse_lazy('messages_list')
            if msg.property:
                url = reverse_lazy('property_detail', args=[msg.property.slug])

            # Обрезаем текст сообщения для превью
            preview_text = msg.message[:100] + '...' if len(msg.message) > 100 else msg.message

            messages_data.append({
                'id': msg.id,
                'sender': sender.get_full_name_or_username() if sender else 'Пользователь',
                'message': preview_text,
                'is_read': msg.is_read if msg.recipient == request.user else True,
                'url': url,
                'time_ago': get_time_ago(msg.created_at),
                'subject': msg.subject or '',
            })

        unread_count = Message.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()

        return JsonResponse({
            'messages': messages_data,
            'unread_count': unread_count
        })
    # === КОНЕЦ AJAX ОБРАБОТКИ ===

    # Обычная логика для HTML-страницы
    sent_messages = Message.objects.filter(sender=request.user).values('recipient').distinct()
    received_messages = Message.objects.filter(recipient=request.user).values('sender').distinct()

    user_ids = set()
    for msg in sent_messages:
        user_ids.add(msg['recipient'])
    for msg in received_messages:
        user_ids.add(msg['sender'])

    conversations = []
    for user_id in user_ids:
        other_user = User.objects.get(id=user_id)
        last_message = Message.objects.filter(
            Q(sender=request.user, recipient=other_user) |
            Q(sender=other_user, recipient=request.user)
        ).order_by('-created_at').first()

        unread_count = Message.objects.filter(
            sender=other_user,
            recipient=request.user,
            is_read=False
        ).count()

        conversations.append({
            'user': other_user,
            'last_message': last_message,
            'unread_count': unread_count,
        })

    conversations.sort(
        key=lambda x: x['last_message'].created_at if x['last_message'] else timezone.make_aware(datetime.min),
        reverse=True
    )

    # Пагинация для диалогов - 5 на странице
    paginator = Paginator(conversations, 5)
    page = request.GET.get('page')
    conversations_page = paginator.get_page(page)

    context = {
        'conversations': conversations_page,
        'title': 'Мои сообщения'
    }
    return render(request, 'core/messages_list.html', context)


@login_required
def send_message(request, user_id=None, property_id=None):
    """Отправка сообщения пользователю или владельцу помещения"""
    recipient = None
    property_obj = None

    if property_id:
        property_obj = get_object_or_404(Property, id=property_id)
        recipient = property_obj.landlord
        if request.user == recipient:
            messages.error(request, 'Вы не можете отправить сообщение самому себе.')
            return redirect('property_detail', slug=property_obj.slug)
    elif user_id:
        recipient = get_object_or_404(User, id=user_id)
        if request.user == recipient:
            messages.error(request, 'Вы не можете отправить сообщение самому себе.')
            return redirect('messages_list')
    else:
        messages.error(request, 'Не указан получатель.')
        return redirect('home')

    if request.method == 'POST':
        subject = request.POST.get('subject', '')
        message_text = request.POST.get('message', '')

        if not message_text:
            messages.error(request, 'Сообщение не может быть пустым.')
        else:
            if not subject and property_obj:
                subject = f'Вопрос по помещению: {property_obj.title}'

            message = Message.objects.create(
                sender=request.user,
                recipient=recipient,
                property=property_obj,
                subject=subject,
                message=message_text
            )
            create_message_notification(message)
            messages.success(request, 'Сообщение отправлено.')

            if property_obj:
                return redirect('property_detail', slug=property_obj.slug)
            else:
                return redirect('messages_list')

    conversation = Message.objects.filter(
        Q(sender=request.user, recipient=recipient) |
        Q(sender=recipient, recipient=request.user)
    ).order_by('created_at')

    # Помечаем сообщения как прочитанные
    Message.objects.filter(
        sender=recipient,
        recipient=request.user,
        is_read=False
    ).update(is_read=True)

    context = {
        'recipient': recipient,
        'property': property_obj,
        'conversation': conversation,
        'title': f'Сообщение для {recipient.get_full_name_or_username()}' if recipient else 'Новое сообщение'
    }
    return render(request, 'core/send_message.html', context)


# ============================================================================
# УПРАВЛЕНИЕ ПОМЕЩЕНИЯМИ (ДЛЯ АРЕНДОДАТЕЛЕЙ)
# ============================================================================

@login_required
def add_property(request):
    """Добавление нового помещения"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Только арендодатели могут добавлять помещения.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = PropertyForm(
            request.POST,
            request.FILES,
            allow_featured=_is_platform_admin(request.user),
            allow_admin_statuses=_is_platform_admin(request.user),
        )
        if form.is_valid():
            property_obj = form.save(commit=False)
            property_obj.landlord = request.user
            property_obj.status = 'pending'  # Отправляем на модерацию
            if not _is_platform_admin(request.user):
                property_obj.is_featured = False
            property_obj.save()
            form.save_m2m()

            images = request.FILES.getlist('images')
            for image in images:
                property_obj.images.create(image=image)

            # Уведомление администраторам
            admins = User.objects.filter(user_type='admin', is_active=True)
            for admin in admins:
                create_notification(
                    user=admin,
                    notification_type='system',
                    title='Новое помещение на модерации',
                    message=f'Помещение "{property_obj.title}" от {request.user.get_full_name_or_username()} требует проверки.',
                    related_object_id=property_obj.id,
                    related_object_type='property'
                )

            messages.success(request,
                             'Помещение отправлено на модерацию. После проверки оно станет доступным для бронирования.')
            return redirect('my_properties')
    else:
        form = PropertyForm(
            allow_featured=_is_platform_admin(request.user),
            allow_admin_statuses=_is_platform_admin(request.user),
        )

    return render(request, 'core/add_property.html', {
        'form': form,
        'title': 'Добавление помещения'
    })


@login_required
def edit_property(request, property_id):
    """Редактирование помещения"""
    property_obj = get_object_or_404(Property, id=property_id)

    if request.user != property_obj.landlord:
        messages.error(request, 'Вы не можете редактировать это помещение.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = PropertyForm(
            request.POST,
            request.FILES,
            instance=property_obj,
            allow_featured=_is_platform_admin(request.user),
            allow_admin_statuses=_is_platform_admin(request.user),
        )
        if form.is_valid():
            property_obj = form.save()

            images = request.FILES.getlist('images')
            for image in images:
                property_obj.images.create(image=image)

            messages.success(request, 'Помещение успешно обновлено.')
            return redirect('my_properties')
    else:
        form = PropertyForm(
            instance=property_obj,
            allow_featured=_is_platform_admin(request.user),
            allow_admin_statuses=_is_platform_admin(request.user),
        )

    return render(request, 'core/edit_property.html', {
        'form': form,
        'property': property_obj,
        'existing_images': property_obj.images.all(),
        'title': 'Редактирование помещения'
    })


@login_required
def delete_property(request, property_id):
    """Удаление помещения"""
    property_obj = get_object_or_404(Property, id=property_id)

    if request.user != property_obj.landlord:
        messages.error(request, 'Вы не можете удалить это помещение.')
        return redirect('dashboard')

    if request.method == 'POST':
        property_obj.delete()
        messages.success(request, 'Помещение успешно удалено.')
        return redirect('my_properties')

    return render(request, 'core/confirm_delete.html', {
        'object': property_obj,
        'type': 'помещение',
        'title': 'Удаление помещения'
    })


@login_required
def delete_property_image(request, image_id):
    """Удаление изображения помещения"""
    from .models import PropertyImage
    image = get_object_or_404(PropertyImage, id=image_id)

    if request.user != image.property.landlord:
        messages.error(request, 'Вы не можете удалить это изображение.')
        return redirect('dashboard')

    image.delete()
    messages.success(request, 'Изображение успешно удалено.')
    return redirect('edit_property', property_id=image.property.id)


@login_required
def landlord_bookings(request):
    """Бронирования для арендодателя с пагинацией (5 на странице)"""
    if request.user.user_type != 'landlord':
        messages.error(request, 'Эта страница доступна только арендодателям.')
        return redirect('dashboard')

    base = Booking.objects.filter(property__landlord=request.user)
    bookings_count = {
        'all': base.count(),
        'pending': base.filter(status='pending').count(),
        'paid': base.filter(status='paid').count(),
        'confirmed': base.filter(status='confirmed').count(),
        'cancelled': base.filter(status='cancelled').count(),
        'completed': base.filter(status='completed').count(),
    }

    bookings = base.select_related('property', 'tenant').order_by('-created_at')

    status_filter = request.GET.get('status')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    property_id = request.GET.get('property')
    if property_id:
        try:
            pid = int(property_id)
            if request.user.properties.filter(id=pid).exists():
                bookings = bookings.filter(property_id=pid)
        except ValueError:
            pass

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        bookings = bookings.filter(start_datetime__date__gte=date_from)
    if date_to:
        bookings = bookings.filter(start_datetime__date__lte=date_to)

    q = (request.GET.get('q') or '').strip()
    if q:
        bookings = _filter_icase_contains(
            bookings,
            [
                'booking_id',
                'property__title',
                'tenant__username',
                'tenant__first_name',
                'tenant__last_name',
                'tenant__email',
            ],
            q,
            prefix='llq',
        )

    paginator = Paginator(bookings, 5)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    landlord_properties = request.user.properties.order_by('title')

    context = {
        'bookings': bookings_page,
        'current_status': status_filter,
        'landlord_properties': landlord_properties,
        'bookings_count': bookings_count,
        'title': 'Бронирования моих помещений'
    }
    return render(request, 'core/landlord_bookings.html', context)


@login_required
def update_booking_status(request, booking_id, status):
    """Обновление статуса бронирования (для арендодателя)"""
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user != booking.property.landlord:
        messages.error(request, 'Вы не можете изменить статус этого бронирования.')
        return redirect('dashboard')

    valid_statuses = ['confirmed', 'cancelled', 'completed']
    if status not in valid_statuses:
        messages.error(request, 'Недопустимый статус.')
        return redirect('landlord_bookings')

    old_status = booking.status
    booking.status = status
    booking.save()

    if old_status != status and status in ['confirmed', 'cancelled', 'completed']:
        notification_type = f'booking_{status}'
        create_booking_notification(booking, notification_type)

        # Если бронирование подтверждено, генерируем договор
        if status == 'confirmed':
            generate_contract_pdf(booking)

    status_names = {
        'confirmed': 'подтверждено',
        'cancelled': 'отменено',
        'completed': 'завершено'
    }
    messages.success(request, f'Бронирование успешно {status_names[status]}.')
    return redirect('landlord_bookings')


@login_required
def add_property_image(request, property_id):
    """Добавление изображения к помещению"""
    property_obj = get_object_or_404(Property, id=property_id)

    if request.user != property_obj.landlord:
        messages.error(request, 'Вы не можете добавлять изображения к этому помещению.')
        return redirect('dashboard')

    if request.method == 'POST' and request.FILES.get('image'):
        from .models import PropertyImage
        PropertyImage.objects.create(property=property_obj, image=request.FILES['image'])
        messages.success(request, 'Изображение успешно добавлено.')
        return redirect('edit_property', property_id=property_id)


# ============================================================================
# АДМИН-ПАНЕЛЬ
# ============================================================================

@login_required
def custom_admin_dashboard(request):
    """Кастомная админ-панель"""
    if not _is_platform_admin(request.user):
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    stats = {
        'total_users': User.objects.count(),
        'new_users_today': User.objects.filter(date_joined__date=today).count(),
        'new_users_week': User.objects.filter(date_joined__date__gte=week_ago).count(),
        'total_properties': Property.objects.count(),
        'active_properties': Property.objects.filter(status='active').count(),
        'pending_properties': Property.objects.filter(status='pending').count(),
        'total_bookings': Booking.objects.count(),
        'pending_bookings': Booking.objects.filter(status='pending').count(),
        'paid_bookings': Booking.objects.filter(status='paid').count(),
        'today_bookings': Booking.objects.filter(start_datetime__date=today).count(),
        'month_revenue': Booking.objects.filter(
            status__in=['paid', 'confirmed', 'completed'],
            updated_at__gte=month_ago
        ).aggregate(total=Sum('total_price'))['total'] or 0,
        'admin_count': User.objects.filter(user_type='admin').count(),
        'landlord_count': User.objects.filter(user_type='landlord').count(),
        'tenant_count': User.objects.filter(user_type='tenant').count(),
    }

    # Данные для графика
    chart_labels = []
    chart_paid = []
    chart_pending = []
    chart_cancelled = []

    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        chart_labels.append(date.strftime('%d.%m'))
        day_bookings = Booking.objects.filter(created_at__date=date)
        chart_paid.append(day_bookings.filter(status='paid').count())
        chart_pending.append(day_bookings.filter(status='pending').count())
        chart_cancelled.append(day_bookings.filter(status='cancelled').count())

    property_types = Property.objects.values('property_type').annotate(
        count=Count('id')
    ).order_by('-count')

    property_labels = []
    property_data = []
    type_names = dict(Property.PROPERTY_TYPE_CHOICES)
    for item in property_types:
        property_labels.append(type_names.get(item['property_type'], item['property_type']))
        property_data.append(item['count'])

    recent_users = User.objects.order_by('-date_joined')[:5]
    recent_bookings = Booking.objects.select_related('property', 'tenant').order_by('-created_at')[:5]
    recent_reviews = Review.objects.select_related('property', 'user').order_by('-created_at')[:5]

    return render(request, 'admin/dashboard.html', {
        'stats': stats,
        'recent_users': recent_users,
        'recent_bookings': recent_bookings,
        'recent_reviews': recent_reviews,
        'chart_labels': json.dumps(chart_labels),
        'chart_paid': json.dumps(chart_paid),
        'chart_pending': json.dumps(chart_pending),
        'chart_cancelled': json.dumps(chart_cancelled),
        'property_labels': json.dumps(property_labels),
        'property_data': json.dumps(property_data),
        'title': 'Админ-панель'
    })


@login_required
def admin_audit_log(request):
    """Журнал аудита действий в кастомной админке."""
    if not _is_platform_admin(request.user):
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    logs = AdminAuditLog.objects.select_related('admin_user').all()

    action_filter = (request.GET.get('action') or '').strip()
    model_filter = (request.GET.get('model') or '').strip()
    admin_filter = (request.GET.get('admin') or '').strip()

    if action_filter:
        logs = logs.filter(action=action_filter)
    if model_filter:
        logs = logs.filter(target_model__iexact=model_filter)
    if admin_filter:
        logs = _filter_icase_contains(
            logs,
            ['admin_user__username', 'admin_user__email', 'details', 'target_repr'],
            admin_filter,
            prefix='aad',
        )

    paginator = Paginator(logs, 20)
    page = request.GET.get('page')
    logs_page = paginator.get_page(page)

    return render(request, 'admin/audit_log.html', {
        'logs': logs_page,
        'action_filter': action_filter,
        'model_filter': model_filter,
        'admin_filter': admin_filter,
        'action_choices': AdminAuditLog.ACTION_CHOICES,
        'title': 'Аудит админки'
    })


@login_required
def admin_user_audit_log(request):
    """Журнал пользовательской активности."""
    if not _is_platform_admin(request.user):
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    logs = UserAuditLog.objects.select_related('user').all()
    event_filter = (request.GET.get('event') or '').strip()
    user_filter = (request.GET.get('user_q') or '').strip()

    if event_filter:
        logs = logs.filter(event_type=event_filter)
    if user_filter:
        logs = _filter_icase_contains(
            logs,
            ['username_snapshot', 'user__username', 'user__email', 'details', 'ip_address'],
            user_filter,
            prefix='aul',
        )

    paginator = Paginator(logs, 20)
    page = request.GET.get('page')
    logs_page = paginator.get_page(page)

    return render(request, 'admin/user_audit_log.html', {
        'logs': logs_page,
        'event_filter': event_filter,
        'user_filter': user_filter,
        'event_choices': UserAuditLog.EVENT_CHOICES,
        'title': 'Аудит пользователей'
    })


@login_required
def admin_user_management(request):
    """Управление пользователями с пагинацией (5 на странице)"""
    if not _is_platform_admin(request.user):
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    users = User.objects.all().order_by('-date_joined')

    search_query = request.GET.get('search')
    user_type_filter = request.GET.get('user_type')
    status_filter = request.GET.get('status')

    if search_query:
        users = _filter_icase_contains(
            users,
            [
                'username', 'email', 'first_name', 'last_name',
                'phone', 'company_name',
            ],
            search_query,
            prefix='adu',
        )
    if user_type_filter:
        users = users.filter(user_type=user_type_filter)
    if status_filter:
        if status_filter == 'active':
            users = users.filter(is_active=True)
        elif status_filter == 'inactive':
            users = users.filter(is_active=False)

    stats = {
        'total_users': users.count(),
        'active_count': users.filter(is_active=True).count(),
        'inactive_count': users.filter(is_active=False).count(),
        'admin_count': users.filter(user_type='admin').count(),
        'landlord_count': users.filter(user_type='landlord').count(),
        'tenant_count': users.filter(user_type='tenant').count(),
    }

    # Пагинация - 5 элементов на странице
    paginator = Paginator(users, 5)
    page = request.GET.get('page')
    users_page = paginator.get_page(page)

    if request.method == 'POST':
        action = request.POST.get('action')
        user_id = request.POST.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            if action == 'toggle_active':
                user.is_active = not user.is_active
                user.save()
                status = 'активирован' if user.is_active else 'деактивирован'
                log_admin_action(
                    request,
                    action='status_change',
                    target_model='User',
                    target_obj=user,
                    details=f'Изменен статус активности: {status}'
                )
                messages.success(request, f'Пользователь {user.username} {status}.')
            elif action == 'delete':
                if user == request.user:
                    messages.error(request, 'Вы не можете удалить свой аккаунт.')
                else:
                    username = user.username
                    user_repr = str(user)
                    user.delete()
                    log_admin_action(
                        request,
                        action='delete',
                        target_model='User',
                        details=f'Удален пользователь: {user_repr} ({username})'
                    )
                    messages.success(request, f'Пользователь {username} удален.')
        except User.DoesNotExist:
            messages.error(request, 'Пользователь не найден.')
        return redirect('admin_user_management')

    return render(request, 'admin/user_management.html', {
        'users': users_page,
        'stats': stats,
        'search_query': search_query,
        'user_type_filter': user_type_filter,
        'status_filter': status_filter,
        'title': 'Управление пользователями'
    })


@login_required
def admin_property_management(request):
    """Управление помещениями (админ) с пагинацией (5 на странице)"""
    if not _is_platform_admin(request.user):
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    properties = Property.objects.select_related('landlord', 'category').all().order_by('-created_at')

    status_filter = request.GET.get('status')
    city_filter = request.GET.get('city')
    type_filter = request.GET.get('type')
    search = (request.GET.get('search') or '').strip()
    landlord_q = (request.GET.get('landlord') or '').strip()

    if search:
        properties = _filter_icase_contains(
            properties,
            ['title', 'address', 'description', 'slug'],
            search,
            prefix='adp',
        )
    if landlord_q:
        properties = _filter_icase_contains(
            properties,
            [
                'landlord__username',
                'landlord__email',
                'landlord__first_name',
                'landlord__last_name',
            ],
            landlord_q,
            prefix='adpl',
        )
    if status_filter:
        properties = properties.filter(status=status_filter)
    if city_filter:
        properties = _filter_icase_contains(properties, ['city'], city_filter, prefix='adpc')
    if type_filter:
        properties = properties.filter(property_type=type_filter)

    all_for_stats = Property.objects.all()
    property_stats = {
        'total': all_for_stats.count(),
        'active': all_for_stats.filter(status='active').count(),
        'pending': all_for_stats.filter(status='pending').count(),
        'views': all_for_stats.aggregate(total=Sum('views_count'))['total'] or 0,
    }

    # Пагинация - 5 элементов на странице
    paginator = Paginator(properties, 5)
    page = request.GET.get('page')
    properties_page = paginator.get_page(page)

    if request.method == 'POST':
        action = request.POST.get('action')
        property_id = request.POST.get('property_id')
        try:
            property_obj = Property.objects.get(id=property_id)
            if action == 'approve':
                property_obj.status = 'active'
                property_obj.save()
                log_admin_action(
                    request,
                    action='moderation',
                    target_model='Property',
                    target_obj=property_obj,
                    details='Помещение одобрено в админке'
                )
                # Уведомление владельцу
                create_notification(
                    user=property_obj.landlord,
                    notification_type='system',
                    title='Помещение одобрено',
                    message=f'Ваше помещение "{property_obj.title}" прошло модерацию и теперь доступно для бронирования.',
                    related_object_id=property_obj.id,
                    related_object_type='property'
                )
                messages.success(request, f'Помещение "{property_obj.title}" одобрено.')
            elif action == 'reject':
                property_obj.status = 'rejected'
                property_obj.save()
                log_admin_action(
                    request,
                    action='moderation',
                    target_model='Property',
                    target_obj=property_obj,
                    details='Помещение отклонено в админке'
                )
                messages.success(request, f'Помещение "{property_obj.title}" отклонено.')
            elif action == 'toggle_featured':
                property_obj.is_featured = not property_obj.is_featured
                property_obj.save()
                state = 'включен' if property_obj.is_featured else 'выключен'
                log_admin_action(
                    request,
                    action='update',
                    target_model='Property',
                    target_obj=property_obj,
                    details=f'Флаг "рекомендуемое" {state}'
                )
                messages.success(request, f'Статус "Рекомендуемое" изменен.')
            elif action == 'delete':
                prop_title = property_obj.title
                prop_id = property_obj.id
                property_obj.delete()
                log_admin_action(
                    request,
                    action='delete',
                    target_model='Property',
                    details=f'Удалено помещение #{prop_id}: {prop_title}'
                )
                messages.success(request, f'Помещение удалено.')
        except Property.DoesNotExist:
            messages.error(request, 'Помещение не найдено.')
        return redirect('admin_property_management')

    return render(request, 'admin/property_management.html', {
        'properties': properties_page,
        'property_stats': property_stats,
        'title': 'Управление помещениями'
    })


@login_required
def admin_booking_management(request):
    """Управление бронированиями (админ) с пагинацией (5 на странице)"""
    if not _is_platform_admin(request.user):
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    all_bookings = Booking.objects.all()
    booking_stats = {
        'total_bookings': all_bookings.count(),
        'pending_bookings': all_bookings.filter(status='pending').count(),
        'paid_bookings': all_bookings.filter(status='paid').count(),
        'confirmed_bookings': all_bookings.filter(status='confirmed').count(),
        'completed_bookings': all_bookings.filter(status='completed').count(),
        'cancelled_bookings': all_bookings.filter(status='cancelled').count(),
        'total_revenue': all_bookings.filter(
            status__in=['paid', 'confirmed', 'completed']
        ).aggregate(total=Sum('total_price'))['total'] or 0,
    }

    if request.method == 'POST':
        action = request.POST.get('action')
        booking_id = request.POST.get('booking_id')
        try:
            booking = Booking.objects.get(id=booking_id)
            if action == 'confirm' and booking.status == 'pending':
                booking.status = 'confirmed'
                booking.save()
                log_admin_action(
                    request,
                    action='status_change',
                    target_model='Booking',
                    target_obj=booking,
                    details='Бронирование подтверждено'
                )
                create_booking_notification(booking, 'booking_confirmed')
                try:
                    generate_contract_pdf(booking)
                except Exception as e:
                    logger.error('Contract PDF: %s', e)
                messages.success(request, 'Бронирование подтверждено.')
            elif action == 'cancel' and booking.status in ('pending', 'paid', 'confirmed'):
                booking.status = 'cancelled'
                booking.save()
                log_admin_action(
                    request,
                    action='status_change',
                    target_model='Booking',
                    target_obj=booking,
                    details='Бронирование отменено'
                )
                create_booking_notification(booking, 'booking_cancelled')
                messages.success(request, 'Бронирование отменено.')
            elif action == 'complete' and booking.status == 'confirmed':
                booking.status = 'completed'
                booking.save()
                log_admin_action(
                    request,
                    action='status_change',
                    target_model='Booking',
                    target_obj=booking,
                    details='Бронирование завершено'
                )
                create_booking_notification(booking, 'booking_completed')
                messages.success(request, 'Бронирование завершено.')
            elif action == 'delete':
                bid = booking.booking_id
                booking.delete()
                log_admin_action(
                    request,
                    action='delete',
                    target_model='Booking',
                    details=f'Удалено бронирование: {bid}'
                )
                messages.success(request, f'Бронирование {bid} удалено.')
            else:
                messages.error(request, 'Действие недоступно для текущего статуса.')
        except Booking.DoesNotExist:
            messages.error(request, 'Бронирование не найдено.')
        qs = request.GET.copy()
        qs.pop('page', None)
        if qs:
            return redirect(f'{reverse("admin_booking_management")}?{qs.urlencode()}')
        return redirect('admin_booking_management')

    bookings = Booking.objects.select_related('property', 'tenant', 'property__landlord').order_by('-created_at')

    search = (request.GET.get('search') or '').strip()
    status_filter = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    paid_filter = request.GET.get('paid')
    property_filter = (request.GET.get('property_q') or '').strip()

    if search:
        bookings = _filter_icase_contains(
            bookings,
            [
                'booking_id',
                'property__title',
                'tenant__username',
                'tenant__email',
                'tenant__first_name',
                'tenant__last_name',
            ],
            search,
            prefix='adbk',
        )
    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if date_from:
        bookings = bookings.filter(start_datetime__date__gte=date_from)
    if date_to:
        bookings = bookings.filter(start_datetime__date__lte=date_to)
    if paid_filter == 'yes':
        bookings = bookings.filter(is_paid=True)
    elif paid_filter == 'no':
        bookings = bookings.filter(is_paid=False)
    if property_filter:
        bookings = _filter_icase_contains(
            bookings,
            ['property__title', 'property__city'],
            property_filter,
            prefix='adpf',
        )

    paginator = Paginator(bookings, 5)
    page = request.GET.get('page')
    bookings_page = paginator.get_page(page)

    context = {
        'bookings': bookings_page,
        'title': 'Управление бронированиями',
        **booking_stats,
    }
    return render(request, 'admin/booking_management.html', context)


@login_required
def admin_review_management(request):
    """Управление отзывами (админ) с пагинацией (5 на странице)"""
    if not _is_platform_admin(request.user):
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')
        review_id = request.POST.get('review_id')
        try:
            review = Review.objects.get(id=review_id)
            if action == 'approve':
                review.status = 'approved'
                review.admin_comment = None
                review.save()
                log_admin_action(
                    request,
                    action='moderation',
                    target_model='Review',
                    target_obj=review,
                    details='Отзыв одобрен'
                )
                messages.success(request, 'Отзыв одобрен и опубликован.')
            elif action == 'reject':
                review.status = 'rejected'
                comment = (request.POST.get('admin_comment') or '').strip()
                review.admin_comment = comment if comment else None
                review.save()
                log_admin_action(
                    request,
                    action='moderation',
                    target_model='Review',
                    target_obj=review,
                    details=f'Отзыв отклонен. Комментарий: {comment or "без комментария"}'
                )
                messages.success(request, 'Отзыв отклонён.')
            elif action == 'delete':
                review_repr = str(review)
                review.delete()
                log_admin_action(
                    request,
                    action='delete',
                    target_model='Review',
                    details=f'Удален отзыв: {review_repr}'
                )
                messages.success(request, 'Отзыв удалён.')
            else:
                messages.error(request, 'Неизвестное действие.')
        except Review.DoesNotExist:
            messages.error(request, 'Отзыв не найден.')
        next_url = request.POST.get('next')
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect('admin_review_management')

    reviews = Review.objects.select_related('property', 'user').order_by('-created_at')

    search = (request.GET.get('search') or '').strip()
    if search:
        reviews = _filter_icase_contains(
            reviews,
            [
                'comment',
                'property__title',
                'property__city',
                'user__username',
                'user__first_name',
                'user__last_name',
                'user__email',
            ],
            search,
            prefix='arv',
        )

    status_filter = request.GET.get('status')
    rating_filter = request.GET.get('rating')
    if status_filter:
        reviews = reviews.filter(status=status_filter)
    if rating_filter:
        reviews = reviews.filter(rating=rating_filter)

    paginator = Paginator(reviews, 5)
    page = request.GET.get('page')
    reviews_page = paginator.get_page(page)

    total_reviews = Review.objects.count()
    avg_rating = Review.objects.filter(status='approved').aggregate(v=Avg('rating'))['v']
    if avg_rating is None:
        avg_rating = 0
    pending_reviews_count = Review.objects.filter(status='pending').count()
    rating_5_count = Review.objects.filter(rating=5).count()

    pending_properties_count = Property.objects.filter(status='pending').count()
    pending_bookings_count = Booking.objects.filter(status='pending').count()

    return render(request, 'admin/review_management.html', {
        'reviews': reviews_page,
        'title': 'Управление отзывами',
        'total_reviews': total_reviews,
        'avg_rating': avg_rating,
        'pending_reviews_count': pending_reviews_count,
        'rating_5': rating_5_count,
        'pending_users_count': 0,
        'pending_properties_count': pending_properties_count,
        'pending_bookings_count': pending_bookings_count,
    })


@login_required
def export_users_csv(request):
    """Экспорт пользователей в CSV"""
    if not _is_platform_admin(request.user):
        messages.error(request, 'У вас нет прав для доступа к этой странице.')
        return redirect('dashboard')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Имя пользователя', 'Email', 'Имя', 'Фамилия', 'Тип', 'Статус', 'Дата регистрации'])

    users = User.objects.all().order_by('-date_joined')
    for user in users:
        writer.writerow([
            user.id,
            user.username,
            user.email,
            user.first_name or '',
            user.last_name or '',
            user.get_user_type_display(),
            'Активен' if user.is_active else 'Неактивен',
            user.date_joined.strftime('%Y-%m-%d %H:%M')
        ])

    return response


# ============================================================================
# API ЭНДПОИНТЫ
# ============================================================================

@login_required
def ajax_create_booking(request, property_id):
    """AJAX бронирование"""
    if request.method != 'POST' or not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    property_obj = get_object_or_404(Property, id=property_id)

    try:
        data = json.loads(request.body)
        start_datetime = datetime.fromisoformat(f"{data['booking_date']} {data['start_time']}")
        end_datetime = datetime.fromisoformat(f"{data['booking_date']} {data['end_time']}")

        conflicting_bookings = Booking.objects.filter(
            property=property_obj,
            status__in=['pending', 'paid', 'confirmed'],
            start_datetime__lt=end_datetime,
            end_datetime__gt=start_datetime
        )

        if conflicting_bookings.exists():
            return JsonResponse({'error': 'Выбранное время уже занято.'}, status=400)

        booking = Booking.objects.create(
            property=property_obj,
            tenant=request.user,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            guests=data.get('guests', 1),
            special_requests=data.get('special_requests', ''),
            status='pending'
        )

        create_booking_notification(booking, 'booking_created')

        return JsonResponse({
            'success': True,
            'message': 'Бронирование создано. Перейдите к оплате.',
            'booking_id': booking.id,
            'redirect_url': reverse_lazy('payment', args=[booking.id])
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def booking_calendar(request, property_id):
    """Календарь занятости: три календарных месяца подряд и почасовая сетка выбранного дня."""
    property_obj = get_object_or_404(Property, id=property_id)

    month_str = request.GET.get('month')
    if month_str:
        try:
            anchor = datetime.strptime(month_str, '%Y-%m').date().replace(day=1)
        except ValueError:
            anchor = timezone.now().date().replace(day=1)
    else:
        anchor = timezone.now().date().replace(day=1)

    third = add_calendar_months(anchor, 2)
    last_day = datetime(third.year, third.month,
                        calendar.monthrange(third.year, third.month)[1]).date()

    range_start_dt = timezone.make_aware(datetime.combine(anchor, datetime.min.time()))
    range_end_dt = timezone.make_aware(datetime.combine(last_day, dt_time(23, 59, 59)))

    bookings_list = list(property_obj.bookings.filter(
        status__in=['pending', 'paid', 'confirmed'],
        end_datetime__gte=range_start_dt,
        start_datetime__date__lte=last_day,
    ).select_related('tenant'))

    cal = calendar.Calendar()
    three_month_blocks = []
    month_names = [
        '', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
        'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
    ]
    for mi in range(3):
        cur_first = add_calendar_months(anchor, mi)
        y, m = cur_first.year, cur_first.month
        calendar_weeks = []
        for week in cal.monthdatescalendar(y, m):
            week_days = []
            for day in week:
                in_month = day.month == m
                overlapping = [b for b in bookings_list if booking_overlaps_calendar_day(b, day)]
                week_days.append({
                    'date': day,
                    'in_month': in_month,
                    'is_today': day == timezone.now().date(),
                    'has_bookings': len(overlapping) > 0,
                    'booking_count': len(overlapping),
                    'bookings': [{
                        'tenant': b.tenant.get_full_name_or_username(),
                        'start_time': b.start_datetime.time().strftime('%H:%M'),
                        'end_time': b.end_datetime.time().strftime('%H:%M')
                    } for b in overlapping[:4]]
                })
            calendar_weeks.append(week_days)
        three_month_blocks.append({
            'year': y,
            'month': m,
            'title': f'{month_names[m]} {y}',
            'weeks': calendar_weeks,
        })

    today = timezone.now().date()
    selected_day_str = request.GET.get('day') or today.isoformat()
    try:
        selected_day = datetime.strptime(selected_day_str, '%Y-%m-%d').date()
    except ValueError:
        selected_day = today
        selected_day_str = selected_day.isoformat()
    if selected_day < anchor:
        selected_day = anchor
        selected_day_str = selected_day.isoformat()
    elif selected_day > last_day:
        selected_day = last_day
        selected_day_str = selected_day.isoformat()

    hourly_slots = []
    for h in range(8, 22):
        slot_start = timezone.make_aware(datetime.combine(selected_day, dt_time(h, 0)))
        slot_end = slot_start + timedelta(hours=1)
        overlapping = [b for b in bookings_list if b.end_datetime > slot_start and b.start_datetime < slot_end]
        hourly_slots.append({
            'hour': h,
            'busy': len(overlapping) > 0,
            'bookings': overlapping,
        })

    prev_anchor = add_calendar_months(anchor, -3)
    next_anchor = add_calendar_months(anchor, 3)

    upcoming_bookings = property_obj.bookings.filter(
        start_datetime__gte=timezone.now(),
        status__in=['pending', 'paid', 'confirmed']
    ).select_related('tenant').order_by('start_datetime')[:8]

    total_days = (last_day - anchor).days + 1
    booked_day_set = set()
    for offset in range(total_days):
        d = anchor + timedelta(days=offset)
        if any(booking_overlaps_calendar_day(b, d) for b in bookings_list):
            booked_day_set.add(d)
    occupancy_rate = round(len(booked_day_set) / total_days * 100) if total_days > 0 else 0

    return render(request, 'core/booking_calendar.html', {
        'property': property_obj,
        'anchor_month': anchor,
        'prev_anchor': prev_anchor,
        'next_anchor': next_anchor,
        'three_month_blocks': three_month_blocks,
        'range_label': f'{anchor.strftime("%d.%m.%Y")} — {last_day.strftime("%d.%m.%Y")}',
        'hourly_slots': hourly_slots,
        'selected_day': selected_day,
        'selected_day_str': selected_day_str,
        'upcoming_bookings': upcoming_bookings,
        'bookings_count': len(bookings_list),
        'occupancy_rate': occupancy_rate,
        'title': f'Календарь бронирований - {property_obj.title}'
    })