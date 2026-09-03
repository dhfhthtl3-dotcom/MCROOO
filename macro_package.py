"""
4단계 보안 검증 기반 .gmac 매크로 패키지 내보내기/가져오기 엔진
- 무단 실행 파일/스크립트 100% 차단 (화이트리스트 검사)
- Zip Slip(경로 조작) 및 Zip Bomb(용량 폭탄) 방어
- 윈도우 시스템 및 백신 창 타겟팅 방어 (Target Guard)
- 이미지 바이너리 디코딩 검증 및 안전 수치 강제 보정
"""

import os
import io
import json
import zipfile
import uuid
import cv2
import numpy as np
from typing import Dict, Any, List, Optional, Tuple

from profile_manager import MacroProfile, ProfileManager, get_app_dir

# ------------------ 보안 검증 상수 ------------------
MAX_PACKAGE_SIZE = 15 * 1024 * 1024   # 최대 15 MB
MAX_TARGET_COUNT = 30                 # 최대 30개 버튼
MIN_INTERVAL = 0.1                    # 최소 스캔 주기 (DoS 방지)
MIN_COOLDOWN = 0.1                    # 최소 재클릭 쿨다운

# 악성 실행 가능 확장자 블랙리스트
DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".vbs", ".vbe", ".js", ".jse", 
    ".wsf", ".wsh", ".msc", ".ps1", ".ps1xml", ".ps2", ".ps2xml", 
    ".psc1", ".psc2", ".py", ".pyw", ".dll", ".scr", ".pif", ".hta", 
    ".cpl", ".jar", ".reg", ".lnk", ".inf"
}

# 윈도우 시스템 및 보안 프로그램 창 제목 블랙리스트
DANGEROUS_WINDOW_KEYWORDS = [
    "작업 관리자", "task manager", "명령 프롬프트", "cmd.exe", 
    "powershell", "레지스트리 편집기", "regedit", "제어판", "control panel",
    "windows defender", "v3", "알약", "ahnlab", "avast", "kaspersky", 
    "eset", "방화벽", "firewall", "서비스 관리", "services.msc"
]


