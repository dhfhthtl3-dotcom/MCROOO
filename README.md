# 🎮 GameMacro (게임 매크로 v2.4.2)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?style=flat&logo=windows&logoColor=white)](https://microsoft.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Release](https://img.shields.io/badge/Release-v2.4.2-brightgreen.svg)](https://github.com/dhfhthtl3-dotcom/MCROOO/releases/latest)
[![Download](https://img.shields.io/badge/Download-GameMacro.zip-blue.svg)](https://github.com/dhfhthtl3-dotcom/MCROOO/releases/download/v2.4.2/GameMacro-v2.4.2-windows-x64.zip)

> **컴퓨터 비전(OpenCV)과 Windows Win32 API를 결합한 차세대 멀티 타겟 감지, 4단계 보안 검증 공유 패키지 및 하이브리드 자동 클릭 도구**

### 📦 [👉 최신 스탠드얼론 실행 파일 (v2.4.2) 다운로드](https://github.com/dhfhthtl3-dotcom/MCROOO/releases/download/v2.4.2/GameMacro-v2.4.2-windows-x64.zip)
*파이썬 설치 없이 다운로드받아 압축만 풀면 바로 실행 가능합니다.*

---

## 🌟 주요 기능 (Key Features)

### 1. 🎯 다중 타겟 실시간 동시 감지 (Multi-Target Detection)
- **무제한 복수 버튼 등록**: '확인', '전투 시작', '건너뛰기', '닫기' 등 원하는 버튼을 무제한 등록 가능
- **버튼별 독립 설정**:
  - 개별 감지 임계치(Threshold Slider 50% ~ 99%)
  - 실행 우선순위(Priority: 여러 버튼이 동시에 보일 때 먼저 누를 순서)
  - 개별 쿨다운(Cooldown: 중복 클릭 방지 타이머)
  - 개별 ON/OFF 스위치

### 2. 📐 해상도 자동 보정 (Multi-Scale Dynamic Matching)
- **화면 크기 변화 자동 대응**: 창 모드 크기 조절이나 해상도 변경(720p ➔ 1080p, 전체화면 등) 시에도 기준 해상도 대비 배율을 실시간 계산하여 템플릿 이미지를 최적 크기로 자동 리사이징 매칭합니다.
- **클릭 좌표 자동 스케일링**: 확대/축소된 비율에 맞춰 클릭 중심 좌표도 오차 없이 정확히 보정됩니다.

### 3. ⚡ 초고속 하이브리드 클릭 엔진 (Hybrid Click Engine)
- **초고속 하드웨어 클릭 (`SendInput`)**: 0.01초(10ms) 내에 마우스 순간 이동 ➔ 클릭 ➔ 원래 커서 위치로 즉시 복귀하여 사용자 작업을 방해하지 않으면서 3D/DirectX/보안 게임에서도 100% 클릭을 보장합니다.
- **비활성 백그라운드 클릭 (`PostMessage`)**: 마우스 커서를 전혀 움직이지 않고 백그라운드 Win32 메시지 전송.
- **창 활성화 후 클릭 (`Activate`)**: 백그라운드 인식이 어려운 환경에서 일시적 포커스 부여 후 클릭.

### 4. 🖥️ Windows OS DPI 스케일링 및 타이틀바 오프셋 보정
- 윈도우 디스플레이 배율(125%, 150%, 200%) 및 울트라와이드 모니터 환경에서도 클라이언트 캔버스(0, 0)를 1픽셀 오차 없이 정확하게 인식합니다.
- GUI 좌측에 **상/하(Y축) 미세보정 패널** 및 `[▲-30px]`, `[▲-15px]`, `[0px]`, `[▼+15px]` 퀵 프리셋 버튼을 탑재하여 언제든 클릭 높이를 쉽게 조절할 수 있습니다.

### 5. 🎯 템플릿 특정 부위 정밀 클릭 (Relative Pinpoint Click)
- **원하는 지점 콕 찍어 클릭**: 기본값은 정중앙이지만, 타겟 카드의 `[🎯]` 버튼을 눌러 팝업된 이미지 위에서 마우스로 원하는 곳(우측 상단 'X' 닫기 버튼, 체크박스 등)을 콕 찍어 지정 가능.
- **해상도 스케일링 자동 비례 연동**: 창 크기나 해상도가 달라져도 사용자가 찍은 위치가 비율에 맞춰 정확하게 자동 보정됩니다.

### 6. 🔄 화면 연속 탭 (오토클릭 / 화면 계속 누르기)
- **화면 계속 누르기 지원**: 특정 이미지 감지와 병행하거나 단독으로 화면을 일정 주기(0.1초~10초)로 툭툭 계속 클릭해 주는 오토클릭 모드.
- **스마트 동작 조건**:
  - `버튼 없을 때만 탭 (추천)`: 대화나 스토리를 계속 넘기다가 등록된 확인/전투시작 버튼이 나타나면 해당 버튼을 누르고 다시 화면 탭 재개.
  - `항상 계속 탭`: 버튼 감지와 무관하게 화면 탭을 계속 병행.
- **클릭 위치 커스텀**: 기본 `창 중앙` 외에도 `[🎯 화면에서 찍기]`를 눌러 프리뷰 화면에서 원하는 좌표를 클릭 한 번으로 지정 가능.

### 7. 🎨 세련된 다크 테마 GUI 대시보드
- `CustomTkinter` 기반의 모던 UI
- 실시간 감지 현황 시각화 캔버스 (타겟별 색상 박스 및 일치율 표시)
- 드래그 앤 드롭 영역 캡처 스니핑 툴 내장
- 상세 동작 및 활동 로그 실시간 출력

### 8. 🛡️ 무결점 화면 캡처 및 자동 복구 엔진 (v2.4.1)
- **GDI 자원 누수 완전 차단**: Windows DC 테이블 오염 및 비트맵 핸들 누수를 원천 차단하여 장시간 연속 실행 시에도 캡처 실패 0% 보장.
- **창 재시작 자동 감지 및 재연결 (Auto-Reacquisition)**: 게임 재접속이나 클라이언트 재실행 등으로 윈도우 핸들(HWND)이 변경되더라도 매크로가 게임 창을 자동으로 찾아 즉각 재연결.
- **4단계 폴백 캡처**: DWM PrintWindow ➔ WindowDC BitBlt ➔ Desktop BitBlt ➔ MSS 라이브러리 연동으로 최소화/가려진 창/보안 환경에서도 안정적 캡처 지원.

### 9. ⚡ 초고속 계층적 매칭 & 무지연 UI 렌더링 (v2.4.2)
- **계층적 Coarse-to-Fine 매칭**: 대형 화면(1080p 등)에서 2배 축소(1/4 픽셀) 초고속 선행 스캔을 거쳐 유망 영역만 정밀 매칭. 타겟 9종 스캔 속도 **4.4배 향상 (151ms ➔ 34ms)**.
- **창 크기 조절 렉 완전 제거**: 
  - UI 스레드 렌더링을 OpenCV C++ 고속 리사이즈로 전환하여 **10ms ➔ 1.9ms (8배 단축)**.
  - 단일 슬롯 프레임 드롭 버퍼 및 30ms 캔버스 리사이즈 디바운서를 적용하여 창 테두리를 빠르게 드래그해도 마우스 굳음이나 버벅임 없는 144Hz급 부드러움 보장.

---

## 📦 다운로드 및 빠른 실행 (Releases)

파이썬 설치가 필요 없는 **무설치 단일 실행 파일**을 다운로드하여 바로 사용하실 수 있습니다:

1. [GitHub Releases](../../releases) 페이지로 이동합니다.
2. 최신 버전의 **`GameMacro-v2.4.2-windows-x64.zip`** 파일을 다운로드합니다.
3. 압축을 풀고 **`GameMacro.exe`**를 실행합니다.  
   *(관리자 권한 UAC 확인 창이 뜨면 **'예'**를 누릅니다)*

> 💡 **알림**: 사용자가 등록한 캡처 버튼(`templates/`)과 설정(`targets_config.json`), 프로필(`profiles/`)은 `GameMacro.exe`가 위치한 폴더에 자동으로 영구 보관됩니다.

---

## 💻 소스코드에서 직접 실행하기

파이썬 환경이 설치되어 있는 경우 소스코드로 직접 실행할 수 있습니다.

### 요구 사항
- Windows 10 또는 11 (64-bit)
- Python 3.10 이상

### 설치 및 실행
```powershell
# 1. 저장소 복제
git clone https://github.com/your-username/GameMacro.git
cd GameMacro

# 2. 필수 라이브러리 설치
pip install -r requirements.txt

# 3. 매크로 GUI 실행
python main_gui.py
# 또는 run_macro.bat 더블 클릭
```

---

## 🔨 스탠드얼론 `.exe` 파일 직접 빌드하기

제공되는 빌드 자동화 스크립트를 통해 원클릭으로 독립 실행 파일을 패키징할 수 있습니다:

```powershell
python build_exe.py
```
빌드가 완료되면 `dist/` 폴더에 `GameMacro.exe`가 생성됩니다.

---

## 🧪 단위 테스트 (Unit Tests)

5개 핵심 기능에 대한 자동화 테스트 스위트가 포함되어 있습니다:
```powershell
python test_suite.py
```
- 다중 버튼 동시 탐색 및 우선순위 정렬 검증 (`PASS`)
- 비활성화 타겟 필터링 검증 (`PASS`)
- 매크로 코어 루프 및 개별 쿨다운 검증 (`PASS`)
- 타겟 설정 및 이미지 디스크 저장/복원 무결성 검증 (`PASS`)
- 해상도 확대(1.5x)/축소(0.8x) 멀티 스케일 동적 매칭 검증 (`PASS`)

---

## ⚠️ 면책 조항 (Disclaimer)

- 본 소프트웨어는 **컴퓨터 비전(OpenCV) 알고리즘 및 Windows Win32 API 제어 연구/학습/개발 목적**으로 제작되었습니다.
- 사용자는 자동화 도구 사용 시 해당 게임 및 애플리케이션 서비스 제공자의 이용약관(ToS)을 준수할 책임이 있습니다.
- 본 프로그램을 사용하여 발생하는 계정 제재, 데이터 손실 등의 결과에 대해 개발자는 어떠한 법적 책임도 지지 않습니다.

---

## 📄 라이선스 (License)

이 프로젝트는 [MIT License](LICENSE) 하에 자유롭게 배포 및 수정이 가능합니다.
