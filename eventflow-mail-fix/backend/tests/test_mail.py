import contextlib
import http.cookiejar
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

spec = importlib.util.spec_from_file_location('mail_app', Path(__file__).resolve().parents[1] / 'server.py')
app = importlib.util.module_from_spec(spec)
# No .env or real credential is used by these tests.
with patch.dict(os.environ, {}, clear=True):
    spec.loader.exec_module(app)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'RESEND_API_KEY': 'test-key-not-a-credential',
            'EMAIL_FROM': 'Test <noreply@example.test>',
            'SUPPORT_EMAIL': 'support@example.test',
        }, clear=True)
        self.env.start()
        self.db = patch.object(app, 'DB_PATH', Path(self.temp.name) / 'test.sqlite3')
        self.db.start()
        app.initialize_db()
        app.RATE_LIMITS.clear()
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.AppHandler)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.config = [patch.object(app, 'BASE_URL', self.base),
                       patch.object(app, 'FRONTEND_URL', 'http://localhost:5500'),
                       patch.object(app, 'ALLOWED_ORIGINS', {self.base, 'http://localhost:5500'}),
                       patch.object(app.AppHandler, 'log_message', lambda *args: None)]
        for item in self.config: item.start()
        self.mail = patch.object(app, 'send_email')
        self.send = self.mail.start()
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.account = {'name': 'Test User', 'email': 'user@example.test',
                        'password': 'TemporaryPassword123', 'role': 'participant', 'consent': True}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.mail.stop()
        for item in reversed(self.config): item.stop()
        self.db.stop()
        self.env.stop()
        self.temp.cleanup()

    def request(self, path, data=None, method=None, headers=None, raw=None):
        payload = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
        req = Request(self.base + path, data=payload, method=method,
                      headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = self.opener.open(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            try: body = json.loads(content)
            except ValueError: body = content
            return response.code, body, response.headers

    def register(self):
        with patch('builtins.input', side_effect=AssertionError('must not prompt')):
            result = self.request('/api/auth/register', self.account)
        self.assertEqual(result[0], 201)
        return self.last_token()

    def last_token(self):
        text = self.send.call_args.args[2]
        link = next(word for word in text.split() if word.startswith('http'))
        return parse_qs(urlparse(link).query)['token'][0]

    def credentials(self):
        return {k: self.account[k] for k in ('email', 'password')}

    def test_register_verify_login_logout(self):
        token = self.register()
        with app.db_connect() as db:
            user = db.execute('SELECT * FROM users').fetchone()
            self.assertEqual(user['email_verified'], 0)
            self.assertEqual(user['verification_hash'], app.token_hash(token))
            self.assertNotEqual(user['password_hash'], self.account['password'])
        self.assertEqual(self.request('/api/auth/login', self.credentials())[1]['code'], 'email_not_verified')
        status, _, headers = self.request('/api/auth/verify?token=' + token)
        self.assertEqual(status, 302)
        self.assertEqual(headers['Location'], 'http://localhost:5500/login.html?verified=1')
        self.assertEqual(self.request('/api/auth/verify?token=' + token)[0], 400)
        self.assertEqual(self.request('/api/auth/login', self.credentials())[0], 200)
        status, body, _ = self.request('/api/auth/me')
        self.assertEqual(status, 200)
        self.assertTrue(body['user']['emailVerified'])
        self.assertNotIn('password_hash', body['user'])
        self.assertEqual(self.request('/api/auth/logout', {})[0], 200)
        self.assertEqual(self.request('/api/auth/me')[0], 401)

    def test_unconfigured_registration_creates_no_account(self):
        os.environ.pop('RESEND_API_KEY')
        self.assertEqual(self.request('/api/auth/register', self.account)[0], 503)
        with app.db_connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 0)
        self.send.assert_not_called()

    def test_delivery_failure_can_be_recovered_by_resend(self):
        self.send.side_effect = RuntimeError('provider offline')
        result = self.request('/api/auth/register', self.account)
        self.assertEqual(result[0], 503)
        self.assertEqual(result[1]['code'], 'verification_delivery_failed')
        self.assertEqual(self.request('/api/auth/login', self.credentials())[0], 403)
        self.send.side_effect = None
        self.assertEqual(self.request('/api/auth/resend-verification', self.credentials())[0], 200)
        self.assertEqual(self.request('/api/auth/verify?token=' + self.last_token())[0], 302)

    def test_resend_rotates_token_and_limits_rate(self):
        original = self.register()
        self.assertEqual(self.request('/api/auth/resend-verification', self.credentials())[0], 200)
        replacement = self.last_token()
        self.assertNotEqual(original, replacement)
        self.assertEqual(self.request('/api/auth/verify?token=' + original)[0], 400)
        self.assertEqual(self.request('/api/auth/resend-verification', self.credentials())[0], 429)
        self.assertEqual(self.request('/api/auth/verify?token=' + replacement)[0], 302)

    def test_resend_requires_correct_password(self):
        original = self.register()
        credentials = {**self.credentials(), 'password': 'incorrect'}
        self.assertEqual(self.request('/api/auth/resend-verification', credentials)[0], 401)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.request('/api/auth/verify?token=' + original)[0], 302)

    def test_expired_token_is_rejected(self):
        token = self.register()
        with app.db_connect() as db:
            db.execute('UPDATE users SET verification_expires = ?', ((app.now_utc() - timedelta(days=1)).isoformat(),))
        self.assertEqual(self.request('/api/auth/verify?token=' + token)[0], 400)
        self.assertEqual(self.request('/api/auth/login', self.credentials())[0], 403)

    def test_duplicate_registration(self):
        self.register()
        self.assertEqual(self.request('/api/auth/register', self.account)[0], 409)
        self.assertEqual(self.send.call_count, 1)

    def test_allowed_and_disallowed_origins(self):
        status, _, headers = self.request('/api/auth/login', method='OPTIONS', headers={'Origin': 'http://localhost:5500'})
        self.assertEqual(status, 204)
        self.assertEqual(headers['Access-Control-Allow-Origin'], 'http://localhost:5500')
        self.assertEqual(headers['Access-Control-Allow-Credentials'], 'true')
        status, _, headers = self.request('/api/auth/login', {}, headers={'Origin': 'https://untrusted.example'})
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get('Access-Control-Allow-Origin'))

    def test_support_requires_complete_configuration(self):
        os.environ.pop('EMAIL_FROM')
        self.assertEqual(self.request('/api/support', {'email': 'user@example.test', 'message': 'Test message'})[0], 503)
        self.send.assert_not_called()

    def test_support_provider_failure_is_not_success(self):
        self.send.side_effect = RuntimeError('provider offline')
        self.assertEqual(self.request('/api/support', {'email': 'user@example.test', 'message': 'Test message'})[0], 503)

    def test_support_reply_to_and_html_escape(self):
        result = self.request('/api/support', {'email': 'user@example.test', 'message': '<script>test</script>'})
        self.assertEqual(result[0], 200)
        self.assertEqual(self.send.call_args.kwargs['reply_to'], 'user@example.test')
        self.assertNotIn('<script>', self.send.call_args.args[3])

    def test_invalid_request_and_body_limit(self):
        self.assertEqual(self.request('/api/auth/register', raw=b'not json')[0], 400)
        self.assertEqual(self.request('/api/auth/register', raw=b' ' * (app.MAX_BODY + 1))[0], 413)

    def test_existing_verified_account_is_preserved(self):
        self.register()
        with app.db_connect() as db:
            db.execute('UPDATE users SET email_verified = 1')
        app.initialize_db()
        self.assertEqual(self.request('/api/auth/login', self.credentials())[0], 200)

