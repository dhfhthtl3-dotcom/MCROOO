"""
다중 타겟(버튼) 정밀 이미지 감지 엔진 (Multi-Target Detection Engine)
- 여러 개의 버튼/프레임 템플릿을 등록하고 화면에서 동시 탐색
- 각 버튼별 독립적인 일치율(Threshold), 우선순위(Priority), 쿨다운 관리
- 감지된 모든 버튼을 화면 미리보기에 색상별로 시각화
"""

import uuid
import time
import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple, Union
from PIL import Image


class TargetItem:
    def __init__(
        self,
        name: str,
        template_img: np.ndarray,
        threshold: float = 0.85,
        priority: int = 1,
        cooldown: float = 2.0,
        offset_x: int = 0,
        offset_y: int = 0,
        enabled: bool = True,
        target_id: Optional[str] = None,
        base_width: int = 0,
        base_height: int = 0
    ):
        self.id = target_id if target_id else str(uuid.uuid4())[:8]
        self.name = name
        self.template_img = template_img.copy()
        
        if len(self.template_img.shape) == 3:
            self.template_gray = cv2.cvtColor(self.template_img, cv2.COLOR_BGR2GRAY)
        else:
            self.template_gray = self.template_img.copy()
            
        self.h, self.w = self.template_gray.shape[:2]
        self.threshold = threshold
        self.priority = priority
        self.cooldown = cooldown
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.enabled = enabled
        self.last_click_time = 0.0

        # 등록 당시 기준 화면 해상도 (해상도 자동 보정에 사용)
        self.base_width = base_width
        self.base_height = base_height

        # 리사이즈 템플릿 캐시: (w, h) -> np.ndarray
        self._scaled_cache: Dict[Tuple[int, int], np.ndarray] = {
            (self.w, self.h): self.template_gray
        }

    def get_scaled_template(self, target_w: int, target_h: int) -> np.ndarray:
        """지정된 크기의 리사이즈 그레이스케일 템플릿을 캐싱하여 반환합니다."""
        key = (target_w, target_h)
        if key not in self._scaled_cache:
            interp = cv2.INTER_AREA if target_w < self.w else cv2.INTER_LINEAR
            self._scaled_cache[key] = cv2.resize(self.template_gray, (target_w, target_h), interpolation=interp)
        return self._scaled_cache[key]

    def to_dict(self) -> Dict[str, any]:
        return {
            "id": self.id,
            "name": self.name,
            "threshold": self.threshold,
            "priority": self.priority,
            "cooldown": self.cooldown,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "enabled": self.enabled,
            "w": self.w,
            "h": self.h,
            "base_width": self.base_width,
            "base_height": self.base_height
        }


