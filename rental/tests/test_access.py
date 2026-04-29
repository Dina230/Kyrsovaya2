from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Booking, Contract, Property, User


class AccessControlTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(
            username='tenant_access',
            email='tenant_access@example.com',
            password='Pass12345!',
            user_type='tenant',
        )
        self.landlord = User.objects.create_user(
            username='landlord_access',
            email='landlord_access@example.com',
            password='Pass12345!',
            user_type='landlord',
        )
        self.admin = User.objects.create_user(
            username='admin_access',
            email='admin_access@example.com',
            password='Pass12345!',
            user_type='admin',
            is_staff=True,
        )
        self.property = Property.objects.create(
            landlord=self.landlord,
            title='Access test property',
            description='Test description',
            status='active',
            price_per_hour=1200,
        )
        self.booking = Booking.objects.create(
            property=self.property,
            tenant=self.tenant,
            start_datetime=timezone.now() + timedelta(days=2),
            end_datetime=timezone.now() + timedelta(days=2, hours=2),
            status='pending',
            total_price=2400,
        )

    def test_tenant_cannot_access_landlord_pages(self):
        self.client.force_login(self.tenant)
        response = self.client.get(reverse('my_properties'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.request['PATH_INFO'], reverse('my_properties'))

    def test_landlord_cannot_book_as_tenant(self):
        self.client.force_login(self.landlord)
        response = self.client.post(
            reverse('create_booking', args=[self.property.id]),
            data={
                'start_date': (timezone.now() + timedelta(days=3)).date().isoformat(),
                'start_hour': '10',
                'start_minute': '00',
                'end_date': (timezone.now() + timedelta(days=3)).date().isoformat(),
                'end_hour': '12',
                'end_minute': '00',
                'guests': 2,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Booking.objects.filter(property=self.property).count(), 1)

    def test_admin_can_force_confirm_booking(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('admin_booking_management'),
            data={'action': 'confirm', 'booking_id': self.booking.id},
            follow=True,
        )
        self.booking.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.booking.status, 'confirmed')

    def test_tenant_cannot_sign_contract_on_behalf_of_landlord(self):
        contract = Contract.objects.create(
            booking=self.booking,
            signed_by_tenant=True,
            signed_by_landlord=False,
        )
        self.client.force_login(self.tenant)

        # Пытаемся провести административное действие, которое tenant не должен иметь права выполнять.
        response = self.client.post(
            reverse('admin_booking_management'),
            data={'action': 'confirm', 'booking_id': self.booking.id},
            follow=True,
        )
        contract.refresh_from_db()
        self.booking.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(contract.signed_by_landlord)
        self.assertEqual(self.booking.status, 'pending')
