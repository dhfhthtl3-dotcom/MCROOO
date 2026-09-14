import os
import urllib.request
import cv2
import numpy as np

def main():
    dest_dir = os.path.join(r"c:\게임매크로", "templates", "secret_shop")
    os.makedirs(dest_dir, exist_ok=True)

    targets = [
        {
            "filename": "cov.png",
            "url": "https://raw.githubusercontent.com/Solunium/Epic-Seven-E7-Secret-Shop-Refresh/main/assets/cov.png",
            "desc": "성약의 책갈피"
        },
        {
            "filename": "mys.png",
            "url": "https://raw.githubusercontent.com/Solunium/Epic-Seven-E7-Secret-Shop-Refresh/main/assets/mys.png",
            "desc": "신비의 메달"
        },
        {
            "filename": "fb.png",
            "url": "https://raw.githubusercontent.com/Solunium/Epic-Seven-E7-Secret-Shop-Refresh/main/assets/fb.png",
            "desc": "우정의 책갈피"
        },
        {
            "filename": "cov_adb.png",
            "url": "https://raw.githubusercontent.com/Solunium/Epic-Seven-E7-Secret-Shop-Refresh/main/adb-assets/cov.png",
            "desc": "고해상도 성약 책갈피"
        },
        {
            "filename": "mys_adb.png",
            "url": "https://raw.githubusercontent.com/Solunium/Epic-Seven-E7-Secret-Shop-Refresh/main/adb-assets/mys.png",
            "desc": "고해상도 신비 메달"
        }
    ]

    results = []
    for item in targets:
        file_path = os.path.join(dest_dir, item["filename"])
        req = urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        file_size = os.path.getsize(file_path)
        
        # Verify relative path cv2.imread
        rel_path = os.path.relpath(file_path, r"c:\게임매크로")
        img_rel = cv2.imread(rel_path)
        
        # Verify absolute path with cv2.imdecode
        with open(file_path, "rb") as f:
            buf = np.frombuffer(f.read(), dtype=np.uint8)
            img_decode = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            
        shape_str = f"{img_decode.shape[1]}x{img_decode.shape[0]} ({img_decode.shape[2]} channels)" if img_decode is not None else "None"
        
        results.append({
            "name": item["filename"],
            "desc": item["desc"],
            "path": file_path,
            "size": file_size,
            "cv2_imread_rel": img_rel is not None,
            "cv2_imdecode": img_decode is not None,
            "resolution": shape_str
        })

    print("=== DOWNLOAD & VERIFICATION RESULTS ===")
    for r in results:
        status_str = "SUCCESS" if (r["cv2_imread_rel"] and r["cv2_imdecode"]) else "FAIL"
        print(f"File: {r['name']} ({r['desc']})")
        print(f"  Path: {r['path']}")
        print(f"  Size: {r['size']:,} bytes")
        print(f"  Resolution (WxH): {r['resolution']}")
        print(f"  cv2.imread(relative path): {'SUCCESS' if r['cv2_imread_rel'] else 'FAIL'}")
        print(f"  cv2.imdecode(full path): {'SUCCESS' if r['cv2_imdecode'] else 'FAIL'}")
        print(f"  Final Status: {status_str}")
        print()

if __name__ == "__main__":
    main()
