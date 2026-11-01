# Sum Path(NC Tool List) 홍보영상 만들기

실제 앱 화면을 자동으로 캡처해서 **쇼츠(세로 1080×1920, 약 45초)** 와 **설명영상(가로 1920×1080, 약 3분)** 을 만듭니다.
화면은 전부 이 저장소의 실제 프로그램(`NC_Tool_List.py`)을 띄워서 찍은 것이고, 배경음악도 코드로 직접 합성하므로 저작권 걱정이 없습니다.

| 결과 파일 | 내용 |
|---|---|
| `promo/output/SumPath_Shorts.mp4` (+ `.srt`) | 쇼츠: 주석 → 툴리스트, 버튼 하나로 산출, 소재·형상 시뮬레이션, 장비별 모션, 저사양 PC |
| `promo/output/SumPath_Explainer.mp4` (+ `.srt`) | 3분 설명: 현장 고민 → 핵심 기능 4가지 → CATIA PPTABLE 주석 설정 → 툴리스트(밀링·선반) → 5축 실가공 프로그램 → 장비 타입 → 소재 설정 → 밀링·선반 형상 시뮬레이션 → 저사양 PC |

## Windows 11에서 실행

PowerShell을 열고 저장소 폴더에서:

```powershell
# 1) 패키지 (한 번만)
py -m pip install -r promo\requirements-promo.txt

# 2) 실제 앱 화면 캡처 — 앱 창이 잠깐 떴다가 자동으로 닫힙니다 (약 1분)
py promo\capture_app.py

# 3) 영상 합성 — 자막 + 배경음악
py promo\make_video.py --all

# 3') 한국어 AI 나레이션까지 넣기 (인터넷 필요, edge-tts)
py promo\make_video.py --all --tts
py promo\make_video.py --all --tts --voice ko-KR-InJoonNeural   # 남성 목소리
```

- ffmpeg가 없으면 `imageio-ffmpeg` 패키지가 대신 씁니다. 직접 설치하려면 `winget install Gyan.FFmpeg`.
- 글꼴은 Windows 기본 **맑은 고딕**(`malgunbd.ttf`)과 **Consolas**를 씁니다.
- 빠르게 구성만 확인하려면 `--preview`(절반 해상도·12fps). 하나만 만들려면 `--shorts` 또는 `--long`.
- CPU 코어 수만큼 병렬로 렌더링합니다. 4코어 기준 쇼츠 약 1.5분, 3분 영상 약 6~7분.
- `--tts`를 쓰면 장면 길이를 나레이션 길이에 맞춰 자동으로 늘립니다. 영어 약어는 `make_video.py`의 `TTS_PRONOUNCE` 표에 맞춰 바꿔 읽습니다(예: `PPTABLE` → "피피 테이블").

## 구성

| 파일 | 역할 |
|---|---|
| `capture_app.py` | 앱(App 창)을 직접 띄워 사람이 하는 순서대로 조작하고 화면을 PNG로 저장. 라이선스 창은 건너뛰고, 설정(QSettings)은 임시 폴더를 써서 **이 PC의 실제 설정을 건드리지 않습니다.** |
| `demo_nc/make_demo_programs.py` | 영상용 데모 NC 프로그램 생성(밀링 5공정 / 선반 4공정). CATIA 포스트(PPTABLE)가 출력하는 공구 정보 주석 형식을 그대로 따릅니다. `.nc`는 `.gitignore` 대상이라 캡처할 때마다 새로 만듭니다. |
| `make_video.py` | 장면 구성·나레이션 문구·자막·화면 이동을 정의하고 영상 2편을 렌더링 |
| `video_kit.py` | 글꼴, 그리기, 화면 확대 이동, 배경음악 합성, ffmpeg 인코딩/합치기 |

실가공 5축 장면에는 저장소의 `ncdata.nc`(32,903줄)를 그대로 씁니다.

## 문구·장면 고치기

- 나레이션/자막: `make_video.py`의 `long_scenes()` / `short_scenes()` 안 `Scene(길이초, '문장', 그리기함수, '제목')`.
- 장면 길이: 같은 자리의 첫 숫자. 자막은 문장 길이에 비례해 자동으로 나눠 표시됩니다.
- 색: `video_kit.py` 위쪽 `ACCENT`(파랑) / `ACCENT2`(주황).

## 참고(영상 내용과 실제 동작)

- 형상 시뮬레이션 장면은 실제 시뮬레이션 엔진 결과입니다. 앱에서는 **공정 필터에서 고른 공정까지의 누적 형상**을 보여 주고, 영상에서는 같은 엔진을 프레임마다 조금씩 전진시켜 깎여 나가는 과정을 연속 화면으로 만들었습니다.
- 데모 프로그램(블록 100×80×30, 축 Ø60×80)은 영상용 예제이고, 실제 공구 조건은 예시 값입니다.
