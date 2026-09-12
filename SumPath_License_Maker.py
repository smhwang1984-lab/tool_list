# -*- coding: utf-8 -*-
"""
SumPath License Maker (v1.8.0)

Sum Path 라이선스 파일(.lic) 발급 프로그램. **발급자(관리자) PC에만** 두고,
Sum Path 설치본/포터블/업데이트 공유 폴더에는 절대 포함하지 않는다
(v1.8.0_PLAN.md §3.6). 서명 개인키는 이 프로그램을 실행하는 PC의
`%APPDATA%\\SumPath License Maker\\signing_key.pem`에만 있다 — 저장소에는
절대 넣지 않는다.

형식/기간 규칙은 `sumpath_license.py`(본 앱과 공유)를 그대로 쓴다.
"""
import base64
import csv
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QDateEdit, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QTabWidget, QVBoxLayout, QWidget,
)

import sumpath_license as lic


MAKER_APP_NAME = 'SumPath License Maker'
MAKER_VERSION = '1.0.0'
ISSUED_LOG_FIELDS = (
    'license_id', 'licensee', 'machine', 'plan_days', 'starts',
    'valid_until', 'issued_at', 'memo',
)


# ---------- 서명 키 관리 ----------
def maker_dir():
    base = os.environ.get('APPDATA') or str(Path.home())
    return Path(base) / MAKER_APP_NAME


def signing_key_path():
    return maker_dir() / 'signing_key.pem'


def issued_log_path():
    return maker_dir() / 'issued_licenses.csv'


def load_signing_key():
    path = signing_key_path()
    if not path.is_file():
        return None
    try:
        with path.open('rb') as fp:
            return serialization.load_pem_private_key(fp.read(), password=None)
    except (ValueError, TypeError, OSError):
        return None


def generate_signing_key():
    path = signing_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with path.open('wb') as fp:
        fp.write(pem)
    return key


def public_key_hex(key):
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    ).hex()


def public_key_matches_app(key):
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    return raw == lic.LICENSE_PUBLIC_KEY


# ---------- 라이선스 발급 ----------
def build_license(licensee, machine, plan_days, starts, memo=''):
    valid_until = lic.compute_valid_until(starts, plan_days)
    return {
        'format': lic.LICENSE_FORMAT,
        'product': lic.PRODUCT_NAME,
        'license_id': str(uuid.uuid4()),
        'licensee': licensee,
        'machine': lic.normalize_machine_code(machine),
        'plan_days': int(plan_days),
        'starts': starts.isoformat(),
        'valid_until': valid_until.isoformat(),
        'issued_at': datetime.now().isoformat(timespec='seconds'),
        'memo': memo or '',
    }


def sign_license(data, private_key):
    payload = lic.canonical_payload(data)
    signature = private_key.sign(payload)
    signed = dict(data)
    signed['signature'] = base64.b64encode(signature).decode('ascii')
    return signed


def default_license_filename(data):
    def clean(value):
        value = re.sub(r'[\\/:*?"<>|]+', '_', str(value or '').strip())
        return value or 'unknown'
    machine = str(data.get('machine') or '')
    return 'SumPath_%s_%s_%s.lic' % (
        clean(data.get('licensee')),
        machine[:4] if machine else 'XXXX',
        data.get('valid_until', ''),
    )


