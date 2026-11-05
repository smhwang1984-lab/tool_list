# Sum Path 라이선스 서버 — Synology NAS 배포 가이드 (v1.1.0, 앱 v2.3.1~)

Sum Path(NC Tool List)는 v2.2.9부터 **로컬 라이선스와 서버 라이선스를 함께** 쓸 수 있습니다.

| 방식 | 대상 | 발급 | 동작 |
|---|---|---|---|
| 로컬 라이선스 | PC 한 대 | PC 코드로 `.lic` 발급 → PC에 등록 | 서버 없이 그 PC에서만 동작(기존 그대로) |
| 서버 라이선스 | 사내 여러 PC | 서버 ID + 좌석 수로 `.lic` 발급 → NAS에 등록 | PC가 NAS 서버에서 사용권을 받아 동작. 좌석 수만큼 PC 사용 |

앱 판정 순서(v2.3.1~): 서버 주소가 설정된 PC는 **서버 라이선스 → 30일 체험판**(서버 > 로컬), 서버 주소가 없는 PC는 **로컬 라이선스 → 30일 체험판**입니다.
서버에서 사용권을 받으면 그 PC의 로컬 라이선스는 **해제(보관)**됩니다(`license.lic` → `license_released.lic`). 서버가 거부(차단·좌석 없음·만료)하면 로컬로 돌아가지 않고, 서버에 연결할 수 없고 저장된 사용권(7일)까지 끝났을 때만 보관된 로컬 라이선스를 비상용으로 씁니다. About에서 서버 연결을 해제하면 로컬 라이선스가 되살아납니다.

```
각 PC (NC_Tool_List.exe) ──HTTP 8765──▶ sumpath-license 컨테이너 (NAS) ──▶ /data (키·라이선스·좌석 DB)
```

TSERP API 서버(8000번)와는 완전히 별개 컨테이너이며 DB(MariaDB)도 쓰지 않습니다(SQLite 파일).

---

## 1. NAS 폴더 만들기

File Station에서 예를 들어 다음 폴더를 만듭니다.

```
/volume1/docker/SumPath_License_Server/
├── app.py  core.py  sumpath_license.py  admin.html
├── Dockerfile  docker-compose.yml  requirements.txt  .env.example
├── data/          ← ★ 빈 폴더를 먼저 만든다(없으면 컨테이너 기동 실패)
└── updates/       ← ★ v1.1.0: 앱 업데이트 설치 파일을 넣는 폴더(빈 폴더라도 먼저 만든다)
```

Windows 탐색기 경로로는 `\\192.168.0.210\docker\SumPath_License_Server` 입니다(`updates`는 `\\192.168.0.210\docker\SumPath_License_Server\updates`).

저장소의 `license_server/` 폴더 내용을 그대로 복사하고, `data` 폴더만 새로 만듭니다.

## 2. 컨테이너 만들기 (Container Manager)

1. Container Manager → **프로젝트** → **생성**
2. 프로젝트 이름: `sumpathlicense`(**영어 소문자만** — NAS에 따라 `-`·대문자를 거부한다. 이름은 표시용이라 아무거나 돼도 서버 ID와 무관), 경로: 위 폴더, 소스: **기존 docker-compose.yml 사용**
3. 다음 → 완료. 처음에는 이미지 빌드(PyPI에서 fastapi/uvicorn/cryptography 설치) 때문에 1~3분 걸립니다.
4. 컨테이너 로그에 다음 줄이 보이면 정상입니다.
   ```
   [SumPath License Server 1.1.0] server_id=XXXX-XXXX-XXXX-XXXX data=/data
   ```

(선택) `.env.example`을 `.env`로 복사해 관리 토큰·오프라인 허용 일수를 바꿀 수 있습니다. 바꾼 뒤에는 프로젝트를 **중지 → 빌드/시작**합니다.

## 3. 방화벽

NAS 제어판 → 보안 → 방화벽을 쓰고 있다면 **TCP 8765**를 사내 LAN 대역에서 허용합니다.
외부(인터넷) 공개는 필요 없습니다 — 공유기 포트포워딩을 하지 마세요.

