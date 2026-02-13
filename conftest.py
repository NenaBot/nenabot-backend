"""Root pytest configuration"""
import sys
from pathlib import Path

# Add subdirectory packages to Python path for imports
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir / "camera_detection"))
sys.path.insert(0, str(root_dir / "orchestrator"))