def append_issued_log(data):
    path = issued_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.is_file()
    # utf-8-sig: 엑셀에서 한글이 깨지지 않도록 BOM을 붙인다.
    with path.open('a', newline='', encoding='utf-8-sig') as fp:
        writer = csv.DictWriter(fp, fieldnames=ISSUED_LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({key: data.get(key, '') for key in ISSUED_LOG_FIELDS})


# ---------- UI ----------
class LicenseMakerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('%s v%s' % (MAKER_APP_NAME, MAKER_VERSION))
        self.resize(560, 640)
        self.signing_key = None

        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        tabs.addTab(self._build_issue_tab(), '발급')
        tabs.addTab(self._build_verify_tab(), '확인')

    # ----- 발급 탭 -----
    def _build_issue_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.key_status_label = QLabel('')
        self.key_status_label.setWordWrap(True)
        layout.addWidget(self.key_status_label)

        self.generate_key_button = QPushButton('새 서명 키 생성...')
        self.generate_key_button.clicked.connect(self._generate_key)
        layout.addWidget(self.generate_key_button)

        form_group = QGroupBox('라이선스 정보')
        form_layout = QVBoxLayout(form_group)

        licensee_row = QHBoxLayout()
        licensee_row.addWidget(QLabel('사용자(회사/부서/이름)'))
        self.licensee_edit = QLineEdit()
        licensee_row.addWidget(self.licensee_edit, 1)
        form_layout.addLayout(licensee_row)

        machine_row = QHBoxLayout()
        machine_row.addWidget(QLabel('PC 코드'))
        self.machine_edit = QLineEdit()
        self.machine_edit.setPlaceholderText('XXXX-XXXX-XXXX-XXXX')
        machine_row.addWidget(self.machine_edit, 1)
        form_layout.addLayout(machine_row)

        plan_row = QHBoxLayout()
        plan_row.addWidget(QLabel('기간'))
        self.plan_group = QButtonGroup(self)
        for index, (days, label) in enumerate(lic.LICENSE_PLANS):
            radio = QRadioButton(label)
            radio.setProperty('plan_days', days)
            if index == 1:  # 30일을 기본 선택으로 둔다.
                radio.setChecked(True)
            self.plan_group.addButton(radio, days)
            plan_row.addWidget(radio)
        self.plan_group.buttonClicked.connect(self._update_valid_until_preview)
        form_layout.addLayout(plan_row)

        start_row = QHBoxLayout()
        start_row.addWidget(QLabel('시작일'))
        self.start_date_edit = QDateEdit(QDate.currentDate())
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.dateChanged.connect(self._update_valid_until_preview)
        start_row.addWidget(self.start_date_edit)
        start_row.addStretch(1)
        form_layout.addLayout(start_row)

        self.valid_until_label = QLabel('')
        form_layout.addWidget(self.valid_until_label)

        memo_row = QHBoxLayout()
        memo_row.addWidget(QLabel('메모(선택)'))
        self.memo_edit = QLineEdit()
        memo_row.addWidget(self.memo_edit, 1)
        form_layout.addLayout(memo_row)

        layout.addWidget(form_group)

        self.issue_button = QPushButton('라이선스 발급')
        self.issue_button.clicked.connect(self._issue_license)
        layout.addWidget(self.issue_button)

        self.issue_status_label = QLabel('')
        self.issue_status_label.setWordWrap(True)
        layout.addWidget(self.issue_status_label)
        layout.addStretch(1)

        self._refresh_key_status()
        self._update_valid_until_preview()
        return widget

    def _selected_plan_days(self):
        button = self.plan_group.checkedButton()
        return button.property('plan_days') if button else lic.LICENSE_PLANS[0][0]

    def _update_valid_until_preview(self, *_args):
        starts = self.start_date_edit.date().toPyDate()
        plan_days = self._selected_plan_days()
        valid_until = lic.compute_valid_until(starts, plan_days)
        self.valid_until_label.setText('사용 기한: %s' % valid_until.isoformat())

    def _refresh_key_status(self):
        self.signing_key = load_signing_key()
        if self.signing_key is None:
            self.key_status_label.setText(
                '서명 키가 없습니다. 라이선스를 발급하려면 먼저 키를 생성하거나\n'
                '기존 키 파일을 이 PC의 %s 에 놓으세요.' % signing_key_path()
            )
            self.generate_key_button.setEnabled(True)
            self.generate_key_button.setText('새 서명 키 생성...')
            self.issue_button.setEnabled(False)
            return
        if public_key_matches_app(self.signing_key):
            self.key_status_label.setText('서명 키 준비됨(현재 앱의 공개키와 일치).')
            self.issue_button.setEnabled(True)
        else:
            self.key_status_label.setText(
                '⚠ 이 서명 키는 현재 앱(sumpath_license.py)에 내장된 공개키와\n'
                '일치하지 않습니다. 이 키로 발급한 라이선스는 그 앱에서 통과되지\n'
                '않습니다 — 앱을 이 키의 공개키로 다시 빌드하기 전에는 발급하지 마세요.'
            )
            self.issue_button.setEnabled(False)
        self.generate_key_button.setEnabled(False)
        self.generate_key_button.setText('서명 키 있음')

    def _generate_key(self):
        if signing_key_path().is_file():
            confirm = QMessageBox.warning(
                self, '서명 키 교체',
                '이미 서명 키가 있습니다. 새로 만들면 이전 키로 발급한 라이선스와는\n'
                '다른 새 키 체계가 시작되어, 본 앱도 새 공개키로 다시 빌드해야\n'
                '기존/신규 라이선스가 통과됩니다. 정말 새로 만들까요?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
        key = generate_signing_key()
        QMessageBox.information(
            self, '서명 키 생성 완료',
            '새 서명 키를 만들었습니다.\n\n'
            '공개키(sumpath_license.py의 LICENSE_PUBLIC_KEY에 반영하고 앱을\n'
            '다시 빌드해야 이 키로 만든 라이선스를 인식합니다):\n%s\n\n'
            '개인키 위치(반드시 안전한 곳에 백업하세요. 잃어버리면 새 라이선스를\n'
            '더는 만들 수 없습니다):\n%s' % (public_key_hex(key), signing_key_path()),
        )
        self._refresh_key_status()

    def _issue_license(self):
        licensee = self.licensee_edit.text().strip()
        if not licensee:
            QMessageBox.warning(self, '입력 필요', '사용자를 입력하세요.')
            return
        machine = lic.normalize_machine_code(self.machine_edit.text())
        if len(machine) != 16:
            QMessageBox.warning(
                self, '입력 필요',
                'PC 코드 형식이 올바르지 않습니다. (예: XXXX-XXXX-XXXX-XXXX)',
            )
            return
        if self.signing_key is None or not public_key_matches_app(self.signing_key):
            QMessageBox.warning(self, '발급 불가', '서명 키가 없거나 앱과 일치하지 않습니다.')
            return

        starts = self.start_date_edit.date().toPyDate()
        plan_days = self._selected_plan_days()
        memo = self.memo_edit.text().strip()

        data = build_license(licensee, machine, plan_days, starts, memo)
        signed = sign_license(data, self.signing_key)

        # 발급 직후 앱과 같은 검증기로 왕복 확인 — 발급 로직 자체의 버그를
        # (엉뚱한 필드 순서, 날짜 계산 오차 등) 파일을 건네기 전에 잡는다.
        check = lic.verify_license(signed, machine=machine, today=starts)
        if not check.ok:
            QMessageBox.critical(
                self, '발급 실패',
                '발급한 라이선스 자체 검증에 실패했습니다: %s' % check.message,
            )
            return

        default_name = default_license_filename(signed)
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, '라이선스 파일 저장', default_name, 'License files (*.lic)',
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as fp:
                json.dump(signed, fp, ensure_ascii=False, indent=2)
            append_issued_log(signed)
        except OSError as error:
            QMessageBox.critical(self, '발급 실패', '파일을 저장하지 못했습니다.\n%s' % error)
            return

        self.issue_status_label.setText(
            '발급 완료: %s\n사용 기한: %s (남은 %d일)' % (
                path, signed['valid_until'], check.days_left,
            )
        )

    # ----- 확인 탭 -----
    def _build_verify_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        open_button = QPushButton('라이선스 파일 열기...')
        open_button.clicked.connect(self._verify_file)
        layout.addWidget(open_button)

        self.verify_output = QPlainTextEdit()
        self.verify_output.setReadOnly(True)
        layout.addWidget(self.verify_output, 1)

        return widget

    def _verify_file(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, '라이선스 파일 선택', '', 'License files (*.lic)',
        )
        if not path:
            return
        data = lic.load_license_file(path)
        if data is None:
            self.verify_output.setPlainText('파일을 읽을 수 없습니다: %s' % path)
            return
        # 발급자는 대상 PC가 아닐 수 있으므로 PC 코드 일치는 확인하지 않고
        # 형식/서명/기간만 본다(PC 코드는 아래에 정보로만 표시).
        status = lic.verify_license(data)
        lines = ['파일: %s' % path, '']
        for key in ('license_id', 'licensee', 'machine', 'plan_days', 'starts', 'valid_until', 'issued_at', 'memo'):
            lines.append('%s: %s' % (key, data.get(key, '')))
        lines.append('')
        lines.append(
            '서명/형식/기간 검증: %s' % (
                '통과' if status.ok else '실패(%s) - %s' % (status.reason, status.message)
            )
        )
        if status.days_left is not None:
            lines.append('남은 일수(오늘 기준): %d일' % status.days_left)
        self.verify_output.setPlainText('\n'.join(lines))


def main():
    app = QApplication(sys.argv)
    window = LicenseMakerWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
