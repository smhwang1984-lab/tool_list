# -*- coding: utf-8 -*-
"""v2.3.1: 시작할 때 업데이트 감지 — 라이선스 서버(NAS) 배포 + 공유 폴더 (Qt 없음, 테스트 가능).

· 라이선스 서버 주소가 설정된 PC: 서버 `GET /api/v1/update`로 배포 중인 최신 설치 파일을 묻는다
  (NAS `SumPath_License_Server/updates` 폴더 → 컨테이너 `/updates`). 내려받은 뒤 크기·SHA-256을
  서버 값과 비교하고, 맞을 때만 설치 마법사를 띄운다(v2.3.1_PLAN.md D-1 (a), D-3 (b)).
· 서버가 없거나 서버에 업데이트가 없으면 About의 업데이트 경로(공유 폴더)에서 찾는다(기존 방식).
"""
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UPDATE_API_PATH = '/api/v1/update'
UPDATE_DOWNLOAD_PATH = '/api/v1/update/download/'
UPDATE_REQUEST_TIMEOUT = 4  # 초 — 시작 확인은 백그라운드라 화면은 멈추지 않는다
DOWNLOAD_TIMEOUT = 30
INSTALLER_RE = re.compile(r'^NC_Tool_List_Setup_v(\d+)\.(\d+)\.(\d+)\.exe$', re.I)


class UpdateError(Exception):
    pass


class UpdateCancelled(UpdateError):
    pass


def version_tuple(text):
    try:
        parts = tuple(int(p) for p in str(text).strip().lstrip('vV').split('.'))
    except (TypeError, ValueError):
        return None
    return parts if len(parts) == 3 else None


def _opener():
    # 사내 NAS로 가는 요청이 시스템 프록시를 타지 않게 한다(라이선스 요청과 같음).
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_server_update(server_url, timeout=UPDATE_REQUEST_TIMEOUT):
    """서버가 배포 중인 최신 업데이트 dict({version, file, size, sha256}) 또는 None.
    서버에 닿지 못하거나 응답이 이상하면 None(업데이트 확인 실패는 조용히 넘어간다)."""
    if not server_url:
        return None
    try:
        with _opener().open(server_url.rstrip('/') + UPDATE_API_PATH, timeout=timeout) as resp:
            data = json.loads(resp.read(256 * 1024).decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError):
        return None
    info = data.get('update') if isinstance(data, dict) else None
    if not isinstance(info, dict):
        return None
    if not INSTALLER_RE.match(str(info.get('file') or '')) or version_tuple(info.get('version')) is None:
        return None
    try:
        info['size'] = int(info.get('size'))
    except (TypeError, ValueError):
        return None
    if not re.fullmatch(r'[0-9a-fA-F]{64}', str(info.get('sha256') or '')):
        return None
    return info


def find_update(current_version, server_url=None, share_root=None, share_finder=None):
    """현재 버전보다 높은 업데이트를 찾는다. 서버(설정돼 있으면) → 공유 폴더 순.

    반환: {'source': 'server'|'share', 'version': (x, y, z), 'version_text', 'file',
           'server_url'/'size'/'sha256' 또는 'path'} 또는 None.
    share_finder(root) → (Path, version_tuple) | None (NC_Tool_List.find_latest_installer)."""
    current = version_tuple(current_version)
    if current is None:
        return None
    info = fetch_server_update(server_url) if server_url else None
    if info is not None:
        version = version_tuple(info['version'])
        if version > current:
            return {
                'source': 'server', 'version': version, 'version_text': '.'.join(map(str, version)),
                'file': info['file'], 'size': info['size'], 'sha256': info['sha256'].lower(),
                'server_url': server_url.rstrip('/'),
            }
    if share_root and share_finder is not None:
        try:
            found = share_finder(share_root)
        except OSError:
            found = None
        if found is not None and tuple(found[1]) > current:
            path, version = found
            return {
                'source': 'share', 'version': tuple(version), 'version_text': '.'.join(map(str, version)),
                'file': Path(path).name, 'path': str(path),
            }
    return None


def download_server_update(candidate, dest_dir=None, progress=None, cancelled=None,
                           timeout=DOWNLOAD_TIMEOUT, chunk_size=256 * 1024):
    """서버 업데이트를 임시 폴더로 내려받고 크기·SHA-256을 확인한다. 성공하면 파일 경로.

    progress(done_bytes, total_bytes), cancelled() → True면 중단(UpdateCancelled).
    확인에 실패하면 받은 파일을 지우고 UpdateError."""
    dest_dir = Path(dest_dir or tempfile.gettempdir())
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / candidate['file']
    part = final.with_name(final.name + '.part')
    url = candidate['server_url'] + UPDATE_DOWNLOAD_PATH + urllib.parse.quote(candidate['file'])
    total = int(candidate['size'])
    digest = hashlib.sha256()
    done = 0
    try:
        with _opener().open(url, timeout=timeout) as resp, part.open('wb') as fp:
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateCancelled('업데이트 다운로드를 취소했습니다.')
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                fp.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if done > total:
                    raise UpdateError('업데이트 파일 크기가 서버 정보와 다릅니다.')
                if progress is not None:
                    progress(done, total)
        if done != total:
            raise UpdateError('업데이트 파일을 끝까지 받지 못했습니다. (%d / %d 바이트)' % (done, total))
        if digest.hexdigest() != candidate['sha256']:
            raise UpdateError('업데이트 파일 검증(SHA-256)에 실패했습니다. 파일이 손상되었을 수 있습니다.')
        os.replace(str(part), str(final))
        return final
    except (urllib.error.URLError, OSError) as error:
        _remove(part)
        raise UpdateError('업데이트 파일을 받지 못했습니다.\n%s' % error)
    except UpdateError:
        _remove(part)
        raise


def _remove(path):
    try:
        Path(path).unlink()
    except OSError:
        pass
