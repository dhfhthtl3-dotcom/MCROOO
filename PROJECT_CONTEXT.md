# PROJECT CONTEXT: 백그라운드 창 특정 프레임(이미지) 감지 및 자동 클릭 매크로

## 1. 프로젝트 목표 (Objective)
- Windows 환경에서 특정 창(Background / Inactive 상태 포함)의 프레임을 실시간으로 캡처.
- 사용자가 등록한 타겟 템플릿 이미지를 OpenCV 템플릿 매칭(`cv2.TM_CCOEFF_NORMED`)으로 탐색.
- 설정된 일치율(X% 이상) 조건을 만족하면 마우스 커서를 뺏지 않고 해당 창의 좌표에 비활성 마우스 클릭(`PostMessage`) 수행.

## 2. 핵심 기술 스택 및 메커니즘 (Tech Stack & Architecture)
- **언어**: Python 3.11
- **윈도우 제어 및 백그라운드 캡처 (`window_capture.py`)**:
  - `pywin32` (`win32gui`, `win32ui`, `win32con`, `win32process`, `win32api`)
  - `PrintWindow` API (`PW_RENDERFULLCONTENT` = 2, `PW_CLIENTONLY` = 1) 및 DC(Device Context) 비트맵 복사
  - 클라이언트 영역(Client Area) 좌표 보정 및 DPI 인식 처리
- **이미지 매칭 엔진 (`detector.py`)**:
  - `MultiTargetDetector` & `TargetItem`: 여러 개의 버튼/타겟을 등록하고 화면에서 동시 탐색
  - 개별 임계치(Threshold), 우선순위(Priority), 개별 쿨다운(Cooldown), 중심 좌표 자동 산출
  - 감지된 모든 버튼을 화면 미리보기에 색상별로 시각화 (`draw_detections`)
- **하이브리드 마우스 클릭 모듈 (`clicker.py`)**:
  - [모드 1] `hardware` (SendInput): 0.01초 내 마우스 순간 이동 -> 물리 클릭 -> 커서 복귀 (모든 게임 100% 호환, 권장)
  - [모드 2] `activate`: 창을 일시적으로 전면 활성화 후 클릭
  - [모드 3] `postmessage`: 커서 미이동 백그라운드 메시지 전송 (자식 창 핸들 자동 탐색)
  - `dispatch_click`: 사용자 선택 모드에 따라 안전한 클릭 실행
- **매크로 코어 루프 (`macro_core.py`)**:
  - 등록된 타겟들을 실시간 다중 스캔하여 우선순위 및 쿨다운을 검사하여 자동 클릭
  - 타겟 설정 및 템플릿 이미지를 JSON/PNG로 영구 저장/자동 복원 (`targets_config.json`, `templates/`)
- **모던 GUI 대시보드 (`main_gui.py` v2.0)**:
  - 3개 컬럼 레이아웃:
    1. 대상 창 선택 + 클릭 모드 라디오 + 창 중앙 및 캔버스 클릭 테스트 버튼
    2. 다중 버튼 목록 카드 뷰 (썸네일, 이름, 개별 일치율 슬라이더, ON/OFF 스위치, 삭제 버튼) + `[✂️ 캡처 추가]`, `[📂 파일 추가]`
    3. 실시간 다중 감지 시각화 캔버스 + 1회 테스트 버튼 + 활동 로그 뷰어

## 3. 주요 기술적 제약 및 해결 방안
- **클릭 미작동 이슈 해결**:
  - DirectX/OpenGL/보안 적용 게임이 비활성 Win32 메시지(`WM_LBUTTONDOWN`)를 무시하는 문제 해결.
  - 초고속 `SendInput` 물리 입력(10ms 순간 이동 후 원위치 복구) 모드를 도입하여 사용자의 마우스 작업 간섭을 최소화하면서 100% 클릭 보장.
  - 캔버스를 직접 클릭하여 해당 창에 클릭 신호가 들어가는지 즉시 확인 가능한 인터랙티브 테스트 기능 추가.
