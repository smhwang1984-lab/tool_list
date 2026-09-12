# -*- coding: utf-8 -*-
"""
v1.8.0 라이선스 기능 테스트 — sumpath_license.py(공용 모듈), NC_Tool_List.py의
main() 진입점/등록 창/About 연동, SumPath_License_Maker.py(발급 프로그램).

기존 tests/test_nc_tool_list.py와 마찬가지로 offscreen QPA를 쓴다. 어떤
테스트도 실제 %PROGRAMDATA%\\NC Tool List 나 이 PC의 실제 서명 키를 건드리지
않는다 — 저장 위치와 공개키는 매 테스트마다 임시 값으로 바꿔치기한다.
"""
import base64
import inspect
import json
import os
import random
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import NC_Tool_List as app
import sumpath_license as lic

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    CRYPTO_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - 개발 환경엔 항상 있음
    CRYPTO_IMPORT_ERROR = error

try:
    import SumPath_License_Maker as maker
    MAKER_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - cryptography 미설치 등
    maker = None
    MAKER_IMPORT_ERROR = error


def _raw_public_key(private_key):
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )


def _sign(data, private_key):
    payload = lic.canonical_payload(data)
    signature = private_key.sign(payload)
    signed = dict(data)
    signed['signature'] = base64.b64encode(signature).decode('ascii')
    return signed


def _license_data(**overrides):
    starts = date(2026, 9, 1)
    data = {
        'format': 1,
        'product': 'SumPath',
        'license_id': 'test-license-id',
        'licensee': '생산부 1공장',
        'machine': 'AAAA-BBBB-CCCC-DDDD',
        'plan_days': 30,
        'starts': starts.isoformat(),
        'valid_until': lic.compute_valid_until(starts, 30).isoformat(),
        'issued_at': '2026-09-01T09:00:00',
        'memo': '',
    }
    data.update(overrides)
    return data


@unittest.skipIf(CRYPTO_IMPORT_ERROR is not None, 'cryptography가 설치되어 있지 않음')
class Ed25519VerifyTests(unittest.TestCase):
    """순수 파이썬 검증기를 cryptography가 만든 서명으로 교차 검증한다
    (v1.8.0_PLAN.md 결정 F — 앱은 cryptography 없이 검증만 한다)."""

    def test_cross_checked_signatures_verify_and_tampering_is_rejected(self):
        random.seed(20260912)
        for _ in range(15):
            private_key = Ed25519PrivateKey.generate()
            public_key = _raw_public_key(private_key)
            message = os.urandom(random.randint(0, 300))
            signature = private_key.sign(message)

            self.assertTrue(lic.verify_signature(message, signature, public_key))

            if message:
                tampered_message = bytearray(message)
                tampered_message[0] ^= 0xFF
                self.assertFalse(
                    lic.verify_signature(bytes(tampered_message), signature, public_key)
                )

            tampered_sig = bytearray(signature)
            tampered_sig[0] ^= 0xFF
            self.assertFalse(lic.verify_signature(message, bytes(tampered_sig), public_key))

    def test_wrong_public_key_is_rejected(self):
        key_a = Ed25519PrivateKey.generate()
        key_b = Ed25519PrivateKey.generate()
        message = b'sumpath license payload'
        signature = key_a.sign(message)
        self.assertTrue(lic.verify_signature(message, signature, _raw_public_key(key_a)))
        self.assertFalse(lic.verify_signature(message, signature, _raw_public_key(key_b)))

    def test_malformed_inputs_do_not_raise(self):
        self.assertFalse(lic.verify_signature(b'x', b'too-short', b'also-short'))
        self.assertFalse(lic.verify_signature(b'', b'', b''))
        self.assertFalse(lic.verify_signature(b'x' * 10, b'\x00' * 64, b'\x00' * 10))


