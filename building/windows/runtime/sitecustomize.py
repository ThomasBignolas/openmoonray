"""Register this bundle's native libraries for Python 3.8+ extension loading."""
import os
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
_dll_directories = [os.add_dll_directory(str(_root / directory))
                    for directory in ("bin", "lib", "python", "python/DLLs")]
