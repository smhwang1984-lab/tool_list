# -*- coding: utf-8 -*-
"""v2.2.9 서버 라이선스(로컬 겸용) 테스트.

- sumpath_license.py 의 서버 라이선스/사용권 검증, 클라이언트 설정·캐시, ensure_license 판정 순서
- license_server/core.py 의 좌석·차단·자동 회수·라이선스 교체
- license_server/app.py 를 실제 uvicorn 으로 띄워 앱의 urllib 요청까지 왕복

실제 %PROGRAMDATA%, 실제 서명 키, 레지스트리는 건드리지 않는다(임시 폴더·테스트 키로 바꿔치기).
"""
import base64
import importlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'license_server'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sumpath_license as lic

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    CRYPTO_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    CRYPTO_IMPORT_ERROR = error

if str(SERVER_DIR) not in sys.path:
    sys.path.append(str(SERVER_DIR))
try:
    import core as server_core
    CORE_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    server_core = None
    CORE_IMPORT_ERROR = error

PC = 'AAAA-BBBB-CCCC-DDDD'


def _raw(private_key):
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )


def _sign(data, private_key):
    signed = dict(data)
    signed['signature'] = base64.b64encode(private_key.sign(lic.canonical_payload(data))).decode('ascii')
    return signed


def _server_license(private_key, server_id, seats=2, plan_days=365, starts=date(2026, 11, 1),
                    issued_at='2026-11-01T09:00:00', **overrides):
    data = {
        'format': 1, 'product': 'SumPath', 'kind': 'server',
        'license_id': 'srv-%s' % issued_at, 'licensee': '테크스타 생산부',
        'server_id': server_id, 'seats': seats, 'plan_days': plan_days,
        'starts': starts.isoformat(),
        'valid_until': None if plan_days == 0 else lic.compute_valid_until(starts, plan_days).isoformat(),
        'issued_at': issued_at, 'memo': '',
    }
    data.update(overrides)
    return _sign(data, private_key)


class SharedModuleCopyTests(unittest.TestCase):
    def test_server_copy_is_byte_identical(self):
        self.assertEqual(
            (ROOT / 'sumpath_license.py').read_bytes(),
            (SERVER_DIR / 'sumpath_license.py').read_bytes(),
            'license_server/sumpath_license.py 를 루트 파일과 같게 복사하세요.',
        )


class UrlTests(unittest.TestCase):
    def test_normalize_server_url(self):
        self.assertEqual(lic.normalize_server_url('192.168.0.210'), 'http://192.168.0.210:8765')
        self.assertEqual(lic.normalize_server_url(' http://nas:9000/ '), 'http://nas:9000')
        self.assertEqual(lic.normalize_server_url('HTTP://nas'), 'http://nas:8765')
        self.assertEqual(lic.normalize_server_url(''), '')

    def test_server_id_is_stable_and_formatted(self):
        a = lic.server_id_from_public_key('ab' * 32)
        self.assertEqual(a, lic.server_id_from_public_key('AB' * 32))
        self.assertRegex(a, r'^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$')
        self.assertNotEqual(a, lic.server_id_from_public_key('cd' * 32))


