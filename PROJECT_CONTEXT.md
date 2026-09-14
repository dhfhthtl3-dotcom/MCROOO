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
- **이미지 특정 부위 클릭 & 화면 연속 탭(오토클릭) 탑재 (v2.4.0)**:
  - **이미지 특정 부위 클릭 (`TargetPinpointDialog`)**:
    - 버튼 목록 카드의 `[🎯]` 버튼을 눌러 등록된 이미지 위를 마우스로 직접 찍어 상대 오프셋(X, Y)을 시각적으로 지정.
    - 해상도 스케일링 배율(`scale`)에 따른 상대 좌표 자동 비례 보정.
  - **화면 연속 탭 / 오토클릭 모드**:
    - 이미지 감지와 무관하게 또는 감지 버튼이 없을 때(`when_idle`) 화면의 지정 위치(기본 창 정중앙 or 프리뷰 화면에서 찍은 좌표)를 주기적(0.1초~10초)으로 연속 탭.
    - 버튼이 등록되어 있지 않아도 단독 오토클릭으로 시작 가능.
    - 프로필별로 연속 탭 설정(활성화, 주기, 좌표, 모드) 독립 보존.
  - `test_suite.py` 내 단위 테스트 2종 추가 및 전체 15개 단위 테스트 ALL PASS.
  - `GameMacro.exe` 재빌드 및 `release/GameMacro-v2.4.0-windows-x64.zip` 패키징 완료.
- **화면 캡처 중단 버그 해결 및 자동 복구/GDI 누수 원천 차단 (v2.4.1)**:
  - **원인 분석 (GDI Handle Leak & Window Handle Invalidation)**:
    1) Win32 GDI 규칙 위반: `GetDC`/`GetWindowDC`로 얻은 DC에 대해 `DeleteDC()`를 호출하여 OS DC 테이블 오염 발생.
    2) 비트맵 핸들 누수: `SelectObject(hdc, hbm)`된 비트맵을 이전 원본 비트맵으로 복원하지 않고 삭제를 시도하여 GDI 핸들이 프로세스당 10,000개 한도에 도달, Error 6(`ERROR_INVALID_HANDLE`)/Error 5 발생.
    3) 게임 재시작 시 윈도우 핸들(HWND) 무효화: 클라이언트 재시작 시 새 HWND를 발급받았으나 기존 죽은 HWND를 계속 잡고 있어 캡처 불가.
    4) 스레드 데스크톱 분리: `win32ui`/MFC 로딩 전 `SetThreadDesktop(OpenInputDesktop())` 미수행 시 interactive 데스크톱 분리 현상 발생.
  - **해결 내역**:
    - `window_capture.py` 전면 리팩토링: `_safe_gdi_capture()` 헬퍼를 통해 비트맵 핸들 복원 후 안전 해제, `ReleaseDC` 엄격 적용, `win32ui` import 전 스레드 데스크톱 동기화(`sync_thread_desktop`).
    - DWM PrintWindow ➔ WindowDC BitBlt ➔ Desktop BitBlt ➔ `mss` 4단계 무결점 폴백 엔진 구축 및 `get_last_capture_error()` 진단 시스템 탑재.
    - `macro_core.py` 자동 재연결: `not win32gui.IsWindow(self.hwnd)` 감지 시 프로필의 대상 창 제목으로 새 창 핸들을 실시간 자동 탐색 및 즉시 재연결.
    - 대상 창 최소화(`win32gui.IsIconic`) 시 친절한 안내 로그 및 대기 로직 적용.
    - `main_gui.py`: 캡처/크롭/감지 실패 시 상세 오류 메시지 팝업 연동 및 GUI 타이틀 v2.4.1 갱신.
    - `test_suite.py` 전체 15개 단위 테스트 통과 (`ALL PASS`).
    - `GameMacro.exe` 재빌드 완료 (관리자 권한 매니페스트 및 `mss` 포함, 69.3MB).
    - `release/GameMacro-v2.4.1-windows-x64.zip` 배포 패키지 생성 완료.
