from pathlib import Path
import sys

Path(sys.argv[1]).write_bytes(bytes(range(256)) * 3 + b"\x00\xff\x1a")
