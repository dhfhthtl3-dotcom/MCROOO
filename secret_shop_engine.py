"""
에픽세븐 비밀상점 갱신 자동화 전용 코어 엔진 (Secret Shop Refresh Engine)
- Solunium 알고리즘 기반 좌표 비율(Ratio) 및 템플릿 매칭
- 16:9 해상도(1600x900, 1280x720, 1920x1080 등) 동적 스케일링
- 성약의 책갈피 / 신비의 메달 자동 탐지 및 구매
- 부드러운 스크롤/드래그 및 새로고침 루프
- 실시간 6대 통계(새로고침, 소모 하늘석, 성약, 신비, 골드, 소요 시간) 수집
"""

import os
import sys
import time
import math
import random
import threading
from typing import Optional, Callable, Dict, Any, List, Tuple
import cv2
import numpy as np
import win32gui

from window_capture import capture_window, resize_window_client
from clicker import dispatch_click, dispatch_drag


def load_image_unicode(file_path: str) -> Optional[np.ndarray]:
    """한글/특수문자 경로에서도 안전하게 이미지를 로드합니다."""
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "rb") as f:
            buf = np.frombuffer(f.read(), dtype=np.uint8)
            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            return img
    except Exception as e:
        print(f"[SecretShop] 이미지 로드 오류 ({file_path}): {e}")
        return None


class SecretShopStats:
    """비상런 실시간 통계 데이터 클래스"""
    def __init__(self):
        self.refreshes: int = 0
        self.covenant_count: int = 0
        self.mystic_count: int = 0
        self.friendship_count: int = 0
        self.start_time: float = 0.0
        self.is_running: bool = False

        # 단위 비용 정의 (에픽세븐 기준)
        self.COVENANT_GOLD_PRICE = 184000
        self.MYSTIC_GOLD_PRICE = 280000
        self.FRIENDSHIP_GOLD_PRICE = 18000
        self.SKYSTONE_PER_REFRESH = 3

    def reset(self):
        self.refreshes = 0
        self.covenant_count = 0
        self.mystic_count = 0
        self.friendship_count = 0
        self.start_time = time.time()
        self.is_running = False

    @property
    def skystones_spent(self) -> int:
        return self.refreshes * self.SKYSTONE_PER_REFRESH

    @property
    def covenant_gold(self) -> int:
        return self.covenant_count * self.COVENANT_GOLD_PRICE

    @property
    def mystic_gold(self) -> int:
        return self.mystic_count * self.MYSTIC_GOLD_PRICE

    @property
    def total_gold(self) -> int:
        return self.covenant_gold + self.mystic_gold + (self.friendship_count * self.FRIENDSHIP_GOLD_PRICE)

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time <= 0:
            return 0.0
        return time.time() - self.start_time

    @property
    def elapsed_str(self) -> str:
        sec = int(self.elapsed_seconds)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        if h > 0:
            return f"{h:02d}시간 {m:02d}분 {s:02d}초"
        return f"{m:02d}분 {s:02d}초"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "refreshes": self.refreshes,
            "skystones_spent": self.skystones_spent,
            "covenant_count": self.covenant_count,
            "mystic_count": self.mystic_count,
            "friendship_count": self.friendship_count,
            "covenant_gold": self.covenant_gold,
            "mystic_gold": self.mystic_gold,
            "total_gold": self.total_gold,
            "elapsed_seconds": self.elapsed_seconds,
            "elapsed_str": self.elapsed_str
        }


