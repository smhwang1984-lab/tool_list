# -*- coding: utf-8 -*-
"""Sum Path 라이선스 서버 — 판정/저장 로직 (v2.2.9, FastAPI 없이 테스트 가능).

- 서버 키: 처음 기동할 때 /data/server_key.pem(Ed25519)을 만든다. 서버 ID는 이 공개키에서
  계산되므로(sumpath_license.server_id_from_public_key) 키 파일을 지우면 서버 ID가 바뀌고
  서버 라이선스를 다시 발급받아야 한다 → /data 폴더는 반드시 백업한다.
- 서버 라이선스: 발급 프로그램(SumPath License Maker)의 '서버 라이선스' 탭에서 서버 ID와
  좌석 수로 발급한 .lic 파일을 /data/server_license.lic 로 둔다(관리 화면에서 올려도 된다).
- 좌석: 사용권을 받은 PC(PC 코드) 1대 = 1좌석. 오래 접속하지 않은 PC(기본 30일)는 새 PC가
  좌석을 요청할 때 자동으로 회수된다. 관리자는 관리 화면에서 해제/차단할 수 있다.
"""
import base64
import hmac
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, time, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import sumpath_license as lic

SERVER_VERSION = '1.0.0'


def _now():
    return datetime.now().astimezone()


def _iso(value):
    return value.isoformat(timespec='seconds')


