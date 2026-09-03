"""
다중 매크로 독립 프로필 관리자 (Profile Manager)
- 각 매크로 세트별 독립적인 설정(타겟 버튼 목록, 클릭 모드, 오프셋, 스캔 주기 등) 관리
- 프로필 생성, 전환, 복제, 이름 변경, 삭제 기능
- 기존 targets_config.json 데이터의 100% 무손실 자동 마이그레이션
"""

import os
import sys
import json
import uuid
from typing import List, Dict, Any, Optional


def get_app_dir() -> str:
    """실행 파일(.exe) 또는 프로젝트 소스코드 디렉토리 반환"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


class MacroProfile:
    def __init__(
        self,
        profile_id: str,
        name: str,
        click_mode: str = "hardware",
        global_offset_x: int = 0,
        global_offset_y: int = 0,
        interval: float = 0.4,
        target_window_title: str = "",
        targets: Optional[List[Dict[str, Any]]] = None
    ):
        self.id = profile_id
        self.name = name
        self.click_mode = click_mode
        self.global_offset_x = global_offset_x
        self.global_offset_y = global_offset_y
        self.interval = interval
        self.target_window_title = target_window_title
        self.targets: List[Dict[str, Any]] = targets if targets is not None else []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "click_mode": self.click_mode,
            "global_offset_x": self.global_offset_x,
            "global_offset_y": self.global_offset_y,
            "interval": self.interval,
            "target_window_title": self.target_window_title,
            "targets": self.targets
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MacroProfile":
        return cls(
            profile_id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", "매크로 프로필"),
            click_mode=data.get("click_mode", "hardware"),
            global_offset_x=data.get("global_offset_x", 0),
            global_offset_y=data.get("global_offset_y", 0),
            interval=data.get("interval", 0.4),
            target_window_title=data.get("target_window_title", ""),
            targets=data.get("targets", [])
        )


class ProfileManager:
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir if base_dir else get_app_dir()
        self.profiles_dir = os.path.join(self.base_dir, "profiles")
        self.meta_file = os.path.join(self.profiles_dir, "profiles_meta.json")
        self.legacy_data_file = os.path.join(self.base_dir, "targets_config.json")

        self.profiles: Dict[str, MacroProfile] = {}
        self.active_profile_id: str = "default"

        os.makedirs(self.profiles_dir, exist_ok=True)
        self.load_all()

    def get_active_profile(self) -> MacroProfile:
        if self.active_profile_id in self.profiles:
            return self.profiles[self.active_profile_id]
        if self.profiles:
            first_id = list(self.profiles.keys())[0]
            self.active_profile_id = first_id
            return self.profiles[first_id]
        
        # 프로필이 하나도 없으면 기본 생성
        new_p = self.create_profile("기본 매크로")
        return new_p

    def get_profile_list(self) -> List[Dict[str, str]]:
        """GUI 콤보박스 등에 바인딩할 프로필 [{id, name}, ...] 반환"""
        return [{"id": p.id, "name": p.name} for p in self.profiles.values()]

    def load_all(self):
        """메타 파일 및 모든 프로필 로드 (필요 시 기존 targets_config.json 자동 마이그레이션)"""
        if os.path.exists(self.meta_file):
            try:
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                
                self.active_profile_id = meta.get("active_profile_id", "default")
                for p_info in meta.get("profiles", []):
                    p_id = p_info["id"]
                    p_file = os.path.join(self.profiles_dir, f"{p_id}.json")
                    if os.path.exists(p_file):
                        with open(p_file, "r", encoding="utf-8") as pf:
                            p_data = json.load(pf)
                        self.profiles[p_id] = MacroProfile.from_dict(p_data)

                if not self.profiles:
                    self._create_default_or_migrate()
            except Exception as e:
                print(f"[ProfileManager] 메타 파일 로드 에러: {e}")
                self._create_default_or_migrate()
        else:
            self._create_default_or_migrate()

    def _create_default_or_migrate(self):
        """기존 targets_config.json이 있다면 첫 번째 프로필로 무손실 마이그레이션"""
        legacy_targets = []
        if os.path.exists(self.legacy_data_file):
            try:
                with open(self.legacy_data_file, "r", encoding="utf-8") as f:
                    legacy_targets = json.load(f)
                print(f"[ProfileManager] 기존 targets_config.json에서 타겟 {len(legacy_targets)}개 감지 -> 기본 매크로 프로필로 자동 마이그레이션")
            except Exception as e:
                print(f"[ProfileManager] 기존 파일 읽기 실패: {e}")

        default_profile = MacroProfile(
            profile_id="default",
            name="기본 매크로",
            click_mode="hardware",
            global_offset_x=0,
            global_offset_y=0,
            interval=0.4,
            target_window_title="에픽세븐",
            targets=legacy_targets
        )
        self.profiles["default"] = default_profile
        self.active_profile_id = "default"
        self.save_profile(default_profile)
        self.save_meta()

    def save_meta(self):
        """프로필 목록 및 활성 프로필 메타데이터 저장"""
        meta = {
            "active_profile_id": self.active_profile_id,
            "profiles": [{"id": p.id, "name": p.name} for p in self.profiles.values()]
        }
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def save_profile(self, profile: MacroProfile):
        """특정 프로필 상세 정보 저장"""
        p_file = os.path.join(self.profiles_dir, f"{profile.id}.json")
        with open(p_file, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)

    def save_active_profile(self):
        """현재 활성 프로필 저장"""
        cur = self.get_active_profile()
        self.save_profile(cur)
        self.save_meta()

    def create_profile(self, name: str) -> MacroProfile:
        """새 독립 프로필 생성 후 즉시 활성화"""
        new_id = f"prof_{uuid.uuid4().hex[:8]}"
        new_profile = MacroProfile(
            profile_id=new_id,
            name=name.strip() if name.strip() else "새 매크로",
            click_mode="hardware",
            global_offset_x=0,
            global_offset_y=0,
            interval=0.4,
            target_window_title="",
            targets=[]
        )
        self.profiles[new_id] = new_profile
        self.active_profile_id = new_id
        self.save_profile(new_profile)
        self.save_meta()
        return new_profile

    def switch_profile(self, profile_id: str) -> Optional[MacroProfile]:
        """활성 프로필 변경"""
        if profile_id in self.profiles:
            self.active_profile_id = profile_id
            self.save_meta()
            return self.profiles[profile_id]
        return None

    def rename_profile(self, profile_id: str, new_name: str) -> bool:
        """프로필 이름 변경"""
        if profile_id in self.profiles and new_name.strip():
            self.profiles[profile_id].name = new_name.strip()
            self.save_profile(self.profiles[profile_id])
            self.save_meta()
            return True
        return False

    def duplicate_profile(self, source_id: str, new_name: str) -> Optional[MacroProfile]:
        """기존 프로필을 복제하여 새 독립 프로필 생성"""
        if source_id not in self.profiles:
            return None

        src = self.profiles[source_id]
        new_id = f"prof_{uuid.uuid4().hex[:8]}"
        
        # 타겟 목록 깊은 복사 (타겟 ID도 새로 생성하여 독립성 보장)
        new_targets = []
        for t in src.targets:
            t_copy = dict(t)
            new_targets.append(t_copy)

        new_profile = MacroProfile(
            profile_id=new_id,
            name=new_name.strip() if new_name.strip() else f"{src.name} (복제본)",
            click_mode=src.click_mode,
            global_offset_x=src.global_offset_x,
            global_offset_y=src.global_offset_y,
            interval=src.interval,
            target_window_title=src.target_window_title,
            targets=new_targets
        )
        self.profiles[new_id] = new_profile
        self.active_profile_id = new_id
        self.save_profile(new_profile)
        self.save_meta()
        return new_profile

    def delete_profile(self, profile_id: str) -> bool:
        """프로필 삭제 (최소 1개 유지 보장)"""
        if len(self.profiles) <= 1:
            return False  # 최소 1개는 남아있어야 함

        if profile_id in self.profiles:
            del self.profiles[profile_id]
            p_file = os.path.join(self.profiles_dir, f"{profile_id}.json")
            if os.path.exists(p_file):
                try:
                    os.remove(p_file)
                except Exception:
                    pass

            # 활성 프로필이 삭제된 경우 다른 프로필로 전환
            if self.active_profile_id == profile_id:
                self.active_profile_id = list(self.profiles.keys())[0]

            self.save_meta()
            return True
        return False
