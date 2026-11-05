# -*- coding: utf-8 -*-
"""
Sum Path 라이선스 — 공용 모듈 (v1.8.1, 서버 라이선스 겸용은 v2.2.9)

NC_Tool_List.py(본 앱)와 SumPath_License_Maker.py(발급 프로그램)가 함께 쓴다.
본 앱에는 이 모듈만 있으면 되고 `cryptography` 등 외부 서명 라이브러리가 필요
없다 — 서명 **검증**은 아래 순수 파이썬 Ed25519 구현(RFC 8032)으로 하고, 서명
**생성**(발급)은 발급 프로그램에서만 `cryptography`로 한다(v1.8.0_PLAN.md 결정 F).

라이선스 파일(.lic)은 UTF-8 JSON이다. 자세한 필드/기간 규칙은
`v1.8.0_PLAN.md` §3.2~3.5, 30일 체험판/영구 라이선스는 `v1.8.1_PLAN.md` §3.1~3.3 참고.

v2.2.9: NAS 컨테이너의 라이선스 서버(`license_server/`)가 좌석 수만큼 PC에 사용권(lease)을
나눠 주는 **서버 라이선스**를 로컬 라이선스와 겸용한다(`v2.2.9_PLAN.md`). 판정 순서는
로컬 .lic → 서버 라이선스 → 30일 체험판이다. `license_server/sumpath_license.py`는 이 파일과
바이트 단위로 같아야 한다(tests/test_license_server.py가 검사).
"""
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import urllib.error
import urllib.request
from collections import namedtuple
from datetime import date, datetime, timedelta
from pathlib import Path


PRODUCT_NAME = 'SumPath'
LICENSE_FORMAT = 1

# plan_days -> 표시 라벨. 7일/30일은 v1.8.0에서 이미 발급된 파일을 계속 인정하기
# 위해 남겨 둔다(v1.8.1_PLAN.md 결정 F) — 새로 발급할 때는 ISSUABLE_PLANS만 쓴다.
# v1.8.0_PLAN.md 결정 D: 3년 = 365*3일(달력 기준 아님). 0 = 영구(v1.8.1_PLAN.md 결정 C).
LICENSE_PLANS = (
    (7, '7일'),
    (30, '30일'),
    (365, '1년 (365일)'),
    (1095, '3년'),
    (0, '영구'),
)

# 발급 프로그램이 실제로 발급 가능한 기간(v1.8.1_PLAN.md §3.3).
ISSUABLE_PLANS = (
    (365, '1년 (365일)'),
    (1095, '3년'),
    (0, '영구'),
)

PERPETUAL_PLAN_DAYS = 0

# 라이선스 없이 첫 실행부터 그대로 쓸 수 있는 체험 기간(v1.8.1_PLAN.md §3.1).
TRIAL_DAYS = 30

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


# trial 필드는 기본 False — v1.8.0 코드/테스트가 5개 인자로 만들어도 그대로 동작한다.
# v2.2.9: source = 'local' | 'server' | 'trial' | '' (판정 실패). 기본값이 있어
# 기존 5~6개 인자 호출도 그대로 동작한다.
LicenseStatus = namedtuple('LicenseStatus', 'ok reason message license days_left trial source')
LicenseStatus.__new__.__defaults__ = (False, '')


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
        plan_days = int(data['plan_days'])
    except (KeyError, ValueError, TypeError):
        return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', None, None)

    # 영구 라이선스(v1.8.1_PLAN.md §3.2): plan_days=0 + valid_until=null 조합만 인정한다.
    if plan_days == PERPETUAL_PLAN_DAYS:
        if data.get('valid_until') is not None:
            return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', data, None)
        if today < starts:
            return LicenseStatus(
                False, 'not_started',
                '라이선스 시작일(%s)이 아직 되지 않았습니다.' % starts.isoformat(),
                data, None,
            )
        return LicenseStatus(True, 'ok', '', data, None)

    try:
        valid_until = _parse_date(data['valid_until'])
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


