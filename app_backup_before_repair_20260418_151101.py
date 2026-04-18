
from pathlib import Path
from datetime import datetime
import re

ROOT = Path.home() / "Projects" / "invest-dashboard"
APP = ROOT / "app.py"

def main():
    if not APP.exists():
        raise FileNotFoundError(f"app.py not found: {APP}")

    src = APP.read_text(encoding="utf-8")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / f"app_backup_before_repair_{stamp}.py"
    backup.write_text(src, encoding="utf-8")

    patterns = [
        r'if __name__ == "__main__":\s*\n\s*main\(\)\s*',
        r"if __name__ == '__main__':\s*\n\s*main\(\)\s*",
    ]

    end = None
    for pat in patterns:
        m = re.search(pat, src, flags=re.MULTILINE)
        if m:
            end = m.end()
            break

    if end is None:
        raise RuntimeError("main() 실행 블록을 찾지 못했습니다. 현재 app.py 구조를 다시 확인해야 합니다.")

    cleaned = src[:end].rstrip() + "\n"

    if cleaned == src:
        print("추가로 잘라낼 top-level 코드가 없었습니다.")
    else:
        APP.write_text(cleaned, encoding="utf-8")
        print("app.py 정리 완료")
        print(f"백업 파일: {backup}")
        print("main() 아래에 잘못 붙은 top-level 코드들을 제거했습니다.")

if __name__ == "__main__":
    main()
