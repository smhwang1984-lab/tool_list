# -*- coding: utf-8 -*-
"""
Sum Path 라이선스 — 공용 모듈 (v1.8.0)

NC_Tool_List.py(본 앱)와 SumPath_License_Maker.py(발급 프로그램)가 함께 쓴다.
본 앱에는 이 모듈만 있으면 되고 `cryptography` 등 외부 서명 라이브러리가 필요
없다 — 서명 **검증**은 아래 순수 파이썬 Ed25519 구현(RFC 8032)으로 하고, 서명
**생성**(발급)은 발급 프로그램에서만 `cryptography`로 한다(v1.8.0_PLAN.md 결정 F).

라이선스 파일(.lic)은 UTF-8 JSON이다. 자세한 필드/기간 규칙은
`v1.8.0_PLAN.md` §3.2~3.5 참고.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta
from pathlib import Path


PRODUCT_NAME = 'SumPath'
LICENSE_FORMAT = 1

# 발급 가능한 기간(일수, 표시 라벨). v1.8.0_PLAN.md 결정 D: 3년 = 365*3일(달력 기준 아님).
LICENSE_PLANS = (
    (7, '7일'),
    (30, '30일'),
    (365, '1년 (365일)'),
    (1095, '3년'),
)

# Sum Path 라이선스 서명 검증용 Ed25519 공개키(32바이트). 개인키는 발급 PC의
# %APPDATA%\SumPath License Maker\signing_key.pem 에만 있다 — 저장소에는 절대
# 넣지 않는다(v1.8.0_PLAN.md §3.7).
LICENSE_PUBLIC_KEY = bytes.fromhex(
    '98325d4157825ce1f6c5e9604a966492434d8b65cce7a0205f43942c731efab6'
)

REQUIRED_FIELDS = (
    'format', 'product', 'license_id', 'licensee', 'machine',
    'plan_days', 'starts', 'valid_until', 'issued_at', 'signature',
)

# PC 코드에 헷갈리는 글자(0/O, 1/I)를 뺀 알파벳.
MACHINE_CODE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'

# 시계 되돌림 허용 오차(표준시 변경·BIOS 오차 대비). v1.8.0_PLAN.md §3.5.
CLOCK_TOLERANCE = timedelta(hours=24)

# 만료 임박 안내 기준(남은 일수). 7일 라이선스는 더 짧게(2일 이하)만 안내한다.
EXPIRY_NOTICE_DAYS = 7
EXPIRY_NOTICE_DAYS_SHORT_PLAN = 2
EXPIRY_NOTICE_SHORT_PLAN_THRESHOLD = 7


LicenseStatus = namedtuple('LicenseStatus', 'ok reason message license days_left')


# ---------- 순수 파이썬 Ed25519 서명 검증 (RFC 8032) ----------
# 참고 구현: https://ed25519.cr.yp.to/python/ed25519.py (공개 도메인, DJB 등).
# 서명 검증에만 쓰고 키 생성/서명은 하지 않는다.

_Q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493


def _expmod(b, e, m):
    # Python의 내장 pow(b, e, m)은 C 레벨 모듈러 거듭제곱이라, 재귀 구현보다
    # 훨씬 빠르다(검증 1회당 점 곱셈 수백 회 x 역원 계산이 필요해 체감 속도에
    # 직접 영향을 준다).
    return pow(b, e, m)


def _inv(x):
    return _expmod(x, _Q - 2, _Q)


_D = -121665 * _inv(121666) % _Q
_I = _expmod(2, (_Q - 1) // 4, _Q)


def _x_recover(y):
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = _expmod(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * _I) % _Q
    if x % 2 != 0:
        x = _Q - x
    return x


_BY = 4 * _inv(5)
_BX = _x_recover(_BY)
_BASE_POINT = (_BX % _Q, _BY % _Q)


def _edwards(p, q):
    x1, y1 = p
    x2, y2 = q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _D * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _D * x1 * x2 * y1 * y2)
    return (x3 % _Q, y3 % _Q)


def _scalarmult(p, e):
    if e == 0:
        return (0, 1)
    q = _scalarmult(p, e // 2)
    q = _edwards(q, q)
    if e & 1:
        q = _edwards(q, p)
    return q


def _bit(data, i):
    return (data[i // 8] >> (i % 8)) & 1


def _decode_int(data):
    return sum(2 ** i * _bit(data, i) for i in range(8 * len(data)))


def _is_on_curve(point):
    x, y = point
    return (-x * x + y * y - 1 - _D * x * x * y * y) % _Q == 0


def _decode_point(data):
    bit_length = 8 * len(data)
    y = sum(2 ** i * _bit(data, i) for i in range(bit_length - 1))
    x = _x_recover(y)
    if x & 1 != _bit(data, bit_length - 1):
        x = _Q - x
    point = (x, y)
    if not _is_on_curve(point):
        raise ValueError('not a point on the curve')
    return point


def verify_signature(message, signature, public_key):
    """Ed25519 서명 검증. 서명이 유효하면 True, 아니면(예외 포함) False."""
    try:
        if len(signature) != 64 or len(public_key) != 32:
            return False
        r_bytes = signature[:32]
        s_bytes = signature[32:]
        s = _decode_int(s_bytes)
        if s >= _L:
            return False
        r_point = _decode_point(r_bytes)
        a_point = _decode_point(public_key)
        digest = hashlib.sha512(r_bytes + public_key + message).digest()
        h = _decode_int(digest) % _L
        left = _scalarmult(_BASE_POINT, s)
        right = _edwards(r_point, _scalarmult(a_point, h))
        return left == right
    except Exception:
        return False


# ---------- PC 코드 ----------
def machine_guid():
    """Windows MachineGuid. 읽을 수 없으면(레지스트리 접근 실패 등) None."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\Microsoft\Cryptography',
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
    except OSError:
        return None
    try:
        return winreg.QueryValueEx(key, 'MachineGuid')[0]
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)


