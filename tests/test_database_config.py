"""Unit tests for the Bookora database configuration layer.

Tests DATABASE_URL parsing, environment variable sanitisation, strict port validation,
SSL CA certificate resolution, and connection pool observability logging.
"""
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import mysql.connector
import app as bookora


class TestDatabaseUrlParsing(unittest.TestCase):
    """Test connection URL parsing from DATABASE_URL and MYSQL_URL."""

    def test_empty_or_none_url_returns_empty_dict(self):
        with patch.dict('os.environ', {'DATABASE_URL': '', 'MYSQL_URL': ''}, clear=False):
            self.assertEqual(bookora._parse_database_url(), {})

    def test_standard_mysql_url(self):
        url = 'mysql://avnadmin:securePass123@bookora-db-bookora2910-1.d.aivencloud.com:15053/bookora'
        with patch.dict('os.environ', {'DATABASE_URL': url, 'MYSQL_URL': ''}, clear=False):
            params = bookora._parse_database_url()
            self.assertEqual(params.get('host'), 'bookora-db-bookora2910-1.d.aivencloud.com')
            self.assertEqual(params.get('port'), 15053)
            self.assertEqual(params.get('user'), 'avnadmin')
            self.assertEqual(params.get('password'), 'securePass123')
            self.assertEqual(params.get('database'), 'bookora')

    def test_url_with_encoded_password_and_quotes(self):
        url = '"mysql://user_db:p%40ss%23word@db.example.com:3307/mydb?ssl-mode=REQUIRED"'
        with patch.dict('os.environ', {'DATABASE_URL': url, 'MYSQL_URL': ''}, clear=False):
            params = bookora._parse_database_url()
            self.assertEqual(params.get('host'), 'db.example.com')
            self.assertEqual(params.get('port'), 3307)
            self.assertEqual(params.get('user'), 'user_db')
            self.assertEqual(params.get('password'), 'p@ss#word')
            self.assertEqual(params.get('database'), 'mydb')

    def test_mysql_url_alias(self):
        url = 'mysql://clouduser:pwd@host.internal:3308/customdb'
        with patch.dict('os.environ', {'DATABASE_URL': '', 'MYSQL_URL': url}, clear=False):
            params = bookora._parse_database_url()
            self.assertEqual(params.get('host'), 'host.internal')
            self.assertEqual(params.get('port'), 3308)
            self.assertEqual(params.get('user'), 'clouduser')
            self.assertEqual(params.get('password'), 'pwd')
            self.assertEqual(params.get('database'), 'customdb')


class TestCleanEnv(unittest.TestCase):
    """Test whitespace and quote stripping from environment variables and aliases."""

    def test_strips_quotes_and_spaces(self):
        with patch.dict('os.environ', {'TEST_KEY': '  "hello-world"  '}, clear=False):
            self.assertEqual(bookora._get_clean_env('TEST_KEY'), 'hello-world')

    def test_single_quotes_stripped(self):
        with patch.dict('os.environ', {'TEST_KEY': "'some-value'"}, clear=False):
            self.assertEqual(bookora._get_clean_env('TEST_KEY'), 'some-value')

    def test_alias_resolution(self):
        with patch.dict('os.environ', {'PRIMARY_KEY': '', 'SECONDARY_KEY': 'found-via-alias'}, clear=False):
            self.assertEqual(bookora._get_clean_env('PRIMARY_KEY', ('SECONDARY_KEY',)), 'found-via-alias')

    def test_unset_returns_none(self):
        with patch.dict('os.environ', {'PRIMARY_KEY': '', 'SECONDARY_KEY': '   '}, clear=False):
            self.assertIsNone(bookora._get_clean_env('PRIMARY_KEY', ('SECONDARY_KEY',)))