def export_macro_package(
    profile: MacroProfile,
    templates_dir: str,
    export_filepath: str
) -> str:
    """
    현재 매크로 프로필과 템플릿 이미지를 묶어 안전한 단일 .gmac 패키지로 내보냅니다.
    """
    if not export_filepath.lower().endswith(".gmac"):
        export_filepath += ".gmac"

    meta_data = profile.to_dict()
    # 내보내기 메타 정보 추가
    meta_data["format_version"] = "2.2"
    meta_data["export_app"] = "GameMacro"

    with zipfile.ZipFile(export_filepath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. 메타데이터 JSON 저장
        meta_json = json.dumps(meta_data, ensure_ascii=False, indent=2)
        zf.writestr("macro_meta.json", meta_json.encode("utf-8"))

        # 2. 타겟 템플릿 이미지 저장
        for target in profile.targets:
            img_filename = target.get("image_file", f"target_{target.get('id')}.png")
            img_path = os.path.join(templates_dir, img_filename)
            if os.path.exists(img_path):
                zf.write(img_path, arcname=f"images/{img_filename}")

    return export_filepath


def inspect_and_verify_package(package_filepath: str) -> Dict[str, Any]:
    """
    .gmac 패키지를 분석하고 4단계 보안 검사를 수행합니다.
    사용자에게 보여줄 메타 정보와 이미지 썸네일 데이터를 함께 반환합니다.
    """
    result = {
        "is_safe": False,
        "errors": [],
        "warnings": [],
        "meta": None,
        "images": {},       # target_id -> np.ndarray (BGR)
        "total_size": 0,
        "file_count": 0
    }

    if not os.path.exists(package_filepath):
        result["errors"].append("지정한 매크로 파일이 존재하지 않습니다.")
        return result

    # 1. 파일 크기 검사 (최대 15MB)
    file_size = os.path.getsize(package_filepath)
    result["total_size"] = file_size
    if file_size > MAX_PACKAGE_SIZE:
        result["errors"].append(f"파일 크기 초과: {file_size / (1024*1024):.1f}MB (최대 {MAX_PACKAGE_SIZE//(1024*1024)}MB)")
        return result

    try:
        with zipfile.ZipFile(package_filepath, "r") as zf:
            infolist = zf.infolist()
            result["file_count"] = len(infolist)

            # 2. 파일 목록 화이트리스트 및 Zip Slip(경로 조작) 검사
            has_meta = False
            total_uncompressed = 0

            for info in infolist:
                filename = info.filename
                total_uncompressed += info.file_size

                # 압축 폭탄(Zip Bomb) 방어
                if total_uncompressed > MAX_PACKAGE_SIZE * 3:
                    result["errors"].append("압축 해제 크기가 안전 한도를 초과했습니다 (Zip Bomb 의심).")
                    return result

                # 경로 탈출(Zip Slip) 검사
                if os.path.isabs(filename) or ".." in filename.split("/") or ".." in filename.split("\\"):
                    result["errors"].append(f"비정상적 경로 조작 시도 감지: {filename}")
                    return result

                # 위험 확장자 검사
                _, ext = os.path.splitext(filename.lower())
                if ext in DANGEROUS_EXTENSIONS:
                    result["errors"].append(f"🚨 위험한 실행 파일/스크립트 감지: {filename}")
                    return result

                # 화이트리스트 검사: 오직 macro_meta.json과 images/*.png만 허용
                if filename == "macro_meta.json":
                    has_meta = True
                elif filename.startswith("images/") and ext == ".png":
                    pass
                elif filename.endswith("/"): # 디렉토리 엔트리 허용
                    pass
                else:
                    result["errors"].append(f"허용되지 않은 파일 형식: {filename}")
                    return result

            if not has_meta:
                result["errors"].append("매크로 메타데이터(macro_meta.json)가 누락되었습니다.")
                return result

            # 3. 메타데이터 파싱 및 내용 검사
            try:
                meta_bytes = zf.read("macro_meta.json")
                meta_data = json.loads(meta_bytes.decode("utf-8"))
                result["meta"] = meta_data
            except Exception as e:
                result["errors"].append(f"메타데이터 파싱 실패: {e}")
                return result

            targets = meta_data.get("targets", [])
            if len(targets) > MAX_TARGET_COUNT:
                result["errors"].append(f"타겟 개수 초과: {len(targets)}개 (최대 {MAX_TARGET_COUNT}개)")
                return result

            # 시스템 윈도우 제어 시도 검사
            target_win = meta_data.get("target_window_title", "").lower()
            for kw in DANGEROUS_WINDOW_KEYWORDS:
                if kw.lower() in target_win:
                    result["errors"].append(f"🚨 시스템/보안 프로그램 창을 조작하려는 위험 매크로 감지: '{meta_data.get('target_window_title')}'")
                    return result

            # 4. 이미지 바이너리 디코딩 검증
            for t in targets:
                t_id = t.get("id")
                img_file = t.get("image_file", f"target_{t_id}.png")
                arc_path = f"images/{img_file}"

                if arc_path in zf.namelist():
                    img_data = zf.read(arc_path)
                    file_bytes = np.frombuffer(img_data, dtype=np.uint8)
                    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

                    if img is None:
                        result["errors"].append(f"손상되거나 유효하지 않은 이미지 파일: {img_file}")
                        return result

                    # 이미지 크기 상한선 검사
                    ih, iw = img.shape[:2]
                    if iw > 4000 or ih > 4000 or iw < 4 or ih < 4:
                        result["errors"].append(f"비정상적인 이미지 해상도: {iw}x{ih} ({img_file})")
                        return result

                    result["images"][t_id] = img

    except zipfile.BadZipFile:
        result["errors"].append("손상되었거나 유효하지 않은 매크로 패키지(.gmac) 파일입니다.")
        return result
    except Exception as e:
        result["errors"].append(f"검증 도중 예기치 못한 오류 발생: {e}")
        return result

    # 오류가 없으면 안전 상태로 확인
    result["is_safe"] = (len(result["errors"]) == 0)
    return result


def import_macro_package(
    package_filepath: str,
    profile_manager: ProfileManager,
    templates_dir: str,
    custom_name: Optional[str] = None
) -> Tuple[bool, str, Optional[MacroProfile]]:
    """
    보안 검증 통과 후 패키지를 로컬 프로필 및 템플릿 폴더에 안전하게 설치합니다.
    """
    verification = inspect_and_verify_package(package_filepath)
    if not verification["is_safe"]:
        return False, "보안 검증 실패: " + ", ".join(verification["errors"]), None

    meta = verification["meta"]
    images = verification["images"]

    # 새 프로필 이름 결정
    p_name = custom_name.strip() if (custom_name and custom_name.strip()) else meta.get("name", "가져온 매크로")
    new_profile_id = f"prof_{uuid.uuid4().hex[:8]}"

    # 이미지들을 로컬 templates 폴더에 안전하게 복사
    os.makedirs(templates_dir, exist_ok=True)
    new_targets = []

    for t in meta.get("targets", []):
        old_id = t.get("id")
        new_target_id = uuid.uuid4().hex[:8]
        new_img_filename = f"target_{new_target_id}.png"
        new_img_path = os.path.join(templates_dir, new_img_filename)

        if old_id in images:
            img = images[old_id]
            is_success, buffer = cv2.imencode(".png", img)
            if is_success:
                with open(new_img_path, "wb") as f:
                    f.write(buffer)

        # 안전 수치 강제 적용
        safe_interval = max(MIN_INTERVAL, float(t.get("cooldown", 2.0)))
        safe_threshold = min(0.99, max(0.50, float(t.get("threshold", 0.85))))

        target_dict = {
            "id": new_target_id,
            "name": t.get("name", "버튼"),
            "threshold": safe_threshold,
            "priority": int(t.get("priority", 1)),
            "cooldown": safe_interval,
            "offset_x": int(t.get("offset_x", 0)),
            "offset_y": int(t.get("offset_y", 0)),
            "enabled": bool(t.get("enabled", True)),
            "w": int(t.get("w", 50)),
            "h": int(t.get("h", 30)),
            "base_width": int(t.get("base_width", 0)),
            "base_height": int(t.get("base_height", 0)),
            "image_file": new_img_filename
        }
        new_targets.append(target_dict)

    # 프로필 생성
    safe_scan_interval = max(MIN_INTERVAL, float(meta.get("interval", 0.4)))
    new_profile = MacroProfile(
        profile_id=new_profile_id,
        name=p_name,
        click_mode=meta.get("click_mode", "hardware"),
        global_offset_x=int(meta.get("global_offset_x", 0)),
        global_offset_y=int(meta.get("global_offset_y", 0)),
        interval=safe_scan_interval,
        target_window_title=meta.get("target_window_title", ""),
        targets=new_targets
    )

    profile_manager.profiles[new_profile_id] = new_profile
    profile_manager.active_profile_id = new_profile_id
    profile_manager.save_profile(new_profile)
    profile_manager.save_meta()

    return True, f"매크로 프로필 '{p_name}' 가져오기 성공 (버튼 {len(new_targets)}개 등록)", new_profile