## 4. 관리 화면 접속 & 서버 ID 확인

브라우저에서 `http://NAS주소:8765` (예: `http://192.168.0.210:8765`)

- **서버 ID**: 화면 맨 위에 표시. [서버 ID 복사]로 복사합니다.
- **관리 토큰**: NAS의 `data/admin_token.txt` 파일 내용(처음 기동 때 자동 생성). `.env`에 `SUMPATH_ADMIN_TOKEN`을 넣었다면 그 값.

## 5. 서버 라이선스 발급 & 등록

1. 발급 PC(USB)에서 **SumPath License Maker v1.4.0** 실행 → **서버 라이선스** 탭
2. 사용자, **서버 ID**, **좌석 수(PC 대수)**, 기간, 시작일 입력 → [서버 라이선스 발급]
3. `발급된 라이선스\SumPath_SERVER_....lic` 파일이 생깁니다.
4. 관리 화면 → 관리자 로그인(토큰) → **서버 라이선스 등록/교체**에 그 파일을 올립니다.
   - 다른 서버 ID용 파일, 위조 파일, 이미 등록된 것보다 먼저 발급된 파일은 거부됩니다.
   - 좌석을 늘리거나 기간을 연장할 때도 새로 발급해 같은 방법으로 교체합니다.
   - 관리 화면 대신 `data/server_license.lic` 이름으로 직접 넣어도 됩니다.

## 6. 각 PC 연결

Sum Path 실행 →
- 라이선스가 없거나 체험판이 끝난 PC: 등록 창의 **[라이선스 서버 연결...]** → `192.168.0.210` 입력
- 이미 쓰는 PC(체험판 등): **About → 라이선스 → [라이선스 서버 설정...]**

주소만 넣으면 `http://…:8765`가 자동으로 붙습니다. 연결에 성공해야만 설정이 저장됩니다.

여러 PC에 미리 넣어 두려면(선택):
- 설치 폴더 `C:\NC_Tool_List\license_server.json` 에 `{"url": "192.168.0.210"}` 를 두거나
- 환경변수 `SUMPATH_LICENSE_SERVER=192.168.0.210`

PC 설정은 `C:\ProgramData\NC Tool List\license_server.json`, 받은 사용권은 같은 폴더의 `server_lease.json`에 저장됩니다.

## 7. 운영 규칙

| 항목 | 기본값 | 설명 |
|---|---|---|
| 좌석 | 라이선스의 `seats` | 사용권을 받은 PC 1대 = 1좌석. 차단된 PC는 좌석에서 빠짐 |
| 오프라인 허용 | 7일 (`SUMPATH_LEASE_DAYS`) | NAS가 꺼져도 마지막 연결 후 7일까지 계속 사용. 서버 라이선스 만료일은 넘지 않음 |
| 자동 회수 | **100일** (`SUMPATH_SEAT_IDLE_DAYS`, 0=끔) | 좌석이 꽉 찼을 때 100일 넘게 접속 없는 PC의 좌석을 새 PC에 넘김(v1.1.0에서 30일 → 100일). 항상 오프라인 허용 일수보다 길게 맞춰짐 |
| 재확인 | 앱 시작 시 + 실행 중 1시간마다 | 그때마다 사용권을 7일로 갱신 |

관리 화면의 PC 목록에서:
- **좌석 해제**: 그 PC를 목록에서 지웁니다(교체·폐기한 PC). 다시 접속하면 좌석이 남아 있을 때 다시 등록됩니다.
- **차단**: 그 PC는 다음 연결 때부터 거부되고, 저장된 사용권도 지워집니다. (네트워크에서 떨어진 채라면 남은 오프라인 허용 기간까지는 쓸 수 있습니다.)
- **차단 해제**: 목록에서 지웁니다. 좌석이 있으면 다음 접속 때 다시 등록됩니다.

## 8. 앱 업데이트 배포 (v1.1.0)

