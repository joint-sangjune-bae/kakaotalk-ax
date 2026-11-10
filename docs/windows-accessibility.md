# Windows 카카오톡 접근성 검증

Windows 카카오톡이 메시지 본문을 어떤 접근성 정보로 노출하는지 먼저 확인합니다.
현재 제공하는 `kax-win-probe`는 선택한 창의 구조와 지원 패턴을 조사하는 실험용 명령입니다.
대화 본문 추출·방 열기·검색·스크롤은 후속 구현 범위입니다.

## 현재 상태

| 항목 | 상태 |
| --- | --- |
| Windows용 독립 진단 명령 | 구현됨 |
| 민감한 텍스트 출력 방지와 범위 제한 | 합성 테스트로 검증 |
| macOS에서 Windows 명령의 실행 차단 | 자동 검증 |
| 실제 Windows의 UI Automation·Win32 조회 | 미실행 |
| Windows 카카오톡 본문·작성자·시각 추출 | 미구현·미확인 |
| Mac용 CLI·MCP | 기존 구현 유지 |

`ok`는 지정한 범위의 구조를 조사했다는 뜻입니다. `bodyReadVerified`와
`messageTextRead`는 항상 `false`이며, 본문 수집이 검증됐다는 뜻으로 해석하지 않습니다.

## 참고한 코드