@unittest.skipIf(CRYPTO_IMPORT_ERROR or CORE_IMPORT_ERROR, 'cryptography/license_server 를 불러올 수 없음')
class ServerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.issuer = Ed25519PrivateKey.generate()
        saved = {name: getattr(lic, name) for name in (
            'LICENSE_PUBLIC_KEY', 'license_dir', 'machine_code', 'read_registry_trial_started',
            'write_registry_trial_started', 'bundled_license_path', 'request_lease',
        )}

        def restore():
            for name, value in saved.items():
                setattr(lic, name, value)
        self.addCleanup(restore)
        self._orig_machine_code = saved['machine_code']
        lic.LICENSE_PUBLIC_KEY = _raw(self.issuer)
        self.program_data = Path(self.tmp.name) / 'ProgramData'
        lic.license_dir = lambda: self.program_data
        lic.bundled_license_path = lambda: Path(self.tmp.name) / 'exe' / 'license.lic'
        self.registry = {'value': None}
        lic.read_registry_trial_started = lambda: self.registry['value']
        lic.write_registry_trial_started = lambda d: self.registry.__setitem__('value', d)
        orig_code = saved['machine_code']
        lic.machine_code = lambda guid=None: PC if guid is None else orig_code(guid)
        old_env = os.environ.pop(lic.LICENSE_SERVER_ENV, None)
        if old_env is not None:
            self.addCleanup(os.environ.__setitem__, lic.LICENSE_SERVER_ENV, old_env)
        self.clock = {'now': datetime(2026, 11, 5, 9, 0, 0).astimezone()}
        self.server = server_core.LicenseServer(
            Path(self.tmp.name) / 'data', lease_days=7, seat_idle_days=30,
            now_fn=lambda: self.clock['now'],
        )

    def install(self, **kwargs):
        text = json.dumps(_server_license(self.issuer, self.server.server_id, **kwargs), ensure_ascii=False)
        return self.server.install_license(text)

    def connect_client_directly(self):
        """앱의 HTTP 요청을 서버 객체 호출로 바꿔치기한다(네트워크 없이)."""
        calls = {'n': 0, 'down': False}

        def fake_request(url, machine, client_info=None, timeout=None):
            calls['n'] += 1
            if calls['down']:
                raise lic.LicenseServerUnavailable('down')
            return json.loads(json.dumps(self.server.lease(machine, 'PC-1', '127.0.0.1',
                                                           (client_info or {}).get('app_version', ''))))
        lic.request_lease = fake_request
        return calls


class ServerLicenseVerifyTests(ServerTestBase):
    def test_valid_and_tampered_and_wrong_server(self):
        data = _server_license(self.issuer, 'AAAA-AAAA-AAAA-AAAA', seats=3)
        ok = lic.verify_server_license(data, server_id='aaaa aaaa aaaa aaaa', today=date(2026, 11, 5))
        self.assertTrue(ok.ok)
        self.assertEqual(ok.source, 'server')
        tampered = dict(data, seats=99)
        self.assertEqual(lic.verify_server_license(tampered, today=date(2026, 11, 5)).reason, 'tampered')
        self.assertEqual(lic.verify_server_license(data, server_id='BBBB-BBBB-BBBB-BBBB',
                                                   today=date(2026, 11, 5)).reason, 'wrong_server')

    def test_zero_seats_and_expired(self):
        self.assertEqual(lic.verify_server_license(
            _server_license(self.issuer, 'AAAA-AAAA-AAAA-AAAA', seats=0)).reason, 'invalid_format')
        expired = _server_license(self.issuer, 'AAAA-AAAA-AAAA-AAAA', starts=date(2025, 1, 1))
        self.assertEqual(lic.verify_server_license(expired, today=date(2026, 11, 5)).reason, 'expired')
        perpetual = _server_license(self.issuer, 'AAAA-AAAA-AAAA-AAAA', plan_days=0)
        status = lic.verify_server_license(perpetual, today=date(2030, 1, 1))
        self.assertTrue(status.ok)
        self.assertIsNone(status.days_left)

    def test_server_license_is_not_a_local_license(self):
        data = _server_license(self.issuer, 'AAAA-AAAA-AAAA-AAAA')
        self.assertFalse(lic.verify_license(data, machine=PC).ok)
        path = Path(self.tmp.name) / 'srv.lic'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        outcome = lic.register_license_file(path)
        self.assertEqual(outcome.reason, 'server_license_file')
        self.assertFalse(lic.license_file_path().exists())


