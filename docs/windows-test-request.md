# Windows PC 카카오톡 접근성 테스트 요청서

Windows PC에서 아래 저장소의 진단 도구를 실행하고 결과를 공유해 주세요. 이번 테스트는 실제 카카오톡 창의 접근성 구조를 확인하는 단계입니다. 진단 명령은 본문을 추출하거나 메시지를 전송하지 않습니다.

## 대상과 확인된 상태

- 저장소: https://github.com/joint-sangjune-bae/kakaotalk-ax
- 작업 브랜치: `joint-sangjune-bae/windows-accessibility-probe`
- 테스트할 코드: `d24a032f483bfeed22ce461ea2244be06e7f5db3`
- Windows CI: https://github.com/joint-sangjune-bae/kakaotalk-ax/actions/runs/42742620331

macOS에서 전체 71개 테스트가 통과했습니다. Windows CI에서는 Python 3.11 환경의 설치, 실제 `pywinauto` import, 새 합성 테스트 10개, 잘못된 창 핸들 차단을 확인했습니다. 실제 카카오톡의 대화창 구조와 본문 접근 가능성은 이번 PC 테스트로 확인해야 합니다.

## 준비

Windows 11 x64를 우선 사용하고 실제 환경이 다르면 결과에 적어 주세요. Git과 Python 3.11, 설치·로그인된 공식 카카오톡이 필요합니다. PowerShell은 기본 사용자 권한으로 시작해 주세요.

본인 채팅방을 별도 창으로 열고 테스트 메시지는 사용자가 직접 준비해 주세요. 예시는 `안녕하세요. 오늘 일정 확인 부탁드립니다.`, `Meeting is at 3 PM.`, 줄바꿈·이모지가 포함된 짧은 문장, 두 번 연속 보낸 `확인했습니다.`입니다. 실제 고객 대화 대신 이 테스트 채팅방을 사용합니다.

## 설치와 자동 테스트

기존 작업을 보존할 수 있도록 새 폴더에 받습니다. 아래 폴더가 이미 있으면 다른 새 이름을 사용해 주세요. 코드 변경이 섞이지 않도록 검증된 커밋을 선택합니다.

```powershell
git clone --branch joint-sangjune-bae/windows-accessibility-probe https://github.com/joint-sangjune-bae/kakaotalk-ax.git kakaotalk-windows-test
Set-Location kakaotalk-windows-test
git switch --detach d24a032f483bfeed22ce461ea2244be06e7f5db3
git rev-parse HEAD
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[windows-probe]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_windows_probe.py -v
.\.venv\Scripts\kax-win-probe.exe --help
```

Windows에서는 `test_windows_probe.py`의 10개 테스트를 실행합니다. 기존 Mac용 전체 테스트에는 macOS 전용 의존성이 있습니다.

설치나 테스트가 실패하면 해당 단계와 오류를 기록해 주세요. 현재 로그에 사용자 폴더 경로 등이 포함될 수 있으므로 공유할 때 가립니다. 실제 메시지나 계정 정보는 공유 대상에서 제외합니다.

## 채팅방 창 선택과 구조 진단

아래 코드를 실행하면 5초 동안 기다립니다. 그 사이에 별도로 연 본인 채팅방 창을 클릭해 주세요. 코드는 선택한 창의 핸들을 얻으며 클릭이나 키 입력을 자동으로 수행하지 않습니다.

```powershell
if (-not ("KakaoProbeForegroundWindow" -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class KakaoProbeForegroundWindow {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
}
'@
}
Write-Host "5초 안에 본인 채팅방 창을 클릭해 주세요."
Start-Sleep -Seconds 5
$kakaoTestHandle = [KakaoProbeForegroundWindow]::GetForegroundWindow().ToInt64()
```

다음 두 명령으로 UI Automation과 Win32 구조를 각각 확인합니다. 결과는 로컬 JSON 파일에 저장합니다. PowerShell 5의 UTF-8 파일에는 BOM이 포함될 수 있으므로 Python에서 읽을 때는 `utf-8-sig`를 사용합니다.

```powershell
New-Item -ItemType Directory -Force .windows-probe-output | Out-Null
.\.venv\Scripts\kax-win-probe.exe --window-handle $kakaoTestHandle --backend uia | Set-Content -Encoding utf8 .windows-probe-output\uia.json
.\.venv\Scripts\kax-win-probe.exe --window-handle $kakaoTestHandle --backend win32 | Set-Content -Encoding utf8 .windows-probe-output\win32.json
Get-Content -Raw .windows-probe-output\uia.json
Get-Content -Raw .windows-probe-output\win32.json
```