- **배치 파일 인코딩 및 실행 방식 전면 개선**:
  - Windows 한국어 CMD(CP949)에서 UTF-8 한글 주석/echo 문자가 구문 에러(`ct`, `愿由ъ옄`, `ON_EXEC` 등)를 유발하던 문제 해결.
  - 배치 파일(`run_macro.bat`)을 100% 순수 ASCII로 재작성하여 어떠한 환경에서도 구문 오류 발생 불가하도록 안정화.
  - 파이썬 프로그램(`main_gui.py`) 내부에서 Win32 `ShellExecuteW(runas)`를 통해 안전하게 관리자 권한을 자동 요청하도록 구조 개선 완료.
- **클릭 위치 하단 밀림(너무 아래로 클릭되는 현상) 원인 규명 및 완벽 해결**:
  - 원인: `window_capture.py`의 Strategy 3(`WindowDC BitBlt`)에서 `(0, 0)`부터 복사하여 윈도우 타이틀바(38px)가 캡처 이미지 상단에 포함됨. 이로 인해 감지된 버튼의 Y좌표가 실제보다 38px 아래로 밀렸고, `ClientToScreen`이 다시 클라이언트 오프셋을 더하면서 클릭이 버튼 아래로 38px 이중 오프셋되어 버튼을 빗나갔음.
  - 해결 1: `WindowDC` 복사 시 `(offset_x, offset_y)`를 적용하여 타이틀바를 완벽 배제하고 순수 클라이언트 캔버스(0,0)부터 1:1 매핑 캡처.
  - 해결 2: `clicker.py`에 `SetCursorPos` + `SendInput` 이중 적용으로 픽셀 단위 마우스 위치 고정.
  - 해결 3: GUI 좌측 패널에 `[3. 클릭 좌표 미세보정]` 및 `[▲-30px]`, `[▲-15px]`, `[0px]`, `[▼+15px]` 퀵 프리셋 버튼을 추가하여 실시간 상/하 미세조정 지원.
- **해상도 자동 보정 (Multi-Scale Dynamic Matching) 탑재 (v2.1)**:
  - 타겟 등록 당시의 기준 해상도(`base_width`, `base_height`)를 저장.
  - 창 크기가 달라지거나 전체화면/해상도 변경 시 현재 프레임 크기 대비 배율(`scale_ratio`)을 자동 계산하여 템플릿 이미지를 실시간 고품질 리사이즈 매칭 및 중심 좌표 비율 보정.
  - 0.8x ~ 1.5x 등 다양한 해상도 변경 환경에서도 100% 감지 및 정밀 클릭 보장.
- **스탠드얼론 실행 파일(`GameMacro.exe`) 및 영구 파일 저장 아키텍처 (v2.1)**:
  - `get_app_dir()` 유틸리티를 통해 `.exe` 실행 파일이 위치한 실제 디렉토리에 `templates/` 폴더와 `targets_config.json`을 영구 보관.
  - 임시 폴더 삭제로 인한 데이터 유실을 원천 방지하고, 단일 실행 파일과 설정 폴더만으로 완벽한 이동성(Portability) 확보.
  - PyInstaller 기반 `--onefile`, `--windowed`(콘솔 숨김), `--uac-admin`(관리자 권한 매니페스트) 단일 패키징 구축.
- **오픈소스 패키징 및 GitHub 자동 릴리즈(CI/CD) 파이프라인 완성 (v2.1.0)**:
  - 오픈소스 표준 문서 작성 완료: `README.md` (고품질 프로젝트 가이드 및 면책조항), `LICENSE` (MIT), `.gitignore`, `requirements.txt`.
  - 로컬 릴리즈 즉시 배포 패키지 생성: `release/GameMacro-v2.1.0-windows-x64.zip` (포터블 무설치 패키지).
  - GitHub Actions 워크플로우 구축: `.github/workflows/release.yml` (태그 푸시 시 클라우드 자동 빌드 및 릴리즈 첨부 자동화).
  - Git 로컬 저장소 초기화(`git init -b main`), 1차 릴리즈 커밋 및 태그(`v2.1.0`) 생성 완료.