class LicenseServerCoreTests(ServerTestBase):
    def test_unlicensed_server_denies(self):
        reply = self.server.lease(PC)
        self.assertFalse(reply['ok'])
        self.assertEqual(reply['reason'], 'server_unlicensed')
        self.assertIn(self.server.server_id, reply['message'])

    def test_key_and_server_id_persist_across_restart(self):
        again = server_core.LicenseServer(self.server.data_dir)
        self.assertEqual(again.server_id, self.server.server_id)
        self.assertEqual(again.admin_token, self.server.admin_token)
        self.assertTrue(self.server.check_admin_token(self.server.admin_token))
        self.assertFalse(self.server.check_admin_token('wrong'))
        self.assertFalse(self.server.check_admin_token(''))

    def test_lease_chain_verifies_on_client(self):
        self.assertTrue(self.install(seats=2)['ok'])
        reply = self.server.lease(PC, 'PC-1')
        self.assertTrue(reply['ok'])
        status = lic.verify_lease(reply['lease'], reply['server_license'], machine=PC, now=self.clock['now'])
        self.assertTrue(status.ok, status.message)
        self.assertEqual(status.source, 'server')
        # 다른 PC에서 같은 사용권을 쓰면 거부
        self.assertEqual(lic.verify_lease(reply['lease'], reply['server_license'], machine='ZZZZ-ZZZZ-ZZZZ-ZZZZ',
                                          now=self.clock['now']).reason, 'wrong_machine')
        # 사용권 기한(7일) 뒤에는 만료
        later = self.clock['now'] + timedelta(days=7, minutes=1)
        self.assertEqual(lic.verify_lease(reply['lease'], reply['server_license'], machine=PC, now=later).reason,
                         'lease_expired')
        # 사용권을 고치면(기한 연장) 서명이 깨진다
        forged = dict(reply['lease'], lease_until='2099-01-01T00:00:00+09:00')
        self.assertEqual(lic.verify_lease(forged, reply['server_license'], machine=PC, now=self.clock['now']).reason,
                         'lease_invalid')

    def test_lease_signed_by_other_server_is_rejected(self):
        self.install(seats=2)
        reply = self.server.lease(PC)
        other = server_core.LicenseServer(Path(self.tmp.name) / 'other', now_fn=lambda: self.clock['now'])
        other.license_path.write_text(json.dumps(reply['server_license']), encoding='utf-8')
        # 다른 서버 키로 서명한 사용권(같은 서버 라이선스를 복사해 와도) → server_id 불일치
        forged = other._sign({k: v for k, v in dict(reply['lease'], server_key=other.server_key_hex).items()
                              if k != 'signature'})
        self.assertEqual(lic.verify_lease(forged, reply['server_license'], machine=PC, now=self.clock['now']).reason,
                         'lease_invalid')

    def test_lease_until_is_capped_by_license_end(self):
        self.install(seats=1, plan_days=365, starts=date(2025, 11, 9))  # 사용 기한 2026-11-08
        reply = self.server.lease(PC)
        self.assertTrue(reply['ok'])
        self.assertTrue(reply['lease']['lease_until'].startswith('2026-11-08T23:59:59'))

    def test_seat_limit_block_release_and_idle_reclaim(self):
        self.install(seats=2)
        self.assertTrue(self.server.lease('AAAA-AAAA-AAAA-AAAA')['ok'])
        self.assertTrue(self.server.lease('BBBB-BBBB-BBBB-BBBB')['ok'])
        third = self.server.lease('CCCC-CCCC-CCCC-CCCC')
        self.assertEqual(third['reason'], 'no_seats')
        # 이미 등록된 PC는 계속 갱신된다
        self.assertTrue(self.server.lease('AAAA-AAAA-AAAA-AAAA')['ok'])
        # 좌석 해제 → 새 PC 등록 가능
        self.assertTrue(self.server.set_device('BBBB-BBBB-BBBB-BBBB', 'release')['ok'])
        self.assertTrue(self.server.lease('CCCC-CCCC-CCCC-CCCC')['ok'])
        # 차단 → 거부, 좌석 수에서 빠진다
        self.server.set_device('CCCC-CCCC-CCCC-CCCC', 'block')
        self.assertEqual(self.server.lease('CCCC-CCCC-CCCC-CCCC')['reason'], 'device_blocked')
        self.assertTrue(self.server.lease('DDDD-DDDD-DDDD-DDDD')['ok'])
        self.assertEqual(self.server.info()['seats_used'], 2)
        # 31일 동안 AAAA만 접속 → DDDD는 회수되고 새 PC가 들어온다
        self.clock['now'] += timedelta(days=31)
        self.assertTrue(self.server.lease('AAAA-AAAA-AAAA-AAAA')['ok'])
        self.assertTrue(self.server.lease('EEEE-EEEE-EEEE-EEEE')['ok'])
        machines = {d['machine']: d['status'] for d in self.server.devices()}
        self.assertNotIn('DDDDDDDDDDDDDDDD', machines)
        self.assertEqual(machines['AAAAAAAAAAAAAAAA'], 'active')
        self.assertEqual(machines['CCCCCCCCCCCCCCCC'], 'blocked')
        actions = [e['action'] for e in self.server.events()]
        self.assertIn('auto_reclaimed', actions)
        # 차단 해제
        self.server.set_device('CCCC-CCCC-CCCC-CCCC', 'unblock')
        self.assertEqual(self.server.lease('CCCC-CCCC-CCCC-CCCC')['reason'], 'no_seats')

    def test_idle_days_never_shorter_than_lease(self):
        srv = server_core.LicenseServer(Path(self.tmp.name) / 'd2', lease_days=10, seat_idle_days=3)
        self.assertEqual(srv.seat_idle_days, 11)

    def test_install_rejects_wrong_server_tampered_and_older(self):
        wrong = _server_license(self.issuer, 'AAAA-AAAA-AAAA-AAAA')
        self.assertEqual(self.server.install_license(json.dumps(wrong))['reason'], 'wrong_server')
        self.assertFalse(self.server.install_license('not json')['ok'])
        self.assertTrue(self.install(issued_at='2026-11-02T09:00:00')['ok'])
        older = self.install(issued_at='2026-11-01T09:00:00')
        self.assertEqual(older['reason'], 'older_license')
        newer = self.install(issued_at='2026-11-03T09:00:00', seats=5)
        self.assertTrue(newer['ok'])
        self.assertEqual(self.server.info()['seats'], 5)


