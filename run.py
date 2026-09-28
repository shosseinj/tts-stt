"""Load local server configuration without executing shell code, then launch Flask."""
import os
from pathlib import Path
import sys

from dotenv import load_dotenv


def load_environment(project_dir):
    # Exported variables win; checkout .env takes priority over workspace .env.
    # Disable interpolation so secret values remain literal.
    for path in (project_dir / ".env", project_dir.parent / ".env"):
        load_dotenv(path, override=False, interpolate=False)


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent
    load_environment(project_dir)
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("OPENAI_API_KEY is missing. Set OPENAI_API_KEY=your-key in .env.", flush=True)
    os.chdir(project_dir)
    os.execv(sys.executable, [sys.executable, "-u", str(project_dir / "app.py")])
