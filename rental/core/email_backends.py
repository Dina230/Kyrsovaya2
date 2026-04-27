"""Бэкенд почты для разработки: читаемый текст в консоли без полного MIME/base64."""
import sys

from django.core.mail.backends.base import BaseEmailBackend


class ReadableConsoleEmailBackend(BaseEmailBackend):
    """Печатает тему и тело письма обычным текстом (UTF-8), без дампа multipart."""

    def send_messages(self, email_messages):
        for message in email_messages:
            self._write_message(message)
        return len(email_messages)

    def _write_message(self, message):
        stream = sys.stdout
        to_addrs = message.to
        if isinstance(to_addrs, (list, tuple)):
            to_str = ', '.join(to_addrs)
        else:
            to_str = str(to_addrs)

        stream.write('\n')
        stream.write('═' * 64 + '\n')
        stream.write('  Письмо (режим разработки, консоль)\n')
        stream.write('─' * 64 + '\n')
        stream.write(f'От:   {message.from_email}\n')
        stream.write(f'Кому: {to_str}\n')
        stream.write(f'Тема: {message.subject}\n')
        stream.write('─' * 64 + '\n')

        body = message.body or ''
        stream.write(body)
        if body and not body.endswith('\n'):
            stream.write('\n')

        alternatives = getattr(message, 'alternatives', None) or []
        if alternatives:
            stream.write('─' * 64 + '\n')
            stream.write('(дополнительно: HTML-версия письма не показана)\n')

        stream.write('═' * 64 + '\n\n')