class LicensePeriodTests(unittest.TestCase):
    def test_compute_valid_until_for_each_plan(self):
        starts = date(2026, 9, 12)
        expected = {
            7: date(2026, 9, 18),
            30: date(2026, 10, 11),
            365: date(2027, 9, 11),
            1095: date(2029, 9, 10),
        }
        for plan_days, expected_until in expected.items():
            with self.subTest(plan_days=plan_days):
                self.assertEqual(lic.compute_valid_until(starts, plan_days), expected_until)

    def test_compute_valid_until_spans_leap_year(self):
        # 2028년은 윤년(2028-02-29 존재) — 2027-09-01부터 2028-09-01까지는
        # 366일이므로, 364일을 더한(=365일째 되는 날) 사용 기한은 그 하루 전인
        # 2028-08-31이 아니라 이틀 전(2028-08-30)이 된다.
        starts = date(2027, 9, 1)
        self.assertEqual(lic.compute_valid_until(starts, 365), date(2028, 8, 30))

    def test_compute_valid_until_accepts_string_start_date(self):
        self.assertEqual(lic.compute_valid_until('2026-09-12', 7), date(2026, 9, 18))

    def test_plan_label_known_and_unknown(self):
        self.assertEqual(lic.plan_label(365), '1년 (365일)')
        self.assertEqual(lic.plan_label(1095), '3년')
        self.assertEqual(lic.plan_label(999), '999일')