# ---------- 30일 체험판 (v1.8.1_PLAN.md §3.1) ----------
def _registry_license_key_path():
    return r'Software\NC Tool List\License'


def read_registry_trial_started():
    """HKCU에 적힌 체험 시작일. 읽을 수 없으면(레지스트리 접근 실패 등) None."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _registry_license_key_path(), 0, winreg.KEY_READ)
    except OSError:
        return None
    try:
        value, _value_type = winreg.QueryValueEx(key, 'TrialStarted')
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)
    try:
        return _parse_date(value)
    except (ValueError, TypeError):
        return None


def write_registry_trial_started(value_date):
    """HKCU에 체험 시작일을 적는다. 실패해도(권한 등) 조용히 무시한다 —
    공용 폴더 쪽 기록이 있으면 그것만으로도 동작한다."""
    try:
        import winreg
    except ImportError:
        return
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _registry_license_key_path())
    except OSError:
        return
    try:
        winreg.SetValueEx(key, 'TrialStarted', 0, winreg.REG_SZ, value_date.isoformat())
    except OSError:
        pass
    finally:
        winreg.CloseKey(key)


def read_trial_started(state):
    """공용 폴더(state['trial_started'])와 레지스트리 중 더 이른 날짜를 진짜
    체험 시작일로 쓰고, 지워졌거나 어긋난 쪽을 그 값으로 복구한다(v1.8.1_PLAN.md
    결정 B). 기록이 전혀 없으면 None. `state`는 호출자가 load_license_state()로
    이미 읽어 둔 딕셔너리 — 필요하면 이 함수가 갱신해 저장한다."""
    try:
        shared = _parse_date(state.get('trial_started')) if state.get('trial_started') else None
    except (ValueError, TypeError):
        shared = None
    registry = read_registry_trial_started()

    if shared is None and registry is None:
        return None

    earliest = min(value for value in (shared, registry) if value is not None)

    if shared != earliest:
        state['trial_started'] = earliest.isoformat()
        save_license_state(state)
    if registry != earliest:
        write_registry_trial_started(earliest)
    return earliest


def evaluate_trial(now):
    """라이선스가 없거나 무효일 때의 30일 체험판 판정(v1.8.1_PLAN.md §3.1)."""
    today = now.date()
    state = load_license_state()
    started = read_trial_started(state)

    if started is None:
        started = today
        state = load_license_state()  # read_trial_started가 이미 저장했을 수 있음 — 최신값 다시 읽기
        state['trial_started'] = started.isoformat()
        state['last_seen'] = now.isoformat(timespec='seconds')
        save_license_state(state)
        write_registry_trial_started(started)
        trial_until = started + timedelta(days=TRIAL_DAYS - 1)
        return LicenseStatus(
            True, 'trial_started',
            '30일 체험판으로 시작합니다. (체험 종료일: %s)' % trial_until.isoformat(),
            None, TRIAL_DAYS - 1, True, 'trial',
        )

    if clock_rollback_detected(now, state, {'issued_at': started.isoformat()}):
        return LicenseStatus(
            False, 'clock_rollback',
            'PC 날짜가 올바르지 않습니다. 날짜/시간을 확인하세요.',
            None, None, True,
        )

    trial_until = started + timedelta(days=TRIAL_DAYS - 1)
    days_left = (trial_until - today).days
    if today > trial_until:
        return LicenseStatus(
            False, 'trial_expired',
            '체험 기간이 끝났습니다. (체험 종료일: %s)' % trial_until.isoformat(),
            None, days_left, True,
        )

    state['last_seen'] = now.isoformat(timespec='seconds')
    save_license_state(state)
    return LicenseStatus(
        True, 'trial',
        '체험판 — 남은 %d일 (체험 종료일: %s)' % (days_left, trial_until.isoformat()),
        None, days_left, True, 'trial',
    )


# ---------- v2.3.1: 서버 라이선스 우선 — 로컬 라이선스 해제(보관)/복원 ----------
SERVER_FALLBACK_REASONS = ('server_unreachable', 'lease_expired')


def released_license_path():
    """서버 라이선스를 쓰는 동안 보관해 두는 로컬 라이선스(ProgramData의 license.lic를 이 이름으로 옮김)."""
    return license_dir() / 'license_released.lic'


def _bundled_license_released():
    return bool(load_license_state().get('bundled_license_released'))


def local_license_released():
    """로컬 라이선스가 해제(보관)된 상태인지 — About 표시용."""
    return released_license_path().is_file() or _bundled_license_released()


def release_local_license(now=None):
    """서버에서 사용권을 받았을 때 부른다(v2.3.1, 서버 > 로컬). ProgramData의 license.lic는
    license_released.lic로 옮기고, exe 옆 license.lic(설치 폴더라 이름을 못 바꿀 수 있음)는
    상태 파일에 '해제됨'만 기록한다. 이미 보관본이 있으면 새 파일로 덮어쓴다. 실패해도 예외를 내지 않는다."""
    changed = False
    primary = license_file_path()
    if primary.is_file():
        try:
            os.replace(str(primary), str(released_license_path()))
            changed = True
        except OSError:
            pass
    if bundled_license_path().is_file() and not _bundled_license_released():
        try:
            state = load_license_state()
            state['bundled_license_released'] = (now or datetime.now()).isoformat(timespec='seconds')
            save_license_state(state)
            changed = True
        except OSError:
            pass
    return changed


def restore_local_license():
    """서버 연결을 해제했을 때 보관한 로컬 라이선스를 되살린다. 이미 license.lic가 있으면 그것을 둔다."""
    changed = False
    released = released_license_path()
    if released.is_file():
        try:
            if license_file_path().is_file():
                released.unlink()
            else:
                os.replace(str(released), str(license_file_path()))
            changed = True
        except OSError:
            pass
    if _bundled_license_released():
        try:
            state = load_license_state()
            state.pop('bundled_license_released', None)
            save_license_state(state)
            changed = True
        except OSError:
            pass
    return changed


def _evaluate_local_license(now, include_released=False):
    """로컬 라이선스 판정. include_released면 해제(보관)된 것도 본다(서버 장애 비상용).
    반환: (LicenseStatus 또는 None(파일 없음))."""
    candidates = []
    if license_file_path().is_file():
        candidates.append(license_file_path())
    if include_released and released_license_path().is_file():
        candidates.append(released_license_path())
    if bundled_license_path().is_file() and (include_released or not _bundled_license_released()):
        candidates.append(bundled_license_path())
    if not candidates:
        return None
    result = None
    for path in candidates:
        data = load_license_file(path)
        if data is None:
            status = LicenseStatus(False, 'invalid_format', '라이선스 파일을 읽을 수 없습니다.', None, None)
        else:
            status = verify_license(data, machine=machine_code(), today=now.date())
            if status.ok:
                state = load_license_state()
                if clock_rollback_detected(now, state, data):
                    return LicenseStatus(
                        False, 'clock_rollback',
                        'PC 날짜가 올바르지 않습니다. 날짜/시간을 확인하세요.',
                        data, status.days_left,
                    )
                state['last_seen'] = now.isoformat(timespec='seconds')
                save_license_state(state)
                return status._replace(source='local')
        if result is None:
            result = status
    return result


def ensure_license(now=None, client_info=None):
    """앱 시작 시(그리고 실행 중 1시간마다) 부르는 진입점.

    판정 순서(v2.3.1, **서버 > 로컬**):
      · 라이선스 서버 주소가 **있는** PC
        1) 서버에서 사용권을 받으면 통과하고, 로컬 라이선스는 해제(보관)한다(release_local_license).
        2) 서버에 연결할 수 없으면 저장된 사용권(기본 7일) 안에서 통과한다.
        3) 서버가 **거부**하면(차단/좌석 없음/서버 라이선스 만료 등) 로컬 라이선스로 돌아가지 않는다.
           서버에 **연결할 수 없고** 사용권도 끝났을 때만 보관한 로컬 라이선스를 비상용으로 쓴다.
      · 서버 주소가 **없는** PC: 보관된 로컬 라이선스가 있으면 되살리고(restore_local_license)
        로컬 라이선스 → 체험판 순(v2.2.9와 같음).
    마지막으로 30일 체험판을 본다(v1.8.1_PLAN.md §3.1). 모두 실패하면 서버 → 로컬 → 체험판 순으로
    가장 쓸모 있는 실패 사유를 돌려준다.
    """
    now = now or datetime.now()

    server_status = None
    license_status = None
    if get_license_server_url():
        server_status = evaluate_server_license(now, client_info=client_info)
        if server_status.ok:
            if server_status.reason == 'server':  # 서버에서 방금 사용권을 받음(오프라인 통과는 아님)
                release_local_license(now)
            return server_status
        if server_status.reason == 'clock_rollback':
            return server_status
        if server_status.reason in SERVER_FALLBACK_REASONS:
            license_status = _evaluate_local_license(now, include_released=True)
            if license_status is not None and license_status.ok:
                return license_status._replace(
                    message='라이선스 서버에 연결할 수 없어 보관된 로컬 라이선스로 실행합니다.')
            if license_status is not None and license_status.reason == 'clock_rollback':
                return license_status
    else:
        restore_local_license()
        license_status = _evaluate_local_license(now)
        if license_status is not None and (license_status.ok or license_status.reason == 'clock_rollback'):
            return license_status

    trial_status = evaluate_trial(now)
    if trial_status.ok or trial_status.reason == 'clock_rollback':
        return trial_status
    if server_status is not None:
        return server_status
    if license_status is not None:
        return license_status
    return trial_status


def register_license_file(source_path, now=None):
    """등록 창의 '라이선스 파일 등록'. 선택한 파일을 검증하고 통과하면
    표준 위치(license_dir())로 복사한다. 실패하면 파일을 건드리지 않는다."""
    now = now or datetime.now()
    data = load_license_file(source_path)
    if data is None:
        return LicenseStatus(False, 'invalid_format', '라이선스 파일을 읽을 수 없습니다.', None, None)

    status = verify_license(data, machine=machine_code(), today=now.date())
    if not status.ok:
        if data.get('kind') == SERVER_LICENSE_KIND:
            return LicenseStatus(
                False, 'server_license_file',
                '서버 라이선스 파일입니다. 이 파일은 PC가 아니라 라이선스 서버(NAS) 관리 화면에 등록하세요.',
                None, None,
            )
        return status
    status = status._replace(source='local')

    dest = license_file_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source_path), str(dest))
    # 새로 등록한 라이선스는 이전 라이선스의 last_seen 이력과 무관하게 취급한다.
    # 다만 trial_started는 이 라이선스와 무관하게 "이 PC가 체험판을 이미
    # 써봤는지"를 기록하는 값이라 지우면 안 된다 — 지우면 유료 라이선스를
    # 등록/교체할 때마다(예: 만료된 라이선스를 새 걸로 교체) 체험판 30일이
    # 초기화되어, 라이선스를 지우고 다시 등록하는 식으로 체험판을 무한
    # 연장할 수 있는 구멍이 생긴다.
    old_state = load_license_state()
    new_state = {'last_seen': now.isoformat(timespec='seconds')}
    if 'trial_started' in old_state:
        new_state['trial_started'] = old_state['trial_started']
    save_license_state(new_state)
    return status


# ======================================================================
# v2.2.9 서버 라이선스 (로컬 라이선스와 겸용) — v2.2.9_PLAN.md
# ======================================================================
#
# 신뢰 사슬(공유 비밀 없음):
#   발급 프로그램(개인키) --서명--> 서버 라이선스 {server_id, seats, 기간}
#   라이선스 서버(자기 키) --서명--> 사용권(lease) {machine, lease_until, server_key}
#   앱: ① 서버 라이선스 서명을 LICENSE_PUBLIC_KEY로 확인 ② server_id ==
#       server_id_from_public_key(lease.server_key) ③ lease 서명을 server_key로 확인
#       ④ lease.machine == 이 PC 코드 ⑤ 기한. 서버 개인키는 NAS /data에만 있다.

SERVER_LICENSE_KIND = 'server'
LEASE_KIND = 'lease'
SERVER_LICENSE_FIELDS = (
    'format', 'product', 'kind', 'license_id', 'licensee', 'server_id', 'seats',
    'plan_days', 'starts', 'valid_until', 'issued_at', 'signature',
)
LEASE_FIELDS = (
    'format', 'product', 'kind', 'server_id', 'server_key', 'license_id', 'machine',
    'issued_at', 'lease_until', 'signature',
)
DEFAULT_LEASE_DAYS = 7          # 서버에 연결하지 못해도 계속 쓸 수 있는 기간(서버 설정으로 변경)
DEFAULT_SERVER_PORT = 8765
SERVER_REQUEST_TIMEOUT = 4.0    # 초. 시작 화면이 오래 멈추지 않도록 짧게
LEASE_API_PATH = '/api/v1/lease'
LICENSE_SERVER_ENV = 'SUMPATH_LICENSE_SERVER'


class LicenseServerUnavailable(Exception):
    """서버에 닿지 못함(네트워크/타임아웃/5xx/응답 해석 실패) — 오프라인 사용권으로 대체한다."""


def server_id_from_public_key(public_key_hex):
    """라이선스 서버 공개키(hex) → 서버 ID(XXXX-XXXX-XXXX-XXXX). PC 코드와 같은 알파벳."""
    return machine_code(guid='sumpath-server:%s' % str(public_key_hex or '').strip().lower())


def _to_aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.astimezone()
    return value


def _check_period(data, today):
    """plan_days/starts/valid_until 기간 판정(서버 라이선스용). (실패 LicenseStatus|None, days_left)."""
    try:
        starts = _parse_date(data['starts'])
        plan_days = int(data['plan_days'])
    except (KeyError, ValueError, TypeError):
        return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', None, None), None
    if plan_days == PERPETUAL_PLAN_DAYS:
        if data.get('valid_until') is not None:
            return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', data, None), None
        if today < starts:
            return LicenseStatus(False, 'not_started',
                                 '라이선스 시작일(%s)이 아직 되지 않았습니다.' % starts.isoformat(), data, None), None
        return None, None
    try:
        valid_until = _parse_date(data['valid_until'])
    except (KeyError, ValueError, TypeError):
        return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', None, None), None
    if compute_valid_until(starts, plan_days) != valid_until:
        return LicenseStatus(False, 'invalid_format', '라이선스 파일 형식을 알 수 없습니다.', data, None), None
    if today < starts:
        return LicenseStatus(False, 'not_started',
                             '라이선스 시작일(%s)이 아직 되지 않았습니다.' % starts.isoformat(), data, None), None
    days_left = (valid_until - today).days
    if today > valid_until:
        return LicenseStatus(False, 'expired',
                             '서버 라이선스가 만료되었습니다. (사용 기한: %s)' % valid_until.isoformat(),
                             data, days_left), days_left
    return None, days_left


def _verify_signed(data, public_key):
    signature = data.get('signature')
    if not isinstance(signature, str):
        return False
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError):
        return False
    return verify_signature(canonical_payload(data), signature_bytes, public_key)


def verify_server_license(data, server_id=None, today=None):
    """발급 프로그램이 만든 서버 라이선스(.lic, kind=server)를 검증한다(순수 함수).
    server_id를 주면 그 서버용인지도 확인한다. 성공 시 days_left는 영구면 None."""
    today = today or date.today()
    bad_format = LicenseStatus(False, 'invalid_format', '서버 라이선스 파일 형식을 알 수 없습니다.', None, None)
    if not isinstance(data, dict) or any(field not in data for field in SERVER_LICENSE_FIELDS):
        return bad_format
    if (data.get('format') != LICENSE_FORMAT or data.get('product') != PRODUCT_NAME
            or data.get('kind') != SERVER_LICENSE_KIND):
        return bad_format
    if not _verify_signed(data, LICENSE_PUBLIC_KEY):
        return LicenseStatus(False, 'tampered', '서버 라이선스 파일이 손상되었거나 수정되었습니다.', None, None)
    try:
        seats = int(data.get('seats'))
    except (TypeError, ValueError):
        seats = 0
    if seats < 1:
        return bad_format
    if server_id is not None and normalize_machine_code(data.get('server_id')) != normalize_machine_code(server_id):
        return LicenseStatus(
            False, 'wrong_server',
            '이 서버용 라이선스가 아닙니다. (파일의 서버 ID: %s / 이 서버: %s)' % (data.get('server_id'), server_id),
            data, None,
        )
    failure, days_left = _check_period(data, today)
    if failure is not None:
        return failure
    return LicenseStatus(True, 'ok', '', data, days_left, False, 'server')


def verify_lease(lease, server_license, machine=None, now=None):
    """서버가 준 사용권(lease)과 그 근거인 서버 라이선스를 함께 검증한다(순수 함수, 오프라인 가능)."""
    now = _to_aware(now or datetime.now())
    lic_status = verify_server_license(server_license, today=now.date())
    if not lic_status.ok:
        return lic_status
    tampered = LicenseStatus(False, 'lease_invalid', '서버 사용권이 올바르지 않습니다. 서버에 다시 연결하세요.',
                             server_license, None)
    if not isinstance(lease, dict) or any(field not in lease for field in LEASE_FIELDS):
        return tampered
    if (lease.get('format') != LICENSE_FORMAT or lease.get('product') != PRODUCT_NAME
            or lease.get('kind') != LEASE_KIND):
        return tampered
    try:
        server_key = bytes.fromhex(str(lease.get('server_key') or ''))
    except ValueError:
        return tampered
    if len(server_key) != 32:
        return tampered
    expected_id = normalize_machine_code(server_license.get('server_id'))
    if (normalize_machine_code(server_id_from_public_key(server_key.hex())) != expected_id
            or normalize_machine_code(lease.get('server_id')) != expected_id
            or lease.get('license_id') != server_license.get('license_id')):
        return tampered
    if not _verify_signed(lease, server_key):
        return tampered
    if machine is not None and normalize_machine_code(lease.get('machine')) != normalize_machine_code(machine):
        return LicenseStatus(False, 'wrong_machine', '이 PC용 서버 사용권이 아닙니다.', server_license, None)
    issued_at = _to_aware(_parse_datetime(lease.get('issued_at')))
    lease_until = _to_aware(_parse_datetime(lease.get('lease_until')))
    if issued_at is None or lease_until is None:
        return tampered
    if now < issued_at - CLOCK_TOLERANCE:
        return LicenseStatus(False, 'clock_rollback', 'PC 날짜가 올바르지 않습니다. 날짜/시간을 확인하세요.',
                             server_license, None)
    if now > lease_until:
        return LicenseStatus(False, 'lease_expired',
                             '서버 사용권 기한(%s)이 지났습니다. 라이선스 서버에 연결하세요.'
                             % lease_until.strftime('%Y-%m-%d %H:%M'),
                             server_license, lic_status.days_left)
    return LicenseStatus(True, 'server', '', server_license, lic_status.days_left, False, 'server')


# ---------- 클라이언트 설정/캐시 ----------
def license_server_config_path():
    return license_dir() / 'license_server.json'


def bundled_license_server_config_path():
    """exe 폴더 옆 license_server.json — 설치본 배포 시 서버 주소를 미리 넣어 둘 수 있다."""
    return bundled_license_path().with_name('license_server.json')


def server_lease_cache_path():
    return license_dir() / 'server_lease.json'


def normalize_server_url(url):
    """'192.168.0.210' → 'http://192.168.0.210:8765'. 빈 값은 ''."""
    url = str(url or '').strip().rstrip('/')
    if not url:
        return ''
    if '://' not in url:
        url = 'http://' + url
    scheme, rest = url.split('://', 1)
    host = rest.split('/', 1)[0]
    if ':' not in host.split(']')[-1]:
        rest = host + ':%d' % DEFAULT_SERVER_PORT + rest[len(host):]
    return '%s://%s' % (scheme.lower(), rest)


def _read_json(path):
    try:
        with Path(path).open('r', encoding='utf-8') as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(path))


def get_license_server_url():
    """환경변수 SUMPATH_LICENSE_SERVER → ProgramData 설정 → exe 옆 설정 순. 없으면 ''."""
    env = os.environ.get(LICENSE_SERVER_ENV)
    if env is not None and env.strip():
        return normalize_server_url(env)
    for path in (license_server_config_path(), bundled_license_server_config_path()):
        data = _read_json(path)
        if data and str(data.get('url') or '').strip():
            return normalize_server_url(data.get('url'))
    return ''


def set_license_server_url(url):
    """서버 주소를 저장한다. 빈 값이면 설정과 저장된 사용권을 지운다(서버 라이선스 해제)."""
    url = normalize_server_url(url)
    if not url:
        for path in (license_server_config_path(), server_lease_cache_path()):
            try:
                path.unlink()
            except OSError:
                pass
        restore_local_license()  # v2.3.1: 서버를 그만 쓰면 보관한 로컬 라이선스를 되살린다
        return ''
    _write_json(license_server_config_path(), {'url': url})
    cache = load_server_lease_cache()
    if cache and cache.get('url') != url:
        clear_server_lease_cache()
    return url


def load_server_lease_cache():
    return _read_json(server_lease_cache_path())


def save_server_lease_cache(url, server_license, lease, now=None):
    _write_json(server_lease_cache_path(), {
        'url': url,
        'server_license': server_license,
        'lease': lease,
        'fetched_at': (now or datetime.now()).isoformat(timespec='seconds'),
    })


def clear_server_lease_cache():
    try:
        server_lease_cache_path().unlink()
    except OSError:
        pass


def pc_name():
    return os.environ.get('COMPUTERNAME') or socket.gethostname() or ''


def request_lease(url, machine, client_info=None, timeout=SERVER_REQUEST_TIMEOUT):
    """서버에 사용권을 요청한다. 서버의 판정 dict를 돌려주고, 닿지 못하면 LicenseServerUnavailable."""
    body = {'machine': machine, 'pc_name': pc_name()}
    body.update(client_info or {})
    request = urllib.request.Request(
        url + LEASE_API_PATH,
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    # 사내 NAS 주소로 가는 요청이 PC의 시스템 프록시를 타지 않도록 프록시를 끈다.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024)
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500:
            try:
                data = json.loads(error.read(1024 * 1024).decode('utf-8'))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        raise LicenseServerUnavailable('HTTP %s' % error.code)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise LicenseServerUnavailable(str(error))
    try:
        data = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as error:
        raise LicenseServerUnavailable('bad response: %s' % error)
    if not isinstance(data, dict):
        raise LicenseServerUnavailable('bad response')
    return data


def _server_ok_message(status, lease, offline):
    lease_until = _to_aware(_parse_datetime(lease.get('lease_until')))
    until_text = lease_until.strftime('%Y-%m-%d %H:%M') if lease_until else '?'
    if offline:
        return '라이선스 서버에 연결할 수 없어 저장된 사용권으로 실행합니다. (사용권 기한: %s)' % until_text
    return '서버 라이선스 사용 중 (사용권 기한: %s)' % until_text


def evaluate_server_license(now=None, url=None, client_info=None, online=True):
    """서버 라이선스 판정. 서버에 닿으면 새 사용권을 받아 저장하고, 닿지 못하면 저장된
    사용권이 기한 안일 때만 통과한다. 서버가 명시적으로 거부하면(좌석 초과/차단 등)
    저장된 사용권도 지운다 — 관리자가 PC를 차단하면 다음 연결 때 바로 반영된다."""
    now = now or datetime.now()
    url = normalize_server_url(url) if url else get_license_server_url()
    if not url:
        return LicenseStatus(False, 'server_not_configured', '라이선스 서버가 설정되어 있지 않습니다.', None, None)
    machine = machine_code()
    if not machine:
        return LicenseStatus(False, 'no_machine_code', '이 PC의 PC 코드를 확인할 수 없습니다.', None, None)

    offline_reason = ''
    if online:
        try:
            reply = request_lease(url, machine, client_info=client_info)
        except LicenseServerUnavailable as error:
            reply = None
            offline_reason = str(error)
        if reply is not None:
            if not reply.get('ok'):
                clear_server_lease_cache()
                return LicenseStatus(
                    False, str(reply.get('reason') or 'server_denied'),
                    str(reply.get('message') or '라이선스 서버가 사용을 허용하지 않았습니다.'),
                    reply.get('server_license') if isinstance(reply.get('server_license'), dict) else None,
                    None, False, 'server',
                )
            server_license = reply.get('server_license')
            lease = reply.get('lease')
            status = verify_lease(lease, server_license, machine=machine, now=now)
            if not status.ok:
                return status._replace(source='server')
            save_server_lease_cache(url, server_license, lease, now)
            _touch_last_seen(now)
            return status._replace(message=_server_ok_message(status, lease, False))

    cache = load_server_lease_cache()
    if not cache or cache.get('url') != url:
        return LicenseStatus(
            False, 'server_unreachable',
            '라이선스 서버(%s)에 연결할 수 없습니다. 네트워크와 서버 상태를 확인하세요.%s'
            % (url, ('\n(%s)' % offline_reason) if offline_reason else ''),
            None, None, False, 'server',
        )
    lease = cache.get('lease') or {}
    status = verify_lease(lease, cache.get('server_license'), machine=machine, now=now)
    if not status.ok:
        if status.reason == 'lease_expired':
            status = status._replace(message=status.message + '\n(서버 %s 연결 실패)' % url)
        return status._replace(source='server')
    state = load_license_state()
    if clock_rollback_detected(now, state, None):
        return LicenseStatus(False, 'clock_rollback', 'PC 날짜가 올바르지 않습니다. 날짜/시간을 확인하세요.',
                             status.license, status.days_left, False, 'server')
    _touch_last_seen(now)
    return status._replace(reason='server_offline', message=_server_ok_message(status, lease, True))


def _touch_last_seen(now):
    try:
        state = load_license_state()
        state['last_seen'] = now.isoformat(timespec='seconds')
        save_license_state(state)
    except OSError:
        pass


def connect_license_server(url, now=None, client_info=None):
    """등록 창/About의 '라이선스 서버 연결'. 주소를 정규화해 서버에서 사용권을 받아 본다.
    성공하면 주소를 저장하고, 실패하면 기존 설정을 바꾸지 않는다."""
    url = normalize_server_url(url)
    if not url:
        return LicenseStatus(False, 'server_not_configured', '서버 주소를 입력하세요.', None, None)
    previous = get_license_server_url()
    previous_cache = load_server_lease_cache()
    status = evaluate_server_license(now=now, url=url, client_info=client_info)
    if status.ok and status.reason == 'server':
        set_license_server_url(url)  # 사용권 캐시는 evaluate_server_license가 이미 저장했다
        release_local_license(now)  # v2.3.1: 서버 > 로컬
        return status
    # 실패 — 설정을 원래대로 둔다(evaluate가 거부 응답으로 캐시를 지웠다면 되돌린다).
    if previous_cache and previous == previous_cache.get('url') and not load_server_lease_cache():
        _write_json(server_lease_cache_path(), previous_cache)
    if status.ok:  # 오프라인 캐시 통과는 '연결 성공'이 아니다
        status = LicenseStatus(False, 'server_unreachable',
                               '라이선스 서버(%s)에 연결할 수 없습니다.' % url, None, None, False, 'server')
    return status