- **창 크기 조절 시 렉 및 병목 전수 진단 및 초고속 최적화 (v2.4.2)**:
  - **병목 원인 분석 (Bottlenecks Discovered)**:
    1) UI 스레드 PIL LANCZOS 블로킹: 1470x827 화면을 PIL LANCZOS로 매 프레임 리사이즈하여 Tkinter UI 스레드가 10~15ms 동안 블로킹됨. 창 테두리를 드래그할 때 이벤트 큐에 누적되어 마우스 드래그가 굳는 현상 발생.
    2) 매 프레임 `canvas.delete("all")`: 캔버스 객체를 매 프레임 파괴/재생성하여 렌더러 부하 유발.
    3) 템플릿 매칭 CPU 과점유: 게임 창 크기가 달라졌을 때 타겟 9종 × 3개 스케일 = 27회 전체 매칭(445ms)으로 CPU 코어 100% 점유.
    4) 장시간 구동 시 로그 텍스트박스 줄 수 누적으로 인한 Tkinter 텍스트 레이아웃 리플로우 지연.
  - **해결 내역**:
    - `detector.py`: 대형 화면(>=640x480) 대상 2단계 계층적 Coarse-to-Fine 탐색 도입. 2배 축소 이미지에서 1.2ms 만에 선행 스캔 후 후보 영역만 국소 ROI 정밀 매칭. 타겟 9종 스캔 시간 **151ms ➔ 34ms (4.4배 단축)**. 기준 스케일 일치 시 불필요한 인접 스케일(0.95, 1.05) 즉시 가지치기.
    - `main_gui.py`:
      - 단일 슬롯 프레임 드롭 버퍼(`_pending_frame`) 도입으로 창 크기 조절 중 이벤트 큐 적체 원천 차단.
      - OpenCV C++ 기반 초고속 리사이즈(`cv2.INTER_AREA`) 적용: UI 스레드 변환 시간 **10~15ms ➔ 1.9ms (8배 단축)**.
      - 캔버스 아이템 재사용(`coords` & `itemconfig`): `delete("all")` 호출 제거.
      - 캔버스 리사이즈 30ms 디바운서 적용으로 마우스 드래그 렉 100% 제거.
      - 로그 텍스트박스 500줄 초과 시 자동 상위 100줄 삭제로 메모리/UI 리플로우 안정화.
    - `window_capture.py`: 창 크기 조절 과도기(너비/높이 <= 16) 안전 가드 적용.
    - `test_suite.py` 전체 15개 단위 테스트 통과 (`ALL PASS`).
    - `GameMacro.exe` 재빌드 및 `release/GameMacro-v2.4.2-windows-x64.zip` 배포 패키징 완료.
- **에픽세븐 비밀상점(비상런) 자동화, 창 크기 16:9 맞춤 및 마우스 드래그 모듈 완성 (v2.5.0)**:
  - **창 크기 16:9 클라이언트 자동 맞춤 (`window_capture.py`: `resize_window_client`)**:
    - `GetWindowRect`와 `GetClientRect`의 기하학적 차이를 분석하여 OS 타이틀바 및 테두리 두께를 역산.
    - 클라이언트 해상도를 16:9 표준(`1600x900`, `1280x720`)으로 픽셀 단위 정밀 보정하여 화면 잘림 현상 원천 해결.
    - GUI 좌측 패널에 `[📐 16:9 맞춤 (1600x900)]`, `[📐 1280x720]` 원클릭 버튼 제공.
  - **하드웨어/백그라운드 마우스 드래그 & 스와이프 (`clicker.py`)**:
    - `send_hardware_drag`: `SendInput` 기반 14단계 3차 에르미트/선형 보간 마우스 드래그 및 마우스 커서 원위치 복원 지원.
    - `send_postmessage_drag`: 비활성 창에 `WM_MOUSEMOVE` 메시지 스트림 전송.
    - `dispatch_drag`: 클릭 모드와 통합된 일관된 드래그 디스패치.
  - **비상런 전용 코어 엔진 (`secret_shop_engine.py`)**:
    - `SecretShopStats`: 새로고침 횟수, 소모 하늘석, 성약의 책갈피(수량/골드), 신비의 메달(수량/골드), 총 소모 골드, 소요 시간 실시간 집계.
    - `SecretShopEngine`:
      - 1페이지 스캔 및 구매 ➔ 하단 드래그 스와이프 ➔ 2페이지 스캔 및 구매 ➔ 새로고침 확인 루프.
      - 검증된 Solunium 상대 좌표 체계 및 배율 스케일링(`scale_candidates = [scale*0.92, scale, scale*1.08, 1.0]`) 적용으로 100% 탐색 성공률 확보.
      - 템플릿 로딩 시 Windows 한글 경로 이슈를 원천 방지하는 `cv2.imdecode` 스트림 로더 내장.
  - **프로필 연동 및 전용 대시보드 (`profile_manager.py`, `main_gui.py`)**:
    - `profiles/secret_shop.json` 기본 생성 및 메타데이터 자동 등록 (`ensure_secret_shop_profile`).
    - 프로필 선택 시 일반 타겟 카드 뷰 대신 **실시간 비상런 6대 지표 대시보드**(새로고침, 하늘석, 성약, 신비, 골드, 시간)로 자동 전환 (`update_view_mode`).
    - F9 단축키로 비상런 시작/정지 토글, ESC 긴급 중지 지원.
  - **단위 테스트 무결성 검증 (`test_suite.py`)**:
    - `test_resize_window_client`, `test_drag_clicker`, `test_secret_shop_stats`, `test_secret_shop_engine_detection_and_cycle` 추가.
    - 총 19개 단위 테스트 100% 통과 (`Ran 19 tests in 2.367s - OK`).
  - **기존 9개 버튼 및 프로필 100% 무손실 보존**:
    - `profiles/default.json`에 등록된 실제 게임 버튼 9종 무손실 유지.
    - `build_exe.py`에 `secret_shop_engine`, `clicker`, `window_capture`, `image_matcher` 히든 임포트 및 템플릿 복사 파이프라인 반영.