class MachineCodeTests(unittest.TestCase):
    def test_machine_code_is_deterministic_and_formatted(self):
        code1 = lic.machine_code(guid='11111111-2222-3333-4444-555555555555')
        code2 = lic.machine_code(guid='11111111-2222-3333-4444-555555555555')
        self.assertEqual(code1, code2)
        self.assertRegex(code1, r'^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$')
        for confusing in '01OI':
            self.assertNotIn(confusing, code1)

    def test_machine_code_differs_for_different_guids(self):
        code1 = lic.machine_code(guid='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        code2 = lic.machine_code(guid='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')
        self.assertNotEqual(code1, code2)

    def test_machine_code_none_when_guid_missing(self):
        self.assertIsNone(lic.machine_code(guid=''))
        original_guid_fn = lic.machine_guid
        lic.machine_guid = lambda: None
        try:
            self.assertIsNone(lic.machine_code())
        finally:
            lic.machine_guid = original_guid_fn

    def test_normalize_machine_code_ignores_case_and_separators(self):
        self.assertEqual(
            lic.normalize_machine_code('aaaa-bbbb-cccc-dddd'),
            lic.normalize_machine_code(' AAAA bbbb-CCCC_dddd '),
        )


@unittest.skipIf(CRYPTO_IMPORT_ERROR is not None, 'cryptography가 설치되어 있지 않음')
class LicenseVerifyTamperTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        self._orig_pubkey = lic.LICENSE_PUBLIC_KEY
        lic.LICENSE_PUBLIC_KEY = _raw_public_key(self.private_key)
        self.addCleanup(self._restore_pubkey)

    def _restore_pubkey(self):
        lic.LICENSE_PUBLIC_KEY = self._orig_pubkey

    def _signed(self, **overrides):
        return _sign(_license_data(**overrides), self.private_key)

    def test_valid_license_passes(self):
        data = self._signed()
        status = lic.verify_license(data, machine='AAAA-BBBB-CCCC-DDDD', today=date(2026, 9, 12))
        self.assertTrue(status.ok)
        self.assertEqual(status.reason, 'ok')
        # starts=2026-09-01, plan_days=30 -> valid_until=2026-09-30; 2026-09-12 기준 남은 18일.
        self.assertEqual(status.days_left, 18)

    def test_tampering_any_signed_field_breaks_signature(self):
        base = self._signed()
        for field, new_value in (
            ('valid_until', '2099-01-01'),
            ('machine', 'ZZZZ-ZZZZ-ZZZZ-ZZZZ'),
            ('licensee', '변조된 이름'),
            ('plan_days', 365),
        ):
            with self.subTest(field=field):
                tampered = dict(base)
                tampered[field] = new_value
                status = lic.verify_license(tampered, today=date(2026, 9, 12))
                self.assertFalse(status.ok)
                self.assertEqual(status.reason, 'tampered')

    def test_missing_required_field_is_invalid_format(self):
        data = self._signed()
        del data['license_id']
        status = lic.verify_license(data)
        self.assertFalse(status.ok)
        self.assertEqual(status.reason, 'invalid_format')

    def test_wrong_product_or_format_is_invalid_format(self):
        for field, value in (('product', 'OtherApp'), ('format', 2)):
            with self.subTest(field=field):
                data = self._signed(**{field: value})
                status = lic.verify_license(data)
                self.assertFalse(status.ok)
                self.assertEqual(status.reason, 'invalid_format')

    def test_wrong_machine_is_rejected(self):
        data = self._signed()
        status = lic.verify_license(data, machine='ZZZZ-ZZZZ-ZZZZ-ZZZZ', today=date(2026, 9, 12))
        self.assertFalse(status.ok)
        self.assertEqual(status.reason, 'wrong_machine')

    def test_machine_check_is_case_and_separator_insensitive(self):
        data = self._signed()
        status = lic.verify_license(data, machine='aaaa bbbb-cccc_dddd', today=date(2026, 9, 12))
        self.assertTrue(status.ok)

    def test_not_started_and_expired(self):
        data = self._signed()
        before = lic.verify_license(data, today=date(2026, 8, 1))
        self.assertFalse(before.ok)
        self.assertEqual(before.reason, 'not_started')

        after = lic.verify_license(data, today=date(2026, 12, 1))
        self.assertFalse(after.ok)
        self.assertEqual(after.reason, 'expired')
        self.assertLess(after.days_left, 0)

    def test_last_day_of_validity_still_passes(self):
        data = self._signed()
        status = lic.verify_license(data, today=date(2026, 9, 30))
        self.assertTrue(status.ok)
        self.assertEqual(status.days_left, 0)

    def test_korean_licensee_roundtrips_through_canonical_payload(self):
        data = self._signed(licensee='한글 사용자 이름 テスト')
        status = lic.verify_license(data, today=date(2026, 9, 12))
        self.assertTrue(status.ok)

    def test_malformed_signature_field_is_tampered(self):
        data = self._signed()
        data['signature'] = 'not-base64!!'
        status = lic.verify_license(data)
        self.assertFalse(status.ok)
        self.assertEqual(status.reason, 'tampered')

    def test_not_a_dict_is_invalid_format(self):
        status = lic.verify_license('not a dict')
        self.assertFalse(status.ok)
        self.assertEqual(status.reason, 'invalid_format')

    def test_inconsistent_valid_until_is_invalid_format(self):
        # 서명은 맞지만(발급 쪽 버그를 가정) plan_days와 valid_until이 어긋난 경우.
        data = _license_data(valid_until='2099-01-01')
        signed = _sign(data, self.private_key)
        status = lic.verify_license(signed, today=date(2026, 9, 12))
        self.assertFalse(status.ok)
        self.assertEqual(status.reason, 'invalid_format')


class ExpiryNoticeTests(unittest.TestCase):
    def test_notice_due_within_seven_days_for_normal_plan(self):
        data = {'plan_days': 30}
        self.assertTrue(lic.is_expiry_notice_due(data, 7))
        self.assertTrue(lic.is_expiry_notice_due(data, 0))
        self.assertFalse(lic.is_expiry_notice_due(data, 8))

    def test_notice_due_within_two_days_for_short_plan(self):
        data = {'plan_days': 7}
        self.assertTrue(lic.is_expiry_notice_due(data, 2))
        self.assertFalse(lic.is_expiry_notice_due(data, 3))

    def test_no_notice_once_expired_or_when_days_left_unknown(self):
        self.assertFalse(lic.is_expiry_notice_due({'plan_days': 30}, -1))
        self.assertFalse(lic.is_expiry_notice_due(None, None))


class ClockRollbackTests(unittest.TestCase):
    def test_rollback_beyond_tolerance_from_last_seen_is_detected(self):
        now = datetime(2026, 9, 12, 12, 0, 0)
        state = {'last_seen': (now + timedelta(hours=25)).isoformat()}
        self.assertTrue(lic.clock_rollback_detected(now, state, None))

    def test_rollback_within_tolerance_is_ok(self):
        now = datetime(2026, 9, 12, 12, 0, 0)
        state = {'last_seen': (now + timedelta(hours=23)).isoformat()}
        self.assertFalse(lic.clock_rollback_detected(now, state, None))

    def test_rollback_beyond_tolerance_from_issued_at_is_detected(self):
        now = datetime(2026, 9, 12, 12, 0, 0)
        license_data = {'issued_at': (now + timedelta(hours=25)).isoformat()}
        self.assertTrue(lic.clock_rollback_detected(now, {}, license_data))

    def test_missing_or_corrupt_state_never_raises(self):
        now = datetime(2026, 9, 12, 12, 0, 0)
        self.assertFalse(lic.clock_rollback_detected(now, {}, None))
        self.assertFalse(lic.clock_rollback_detected(now, {'last_seen': 'garbage'}, None))
        self.assertFalse(lic.clock_rollback_detected(now, None, None))


@unittest.skipIf(CRYPTO_IMPORT_ERROR is not None, 'cryptography가 설치되어 있지 않음')
class LicenseStorageTests(unittest.TestCase):
    """실제 %PROGRAMDATA%를 건드리지 않도록 저장 위치 함수를 임시 경로로
    바꿔치기한다(기존 테스트가 app.QSettings를 바꿔치기하는 것과 같은 방식)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.program_data = Path(self.tmp.name) / 'programdata' / 'NC Tool List'
        self.bundled_path = Path(self.tmp.name) / 'exe_dir' / 'license.lic'

        self._orig_license_dir = lic.license_dir
        self._orig_bundled = lic.bundled_license_path
        self._orig_pubkey = lic.LICENSE_PUBLIC_KEY
        self._orig_machine_code = lic.machine_code

        lic.license_dir = lambda: self.program_data
        lic.bundled_license_path = lambda: self.bundled_path
        # 실제 이 PC의 MachineGuid와 무관하게, 라이선스 픽스처의 machine
        # 필드('AAAA-BBBB-CCCC-DDDD')와 항상 일치하도록 고정한다 — 그렇지
        # 않으면 이 개발 PC에서 wrong_machine으로 엉뚱하게 실패한다.
        lic.machine_code = lambda guid=None: 'AAAA-BBBB-CCCC-DDDD'

        self.private_key = Ed25519PrivateKey.generate()
        lic.LICENSE_PUBLIC_KEY = _raw_public_key(self.private_key)

        self.addCleanup(self._restore)

    def _restore(self):
        lic.license_dir = self._orig_license_dir
        lic.bundled_license_path = self._orig_bundled
        lic.LICENSE_PUBLIC_KEY = self._orig_pubkey
        lic.machine_code = self._orig_machine_code

    def _write_license(self, path, **overrides):
        data = _sign(_license_data(**overrides), self.private_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return data

    def test_find_license_file_returns_none_when_absent(self):
        self.assertIsNone(lic.find_license_file())
        status = lic.ensure_license()
        self.assertFalse(status.ok)
        self.assertEqual(status.reason, 'missing')

    def test_find_license_file_falls_back_to_bundled_path(self):
        self._write_license(self.bundled_path)
        self.assertEqual(lic.find_license_file(), self.bundled_path)

    def test_find_license_file_prefers_program_data(self):
        primary = self.program_data / 'license.lic'
        self._write_license(primary)
        self._write_license(self.bundled_path)
        self.assertEqual(lic.find_license_file(), primary)

    def test_ensure_license_updates_last_seen_state_on_success(self):
        self._write_license(self.program_data / 'license.lic')
        now = datetime(2026, 9, 12, 10, 0, 0)
        status = lic.ensure_license(now=now)
        self.assertTrue(status.ok)
        state = lic.load_license_state()
        self.assertEqual(state.get('last_seen'), now.isoformat(timespec='seconds'))

    def test_ensure_license_detects_clock_rollback(self):
        self._write_license(self.program_data / 'license.lic')
        lic.ensure_license(now=datetime(2026, 9, 12, 10, 0, 0))
        rolled_back = lic.ensure_license(now=datetime(2026, 9, 10, 0, 0, 0))
        self.assertFalse(rolled_back.ok)
        self.assertEqual(rolled_back.reason, 'clock_rollback')

    def test_register_license_file_copies_valid_file_and_rejects_invalid(self):
        source = Path(self.tmp.name) / 'incoming.lic'
        self._write_license(source)
        outcome = lic.register_license_file(source, now=datetime(2026, 9, 12, 10, 0, 0))
        self.assertTrue(outcome.ok)
        self.assertTrue(lic.license_file_path().is_file())

        bad_source = Path(self.tmp.name) / 'bad.lic'
        bad_source.write_text('not json', encoding='utf-8')
        bad_outcome = lic.register_license_file(bad_source)
        self.assertFalse(bad_outcome.ok)
        self.assertEqual(bad_outcome.reason, 'invalid_format')


@unittest.skipIf(CRYPTO_IMPORT_ERROR is not None, 'cryptography가 설치되어 있지 않음')
class LicenseRegistrationDialogUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.program_data = Path(self.tmp.name) / 'programdata' / 'NC Tool List'

        self._orig_license_dir = lic.license_dir
        self._orig_bundled = lic.bundled_license_path
        self._orig_pubkey = lic.LICENSE_PUBLIC_KEY
        self._orig_machine_code = lic.machine_code
        self._orig_open_dialog = app.QFileDialog.getOpenFileName

        lic.license_dir = lambda: self.program_data
        lic.bundled_license_path = lambda: Path(self.tmp.name) / 'no_such_dir' / 'license.lic'
        # 등록 창의 [등록] 버튼이 register_license_file()을 부를 때도 이
        # 개발 PC의 실제 MachineGuid가 아니라 픽스처의 machine 값과 맞도록
        # 고정한다(그렇지 않으면 유효한 파일도 wrong_machine으로 거부되어
        # dialog.accept()가 불리지 않고 exec_()가 영원히 멈춘다).
        lic.machine_code = lambda guid=None: 'AAAA-BBBB-CCCC-DDDD'

        self.private_key = Ed25519PrivateKey.generate()
        lic.LICENSE_PUBLIC_KEY = _raw_public_key(self.private_key)

        self.addCleanup(self._restore)

    def _restore(self):
        lic.license_dir = self._orig_license_dir
        lic.bundled_license_path = self._orig_bundled
        lic.LICENSE_PUBLIC_KEY = self._orig_pubkey
        lic.machine_code = self._orig_machine_code
        app.QFileDialog.getOpenFileName = self._orig_open_dialog

    def _write_license(self, path):
        data = _sign(_license_data(), self.private_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def _find_register_button(self, dialog):
        for button in dialog.findChildren(app.QPushButton):
            if button.text() == '라이선스 파일 등록...':
                return button
        raise AssertionError('등록 버튼을 찾지 못함')

    def test_dialog_shows_message_and_pc_code_then_reject_returns_false(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        status = lic.LicenseStatus(False, 'missing', '등록된 라이선스가 없습니다.', None, None)
        captured = {}

        def inspect_and_close():
            dialog = qapp.activeModalWidget()
            self.assertIsNotNone(dialog)
            message_label = dialog.findChild(app.QLabel, 'license_message_label')
            code_edit = dialog.findChild(app.QLineEdit, 'license_code_edit')
            captured['message'] = message_label.text()
            captured['code'] = code_edit.text()
            dialog.reject()

        app.QTimer.singleShot(0, inspect_and_close)
        accepted = app.show_license_registration_dialog(status)
        self.assertFalse(accepted)
        self.assertEqual(captured['message'], '등록된 라이선스가 없습니다.')
        self.assertTrue(len(captured['code']) > 0)

    def test_dialog_stays_open_and_shows_reason_on_invalid_file(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        bad_path = Path(self.tmp.name) / 'bad.lic'
        bad_path.write_text('not json', encoding='utf-8')
        app.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(bad_path), ''))

        status = lic.LicenseStatus(False, 'missing', '등록된 라이선스가 없습니다.', None, None)
        captured = {}

        def click_register_then_close():
            dialog = qapp.activeModalWidget()
            self._find_register_button(dialog).click()
            message_label = dialog.findChild(app.QLabel, 'license_message_label')
            captured['message'] = message_label.text()
            captured['still_open'] = dialog.isVisible()
            dialog.reject()

        app.QTimer.singleShot(0, click_register_then_close)
        accepted = app.show_license_registration_dialog(status)
        self.assertFalse(accepted)
        self.assertTrue(captured['still_open'])
        self.assertNotEqual(captured['message'], status.message)

    def test_dialog_accepts_and_copies_valid_file(self):
        qapp = app.QApplication.instance() or app.QApplication([])
        good_path = Path(self.tmp.name) / 'good.lic'
        self._write_license(good_path)
        app.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(good_path), ''))

        status = lic.LicenseStatus(False, 'missing', '등록된 라이선스가 없습니다.', None, None)

        def click_register():
            dialog = qapp.activeModalWidget()
            self._find_register_button(dialog).click()

        app.QTimer.singleShot(0, click_register)
        accepted = app.show_license_registration_dialog(status)
        self.assertTrue(accepted)
        self.assertTrue(lic.license_file_path().is_file())


@unittest.skipIf(MAKER_IMPORT_ERROR is not None, 'SumPath_License_Maker를 불러올 수 없음: %r' % MAKER_IMPORT_ERROR)
class LicenseMakerRoundTripTests(unittest.TestCase):
    def setUp(self):
        self._orig_pubkey = lic.LICENSE_PUBLIC_KEY
        self.private_key = Ed25519PrivateKey.generate()
        lic.LICENSE_PUBLIC_KEY = _raw_public_key(self.private_key)
        self.addCleanup(self._restore)

    def _restore(self):
        lic.LICENSE_PUBLIC_KEY = self._orig_pubkey

    def test_issue_and_verify_roundtrip(self):
        starts = date(2026, 9, 12)
        data = maker.build_license('생산부 1공장', 'aaaa-bbbb-cccc-dddd', 30, starts, memo='메모')
        signed = maker.sign_license(data, self.private_key)
        status = lic.verify_license(signed, machine='AAAA-BBBB-CCCC-DDDD', today=starts)
        self.assertTrue(status.ok)
        self.assertEqual(status.days_left, 29)
        self.assertEqual(signed['machine'], 'AAAABBBBCCCCDDDD')

    def test_default_filename_pattern(self):
        data = maker.build_license('생산 1공장', 'AAAA-BBBB-CCCC-DDDD', 7, date(2026, 9, 12))
        name = maker.default_license_filename(data)
        self.assertTrue(name.startswith('SumPath_'))
        self.assertTrue(name.endswith('.lic'))
        self.assertIn(data['valid_until'], name)

    def test_issued_log_appends_csv_row(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            orig_maker_dir = maker.maker_dir
            maker.maker_dir = lambda: Path(tmp_dir)
            try:
                data = maker.build_license('테스트', 'AAAA-BBBB-CCCC-DDDD', 30, date(2026, 9, 12))
                signed = maker.sign_license(data, self.private_key)
                maker.append_issued_log(signed)
                maker.append_issued_log(signed)
                content = maker.issued_log_path().read_text(encoding='utf-8-sig')
                lines = [line for line in content.splitlines() if line.strip()]
                self.assertEqual(lines[0], ','.join(maker.ISSUED_LOG_FIELDS))
                self.assertEqual(len(lines), 3)  # 헤더 + 2행
            finally:
                maker.maker_dir = orig_maker_dir

    def test_public_key_mismatch_is_detected(self):
        other_key = Ed25519PrivateKey.generate()
        self.assertFalse(maker.public_key_matches_app(other_key))
        self.assertTrue(maker.public_key_matches_app(self.private_key))


class LicenseSealTests(unittest.TestCase):
    def test_main_checks_license_between_handoff_and_window_creation(self):
        source = inspect.getsource(app.main)
        handoff_index = source.index('send_to_running_instance(initial_file)')
        gate_index = source.index('run_license_gate()')
        window_index = source.index('window = App()')
        self.assertLess(handoff_index, gate_index)
        self.assertLess(gate_index, window_index)

    def test_gitignore_excludes_private_key_and_license_files(self):
        gitignore = Path('.gitignore').read_text(encoding='utf-8')
        self.assertIn('*.pem', gitignore)
        self.assertIn('*.lic', gitignore)

    def test_no_pem_or_lic_files_in_repo_root(self):
        for pattern in ('*.pem', '*.lic'):
            matches = list(Path('.').glob(pattern))
            self.assertEqual(matches, [], '저장소 루트에 %s 파일이 있으면 안 됨: %s' % (pattern, matches))

    def test_no_private_key_material_embedded_in_source(self):
        for name in ('NC_Tool_List.py', 'sumpath_license.py', 'SumPath_License_Maker.py'):
            content = Path(name).read_text(encoding='utf-8')
            self.assertNotIn('PRIVATE KEY', content)

    def test_installer_does_not_bundle_license_maker(self):
        iss = Path('NC_Tool_List.iss').read_text(encoding='utf-8-sig')
        self.assertNotIn('License_Maker', iss)

    def test_installer_grants_users_modify_on_shared_license_folder(self):
        iss = Path('NC_Tool_List.iss').read_text(encoding='utf-8-sig')
        self.assertIn('[Dirs]', iss)
        self.assertIn('{commonappdata}\\NC Tool List', iss)
        self.assertIn('users-modify', iss)

    def test_spec_declares_sumpath_license_hiddenimport(self):
        spec = Path('NC_Tool_List.spec').read_text(encoding='utf-8-sig')
        self.assertIn("'sumpath_license'", spec)

    def test_about_dialog_source_has_license_group(self):
        source = inspect.getsource(app.App.show_about)
        self.assertIn("QGroupBox('라이선스')", source)


if __name__ == '__main__':
    unittest.main()