class ClientHybridTests(ServerTestBase):
    def test_server_mode_then_offline_then_denied(self):
        self.install(seats=1)
        calls = self.connect_client_directly()
        status = lic.connect_license_server('nas.local', now=self.clock['now'].replace(tzinfo=None))
        self.assertTrue(status.ok, status.message)
        self.assertEqual(lic.get_license_server_url(), 'http://nas.local:8765')

        now = datetime(2026, 11, 6, 9, 0, 0)
        status = lic.ensure_license(now=now)
        self.assertTrue(status.ok)
        self.assertEqual((status.source, status.reason), ('server', 'server'))
        self.assertIsNone(self.registry['value'], '서버 라이선스로 통과하면 체험판을 시작하지 않는다')

        # 서버 다운 → 저장된 사용권(7일)으로 통과
        calls['down'] = True
        offline = lic.ensure_license(now=datetime(2026, 11, 10, 9, 0, 0))
        self.assertTrue(offline.ok)
        self.assertEqual(offline.reason, 'server_offline')
        # 사용권 기한이 지나면 체험판으로 넘어간다(체험판이 남아 있으면)
        after = lic.ensure_license(now=datetime(2026, 11, 14, 9, 0, 0))
        self.assertTrue(after.ok)
        self.assertEqual(after.source, 'trial')

        # 서버가 살아나 거부(차단) → 사용권 캐시 삭제
        calls['down'] = False
        self.server.set_device(PC, 'block')
        denied = lic.evaluate_server_license(now=datetime(2026, 11, 14, 9, 0, 0))
        self.assertEqual(denied.reason, 'device_blocked')
        self.assertIsNone(lic.load_server_lease_cache())

    def test_local_license_wins_without_contacting_server(self):
        calls = self.connect_client_directly()
        lic.set_license_server_url('nas.local')
        starts = date(2026, 11, 1)
        local = _sign({
            'format': 1, 'product': 'SumPath', 'license_id': 'local-1', 'licensee': '개인',
            'machine': PC, 'plan_days': 365, 'starts': starts.isoformat(),
            'valid_until': lic.compute_valid_until(starts, 365).isoformat(),
            'issued_at': '2026-11-01T09:00:00', 'memo': '',
        }, self.issuer)
        lic.license_file_path().parent.mkdir(parents=True, exist_ok=True)
        lic.license_file_path().write_text(json.dumps(local, ensure_ascii=False), encoding='utf-8')
        status = lic.ensure_license(now=datetime(2026, 11, 5, 9, 0, 0))
        self.assertTrue(status.ok)
        self.assertEqual(status.source, 'local')
        self.assertEqual(calls['n'], 0)

    def test_failed_connect_keeps_previous_setting(self):
        self.connect_client_directly()
        status = lic.connect_license_server('nas.local')  # 서버 라이선스 미등록 → 거부
        self.assertFalse(status.ok)
        self.assertEqual(lic.get_license_server_url(), '')

    def test_unreachable_server_with_expired_trial_reports_server_problem(self):
        calls = self.connect_client_directly()
        calls['down'] = True
        lic.set_license_server_url('nas.local')
        self.registry['value'] = date(2026, 9, 1)  # 체험판 이미 끝남
        status = lic.ensure_license(now=datetime(2026, 11, 5, 9, 0, 0))
        self.assertFalse(status.ok)
        self.assertEqual(status.reason, 'server_unreachable')

    def test_env_and_bundled_config(self):
        bundled = lic.bundled_license_server_config_path()
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text(json.dumps({'url': '10.0.0.5'}), encoding='utf-8')
        self.assertEqual(lic.get_license_server_url(), 'http://10.0.0.5:8765')
        lic.set_license_server_url('nas.local')
        self.assertEqual(lic.get_license_server_url(), 'http://nas.local:8765')
        os.environ[lic.LICENSE_SERVER_ENV] = 'env-host:9999'
        try:
            self.assertEqual(lic.get_license_server_url(), 'http://env-host:9999')
        finally:
            del os.environ[lic.LICENSE_SERVER_ENV]
        lic.set_license_server_url('')
        self.assertFalse(lic.license_server_config_path().exists())


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