- **다중 매크로 독립 프로필 시스템 (Multi-Profile System) 완성 (v2.2)**:
  - `profile_manager.py` 모듈 구축: 각 매크로별 독립적인 타겟 버튼 목록, 클릭 모드, 오프셋, 스캔 주기, 대상 창 제목을 `profiles/<id>.json`으로 분리 저장.
  - GUI 최상단에 프로필 제어 바 신설: ComboBox 드롭다운 선택, `[➕ 새 매크로]`, `[✏️ 이름 변경]`, `[💾 복제]`, `[🗑️ 삭제]` 인터페이스 완비.
  - 기존 `targets_config.json`의 타겟 4개를 "기본 매크로"로 자동 마이그레이션하여 데이터 무손실 보장.
  - 프로필 전환 시 대상 윈도우 창 자동 복원 및 설정 즉시 동기화.
  - `test_suite.py` 내 4개 프로필 단위 테스트 추가 및 전체 9개 테스트 통과 (`ALL PASS`).
  - `GameMacro.exe` 재빌드 및 `release/GameMacro-v2.1.0-windows-x64.zip` 최신 배포본 생성 완료.
- **4단계 보안 검증 기반 .gmac 매크로 패키지 내보내기/가져오기 시스템 완성 (v2.3)**:
  - `macro_package.py` 모듈 구축: 설정 JSON과 버튼 템플릿 이미지를 묶는 단일 `.gmac` 패키지 생성 및 4중 보안 필터 탑재.
  - **4중 보안 방어선**:
    1) 화이트리스트 검사: 실행 파일/스크립트(`.exe`, `.bat`, `.vbs`, `.py`, `.dll` 등 25종) 단 1개라도 포함 시 즉시 거부 및 차단.
    2) 경로 조작(Zip Slip) 및 압축 폭탄(Zip Bomb) 방어: 상위 폴더 이동(`../`) 및 비정상 대용량 압축 무력화.
    3) 시스템 윈도우 타겟팅 차단(Target Guard): 작업 관리자, cmd, powershell, 레지스트리 편집기, 백신 프로그램 제어 시도 원천 차단.
    4) 시각적 썸네일 검증 대화상자(`ImportVerifyDialog`): 포함된 버튼들의 실제 이미지 썸네일과 일치율을 눈으로 직접 확인 후 승인하는 2단계 등록 절차.
  - GUI 상단 프로필 바에 `[📤 내보내기]`, `[📥 가져오기]` 버튼 탑재.
  - `GameMacro.exe` (69.1MB) 재빌드 및 `release/GameMacro-v2.3.0-windows-x64.zip` 패키징 완료.
- **실제 게임 타겟 9종 '기본 매크로' 탑재 및 테스트 환경 완전 격리 (v2.3.1)**:
  - 사용자가 등록해 둔 실제 게임 버튼 9종(`버튼_769`, `버튼_327`, `버튼_269`, `버튼_416`, `버튼_609`, `버튼_993`, `버튼_846`, `버튼_749`, `버튼_955`)을 `profiles/default.json`에 영구 탑재.
  - `test_suite.py`의 단위 테스트 파일 쓰기 경로를 임시 폴더(`test_persistence_env`)로 완전 격리하여 테스트 실행 시 프로필이 오염되는 현상 원천 차단.
  - GitHub 저장소(`dhfhthtl3-dotcom/MCROOO`) 및 릴리즈 다운로드 파일(`GameMacro-v2.3.0-windows-x64.zip`) 최종 갱신 완료.
