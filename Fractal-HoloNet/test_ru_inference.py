import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from tests.test_ru_inference import run_ru_inference

if __name__ == "__main__":
    run_ru_inference()