対象이 `KakaoTalk.exe`의 최상위 창으로 확인되어야 진단을 진행합니다. 메인 화면과 대화창의 구분은 사용자가 화면에서 확인합니다. 핸들은 창이 닫히거나 다시 열리면 바뀔 수 있으므로 창 상태가 달라지면 다시 선택해 주세요.

`ok`는 구조 진단 완료, `partial`은 탐색 한도나 일부 조회 오류를 뜻합니다. `messageTextRead=false`, `bodyReadVerified=false`는 현재 도구의 의도된 결과입니다. 본문 수집 성공으로 판단하지 마세요. 패턴 지원만으로 메시지 추출 성공 여부를 단정하지 않습니다.

`partial`이면 현재 결과를 먼저 보관해 주세요. 더 넓은 구조가 필요할 때만 `--max-nodes 500 --max-depth 10 --timeout 30`을 추가해 다시 실행합니다. 오류 코드별 설명은 작업 브랜치의 [Windows 검증 안내](https://github.com/joint-sangjune-bae/kakaotalk-ax/blob/joint-sangjune-bae/windows-accessibility-probe/docs/windows-accessibility.md)에 있습니다.

## 실제 화면에서 확인할 항목

두 백엔드의 구조 진단을 마친 뒤 아래 항목을 확인해 주세요. 스크립트의 결과와 화면에서 직접 확인한 내용을 구분해 적습니다.

1. 진단 중 선택한 대화창과 작성 중인 초안이 유지되는지 확인합니다.
2. 창을 백그라운드로 보내거나 최소화한 상태에서도 진단 결과가 나오는지 확인합니다. 복원하거나 창을 다시 열었다면 대상 핸들을 다시 얻습니다.
3. 가능하면 [Accessibility Insights for Windows](https://accessibilityinsights.io/docs/windows/overview/) 또는 [Inspect](https://learn.microsoft.com/en-us/windows/win32/winauto/inspect-objects)로 테스트 메시지의 말풍선을 조사합니다.
4. 검사 도구의 `Name`, `Value`, `TextPattern` 등의 정보에서 테스트 메시지의 본문이 확인되는지 기록합니다. 어떤 속성에서 확인했는지와 원문 일치 여부만 공유하면 됩니다.
5. 본문을 확인했다면 메시지 구분, 줄바꿈·이모지 보존, 작성자·날짜·시각의 노출 여부를 각각 기록합니다. 같은 본문의 두 메시지를 별개로 구분할 수 있는지도 봅니다.

검사 도구 사용이 어려우면 구조 JSON까지만 공유해 주세요. 확인하지 못한 항목은 `미확인`으로 남깁니다. 이후 구현은 이 결과를 바탕으로 정합니다.

## 결과 공유 양식

아래 양식과 `uia.json`, `win32.json`의 내용을 공유해 주세요. 진단 JSON은 방 이름·본문·계정·프로세스 경로를 출력하지 않도록 설계했습니다. 공유 전 실제 내용을 한 번 확인하고 테스트 외의 개인정보가 보이면 가려 주세요. 본인 테스트 채팅방의 화면이 꼭 필요한 경우에도 다른 채팅방 목록과 프로필은 가립니다.

```text
[실행 환경]
테스트한 커밋:
Windows 버전/빌드:
Python 버전/32·64비트:
카카오톡 버전/프로세스 아키텍처(확인 가능할 때):
화면 배율/카카오톡 표시 언어:

[실행 결과]
설치: 성공 / 실패
새 테스트: 통과 수 / 실패 수
UIA: status, reason, 반환 요소 수, providerErrorCount
Win32: status, reason, 반환 요소 수, providerErrorCount
백그라운드/최소화: 확인한 상태와 결과 / 미확인
기존 초안과 창 상태: 유지 / 변화 있음 / 미확인

[검사 도구에서 직접 확인한 내용]
사용한 검사 도구: 이름 / 미사용
본문 확인: 가능 / 현재 조사 범위에서 확인 안 됨 / 미확인
본문이 보인 속성 또는 패턴:
실제 테스트 메시지와 일치 여부:
메시지 구분/중복 본문 구분:
줄바꿈·이모지 보존:
작성자/날짜/시각: 항목별 결과

[오류와 첨부]
실패한 단계와 고정 오류 코드:
추가 관찰:
UIA JSON:
Win32 JSON:
```

이 테스트에서는 자동 전송·내부 DB 접근·OCR·실제 고객 대화 수집을 진행하지 않습니다. 결과 보고에는 확인한 사실과 다음에 확인할 조건을 나눠 적어 주세요.