class MultiTargetDetector:
    # 감지 박스 표시에 사용할 다양한 색상 팔레트
    COLORS = [
        (0, 255, 0),    # 초록
        (0, 215, 255),  # 금색/노랑
        (255, 105, 180),# 핫핑크
        (0, 165, 255),  # 주황
        (255, 0, 128),  # 자주
        (50, 205, 50),  # 라임
        (255, 215, 0),  # 골드
    ]

    def __init__(self):
        self.targets: Dict[str, TargetItem] = {}

    def add_target(self, target: TargetItem):
        self.targets[target.id] = target

    def remove_target(self, target_id: str):
        if target_id in self.targets:
            del self.targets[target_id]

    def clear_targets(self):
        self.targets.clear()

    def get_target(self, target_id: str) -> Optional[TargetItem]:
        return self.targets.get(target_id)

    def get_all_targets(self) -> List[TargetItem]:
        # 우선순위 기준 정렬
        return sorted(list(self.targets.values()), key=lambda t: (t.priority, -t.threshold))

    def detect_all(self, screen_img: np.ndarray) -> List[Dict[str, any]]:
        """
        화면 프레임에서 등록된 모든 활성 타겟을 검사하여 일치율 기준을 만족하는 탐지 목록을 반환합니다.
        창 해상도가 달라지더라도 기준 해상도(base_width, base_height) 대비 배율을 자동 계산하여 리사이즈 매칭합니다.
        
        :return: 감지된 타겟 목록 (우선순위 순으로 정렬됨)
        """
        if screen_img is None or not self.targets:
            return []

        screen_h, screen_w = screen_img.shape[:2]
        if len(screen_img.shape) == 3:
            screen_gray = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
        else:
            screen_gray = screen_img

        detections = []

        for target in self.targets.values():
            if not target.enabled:
                continue

            # 1. 기준 배율 계산
            if target.base_width > 0 and target.base_height > 0:
                scale_x = screen_w / float(target.base_width)
                scale_y = screen_h / float(target.base_height)
                # 게임의 일반적인 종횡비 스케일 적용
                primary_scale = (scale_x + scale_y) / 2.0
            else:
                primary_scale = 1.0

            # 2. 다중 스케일 후보 탐색 (기본 배율 및 미세 인접 배율)
            candidate_scales = [primary_scale]
            if abs(primary_scale - 1.0) > 0.05:
                candidate_scales.extend([primary_scale * 0.95, primary_scale * 1.05])

            best_match = None
            best_confidence = -1.0

            for sc in candidate_scales:
                cur_w = max(5, int(round(target.w * sc)))
                cur_h = max(5, int(round(target.h * sc)))

                if cur_w > screen_w or cur_h > screen_h:
                    continue

                scaled_tmpl = target.get_scaled_template(cur_w, cur_h)
                res = cv2.matchTemplate(screen_gray, scaled_tmpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                conf = float(max_val)
                if conf > best_confidence:
                    best_confidence = conf
                    best_match = (conf, max_loc, cur_w, cur_h, sc)

            if best_match is None:
                continue

            confidence, max_loc, cur_w, cur_h, best_sc = best_match
            if confidence < 0:
                confidence = 0.0

            matched = confidence >= target.threshold

            top_left_x, top_left_y = max_loc
            center_x = top_left_x + cur_w // 2 + int(round(target.offset_x * best_sc))
            center_y = top_left_y + cur_h // 2 + int(round(target.offset_y * best_sc))

            # 감지 정보 기록
            det = {
                "target": target,
                "target_id": target.id,
                "name": target.name,
                "confidence": round(confidence, 4),
                "matched": matched,
                "center": (center_x, center_y),
                "box": (top_left_x, top_left_y, cur_w, cur_h),
                "scale": round(best_sc, 3),
                "priority": target.priority,
                "threshold": target.threshold
            }

            if matched:
                detections.append(det)

        # 1순위: 우선순위 오름차순(1 -> 2 -> 3), 2순위: 일치율 내림차순
        detections.sort(key=lambda d: (d["priority"], -d["confidence"]))
        return detections

    def draw_detections(self, screen_img: np.ndarray, detections: List[Dict[str, any]]) -> np.ndarray:
        """
        감지된 타겟들을 화면 위에 시각화(라벨, 사각형, 중심 클릭점)하여 반환합니다.
        """
        output = screen_img.copy()

        for idx, det in enumerate(detections):
            color = self.COLORS[idx % len(self.COLORS)]
            x, y, w, h = det["box"]
            cx, cy = det["center"]
            name = det["name"]
            pct = det["confidence"] * 100

            # 경계 박스
            cv2.rectangle(output, (x, y), (x + w, y + h), color, 2)
            
            # 클릭 타겟 중심점 (십자 마크)
            cv2.drawMarker(output, (cx, cy), color, cv2.MARKER_CROSS, 14, 2)
            cv2.circle(output, (cx, cy), 3, (0, 0, 255), -1)

            # 라벨 텍스트 배경 및 문자
            label = f"{name} ({pct:.1f}%)"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.55
            thickness = 1
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)

            text_y = max(th + 5, y - 5)
            cv2.rectangle(output, (x, text_y - th - 3), (x + tw + 6, text_y + 3), (20, 20, 20), -1)
            cv2.putText(output, label, (x + 3, text_y), font, font_scale, color, thickness, cv2.LINE_AA)

        return output
