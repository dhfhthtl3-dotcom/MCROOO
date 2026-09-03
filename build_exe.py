import os
import sys
import subprocess
import shutil

def build():
    print("=== GameMacro 스탠드얼론 실행파일 빌드 시작 ===")
    
    # 1. CustomTkinter 경로 확인
    import customtkinter
    ctk_path = os.path.dirname(customtkinter.__file__)
    print(f"CustomTkinter 경로: {ctk_path}")
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",       # 콘솔 창 숨김
        "--uac-admin",      # Windows UAC 관리자 권한 매니페스트 내장 (에픽세븐 등 제어 필수)
        "--name", "GameMacro",
        "--collect-all", "customtkinter",
        "--hidden-import", "win32gui",
        "--hidden-import", "win32ui",
        "--hidden-import", "win32con",
        "--hidden-import", "win32api",
        "--hidden-import", "win32process",
        "--hidden-import", "cv2",
        "--hidden-import", "numpy",
        "--hidden-import", "PIL",
        "--hidden-import", "profile_manager",
        "main_gui.py"
    ]
    
    print("실행 명령어:", " ".join(cmd))
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("\n✅ 빌드 성공!")
        dist_exe = os.path.abspath(os.path.join("dist", "GameMacro.exe"))
        print(f"생성된 실행 파일: {dist_exe}")
        
        # templates, targets_config.json, profiles 폴더를 dist 폴더에도 동기화하여 바로 사용 가능하도록 준비
        dist_templates = os.path.join("dist", "templates")
        dist_cfg = os.path.join("dist", "targets_config.json")
        dist_profiles = os.path.join("dist", "profiles")
        
        if os.path.exists("templates"):
            if os.path.exists(dist_templates):
                shutil.rmtree(dist_templates)
            shutil.copytree("templates", dist_templates)
            print("templates 폴더를 dist/ 에 복사했습니다.")

        if os.path.exists("targets_config.json"):
            shutil.copy2("targets_config.json", dist_cfg)
            print("targets_config.json 파일을 dist/ 에 복사했습니다.")

        if os.path.exists("profiles"):
            if os.path.exists(dist_profiles):
                shutil.rmtree(dist_profiles)
            shutil.copytree("profiles", dist_profiles)
            print("profiles 폴더를 dist/ 에 복사했습니다.")
    else:
        print(f"\n❌ 빌드 실패 (코드: {res.returncode})")

if __name__ == "__main__":
    build()
