# Sum Path 릴리스·Play 콘솔 준비 (P7)

## 1. 서명 키 (한 번만)
1. `make_keystore.bat` 실행 → `sumpath-upload.jks` 생성(비밀번호는 keytool 이 직접 묻는다).
2. `keystore.properties.example` 을 `keystore.properties` 로 복사해 비밀번호를 적는다.
3. `sumpath-upload.jks`, `keystore.properties` 는 **커밋 금지**(.gitignore 에 등록됨). **키스토어와 비밀번호는 별도 안전한 곳(비밀번호 관리자, 외장 저장소)에 백업.**
   잃으면 같은 앱으로 업데이트를 올릴 수 없다. Play 앱 서명(Play App Signing)을 쓰면 이 키는 "업로드 키"라서 분실 시 Google 에 재설정을 요청할 수 있다.

## 2. 빌드
| 용도 | 명령 | 결과 |
|---|---|---|
| 테스트 | `build_apk.bat` | `out\SumPath_vX.Y.Z_debug.apk` |
| 사내 직접 배포 | `build_release.bat` | `out\SumPath_vX.Y.Z.apk` (서명됨) |
| Play 스토어 | `build_aab.bat` | `out\SumPath_vX.Y.Z.aab` (서명됨) |

`keystore.properties` 가 없으면 release 는 서명 없이 만들어지고 bat 은 중단한다.

## 3. 최종 점검표 (배포 전)
- [ ] `npm test` 전부 통과, `npm run build` 성공
- [ ] 실기기: 파일 열기(내부·USB)·저장, 툴리스트 산출, PDF 출력, Viewer 재생(밀링·선반), 소재 시뮬레이션, STL 내보내기
- [ ] 기본 앱 연결(.nc/.mpf/.tap …)로 파일이 열린다
- [ ] 버전: `package.json` · `src/version.ts` · `android/app/build.gradle`(versionCode 증가) 일치
- [ ] release APK 를 기기에 설치해 실행(`adb install -r`)
- [ ] 개인정보·권한: 이 앱은 네트워크 권한이 없고 파일은 사용자가 고른 위치에서만 읽고 쓴다

## 4. Play 콘솔에서 준비할 것 (등록은 사용자가 결정)
- 앱 이름: Sum Path (패키지 `com.sumpath.nctoollist`)
- 짧은 설명(80자) · 자세한 설명(4000자)
- 앱 아이콘 512×512 PNG, 그래픽 이미지 1024×500 PNG
- 스크린샷: 휴대전화 최소 2장(권장 4~8장) — 툴리스트, Viewer, 소재 시뮬레이션, PDF
- 개인정보처리방침 URL — 수집 정보 없음(오프라인 도구)이라는 내용으로 공개 페이지가 필요
- 앱 콘텐츠 설문: 광고 없음, 데이터 안전 "수집·공유 없음", 대상 연령, 콘텐츠 등급
- 대상 API 수준: 현재 target/compile SDK 36 (콘솔 요구 최신 기준 충족)
- 개발자 계정(등록비 25 USD, 1회), 신규 개인 계정은 비공개 테스트 12명·14일 요건이 있을 수 있음 — 콘솔 안내 확인
- 라이선스 기능은 보류 중이라 포함하지 않는다