def machine_code(guid=None):
    """MachineGuid -> 사람이 옮겨 적기 쉬운 PC 코드(XXXX-XXXX-XXXX-XXXX).
    원래 GUID는 되돌릴 수 없다(SHA-256 해시 기반). 읽을 수 없으면 None."""
    if guid is None:
        guid = machine_guid()
    if not guid:
        return None
    digest = hashlib.sha256(str(guid).encode('utf-8')).digest()
    value = int.from_bytes(digest, 'big')
    base = len(MACHINE_CODE_ALPHABET)
    chars = []
    for _ in range(16):
        value, rem = divmod(value, base)
        chars.append(MACHINE_CODE_ALPHABET[rem])
    chars.reverse()
    code = ''.join(chars)
    return '-'.join(code[i:i + 4] for i in range(0, 16, 4))


def normalize_machine_code(code):
    """비교용 정규화 — 대문자, 구분자 제거(사용자가 붙여넣을 때 공백/소문자 허용)."""
    return re.sub(r'[^A-Z0-9]', '', str(code or '').upper())


# ---------- 라이선스 파일 형식 ----------
def canonical_payload(data):
    """서명 대상 바이트 — signature를 뺀 나머지를 정렬된 키로 직렬화.
    한글 등 비ASCII 문자를 포함해도 항상 같은 바이트열이 나온다."""
    payload = {key: value for key, value in data.items() if key != 'signature'}
    return json.dumps(
        payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False
    ).encode('utf-8')


def compute_valid_until(starts, plan_days):
    """시작일부터 plan_days일을 꽉 채운 마지막 사용 가능일(그날까지 포함)."""
    if isinstance(starts, str):
        starts = _parse_date(starts)
    return starts + timedelta(days=int(plan_days) - 1)


def _parse_date(value):
    return datetime.strptime(str(value), '%Y-%m-%d').date()


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def verify_license(data, machine=None, today=None):
    """라이선스 내용 자체를 검증한다(파일 입출력 없음, 순수 함수).

    machine을 주면 PC 코드까지 확인한다. today를 주지 않으면 오늘 날짜를 쓴다.
    """
    today = today or date.today()
    if not isinstance(data, dict) or any(field not in data for field in REQUIRED_FIELDS):
        return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', None, None)
    if data.get('format') != LICENSE_FORMAT or data.get('product') != PRODUCT_NAME:
        return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', None, None)

    signature = data.get('signature')
    if not isinstance(signature, str):
        return LicenseStatus(False, 'tampered', '라이선스 파일이 손상되었거나 수정되었습니다.', None, None)
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError):
        return LicenseStatus(False, 'tampered', '라이선스 파일이 손상되었거나 수정되었습니다.', None, None)

    payload = canonical_payload(data)
    if not verify_signature(payload, signature_bytes, LICENSE_PUBLIC_KEY):
        return LicenseStatus(False, 'tampered', '라이선스 파일이 손상되었거나 수정되었습니다.', None, None)

    if machine is not None:
        license_machine = normalize_machine_code(data.get('machine'))
        if license_machine != normalize_machine_code(machine):
            return LicenseStatus(
                False, 'wrong_machine',
                '이 PC용 라이선스가 아닙니다. (라이선스 PC 코드: %s)' % data.get('machine'),
                data, None,
            )

    try:
        starts = _parse_date(data['starts'])
        valid_until = _parse_date(data['valid_until'])
        plan_days = int(data['plan_days'])
    except (KeyError, ValueError, TypeError):
        return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', None, None)

    # 서명이 맞더라도(=발급 프로그램이 직접 만든 파일이더라도) plan_days와
    # valid_until이 서로 어긋나면 형식 오류로 본다(발급 쪽 버그 방지용 이중 확인).
    if compute_valid_until(starts, plan_days) != valid_until:
        return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', data, None)

    if today < starts:
        return LicenseStatus(
            False, 'not_started',
            '라이선스 시작일(%s)이 아직 되지 않았습니다.' % starts.isoformat(),
            data, None,
        )

    days_left = (valid_until - today).days
    if today > valid_until:
        return LicenseStatus(
            False, 'expired',
            '라이선스가 만료되었습니다. (사용 기한: %s)' % valid_until.isoformat(),
            data, days_left,
        )

    return LicenseStatus(True, 'ok', '', data, days_left)