class ProviderTests(unittest.TestCase):
    def test_missing_credentials_cannot_pretend_to_send(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                app.send_email('user@example.test', 'Test', 'Test', '<p>Test</p>')

    def test_provider_payload_and_acceptance(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"id":"test-message-id"}'
        with patch.dict(os.environ, {'RESEND_API_KEY': 'fake-test-key', 'EMAIL_FROM': 'sender@example.test'}, clear=True):
            with patch.object(app, 'urlopen', return_value=Response()) as call:
                app.send_email('user@example.test', 'Subject', 'Text', '<p>Text</p>', reply_to='reply@example.test')
                req = call.call_args.args[0]
                self.assertEqual(req.full_url, 'https://api.resend.com/emails')
                self.assertEqual(json.loads(req.data)['reply_to'], 'reply@example.test')
                self.assertEqual(call.call_args.kwargs['timeout'], 15)

    def test_provider_network_failure(self):
        with patch.dict(os.environ, {'RESEND_API_KEY': 'fake-test-key', 'EMAIL_FROM': 'sender@example.test'}, clear=True):
            with patch.object(app, 'urlopen', side_effect=URLError('offline')):
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(RuntimeError):
                        app.send_email('user@example.test', 'Subject', 'Text', '<p>Text</p>')

if __name__ == '__main__':
    unittest.main()
