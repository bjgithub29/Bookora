"""Unit tests for the Bookora email transport layer.

Tests Brevo HTTPS API, Resend HTTPS API, and local SMTP transport,
verifying request headers, JSON payloads, error handling, and provider detection.
"""
import io
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

import app as bookora


class TestEmailProviderDetection(unittest.TestCase):
    """Test environment variable precedence for email provider selection."""

    def test_explicit_brevo_provider(self):
        with patch.dict('os.environ', {'EMAIL_PROVIDER': 'brevo'}):
            self.assertEqual(bookora._get_email_provider(), 'brevo')

    def test_explicit_resend_provider(self):
        with patch.dict('os.environ', {'EMAIL_PROVIDER': 'resend'}):
            self.assertEqual(bookora._get_email_provider(), 'resend')

    def test_explicit_smtp_provider(self):
        with patch.dict('os.environ', {'EMAIL_PROVIDER': 'smtp'}):
            self.assertEqual(bookora._get_email_provider(), 'smtp')

    def test_inferred_brevo_from_api_key(self):
        with patch.dict('os.environ', {'EMAIL_PROVIDER': '', 'BREVO_API_KEY': 'xkeysib-test-123', 'RESEND_API_KEY': ''}):
            with patch.object(bookora, 'EMAIL_PROVIDER', ''):
                with patch.object(bookora, 'BREVO_API_KEY', 'xkeysib-test-123'):
                    with patch.object(bookora, 'RESEND_API_KEY', None):
                        self.assertEqual(bookora._get_email_provider(), 'brevo')

    def test_inferred_resend_from_api_key(self):
        with patch.dict('os.environ', {'EMAIL_PROVIDER': '', 'BREVO_API_KEY': '', 'RESEND_API_KEY': 're_test_123'}):
            with patch.object(bookora, 'EMAIL_PROVIDER', ''):
                with patch.object(bookora, 'BREVO_API_KEY', None):
                    with patch.object(bookora, 'RESEND_API_KEY', 're_test_123'):
                        self.assertEqual(bookora._get_email_provider(), 'resend')

    def test_default_fallback_to_smtp(self):
        with patch.dict('os.environ', {'EMAIL_PROVIDER': '', 'BREVO_API_KEY': '', 'RESEND_API_KEY': ''}):
            with patch.object(bookora, 'EMAIL_PROVIDER', ''):
                with patch.object(bookora, 'BREVO_API_KEY', None):
                    with patch.object(bookora, 'RESEND_API_KEY', None):
                        self.assertEqual(bookora._get_email_provider(), 'smtp')



class TestBrevoHttpTransport(unittest.TestCase):
    """Test Brevo HTTPS REST API email sending."""

    @patch('urllib.request.urlopen')
    def test_brevo_send_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        env_patch = {
            'BREVO_API_KEY': 'xkeysib-fake-key',
            'EMAIL_FROM': 'sender@example.com',
            'EMAIL_FROM_NAME': 'Bookora',
            'EMAIL_USER': 'sender@example.com',
        }
        with patch.dict('os.environ', env_patch):
            with patch.object(bookora, 'BREVO_API_KEY', 'xkeysib-fake-key'):
                with patch.object(bookora, 'EMAIL_FROM', 'sender@example.com'):
                    with patch.object(bookora, 'EMAIL_FROM_NAME', 'Bookora'):
                        result = bookora._send_email_brevo(
                            'recipient@example.com', '123456',
                            'Subject', '<p>Code: 123456</p>', 'Code: 123456'
                        )

        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, 'https://api.brevo.com/v3/smtp/email')
        self.assertEqual(req.headers.get('Api-key'), 'xkeysib-fake-key')
        self.assertEqual(req.headers.get('Content-type'), 'application/json')

        payload = json.loads(req.data.decode('utf-8'))
        self.assertEqual(payload['sender']['email'], 'sender@example.com')
        self.assertEqual(payload['sender']['name'], 'Bookora')
        self.assertEqual(payload['to'], [{'email': 'recipient@example.com'}])
        self.assertIn('123456', payload['htmlContent'])

    @patch('urllib.request.urlopen')
    def test_brevo_send_http_error(self, mock_urlopen):
        err = urllib.error.HTTPError(
            url='https://api.brevo.com/v3/smtp/email',
            code=401,
            msg='Unauthorized',
            hdrs={},
            fp=io.BytesIO(b'{"message": "Invalid API key"}')
        )
        mock_urlopen.side_effect = err

        env_patch = {
            'BREVO_API_KEY': 'bad-key',
            'EMAIL_FROM': 'sender@example.com',
            'EMAIL_USER': 'sender@example.com',
        }
        with patch.dict('os.environ', env_patch):
            with patch.object(bookora, 'BREVO_API_KEY', 'bad-key'):
                with patch.object(bookora, 'EMAIL_FROM', 'sender@example.com'):
                    result = bookora._send_email_brevo(
                        'recipient@example.com', '123456',
                        'Subject', '<p>123456</p>', '123456'
                    )

        self.assertFalse(result)


