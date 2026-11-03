"""根目录入口：调用本项目uv环境，避免依赖全局Python包。"""
import shutil
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("未找到uv，请按README安装后运行。")
    project = Path(__file__).resolve().parent / "03_Codes"
    raise SystemExit(subprocess.call([
        uv, "run", "--project", str(project), "--frozen", "cgm-library", *sys.argv[1:]
    ]))