이 저장소는 [HyunSeob/kakaotalk-ax](https://github.com/HyunSeob/kakaotalk-ax)의 포크입니다.
시작 커밋은 `70c0944f3324b243cb60cf94b1328ff295bbbbe5`이며 원본 MIT 라이선스를 보존합니다.
접근성 구조 조사와 결과 확인 순서는
[mac-app-ax](https://github.com/HyunSeob/skills/tree/4aef542dd9d1aa894bd64cbc03e80e35a87c3c64/skills/mac-app-ax)를 참고합니다.

Mac 구현의 `fcntl`·Swift 브리지를 바로 불러오면 Windows에서 동작하지 않습니다.
진단 코드는 `kakaotalk_windows_probe`로 분리해 Mac 모듈을 가져오지 않습니다.
메시지 데이터 형식이나 행 수 제한은 실제 Windows 결과를 확인한 뒤 정합니다.

## Windows에서 준비하기

첫 검증 환경은 Windows 11 x64와 Python 3.11을 제안합니다. 실제 앱 호환성은 실행 후 기록합니다.
Windows에 설치·로그인된 공식 카카오톡과 사용자가 확인할 본인 테스트 채팅방을 준비합니다.
명령은 Windows의 PowerShell에서 실행합니다. WSL이나 macOS 실행은 실제 Windows 앱 검증을 대신하지 않습니다.

```powershell
git clone --branch joint-sangjune-bae/windows-accessibility-probe https://github.com/joint-sangjune-bae/kakaotalk-ax.git
cd kakaotalk-ax
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[windows-probe]"
.\.venv\Scripts\kax-win-probe.exe --help
```

`pywinauto==0.6.9`를 Windows 전용 선택 의존성으로 추가했습니다.
이 핀과 설치 절차의 실제 Windows 실행은 아직 확인하지 않았습니다.

## 구조 조사 순서

1. [Accessibility Insights for Windows](https://accessibilityinsights.io/docs/windows/overview/) 또는
   [Inspect](https://learn.microsoft.com/en-us/windows/win32/winauto/inspect-objects)로 본인 채팅방을 선택합니다.
2. 해당 채팅방의 최상위 창에 속한 `NativeWindowHandle`을 확인합니다.
   하위 요소가 0을 반환하면 상위의 최상위 창에서 확인합니다.
3. 확인한 핸들을 진단 명령에 전달합니다. 아래 `0x1234`는 형식 예시이며 실제 값으로 바꿉니다.
4. UI Automation 결과를 확인하고 Win32 결과와 비교합니다.

```powershell
.\.venv\Scripts\kax-win-probe.exe --window-handle 0x1234 --backend uia
.\.venv\Scripts\kax-win-probe.exe --window-handle 0x1234 --backend win32
```

대상은 `KakaoTalk.exe`가 소유한 최상위 창으로 제한합니다. 이는 프로세스 파일 이름 확인이며
게시자 서명이나 해당 창이 실제 대화창인지까지 보증하는 판정은 아닙니다.
본인 테스트 채팅방 선택 여부는 검사 도구와 화면에서 직접 확인합니다.

결과에는 요소의 상대 경로, 허용 목록에 있는 요소 종류, UIA 패턴의 지원 여부만 들어갑니다.
창 제목·방 이름·자동화 ID·입력값·본문·프로세스 경로와 핸들은 출력하지 않습니다.
Edit·ComboBox·RichEdit로 식별한 입력 요소는 하위 탐색을 생략합니다.
`patterns.text=available`도 본문을 읽었다는 증거가 아니며, `unsupported` 하나만으로 다른 읽기 경로까지 배제하지 않습니다.

UIA 패턴의 `available`은 인터페이스를 얻었다는 뜻이고 `unsupported`는 해당 패턴의 미지원,
`unavailable`은 조회 중 오류를 뜻합니다. Win32 결과에는 UIA 패턴 필드가 없습니다.

기본 한도는 200개 요소·깊이 6·대기 15초입니다. 범위가 잘리거나 공급자 오류가 발생하면
`partial`과 범위 정보를 반환합니다. 필요할 때 `--max-nodes`(1..1000),
`--max-depth`(1..20), `--timeout`(1..60초)을 지정합니다.
시간 초과 시 진단용 자식 프로세스만 종료합니다. 카카오톡 프로세스는 종료하지 않습니다.

`ok`·`partial`의 종료 코드는 0, 차단·실패·시간 초과는 1입니다. 인수 오류는 2입니다.

## 결과별 다음 조치

| 결과 | 다음 조치 |
| --- | --- |
| `windows_required` | Windows의 Python에서 실행합니다. |
| `top_level_window_or_process_unavailable` | 최상위 창 핸들과 창 유지 상태, 프로세스 조회 권한을 확인합니다. |
| `target_process_mismatch` | 공식 카카오톡 프로세스의 창을 다시 선택합니다. |
| `target_process_changed` | 창을 다시 식별한 뒤 조회합니다. |
| `windows_probe_dependencies_required` | 같은 가상환경에 `.[windows-probe]`를 설치합니다. |
| `probe_time_limit` | 조사 범위를 줄이고 앱 응답 상태를 확인합니다. |
| `accessibility_probe_failed`·`probe_worker_failed`·`probe_worker_exited` | 앱 버전·권한 차이·백엔드를 기록하고 재현합니다. |
| 구조가 일부만 보임 | 검사 도구 결과와 비교하고 다른 백엔드도 확인합니다. |

기본 권한으로 시작하고 권한을 높여야 한다면 필요한 이유를 먼저 확인합니다.
창 최소화·백그라운드·잠금 화면·연결이 끊긴 원격 세션에서의 동작은 각각 따로 검증합니다.

## 실제 앱 검증 기록

다음 내용을 기록합니다. 실제 대화 본문이나 계정 정보는 저장소·이슈·공개 로그에 올리지 않습니다.
테스트 메시지는 본인 채팅방의 비민감한 한글·영문·줄바꿈·이모지 예시를 사용합니다.

- Windows 버전·빌드와 Python 버전·아키텍처
- 카카오톡 버전·프로세스 아키텍처, 표시 언어·화면 배율
- 백엔드·탐색 한도·상태 코드·반환 요소 수·오류 수
- 화면에서 확인한 대화 영역과 진단 구조의 대응 여부
- 본문·메시지 구분·작성자·날짜·시각별 확인 가능 여부
- 새 메시지·스크롤·최소화 등에 따른 결과 변화

본인 대화의 로컬 검증부터 진행합니다. 타인의 정보 저장·외부 전송·고객 배포를 계획하면
데이터 이용 권한과 카카오 서비스 이용 조건을 따로 확인합니다.
접근성 API를 사용한다는 사실만으로 서비스의 허가를 받은 것으로 판단하지 않습니다.

## 구현 순서와 완료 조건

1. **구조 확인:** 실제 Windows에서 선택한 대화창을 두 백엔드로 조사하고 재현 절차를 기록합니다.
2. **본문 읽기:** 확인된 대화 영역에서 본문을 추출하고 실제 화면과 비교합니다. 입력창 초안과 구분하고
   같은 본문이 반복된 서로 다른 메시지도 보존합니다.
3. **범위와 메타데이터:** 확인된 값만 반환합니다. 작성자·생략된 시각은 추정하지 않으며,
   화면 위치·스냅샷을 메시지 고유 ID로 취급하지 않습니다.
4. **화면 이동:** 방 검색·열기·스크롤을 하나씩 검증하며 기존 초안과 창 상태를 보존합니다.
5. **연결:** 안정적으로 확인된 읽기 기능을 CLI·MCP에 연결합니다.

전체 기록 수집, 전송, 원본 첨부 다운로드, OCR, 서버·CRM 동기화는 별도 확장 항목입니다.
본문 접근이 어렵다면 관찰한 한계와 대화 내보내기·OCR 등의 대안을 비교한 뒤 방향을 정합니다.

## 자동 검증

```bash
python -m unittest discover -s tests -p 'test_windows_probe.py' -v
python -m unittest discover -s tests -v
```

새 테스트는 합성 요소와 별도 프로세스로 모듈 독립성, 텍스트 비출력, 잘못된 대상 차단,
입력 요소 생략, 탐색 한도와 공급자 오류를 검사합니다. 실제 Windows 카카오톡 호환성 증거는 별도로 남깁니다.

2026-11-10 macOS·Python 3.14.7에서 전체 71개 테스트와 CLI 도움말·OS 차단 검사를 통과했습니다.
Windows CI는 선택 의존성 설치, 실제 `pywinauto` import, 합성 테스트와 잘못된 창 핸들의 차단을 검사합니다.
CI에도 카카오톡은 설치하지 않으므로 본문 조회나 실제 대화창 탐색의 검증을 대신하지 않습니다.
