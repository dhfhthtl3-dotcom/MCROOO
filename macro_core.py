"""
다중 타겟 매크로 코어 루프 엔진 (Multi-Target Macro Core)
- 복수의 등록된 버튼들을 실시간 스캔하여 감지 시 자동 클릭
- 우선순위(Priority) 및 개별 쿨다운(Cooldown) 제어
- 하이브리드 클릭 디스패치 (SendInput / Activate / PostMessage)
- 등록된 타겟(버튼) 설정 및 템플릿 이미지 영구 자동 저장/불러오기
"""

import os
import json
import time
import threading
from typing import Optional, Callable, Dict, Any, List
import cv2
import numpy as np

import sys

from window_capture import capture_window
from detector import MultiTargetDetector, TargetItem
from clicker import dispatch_click, send_hardware_click
from profile_manager import ProfileManager, MacroProfile, get_app_dir


class MacroEngine:
    @property
    def DATA_FILE(self) -> str:
        if self._custom_data_file:
            return self._custom_data_file
        return os.path.join(get_app_dir(), "targets_config.json")

    @DATA_FILE.setter
    def DATA_FILE(self, path: str):
        self._custom_data_file = path

    @property
    def TEMPLATES_DIR(self) -> str:
        if self._custom_templates_dir:
            os.makedirs(self._custom_templates_dir, exist_ok=True)
            return self._custom_templates_dir
        p = os.path.join(get_app_dir(), "templates")
        os.makedirs(p, exist_ok=True)
        return p

    @TEMPLATES_DIR.setter
    def TEMPLATES_DIR(self, path: str):
        self._custom_templates_dir = path

    def __init__(self):
        self._custom_data_file: Optional[str] = None
        self._custom_templates_dir: Optional[str] = None

        self.hwnd: Optional[int] = None
        self.detector = MultiTargetDetector()

        # 프로필 관리자 연동
        self.profile_manager = ProfileManager(base_dir=get_app_dir())

        # 전역 매크로 설정
        self.click_mode: str = "hardware"   # "hardware" (SendInput 권장), "activate", "postmessage"
        self.interval: float = 0.4          # 화면 스캔 주기 (초)
        self.jitter: int = 1                # 클릭 좌표 미세 오차
        self.max_clicks: int = 0            # 최대 클릭 수 (0: 무제한)

        # 상태 관리
        self.is_running: bool = False
        self.is_paused: bool = False
        self.total_clicks: int = 0
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 전역 클릭 위치 미세조정 오프셋 (X, Y)
        self.global_offset_x: int = 0
        self.global_offset_y: int = 0

        # UI 연동 콜백
        self.on_frame_update: Optional[Callable[[np.ndarray, List[Dict[str, Any]]], None]] = None
        self.on_click_performed: Optional[Callable[[str, int, int, float], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_status_change: Optional[Callable[[str], None]] = None

        # 저장된 타겟 불러오기 (활성 프로필 기준)
        self.load_targets()

    def log(self, message: str):
        print(f"[Macro] {message}")
        if self.on_log:
            self.on_log(message)

    def set_target_window(self, hwnd: int):
        self.hwnd = hwnd

    # ------------------ 타겟 관리 ------------------

    def add_target(
        self,
        name: str,
        template_img: np.ndarray,
        threshold: float = 0.85,
        priority: int = 1,
        cooldown: float = 2.0,
        offset_x: int = 0,
        offset_y: int = 0,
        target_id: Optional[str] = None,
        base_width: int = 0,
        base_height: int = 0
    ) -> TargetItem:
        target = TargetItem(
            name=name,
            template_img=template_img,
            threshold=threshold,
            priority=priority,
            cooldown=cooldown,
            offset_x=offset_x,
            offset_y=offset_y,
            target_id=target_id,
            base_width=base_width,
            base_height=base_height
        )
        self.detector.add_target(target)
        self.save_targets()
        res_info = f", 기준해상도: {base_width}x{base_height}" if base_width > 0 else ""
        self.log(f"타겟 등록 완료: '{name}' (일치율 {int(threshold*100)}%, 우선순위 {priority}{res_info})")
        return target

    def remove_target(self, target_id: str):
        target = self.detector.get_target(target_id)
        if target:
            name = target.name
            self.detector.remove_target(target_id)
            self.save_targets()
            self.log(f"타겟 삭제 완료: '{name}'")

    def toggle_target(self, target_id: str, enabled: bool):
        target = self.detector.get_target(target_id)
        if target:
            target.enabled = enabled
            self.save_targets()

    def update_target(self, target_id: str, **kwargs):
        target = self.detector.get_target(target_id)
        if target:
            for k, v in kwargs.items():
                if hasattr(target, k):
                    setattr(target, k, v)
            self.save_targets()

    def get_all_targets(self) -> List[TargetItem]:
        return self.detector.get_all_targets()

    # ------------------ 프로필 관리 API ------------------

    def get_profile_list(self) -> List[Dict[str, str]]:
        return self.profile_manager.get_profile_list()

    def get_active_profile(self) -> MacroProfile:
        return self.profile_manager.get_active_profile()

    def switch_profile(self, profile_id: str) -> bool:
        if self.is_running:
            self.stop()
        p = self.profile_manager.switch_profile(profile_id)
        if p:
            self.load_targets()
            self.log(f"프로필 전환 완료: '{p.name}'")
            return True
        return False

    def create_profile(self, name: str) -> MacroProfile:
        if self.is_running:
            self.stop()
        new_p = self.profile_manager.create_profile(name)
        self.load_targets()
        self.log(f"새 프로필 생성 및 전환: '{new_p.name}'")
        return new_p

    def rename_profile(self, profile_id: str, new_name: str) -> bool:
        success = self.profile_manager.rename_profile(profile_id, new_name)
        if success:
            self.log(f"프로필 이름 변경 완료: '{new_name}'")
        return success

    def duplicate_profile(self, source_id: str, new_name: str) -> Optional[MacroProfile]:
        if self.is_running:
            self.stop()
        new_p = self.profile_manager.duplicate_profile(source_id, new_name)
        if new_p:
            self.load_targets()
            self.log(f"프로필 복제 완료: '{new_p.name}'")
        return new_p

    def delete_profile(self, profile_id: str) -> bool:
        if self.is_running:
            self.stop()
        success = self.profile_manager.delete_profile(profile_id)
        if success:
            self.load_targets()
            cur = self.profile_manager.get_active_profile()
            self.log(f"프로필 삭제 완료 -> '{cur.name}'(으)로 전환됨")
        return success

    # ------------------ 저장 및 복원 ------------------

    def save_targets(self):
        try:
            os.makedirs(self.TEMPLATES_DIR, exist_ok=True)
            data = []
            for t in self.detector.get_all_targets():
                img_filename = f"target_{t.id}.png"
                img_path = os.path.join(self.TEMPLATES_DIR, img_filename)
                
                # 이미지 저장 (한글 경로 호환)
                is_success, buffer = cv2.imencode(".png", t.template_img)
                if is_success:
                    with open(img_path, "wb") as f:
                        f.write(buffer)

                t_dict = t.to_dict()
                t_dict["image_file"] = img_filename
                data.append(t_dict)

            # 1. 활성 프로필에 타겟 및 설정 동기화 저장
            active_p = self.profile_manager.get_active_profile()
            active_p.targets = data
            active_p.click_mode = self.click_mode
            active_p.global_offset_x = self.global_offset_x
            active_p.global_offset_y = self.global_offset_y
            active_p.interval = self.interval
            self.profile_manager.save_active_profile()

            # 2. 하위 호환성을 위해 DATA_FILE(targets_config.json)도 함께 갱신
            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"타겟 저장 실패: {e}")

    def load_targets(self):
        self.detector.clear_targets()

        # 커스텀 데이터 파일이 지정된 경우 (테스트 코드 등)
        if self._custom_data_file and os.path.exists(self._custom_data_file):
            try:
                with open(self._custom_data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                self.log(f"커스텀 타겟 파일 로드 에러: {e}")
                data = []
        else:
            # 프로필 기반 타겟 로드
            active_p = self.profile_manager.get_active_profile()
            self.click_mode = active_p.click_mode
            self.global_offset_x = active_p.global_offset_x
            self.global_offset_y = active_p.global_offset_y
            self.interval = active_p.interval
            data = active_p.targets

        try:
            for item in data:
                img_path = os.path.join(self.TEMPLATES_DIR, item.get("image_file", ""))
                if os.path.exists(img_path):
                    with open(img_path, "rb") as f:
                        file_bytes = np.frombuffer(f.read(), dtype=np.uint8)
                        img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

                    if img is not None:
                        target = TargetItem(
                            name=item.get("name", "버튼"),
                            template_img=img,
                            threshold=item.get("threshold", 0.85),
                            priority=item.get("priority", 1),
                            cooldown=item.get("cooldown", 2.0),
                            offset_x=item.get("offset_x", 0),
                            offset_y=item.get("offset_y", 0),
                            enabled=item.get("enabled", True),
                            target_id=item.get("id"),
                            base_width=item.get("base_width", 0),
                            base_height=item.get("base_height", 0)
                        )
                        self.detector.add_target(target)
            self.log(f"타겟 {len(self.detector.targets)}개를 성공적으로 불러왔습니다. (프로필: '{self.profile_manager.get_active_profile().name}')")
        except Exception as e:
            self.log(f"타겟 불러오기 실패: {e}")

    # ------------------ 매크로 수명 주기 ------------------

    def start(self) -> bool:
        if self.is_running:
            return False

        if not self.hwnd:
            self.log("대상 윈도우(창)를 먼저 선택하세요.")
            return False

        active_targets = [t for t in self.detector.get_all_targets() if t.enabled]
        if not active_targets:
            self.log("활성화된 감지 버튼(타겟)이 없습니다. 버튼을 등록하거나 활성화하세요.")
            return False

        self.is_running = True
        self.is_paused = False
        self.total_clicks = 0
        self._stop_event.clear()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        if self.on_status_change:
            self.on_status_change("동작 중")
        self.log(f"매크로 시작! (모드: {self.click_mode.upper()}, 활성 타겟: {len(active_targets)}개)")
        return True

    def stop(self):
        if not self.is_running:
            return

        self.is_running = False
        self.is_paused = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=1.5)

        if self.on_status_change:
            self.on_status_change("정지됨")
        self.log(f"매크로 정지. (총 {self.total_clicks}회 클릭 수행)")

    def pause(self):
        self.is_paused = True
        if self.on_status_change:
            self.on_status_change("일시정지")
        self.log("매크로 일시정지.")

    def resume(self):
        self.is_paused = False
        if self.on_status_change:
            self.on_status_change("동작 중")
        self.log("매크로 재개.")

    # ------------------ 실행 루프 ------------------

    def _run_loop(self):
        while not self._stop_event.is_set():
            if self.is_paused:
                time.sleep(0.2)
                continue

            loop_start = time.time()

            try:
                # 1. 화면 캡처
                frame = capture_window(self.hwnd)
                if frame is None:
                    time.sleep(max(0.3, self.interval))
                    continue

                # 2. 다중 타겟 탐색
                detections = self.detector.detect_all(frame)

                # UI 프레임 및 감지 박스 업데이트
                if self.on_frame_update:
                    self.on_frame_update(frame, detections)

                # 3. 감지된 타겟 순차 검사 (우선순위 순서)
                now = time.time()
                for det in detections:
                    target: TargetItem = det["target"]
                    
                    # 개별 타겟 쿨다운 검사
                    if now - target.last_click_time >= target.cooldown:
                        cx, cy = det["center"]
                        conf_pct = det["confidence"] * 100

                        click_x = cx + self.global_offset_x
                        click_y = cy + self.global_offset_y

                        # 클릭 수행
                        success = dispatch_click(
                            self.hwnd,
                            click_x,
                            click_y,
                            mode=self.click_mode,
                            jitter=self.jitter
                        )

                        if success:
                            target.last_click_time = now
                            self.total_clicks += 1
                            self.log(
                                f"🎯 [{target.name}] 감지({conf_pct:.1f}%) -> ({click_x}, {click_y}) 클릭 성공! [누적 {self.total_clicks}회]"
                            )
                            if self.on_click_performed:
                                self.on_click_performed(target.name, click_x, click_y, det["confidence"])

                            # 단일 사이클 당 1회 클릭 후 루프 갱신 (화면 상태 변화 대기)
                            break

                # 최대 클릭 제한 검사
                if 0 < self.max_clicks <= self.total_clicks:
                    self.log(f"최대 클릭 횟수({self.max_clicks}회)에 도달하여 자동 정지합니다.")
                    self.stop()
                    break

            except Exception as e:
                self.log(f"루프 에러: {e}")

            elapsed = time.time() - loop_start
            sleep_time = max(0.05, self.interval - elapsed)
            time.sleep(sleep_time)