class TestResendHttpTransport(unittest.TestCase):
    """Test Resend HTTPS REST API email sending."""

    @patch('urllib.request.urlopen')
    def test_resend_send_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        env_patch = {
            'RESEND_API_KEY': 're_fake_key',
            'EMAIL_FROM': 'onboarding@resend.dev',
            'EMAIL_FROM_NAME': 'Bookora',
            'EMAIL_USER': 'onboarding@resend.dev',
        }
        with patch.dict('os.environ', env_patch):
            with patch.object(bookora, 'RESEND_API_KEY', 're_fake_key'):
                with patch.object(bookora, 'EMAIL_FROM', 'onboarding@resend.dev'):
                    with patch.object(bookora, 'EMAIL_FROM_NAME', 'Bookora'):
                        result = bookora._send_email_resend(
                            'recipient@example.com', '654321',
                            'Subject', '<p>Code: 654321</p>', 'Code: 654321'
                        )

        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, 'https://api.resend.com/emails')
        self.assertEqual(req.headers.get('Authorization'), 'Bearer re_fake_key')

        payload = json.loads(req.data.decode('utf-8'))
        self.assertEqual(payload['from'], 'Bookora <onboarding@resend.dev>')
        self.assertEqual(payload['to'], ['recipient@example.com'])
        self.assertIn('654321', payload['html'])

    @patch('urllib.request.urlopen')
    def test_resend_send_http_error(self, mock_urlopen):
        err = urllib.error.HTTPError(
            url='https://api.resend.com/emails',
            code=403,
            msg='Forbidden',
            hdrs={},
            fp=io.BytesIO(b'{"message": "Validation error"}')
        )
        mock_urlopen.side_effect = err

        env_patch = {
            'RESEND_API_KEY': 'bad-key',
            'EMAIL_FROM': 'onboarding@resend.dev',
            'EMAIL_USER': 'onboarding@resend.dev',
        }
        with patch.dict('os.environ', env_patch):
            with patch.object(bookora, 'RESEND_API_KEY', 'bad-key'):
                result = bookora._send_email_resend(
                    'recipient@example.com', '654321',
                    'Subject', '<p>654321</p>', '654321'
                )

        self.assertFalse(result)


class TestSmtpTransport(unittest.TestCase):
    """Test local fallback SMTP sending."""

    @patch('smtplib.SMTP')
    def test_smtp_send_success(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        with patch.object(bookora, 'EMAIL_USER', 'test@gmail.com'):
            with patch.object(bookora, 'EMAIL_PASSWORD', 'secret'):
                with patch.object(bookora, 'EMAIL_FROM', 'test@gmail.com'):
                    result = bookora._send_email_smtp(
                        'user@example.com', '112233',
                        'Subject', '<p>112233</p>', '112233'
                    )

        self.assertTrue(result)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with('test@gmail.com', 'secret')
        mock_server.send_message.assert_called_once()


class TestSendEmailOtpDispatcher(unittest.TestCase):
    """Test send_email_otp high-level dispatch and content."""

    @patch.object(bookora, '_send_email_brevo', return_value=True)
    def test_dispatch_to_brevo(self, mock_brevo):
        with patch.object(bookora, '_get_email_provider', return_value='brevo'):
            result = bookora.send_email_otp('user@example.com', '999888')
            self.assertTrue(result)
            mock_brevo.assert_called_once()
            args = mock_brevo.call_args[0]
            self.assertEqual(args[0], 'user@example.com')
            self.assertEqual(args[1], '999888')
            self.assertIn('999888', args[3])

    @patch.object(bookora, '_send_email_resend', return_value=True)
    def test_dispatch_to_resend(self, mock_resend):
        with patch.object(bookora, '_get_email_provider', return_value='resend'):
            result = bookora.send_email_otp('user@example.com', '777666')
            self.assertTrue(result)
            mock_resend.assert_called_once()

    @patch.object(bookora, '_send_email_smtp', return_value=True)
    def test_dispatch_to_smtp(self, mock_smtp):
        with patch.object(bookora, '_get_email_provider', return_value='smtp'):
            result = bookora.send_email_otp('user@example.com', '555444')
            self.assertTrue(result)
            mock_smtp.assert_called_once()


if __name__ == '__main__':
    unittest.main()