class SecretShopEngine:
    """에픽세븐 비밀상점 갱신 자동화 엔진"""

    # 16:9 표준 비율 기준 상대 좌표 상수
    # 새로고침 버튼 (좌하단)
    REFRESH_BTN_RATIO = (0.1698, 0.9138)
    # 새로고침 확인 팝업 (하늘석 3개 소모 확인)
    REFRESH_CONFIRM_RATIO = (0.5828, 0.6411)
    # 구매 확인 팝업 (골드 소모 확인)
    BUY_CONFIRM_RATIO = (0.5677, 0.7037)
    # 아이템 감지 위치 대비 구매(골드) 버튼 오프셋
    BUY_BTN_X_OFFSET_RATIO = 0.4718
    # 상점 스크롤(스와이프) 시작 및 종료 좌표 비율
    DRAG_START_RATIO = (0.6250, 0.7481)
    DRAG_END_RATIO = (0.6250, 0.3629)

    def __init__(self, templates_dir: Optional[str] = None):
        self.templates_dir = templates_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "secret_shop")
        self.hwnd: Optional[int] = None
        self.target_window_title: str = "에픽세븐"

        # 옵션 설정
        self.buy_covenant: bool = True
        self.buy_mystic: bool = True
        self.buy_friendship: bool = False
        self.max_refreshes: int = 0  # 0: 무제한
        self.click_mode: str = "hardware"
        self.match_threshold: float = 0.75

        # 지연 시간 (안정적인 게임 반응 보장)
        self.delay_post_refresh: float = 1.35  # 새로고침 후 아이템 떨어지는 애니메이션 대기
        self.delay_post_drag: float = 0.65     # 스크롤 후 애니메이션 정지 대기
        self.delay_click: float = 0.30         # 팝업 반응 대기

        # 통계 및 상태 관리
        self.stats = SecretShopStats()
        self.is_running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # UI 콜백 함수
        self.on_stats_update: Optional[Callable[[SecretShopStats], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_status_change: Optional[Callable[[str], None]] = None
        self.on_frame_preview: Optional[Callable[[np.ndarray, List[Dict[str, Any]]], None]] = None

        # 템플릿 캐시
        self.templates: Dict[str, Dict[str, Any]] = {}
        self.load_templates()

    def log(self, msg: str):
        print(f"[SecretShop] {msg}")
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def load_templates(self):
        """비상런 에셋 템플릿(성약, 신비, 우정)을 메모리에 로드합니다."""
        self.templates.clear()
        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir, exist_ok=True)

        items_def = [
            ("covenant", "cov.png", 906, 539, "성약의 책갈피"),
            ("covenant_adb", "cov_adb.png", 1920, 1080, "성약의 책갈피(고해상도)"),
            ("mystic", "mys.png", 906, 539, "신비의 메달"),
            ("mystic_adb", "mys_adb.png", 1920, 1080, "신비의 메달(고해상도)"),
            ("friendship", "fb.png", 906, 539, "우정의 책갈피"),
        ]

        for item_key, filename, base_w, base_h, desc in items_def:
            p = os.path.join(self.templates_dir, filename)
            img = load_image_unicode(p)
            if img is not None:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
                self.templates[item_key] = {
                    "image": img,
                    "gray": gray,
                    "base_w": base_w,
                    "base_h": base_h,
                    "desc": desc
                }

        self.log(f"비상런 템플릿 {len(self.templates)}개 로드 완료.")

    def find_items_in_frame(
        self,
        frame: np.ndarray,
        item_types: List[str]
    ) -> List[Dict[str, Any]]:
        """
        현재 프레임에서 활성화된 아이템(성약, 신비 등)의 위치를 다중 스케일 매칭으로 탐색합니다.
        반환: [{'type': 'covenant', 'x': cx, 'y': cy, 'score': score, 'w': w, 'h': h}, ...]
        """
        if frame is None or len(frame.shape) < 2:
            return []

        frame_h, frame_w = frame.shape[:2]
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame

        detected = []

        for itype in item_types:
            # 기본 에셋 및 고해상도(adb) 에셋 둘 다 탐색
            keys_to_try = [itype]
            adb_key = f"{itype}_adb"
            if adb_key in self.templates:
                keys_to_try.append(adb_key)

            best_match = None

            for tkey in keys_to_try:
                if tkey not in self.templates:
                    continue

                tdata = self.templates[tkey]
                t_gray = tdata["gray"]
                base_w = tdata["base_w"]
                base_h = tdata["base_h"]

                # 기준 해상도 대비 현재 프레임 크기 배율 계산
                scale = frame_w / float(base_w)
                # 배율 후보군 (스케일 보정 + 원본 1.0x 호환)
                scale_candidates = list(dict.fromkeys([scale * 0.92, scale, scale * 1.08, 1.0]))

                for sc in scale_candidates:

                    target_tw = int(round(t_gray.shape[1] * sc))
                    target_th = int(round(t_gray.shape[0] * sc))

                    if target_tw <= 5 or target_th <= 5 or target_tw >= frame_w or target_th >= frame_h:
                        continue

                    scaled_tmpl = cv2.resize(t_gray, (target_tw, target_th), interpolation=cv2.INTER_AREA if sc < 1.0 else cv2.INTER_LINEAR)

                    res = cv2.matchTemplate(frame_gray, scaled_tmpl, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

                    if max_val >= self.match_threshold:
                        # 중심 좌표 계산
                        cx = int(max_loc[0] + target_tw / 2)
                        cy = int(max_loc[1] + target_th / 2)

                        # 왼쪽 상점 아이템 영역인지 확인 (보통 상점 아이템 아이콘은 왼쪽 X < 0.65W)
                        if cx < frame_w * 0.65:
                            if best_match is None or max_val > best_match["score"]:
                                best_match = {
                                    "type": itype,
                                    "name": tdata["desc"],
                                    "x": cx,
                                    "y": cy,
                                    "score": float(max_val),
                                    "w": target_tw,
                                    "h": target_th
                                }

            if best_match is not None:
                detected.append(best_match)

        return detected

    def start(self, hwnd: Optional[int] = None) -> bool:
        """비상런 자동화 루프를 시작합니다."""
        if self.is_running:
            return False

        if hwnd and win32gui.IsWindow(hwnd):
            self.hwnd = hwnd

        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            # 창 검색 시도
            from window_capture import get_window_list
            for w in get_window_list():
                if self.target_window_title.lower() in w["title"].lower():
                    self.hwnd = w["hwnd"]
                    break

        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self.log("대상 에픽세븐 창을 찾을 수 없습니다.")
            return False

        self._stop_event.clear()
        self.is_running = True
        self.stats.is_running = True
        self.stats.start_time = time.time()

        self._thread = threading.Thread(target=self._run_loop, name="SecretShopThread", daemon=True)
        self._thread.start()

        if self.on_status_change:
            self.on_status_change("실행 중")
        self.log("⚡ 비상런 자동화 루프를 시작했습니다.")
        return True

    def stop(self):
        """비상런 자동화 루프를 안전하게 정지합니다."""
        if not self.is_running:
            return

        self._stop_event.set()
        self.is_running = False
        self.stats.is_running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        if self.on_status_change:
            self.on_status_change("정지됨")
        self.log("⏹️ 비상런 자동화가 정지되었습니다.")

    def _sleep_check(self, seconds: float) -> bool:
        """스톱 이벤트를 실시간 검사하며 대기합니다."""
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self._stop_event.is_set():
                return False
            time.sleep(0.02)
        return True

    def _run_loop(self):
        """비상런 핵심 무한 사이클 루프"""
        self.log("비상런 엔진 가동 시작. 상점 스캔을 시작합니다...")

        while not self._stop_event.is_set():
            # 1. 목표 갱신 횟수 도달 확인
            if self.max_refreshes > 0 and self.stats.refreshes >= self.max_refreshes:
                self.log(f"🎯 설정된 목표 새로고침({self.max_refreshes}회)에 도달하여 비상런을 종료합니다.")
                break

            # 2. 윈도우 유효성 확인
            if not win32gui.IsWindow(self.hwnd):
                self.log("대상 창이 닫혔거나 유효하지 않아 자동 정지합니다.")
                break

            # 3. 1페이지 (상단 슬롯) 검사 및 구매
            bought_in_cycle = self._scan_and_buy_page(page_desc="1페이지(상단)")
            if self._stop_event.is_set():
                break

            # 4. 하단으로 상점 목록 스크롤(드래그)
            cl_rect = win32gui.GetClientRect(self.hwnd)
            win_w = max(cl_rect[2], 100)
            win_h = max(cl_rect[3], 100)

            drag_x1 = int(win_w * self.DRAG_START_RATIO[0])
            drag_y1 = int(win_h * self.DRAG_START_RATIO[1])
            drag_x2 = int(win_w * self.DRAG_END_RATIO[0])
            drag_y2 = int(win_h * self.DRAG_END_RATIO[1])

            dispatch_drag(
                self.hwnd,
                drag_x1, drag_y1,
                drag_x2, drag_y2,
                mode=self.click_mode,
                duration=0.35,
                steps=14
            )

            # 스크롤 애니메이션 대기
            if not self._sleep_check(self.delay_post_drag):
                break

            # 5. 2페이지 (하단 슬롯) 검사 및 구매
            self._scan_and_buy_page(page_desc="2페이지(하단)")
            if self._stop_event.is_set():
                break

            # 6. 새로고침 수행 (하늘석 3개 소모)
            refreshed = self._execute_refresh(win_w, win_h)
            if not refreshed or self._stop_event.is_set():
                break

            # 7. 통계 갱신 및 UI 전달
            if self.on_stats_update:
                try:
                    self.on_stats_update(self.stats)
                except Exception:
                    pass

        self.is_running = False
        self.stats.is_running = False
        if self.on_status_change:
            self.on_status_change("정지됨")
        self.log(f"비상런 종료 - 총 갱신: {self.stats.refreshes}회 | 성약: {self.stats.covenant_count}회 | 신비: {self.stats.mystic_count}회 | 소모 하늘석: {self.stats.skystones_spent}개")

    def _scan_and_buy_page(self, page_desc: str) -> int:
        """한 화면(페이지)의 아이템들을 스캔하고 구매합니다."""
        frame = capture_window(self.hwnd)
        if frame is None:
            return 0

        frame_h, frame_w = frame.shape[:2]

        items_to_search = []
        if self.buy_covenant:
            items_to_search.append("covenant")
        if self.buy_mystic:
            items_to_search.append("mystic")
        if self.buy_friendship:
            items_to_search.append("friendship")

        detected_items = self.find_items_in_frame(frame, items_to_search)

        # 프리뷰 콜백
        if self.on_frame_preview:
            try:
                self.on_frame_preview(frame, detected_items)
            except Exception:
                pass

        bought_count = 0
        for item in detected_items:
            if self._stop_event.is_set():
                break

            itype = item["type"]
            iname = item["name"]
            ix, iy = item["x"], item["y"]

            # 구매 버튼 좌표 계산 (아이템 X + W*0.4718, 아이템 Y)
            buy_btn_x = int(ix + frame_w * self.BUY_BTN_X_OFFSET_RATIO)
            buy_btn_y = iy

            self.log(f"[{page_desc}] ✨ {iname} 발견! (정확도 {item['score']*100:.1f}%) ➔ 구매 진행")

            # 1. 구매 버튼 클릭
            dispatch_click(self.hwnd, buy_btn_x, buy_btn_y, mode=self.click_mode)
            if not self._sleep_check(self.delay_click):
                break

            # 2. 구매 확인 팝업 버튼 클릭
            confirm_x = int(frame_w * self.BUY_CONFIRM_RATIO[0])
            confirm_y = int(frame_h * self.BUY_CONFIRM_RATIO[1])
            dispatch_click(self.hwnd, confirm_x, confirm_y, mode=self.click_mode)
            if not self._sleep_check(self.delay_click):
                break


            # 통계 업데이트
            if itype == "covenant":
                self.stats.covenant_count += 1
                self.log(f"🎉 성약의 책갈피 획득! (누적: {self.stats.covenant_count}회/ {self.stats.covenant_count*5}개)")
            elif itype == "mystic":
                self.stats.mystic_count += 1
                self.log(f"🔮 신비의 메달 획득! (누적: {self.stats.mystic_count}회/ {self.stats.mystic_count*50}개)")
            elif itype == "friendship":
                self.stats.friendship_count += 1
                self.log(f"🤝 우정의 책갈피 획득! (누적: {self.stats.friendship_count}회)")

            bought_count += 1

            if self.on_stats_update:
                try:
                    self.on_stats_update(self.stats)
                except Exception:
                    pass

        return bought_count

    def _execute_refresh(self, win_w: int, win_h: int) -> bool:
        """좌하단 새로고침 및 확인 팝업을 클릭하여 상점을 갱신합니다."""
        # 1. 새로고침 버튼 클릭
        ref_x = int(win_w * self.REFRESH_BTN_RATIO[0])
        ref_y = int(win_h * self.REFRESH_BTN_RATIO[1])

        dispatch_click(self.hwnd, ref_x, ref_y, mode=self.click_mode)
        if not self._sleep_check(self.delay_click):
            return False

        # 2. 새로고침 확인 팝업 (하늘석 3개 소모) 클릭
        conf_x = int(win_w * self.REFRESH_CONFIRM_RATIO[0])
        conf_y = int(win_h * self.REFRESH_CONFIRM_RATIO[1])

        dispatch_click(self.hwnd, conf_x, conf_y, mode=self.click_mode)

        # 갱신 카운트 증가
        self.stats.refreshes += 1

        # 3. 새로운 아이템들이 떨어지는 애니메이션 대기
        if not self._sleep_check(self.delay_post_refresh):
            return False

        return True