def is_expiry_notice_due(license_data, days_left):
    """만료 임박 안내를 띄울지: 7일 이하(단, 7일짜리 라이선스는 2일 이하)."""
    if days_left is None:
        return False
    plan_days = None
    try:
        plan_days = int(license_data.get('plan_days')) if license_data else None
    except (TypeError, ValueError):
        plan_days = None
    threshold = EXPIRY_NOTICE_DAYS
    if plan_days is not None and plan_days <= EXPIRY_NOTICE_SHORT_PLAN_THRESHOLD:
        threshold = EXPIRY_NOTICE_DAYS_SHORT_PLAN
    return 0 <= days_left <= threshold


def plan_label(plan_days):
    for days, label in LICENSE_PLANS:
        if days == plan_days:
            return label
    return '%s일' % plan_days


# ---------- 저장 위치 ----------
def license_dir():
    """PC 전체 공용 라이선스 폴더(사용자 계정과 무관). 관리자 권한 없이도
    쓸 수 있도록 설치 스크립트가 이 폴더에 users-modify 권한을 준다."""
    base = os.environ.get('PROGRAMDATA') or str(Path.home())
    return Path(base) / 'NC Tool List'


def license_file_path():
    return license_dir() / 'license.lic'


def license_state_path():
    return license_dir() / 'license_state.json'


def bundled_license_path():
    """exe 폴더 옆(포터블 배포/수동 배치용) 보조 라이선스 파일."""
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / 'license.lic'


def find_license_file():
    """ProgramData를 먼저 보고, 없으면 exe 폴더 옆을 본다. 둘 다 없으면 None."""
    primary = license_file_path()
    if primary.is_file():
        return primary
    secondary = bundled_license_path()
    if secondary.is_file():
        return secondary
    return None


def load_license_file(path):
    try:
        with Path(path).open('r', encoding='utf-8') as fp:
            data = json.load(fp)
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def load_license_state():
    try:
        with license_state_path().open('r', encoding='utf-8') as fp:
            data = json.load(fp)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {}


def save_license_state(state):
    path = license_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as fp:
        json.dump(state, fp, ensure_ascii=False, indent=2)


def clock_rollback_detected(now, state, license_data):
    """PC 시계를 과거로 되돌려 기간을 늘리는 것을 막는다(24시간 여유)."""
    last_seen = _parse_datetime((state or {}).get('last_seen'))
    if last_seen is not None and now < last_seen - CLOCK_TOLERANCE:
        return True
    issued_at = _parse_datetime((license_data or {}).get('issued_at'))
    if issued_at is not None and now < issued_at - CLOCK_TOLERANCE:
        return True
    return False


def ensure_license(now=None):
    """앱 시작 시 부르는 진입점. 파일을 찾아 읽고 내용/시계를 검증한 뒤,
    통과하면 마지막 확인 시각을 기록한다."""
    now = now or datetime.now()
    today = now.date()
    path = find_license_file()
    if path is None:
        return LicenseStatus(False, 'missing', '등록된 라이선스가 없습니다.', None, None)

    data = load_license_file(path)
    if data is None:
        return LicenseStatus(False, 'invalid_format', '라이선스 파일을 읽을 수 없습니다.', None, None)

    status = verify_license(data, machine=machine_code(), today=today)
    if not status.ok:
        return status

    state = load_license_state()
    if clock_rollback_detected(now, state, data):
        return LicenseStatus(
            False, 'clock_rollback',
            'PC 날짜가 올바르지 않습니다. 날짜/시간을 확인하세요.',
            data, status.days_left,
        )

    state['last_seen'] = now.isoformat(timespec='seconds')
    save_license_state(state)
    return status


def register_license_file(source_path, now=None):
    """등록 창의 '라이선스 파일 등록'. 선택한 파일을 검증하고 통과하면
    표준 위치(license_dir())로 복사한다. 실패하면 파일을 건드리지 않는다."""
    now = now or datetime.now()
    data = load_license_file(source_path)
    if data is None:
        return LicenseStatus(False, 'invalid_format', '라이선스 파일을 읽을 수 없습니다.', None, None)

    status = verify_license(data, machine=machine_code(), today=now.date())
    if not status.ok:
        return status

    dest = license_file_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source_path), str(dest))
    # 새로 등록한 라이선스는 이전 라이선스의 last_seen 이력과 무관하게 취급한다.
    save_license_state({'last_seen': now.isoformat(timespec='seconds')})
    return status
