from datetime import timedelta
import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Booking, Contract, Property, User


class BookingContractAccessTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            username='tenant1',
            email='tenant1@example.com',
            password='Pass12345!',
            user_type='tenant',
        )
        self.landlord = User.objects.create_user(
            username='landlord1',
            email='landlord1@example.com',
            password='Pass12345!',
            user_type='landlord',
        )
        self.other_tenant = User.objects.create_user(
            username='tenant2',
            email='tenant2@example.com',
            password='Pass12345!',
            user_type='tenant',
        )
        self.property = Property.objects.create(
            landlord=self.landlord,
            title='Тестовое помещение',
            description='Описание',
            status='active',
            price_per_hour=1000,
        )
        self.booking = Booking.objects.create(
            property=self.property,
            tenant=self.tenant,
            start_datetime=timezone.now() + timedelta(days=2),
            end_datetime=timezone.now() + timedelta(days=2, hours=2),
            status='pending',
            total_price=2000,
        )

    def test_download_contract_forbidden_for_pending_status(self):
        self.client.force_login(self.tenant)
        response = self.client.get(reverse('download_contract', args=[self.booking.id]), follow=True)
        self.booking.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.booking.status, 'pending')

    def test_payment_by_card_requires_signed_contract(self):
        self.client.force_login(self.tenant)
        url = reverse('payment', args=[self.booking.id])

        response = self.client.post(
            url,
            data={
                'payment_method': 'card',
                'card_number': '4242 4242 4242 4242',
                'card_holder': 'TEST USER',
                'expiry_month': '12',
                'expiry_year': '2030',
                'cvv': '123',
            },
            follow=True,
        )
        self.booking.refresh_from_db()
        contract = Contract.objects.get(booking=self.booking)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(contract.signed_by_tenant)
        self.assertFalse(contract.signed_by_landlord)
        self.assertEqual(self.booking.status, 'pending')
        self.assertFalse(self.booking.is_paid)

        contract.signed_by_tenant = True
        contract.signed_by_landlord = True
        contract.save(update_fields=['signed_by_tenant', 'signed_by_landlord'])

        response = self.client.post(
            url,
            data={
                'payment_method': 'card',
                'card_number': '4242 4242 4242 4242',
                'card_holder': 'TEST USER',
                'expiry_month': '12',
                'expiry_year': '2030',
                'cvv': '123',
            },
            follow=True,
        )
        self.booking.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.booking.status, 'paid')
        self.assertTrue(self.booking.is_paid)
        self.assertIsNotNone(self.booking.payment_date)

    def test_cancel_paid_booking_rolls_back_payment_fields(self):
        self.client.force_login(self.tenant)
        self.booking.status = 'paid'
        self.booking.is_paid = True
        self.booking.payment_date = timezone.now()
        self.booking.save(update_fields=['status', 'is_paid', 'payment_date'])

        response = self.client.get(reverse('cancel_booking', args=[self.booking.id]), follow=True)
        self.booking.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.booking.status, 'cancelled')
        self.assertFalse(self.booking.is_paid)
        self.assertIsNone(self.booking.payment_date)

    def test_role_access_tenant_vs_landlord_for_payment_and_cancel(self):
        self.client.force_login(self.landlord)

        pay_response = self.client.get(reverse('payment', args=[self.booking.id]), follow=True)
        self.booking.refresh_from_db()
        self.assertEqual(pay_response.status_code, 200)
        self.assertEqual(self.booking.status, 'pending')

        cancel_response = self.client.get(reverse('cancel_booking', args=[self.booking.id]), follow=True)
        self.booking.refresh_from_db()
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(self.booking.status, 'pending')

        self.client.force_login(self.other_tenant)
        deny_response = self.client.get(reverse('download_contract', args=[self.booking.id]), follow=True)
        self.assertEqual(deny_response.status_code, 200)


class BookingIntegrationFlowTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            username='tenant_flow',
            email='tenant_flow@example.com',
            password='Pass12345!',
            user_type='tenant',
        )
        self.landlord = User.objects.create_user(
            username='landlord_flow',
            email='landlord_flow@example.com',
            password='Pass12345!',
            user_type='landlord',
        )
        self.property = Property.objects.create(
            landlord=self.landlord,
            title='Flow помещение',
            description='Описание',
            status='active',
            price_per_hour=1500,
        )
        self.booking = Booking.objects.create(
            property=self.property,
            tenant=self.tenant,
            start_datetime=timezone.now() + timedelta(days=3),
            end_datetime=timezone.now() + timedelta(days=3, hours=3),
            status='pending',
            total_price=4500,
        )

    @patch('core.views.generate_contract_pdf')
    def test_full_flow_card_payment_then_landlord_confirm(self, mocked_pdf):
        mocked_pdf.return_value = None

        contract = Contract.objects.create(
            booking=self.booking,
            signed_by_tenant=True,
            signed_by_landlord=True,
        )

        self.client.force_login(self.tenant)
        payment_response = self.client.post(
            reverse('payment', args=[self.booking.id]),
            data={
                'payment_method': 'card',
                'card_number': '4242 4242 4242 4242',
                'card_holder': 'TEST USER',
                'expiry_month': '12',
                'expiry_year': '2030',
                'cvv': '123',
            },
            follow=True,
        )
        self.booking.refresh_from_db()
        self.assertEqual(payment_response.status_code, 200)
        self.assertEqual(self.booking.status, 'paid')
        self.assertTrue(self.booking.is_paid)
        self.assertIsNotNone(self.booking.payment_date)

        self.client.force_login(self.landlord)
        confirm_response = self.client.get(
            reverse('update_booking_status', args=[self.booking.id, 'confirmed']),
            follow=True,
        )
        self.booking.refresh_from_db()
        contract.refresh_from_db()

        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(self.booking.status, 'confirmed')
        self.assertTrue(self.booking.is_paid)
        self.assertTrue(mocked_pdf.called)

    def test_landlord_endpoints_are_role_protected(self):
        self.client.force_login(self.tenant)

        landlord_page = self.client.get(reverse('landlord_bookings'), follow=True)
        self.assertEqual(landlord_page.status_code, 200)
        self.assertNotEqual(landlord_page.request['PATH_INFO'], reverse('landlord_bookings'))

        forbidden_status_change = self.client.get(
            reverse('update_booking_status', args=[self.booking.id, 'confirmed']),
            follow=True,
        )
        self.booking.refresh_from_db()
        self.assertEqual(forbidden_status_change.status_code, 200)
        self.assertEqual(self.booking.status, 'pending')

    def test_landlord_dashboard_has_chart_data(self):
        self.client.force_login(self.landlord)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

        month_labels = json.loads(response.context['landlord_chart_month_labels'])
        month_revenue = json.loads(response.context['landlord_chart_month_revenue'])
        month_bookings = json.loads(response.context['landlord_chart_month_bookings'])
        status_labels = json.loads(response.context['landlord_chart_status_labels'])
        status_values = json.loads(response.context['landlord_chart_status_values'])

        self.assertEqual(len(month_labels), 6)
        self.assertEqual(len(month_revenue), 6)
        self.assertEqual(len(month_bookings), 6)
        self.assertEqual(len(status_labels), 5)
        self.assertEqual(len(status_values), 5)