try:
    import uvicorn  # noqa: F401
    import fastapi  # noqa: F401
    HTTP_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    HTTP_IMPORT_ERROR = error


@unittest.skipIf(HTTP_IMPORT_ERROR is not None, 'fastapi/uvicorn 미설치')
class HttpRoundTripTests(ServerTestBase):
    def test_app_over_real_http(self):
        import urllib.request
        import uvicorn

        os.environ['SUMPATH_DATA_DIR'] = str(self.server.data_dir)
        os.environ['SUMPATH_ADMIN_TOKEN'] = 'test-token'
        try:
            if 'app' in sys.modules and getattr(sys.modules['app'], '__file__', '').startswith(str(SERVER_DIR)):
                server_app = importlib.reload(sys.modules['app'])
            else:
                sys.modules.pop('app', None)
                server_app = importlib.import_module('app')
        finally:
            del os.environ['SUMPATH_DATA_DIR']
            del os.environ['SUMPATH_ADMIN_TOKEN']
        self.assertEqual(server_app.server.server_id, self.server.server_id)

        port = _free_port()
        config = uvicorn.Config(server_app.app, host='127.0.0.1', port=port, log_level='warning')
        httpd = uvicorn.Server(config)
        thread = threading.Thread(target=httpd.run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, httpd, 'should_exit', True)
        deadline = time.time() + 10
        while not httpd.started and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(httpd.started)
        base = 'http://127.0.0.1:%d' % port
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def call(path, body=None, token=None):
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['X-Admin-Token'] = token
            req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers, method='POST' if body is not None else 'GET')
            try:
                with opener.open(req, timeout=5) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read())

        self.assertEqual(call('/api/v1/health')[1]['server_id'], self.server.server_id)
        self.assertEqual(call('/api/v1/admin/devices')[0], 401)
        lic_text = json.dumps(_server_license(self.issuer, self.server.server_id, seats=1), ensure_ascii=False)
        self.assertTrue(call('/api/v1/admin/license', {'text': lic_text}, token='test-token')[1]['ok'])

        # 앱 쪽 실제 urllib 경로
        status = lic.connect_license_server(base, client_info={'app_version': '2.2.9'})
        self.assertTrue(status.ok, status.message)
        code, devices = call('/api/v1/admin/devices', token='test-token')
        self.assertEqual(code, 200)
        self.assertEqual(devices['devices'][0]['app_version'], '2.2.9')
        self.assertEqual(devices['info']['seats_used'], 1)
        # 입력 크기 제한
        self.assertEqual(call('/api/v1/lease', {'machine': 'x' * 500})[0], 422)
        # 관리 화면
        with opener.open(base + '/', timeout=5) as resp:
            self.assertIn('Sum Path 라이선스 서버', resp.read().decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
