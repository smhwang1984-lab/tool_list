# -*- coding: utf-8 -*-
"""Sum Path 라이선스 서버 — HTTP API (FastAPI). Synology NAS 컨테이너에서 실행한다.

  uvicorn app:app --host 0.0.0.0 --port 8765

환경변수
  SUMPATH_DATA_DIR        데이터 폴더(기본 /data) — 서버 키·서버 라이선스·좌석 DB. 반드시 백업.
  SUMPATH_ADMIN_TOKEN     관리 화면 토큰. 비우면 처음 기동할 때 /data/admin_token.txt 에 만든다.
  SUMPATH_LEASE_DAYS      서버에 연결하지 못해도 PC가 계속 쓸 수 있는 일수(기본 7).
  SUMPATH_SEAT_IDLE_DAYS  이 일수 넘게 접속 없는 PC의 좌석을 새 PC에 자동으로 넘긴다(기본 100, 0=끔).
  SUMPATH_UPDATES_DIR     앱 업데이트 설치 파일 폴더(기본 /updates). NC_Tool_List_Setup_vX.Y.Z.exe 중 최고 버전을 배포.

API
  GET  /api/v1/health                  상태 확인
  GET  /api/v1/info                    서버 ID·라이선스 요약(인증 없음, 좌석 사용 수만 공개)
  POST /api/v1/lease                   PC가 사용권 요청 {machine, pc_name, app_version}
  GET  /api/v1/update                  배포 중인 최신 업데이트 {version, file, size, sha256} (v1.1.0)
  GET  /api/v1/update/download/{file}  설치 파일 내려받기 (v1.1.0)
  GET  /api/v1/admin/devices           (X-Admin-Token) 등록 PC 목록·최근 이력
  POST /api/v1/admin/devices/action    (X-Admin-Token) {machine, action: release|block|unblock}
  POST /api/v1/admin/license           (X-Admin-Token) {text: 서버 라이선스 .lic 내용}
  GET  /                               관리 화면(admin.html)
"""
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from core import DEFAULT_SEAT_IDLE_DAYS, SERVER_VERSION, LicenseServer

HERE = Path(__file__).resolve().parent


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


server = LicenseServer(
    os.environ.get('SUMPATH_DATA_DIR', '/data'),
    lease_days=_env_int('SUMPATH_LEASE_DAYS', 7),
    seat_idle_days=_env_int('SUMPATH_SEAT_IDLE_DAYS', DEFAULT_SEAT_IDLE_DAYS),
    admin_token=os.environ.get('SUMPATH_ADMIN_TOKEN') or None,
    updates_dir=os.environ.get('SUMPATH_UPDATES_DIR', '/updates'),
)
print('[SumPath License Server %s] server_id=%s data=%s' % (SERVER_VERSION, server.server_id, server.data_dir))
if not os.environ.get('SUMPATH_ADMIN_TOKEN'):
    print('[SumPath License Server] 관리 토큰: %s 파일을 확인하세요.' % server.admin_token_path)

app = FastAPI(title='SumPath License Server', version=SERVER_VERSION, docs_url=None, redoc_url=None)


class LeaseReq(BaseModel):
    machine: str = Field(..., max_length=64)
    pc_name: str = Field('', max_length=128)
    app_version: str = Field('', max_length=32)


class DeviceActionReq(BaseModel):
    machine: str = Field(..., max_length=64)
    action: str = Field(..., max_length=16)


class LicenseUploadReq(BaseModel):
    text: str = Field(..., max_length=64 * 1024)


def _require_admin(token):
    if not server.check_admin_token(token):
        raise HTTPException(status_code=401, detail='관리 토큰이 올바르지 않습니다.')


def _client_ip(request):
    return request.client.host if request.client else ''


@app.get('/api/v1/health')
def health():
    return {'ok': True, 'server_version': SERVER_VERSION, 'server_id': server.server_id}


@app.get('/api/v1/info')
def info():
    return {'ok': True, **server.info()}


@app.post('/api/v1/lease')
def lease(req: LeaseReq, request: Request):
    return server.lease(req.machine, req.pc_name, _client_ip(request), req.app_version)


@app.get('/api/v1/update')
def update_info():
    return {'ok': True, 'update': server.latest_update()}


@app.get('/api/v1/update/download/{name}')
def update_download(name: str):
    path = server.update_file_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail='업데이트 파일이 없습니다.')
    return FileResponse(str(path), media_type='application/octet-stream', filename=path.name)


@app.get('/api/v1/admin/devices')
def admin_devices(x_admin_token: str = Header(default='')):
    _require_admin(x_admin_token)
    return {'ok': True, 'info': server.info(), 'devices': server.devices(), 'events': server.events(100)}


@app.post('/api/v1/admin/devices/action')
def admin_device_action(req: DeviceActionReq, x_admin_token: str = Header(default='')):
    _require_admin(x_admin_token)
    return server.set_device(req.machine, req.action)


@app.post('/api/v1/admin/license')
def admin_license(req: LicenseUploadReq, x_admin_token: str = Header(default='')):
    _require_admin(x_admin_token)
    return server.install_license(req.text)


@app.get('/', response_class=HTMLResponse)
def admin_page():
    return (HERE / 'admin.html').read_text(encoding='utf-8')