1. 새 설치 파일 `NC_Tool_List_Setup_vX.Y.Z.exe`를 `\\192.168.0.210\docker\SumPath_License_Server\updates` 폴더에 복사합니다(이름을 바꾸지 마세요).
   - 여러 버전이 있으면 **가장 높은 버전**을 배포합니다. 이전 파일은 지워도 되고 남겨 둬도 됩니다.
   - 컨테이너를 다시 시작할 필요는 없습니다. 관리 화면의 "배포 중인 업데이트"에 바로 표시됩니다.
2. 서버 주소가 설정된 각 PC는 **앱을 시작할 때** 서버에 새 버전을 묻고, 있으면 "업데이트 권장" 창을 띄웁니다.
   - [지금 업데이트] → 서버에서 내려받아 크기·SHA-256을 확인한 뒤 설치 마법사를 띄우고 앱을 종료합니다(관리자 권한 필요).
   - [나중에] → 다음에 앱을 시작할 때 다시 묻습니다.
3. 서버 주소가 없는 PC는 기존처럼 About의 업데이트 경로(공유 폴더)를 봅니다.

```
http://NAS주소:8765/api/v1/update   → {"ok": true, "update": {"version": "2.3.1", "file": "...", "size": ..., "sha256": "..."}}
```

## 9. 백업 (중요)

`data/` 폴더 전체를 백업합니다(Hyper Backup 대상에 추가).

- `server_key.pem` — 서버 개인키. **지우거나 바꾸면 서버 ID가 바뀌어** 서버 라이선스를 새로 발급받아야 합니다. 외부에 유출하지 마세요.
- `server_license.lic` — 등록된 서버 라이선스
- `seats.sqlite3` — 좌석(PC) 목록·이력
- `admin_token.txt` — 관리 토큰

NAS를 바꿀 때는 `data/` 폴더를 그대로 옮기면 서버 ID와 좌석이 유지됩니다(PC 쪽 주소만 바뀌면 About에서 다시 설정).

## 10. 점검

```
http://NAS주소:8765/api/v1/health   → {"ok": true, "server_version": "1.1.0", "server_id": "..."}
http://NAS주소:8765/api/v1/info     → 라이선스·좌석 요약
```

| 증상 | 확인 |
|---|---|
| PC에서 "라이선스 서버에 연결할 수 없습니다" | NAS 주소/포트(8765), 방화벽, 컨테이너 실행 상태 |
| "서버 라이선스가 등록되지 않았습니다" | 5번 단계(관리 화면에서 등록) |
| "좌석이 모두 사용 중" | 관리 화면에서 안 쓰는 PC 좌석 해제, 또는 좌석 수를 늘린 라이선스 재발급 |
| "이 서버용 라이선스가 아닙니다" | 발급 때 넣은 서버 ID와 관리 화면의 서버 ID 비교(`data/server_key.pem`이 바뀌지 않았는지) |
| "PC 날짜가 올바르지 않습니다" | PC/NAS 시간 동기화(NAS 제어판 → 지역 옵션 → NTP) |
| 업데이트 창이 안 뜸 | 관리 화면 "배포 중인 업데이트" 확인 — 파일 이름 형식(`NC_Tool_List_Setup_v2.3.1.exe`), compose의 `./updates:/updates:ro`, PC의 서버 주소 설정 |

## 11. v1.0.0 → v1.1.0 올리기

1. `license_server/`의 새 파일(app.py, core.py, sumpath_license.py, admin.html, docker-compose.yml, .env.example)을 NAS 폴더에 덮어씁니다. **`data/`는 건드리지 않습니다.**
2. `updates` 폴더가 있는지 확인합니다(없으면 만든다).
3. `.env`를 만들어 `SUMPATH_SEAT_IDLE_DAYS=30`을 넣어 두었다면 `100`으로 바꿉니다(없으면 그대로 — 기본값 100).
4. Container Manager → 프로젝트 `sumpathlicense` → **중지 → 빌드 → 시작**. 로그에 `[SumPath License Server 1.1.0]`이 보이면 완료. 서버 ID와 좌석은 그대로입니다.