class LicenseServer:
    def __init__(self, data_dir, lease_days=lic.DEFAULT_LEASE_DAYS, seat_idle_days=30,
                 admin_token=None, now_fn=_now):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lease_days = max(1, int(lease_days))
        seat_idle_days = int(seat_idle_days)
        # 회수된 PC의 사용권이 아직 살아 있으면 좌석 수보다 많은 PC가 동시에 쓰게 된다.
        self.seat_idle_days = 0 if seat_idle_days <= 0 else max(seat_idle_days, self.lease_days + 1)
        self.now_fn = now_fn
        self._lock = threading.Lock()
        self._private_key = self._load_or_create_key()
        self.server_key_hex = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        ).hex()
        self.server_id = lic.server_id_from_public_key(self.server_key_hex)
        self.admin_token = self._load_or_create_admin_token(admin_token)
        self._init_db()

    # ---------- 파일 ----------
    @property
    def key_path(self):
        return self.data_dir / 'server_key.pem'

    @property
    def license_path(self):
        return self.data_dir / 'server_license.lic'

    @property
    def db_path(self):
        return self.data_dir / 'seats.sqlite3'

    @property
    def admin_token_path(self):
        return self.data_dir / 'admin_token.txt'

    def _load_or_create_key(self):
        if self.key_path.is_file():
            with self.key_path.open('rb') as fp:
                key = serialization.load_pem_private_key(fp.read(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError('server_key.pem 이 Ed25519 키가 아닙니다.')
            return key
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        tmp = self.key_path.with_name('server_key.pem.tmp')
        with tmp.open('wb') as fp:
            fp.write(pem)
        try:
            os.chmod(str(tmp), 0o600)
        except OSError:
            pass
        os.replace(str(tmp), str(self.key_path))
        return key

    def _load_or_create_admin_token(self, admin_token):
        if admin_token and str(admin_token).strip():
            return str(admin_token).strip()
        if self.admin_token_path.is_file():
            token = self.admin_token_path.read_text(encoding='utf-8').strip()
            if token:
                return token
        token = secrets.token_urlsafe(18)
        self.admin_token_path.write_text(token + '\n', encoding='utf-8')
        try:
            os.chmod(str(self.admin_token_path), 0o600)
        except OSError:
            pass
        return token

    def check_admin_token(self, token):
        return bool(token) and hmac.compare_digest(str(token), self.admin_token)

    # ---------- DB ----------
    def _connect(self):
        cx = sqlite3.connect(str(self.db_path), timeout=10)
        cx.row_factory = sqlite3.Row
        return cx

    def _init_db(self):
        with self._connect() as cx:
            cx.execute(
                'CREATE TABLE IF NOT EXISTS devices ('
                ' machine TEXT PRIMARY KEY,'
                ' pc_name TEXT NOT NULL DEFAULT "",'
                ' ip TEXT NOT NULL DEFAULT "",'
                ' app_version TEXT NOT NULL DEFAULT "",'
                ' status TEXT NOT NULL DEFAULT "active",'
                ' first_seen TEXT NOT NULL,'
                ' last_seen TEXT NOT NULL,'
                ' lease_until TEXT NOT NULL DEFAULT "")'
            )
            cx.execute(
                'CREATE TABLE IF NOT EXISTS events ('
                ' id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, machine TEXT,'
                ' action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT "")'
            )

    def _log(self, cx, machine, action, detail=''):
        cx.execute('INSERT INTO events(at, machine, action, detail) VALUES (?,?,?,?)',
                   (_iso(self.now_fn()), machine, action, detail))
        # 이력은 최근 5000건만 남긴다.
        cx.execute('DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - 5000')

    # ---------- 서버 라이선스 ----------
    def load_license(self):
        return lic.load_license_file(self.license_path) if self.license_path.is_file() else None

    def license_status(self):
        data = self.load_license()
        if data is None:
            return lic.LicenseStatus(
                False, 'server_unlicensed',
                '라이선스 서버에 서버 라이선스가 등록되지 않았습니다. (서버 ID: %s)' % self.server_id,
                None, None,
            )
        return lic.verify_server_license(data, server_id=self.server_id, today=self.now_fn().date())

    def install_license(self, text):
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return {'ok': False, 'message': '라이선스 파일(JSON)을 읽을 수 없습니다.'}
        status = lic.verify_server_license(data, server_id=self.server_id, today=self.now_fn().date())
        if not status.ok and status.reason not in ('not_started',):
            return {'ok': False, 'reason': status.reason, 'message': status.message}
        current = self.load_license()
        if isinstance(current, dict) and lic.verify_server_license(current).reason != 'tampered':
            if str(data.get('issued_at') or '') < str(current.get('issued_at') or ''):
                return {'ok': False, 'reason': 'older_license',
                        'message': '이미 등록된 라이선스보다 먼저 발급된 파일입니다(이전 라이선스로 되돌릴 수 없습니다).'}
        tmp = self.license_path.with_name('server_license.lic.tmp')
        with tmp.open('w', encoding='utf-8') as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(self.license_path))
        with self._lock, self._connect() as cx:
            self._log(cx, None, 'license_installed', str(data.get('license_id')))
        return {'ok': True, 'message': '서버 라이선스를 등록했습니다.', 'info': self.info()}

    # ---------- 사용권 ----------
    def _sign(self, data):
        signature = self._private_key.sign(lic.canonical_payload(data))
        signed = dict(data)
        signed['signature'] = base64.b64encode(signature).decode('ascii')
        return signed

    def _lease_until(self, now, license_data):
        until = now + timedelta(days=self.lease_days)
        valid_until = license_data.get('valid_until')
        if valid_until:
            end = datetime.combine(lic._parse_date(valid_until), time(23, 59, 59)).replace(tzinfo=now.tzinfo)
            until = min(until, end)
        return until

    def _active_rows(self, cx):
        return cx.execute("SELECT * FROM devices WHERE status = 'active' ORDER BY last_seen").fetchall()

    def lease(self, machine, pc_name='', ip='', app_version=''):
        machine = lic.normalize_machine_code(machine)
        if len(machine) != 16:
            return {'ok': False, 'reason': 'bad_request', 'message': 'PC 코드 형식이 올바르지 않습니다.'}
        machine_display = '-'.join(machine[i:i + 4] for i in range(0, 16, 4))
        status = self.license_status()
        if not status.ok:
            return {'ok': False, 'reason': status.reason, 'message': status.message}
        license_data = status.license
        seats = int(license_data['seats'])
        now = self.now_fn()
        with self._lock, self._connect() as cx:
            row = cx.execute('SELECT * FROM devices WHERE machine = ?', (machine,)).fetchone()
            if row is not None and row['status'] == 'blocked':
                self._log(cx, machine, 'denied_blocked', pc_name)
                return {'ok': False, 'reason': 'device_blocked',
                        'message': '관리자가 이 PC의 서버 라이선스 사용을 차단했습니다. (PC 코드: %s)' % machine_display}
            if row is None:
                active = self._active_rows(cx)
                if len(active) >= seats and self.seat_idle_days:
                    cutoff = _iso(now - timedelta(days=self.seat_idle_days))
                    idle = [r for r in active if r['last_seen'] < cutoff]
                    for reclaimed in idle[:len(active) - seats + 1]:
                        cx.execute('DELETE FROM devices WHERE machine = ?', (reclaimed['machine'],))
                        self._log(cx, reclaimed['machine'], 'auto_reclaimed',
                                  '%s (마지막 접속 %s)' % (reclaimed['pc_name'], reclaimed['last_seen']))
                    active = self._active_rows(cx)
                if len(active) >= seats:
                    self._log(cx, machine, 'denied_no_seat', pc_name)
                    return {'ok': False, 'reason': 'no_seats',
                            'message': '서버 라이선스 좌석(%d대)이 모두 사용 중입니다. 관리자에게 좌석 해제를 요청하세요.'
                                       ' (이 PC 코드: %s)' % (seats, machine_display)}
                cx.execute('INSERT INTO devices(machine, pc_name, ip, app_version, status, first_seen, last_seen)'
                           " VALUES (?,?,?,?, 'active', ?, ?)",
                           (machine, pc_name, ip, app_version, _iso(now), _iso(now)))
                self._log(cx, machine, 'registered', pc_name)
            lease_until = self._lease_until(now, license_data)
            lease = self._sign({
                'format': lic.LICENSE_FORMAT,
                'product': lic.PRODUCT_NAME,
                'kind': lic.LEASE_KIND,
                'server_id': self.server_id,
                'server_key': self.server_key_hex,
                'license_id': license_data['license_id'],
                'machine': machine_display,
                'pc_name': pc_name,
                'issued_at': _iso(now),
                'lease_until': _iso(lease_until),
            })
            cx.execute('UPDATE devices SET pc_name = ?, ip = ?, app_version = ?, last_seen = ?, lease_until = ?'
                       ' WHERE machine = ?',
                       (pc_name, ip, app_version, _iso(now), _iso(lease_until), machine))
        return {'ok': True, 'server_license': license_data, 'lease': lease}

    # ---------- 관리 ----------
    def devices(self):
        with self._connect() as cx:
            rows = cx.execute('SELECT * FROM devices ORDER BY status, last_seen DESC').fetchall()
        return [dict(row) for row in rows]

    def events(self, limit=200):
        with self._connect() as cx:
            rows = cx.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
        return [dict(row) for row in rows]

    def set_device(self, machine, action):
        machine = lic.normalize_machine_code(machine)
        with self._lock, self._connect() as cx:
            row = cx.execute('SELECT * FROM devices WHERE machine = ?', (machine,)).fetchone()
            if row is None and action != 'block':
                return {'ok': False, 'message': '등록되지 않은 PC입니다.'}
            if action == 'release':
                cx.execute('DELETE FROM devices WHERE machine = ?', (machine,))
            elif action == 'block':
                if row is None:
                    now = _iso(self.now_fn())
                    cx.execute("INSERT INTO devices(machine, status, first_seen, last_seen) VALUES (?, 'blocked', ?, ?)",
                               (machine, now, now))
                else:
                    cx.execute("UPDATE devices SET status = 'blocked' WHERE machine = ?", (machine,))
            elif action == 'unblock':
                # 차단 해제 = 좌석 없이 목록에서 지운다. 다음 접속 때 좌석이 있으면 다시 등록된다.
                cx.execute('DELETE FROM devices WHERE machine = ?', (machine,))
            else:
                return {'ok': False, 'message': '알 수 없는 동작입니다.'}
            self._log(cx, machine, 'admin_' + action, row['pc_name'] if row else '')
        return {'ok': True}

    def info(self):
        status = self.license_status()
        data = status.license or {}
        with self._connect() as cx:
            used = cx.execute("SELECT COUNT(*) FROM devices WHERE status = 'active'").fetchone()[0]
        return {
            'server_version': SERVER_VERSION,
            'server_id': self.server_id,
            'licensed': bool(status.ok),
            'license_reason': status.reason,
            'license_message': status.message,
            'licensee': data.get('licensee', ''),
            'seats': data.get('seats'),
            'seats_used': used,
            'plan': lic.plan_label(data.get('plan_days')) if data else '',
            'valid_until': data.get('valid_until') if data else None,
            'days_left': status.days_left,
            'lease_days': self.lease_days,
            'seat_idle_days': self.seat_idle_days,
        }