class TestDbSetting(unittest.TestCase):
    """Test database setting retrieval across environment, URL, and development defaults."""

    def test_direct_env_takes_precedence(self):
        with patch.dict('os.environ', {'DB_HOST': 'custom-host.com'}, clear=False):
            val = bookora._db_setting('DB_HOST', 'localhost')
            self.assertEqual(val, 'custom-host.com')

    def test_dev_fallback_when_debug_true(self):
        with patch.object(bookora, 'DEBUG', True):
            with patch.dict('os.environ', {'NONEXISTENT_KEY': ''}, clear=False):
                val = bookora._db_setting('NONEXISTENT_KEY', 'default_val')
                self.assertEqual(val, 'default_val')

    def test_raises_when_debug_false_and_missing(self):
        with patch.object(bookora, 'DEBUG', False):
            with patch.dict('os.environ', {'NONEXISTENT_KEY': ''}, clear=False):
                with self.assertRaises(RuntimeError):
                    bookora._db_setting('NONEXISTENT_KEY', 'default_val')


class TestDbPort(unittest.TestCase):
    """Test database port validation and production enforcement."""

    def test_valid_integer_port(self):
        with patch.dict('os.environ', {'DB_PORT': '15053'}, clear=False):
            self.assertEqual(bookora._db_port(), 15053)

    def test_quoted_integer_port(self):
        with patch.dict('os.environ', {'DB_PORT': ' "15053" '}, clear=False):
            self.assertEqual(bookora._db_port(), 15053)

    def test_invalid_integer_raises(self):
        with patch.dict('os.environ', {'DB_PORT': 'not-a-number'}, clear=False):
            with self.assertRaises(RuntimeError):
                bookora._db_port()

    def test_fallback_to_3306_only_in_debug(self):
        with patch.object(bookora, 'DEBUG', True):
            with patch.dict('os.environ', {'DB_PORT': '', 'MYSQL_PORT': '', 'DATABASE_URL': '', 'MYSQL_URL': ''}, clear=False):
                with patch.object(bookora, '_PARSED_DB_URL', {}):
                    self.assertEqual(bookora._db_port(), 3306)

    def test_raises_in_production_when_port_missing(self):
        with patch.object(bookora, 'DEBUG', False):
            with patch.dict('os.environ', {'DB_PORT': '', 'MYSQL_PORT': '', 'DATABASE_URL': '', 'MYSQL_URL': ''}, clear=False):
                with patch.object(bookora, '_PARSED_DB_URL', {}):
                    with self.assertRaises(RuntimeError):
                        bookora._db_port()


class TestResolveSslCa(unittest.TestCase):
    """Test SSL CA resolution from direct PEM content, existing files, and missing files."""

    def test_direct_pem_content_writes_temp_file(self):
        pem_content = "-----BEGIN CERTIFICATE-----\\\nMIIB...\\\n-----END CERTIFICATE-----"
        with patch.dict('os.environ', {'DB_SSL_CA_CERT': pem_content, 'DB_SSL_CA': ''}, clear=False):
            path = bookora._resolve_ssl_ca()
            self.assertIsNotNone(path)
            self.assertTrue(os.path.exists(path))
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertIn('BEGIN CERTIFICATE', content)

    def test_nonexistent_ca_file_returns_none_and_does_not_crash(self):
        with patch.dict('os.environ', {'DB_SSL_CA': 'nonexistent-cert-file-xyz.pem', 'DB_SSL_CA_CERT': ''}, clear=False):
            path = bookora._resolve_ssl_ca()
            self.assertIsNone(path)


class TestPoolObservability(unittest.TestCase):
    """Test connection pool creation error logging and sensitive data masking."""

    @patch('mysql.connector.pooling.MySQLConnectionPool')
    def test_pool_creation_critical_log_on_error(self, mock_pool_cls):
        mock_pool_cls.side_effect = mysql.connector.errors.InterfaceError(errno=2003, msg="Can't connect to MySQL server")
        with patch.object(bookora, '_db_pool', None):
            with patch.object(bookora.logger, 'critical') as mock_critical:
                with self.assertRaises(mysql.connector.Error):
                    bookora._get_pool()
                mock_critical.assert_called_once()
                call_args = mock_critical.call_args[0]
                self.assertIn(bookora.DB_CONFIG['host'], call_args)
                self.assertIn(bookora.DB_CONFIG['port'], call_args)
