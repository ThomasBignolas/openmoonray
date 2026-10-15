# SPDX-License-Identifier: Apache-2.0
"""Verify that Lua bytecode embedding preserves every byte on Windows."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="lua binary test ") as directory:
    source = Path(directory) / "all bytes.bin"
    output = Path(directory) / "generated.cc"
    data = bytes(range(256)) * 3
    source.write_bytes(data)
    subprocess.run([sys.argv[1], sys.argv[2], str(source), str(output)], check=True)
    text = output.read_text()
    result = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-f]{2})", text))
    if result != data or f"bin2cc_len = {len(data)};" not in text:
        raise RuntimeError("Lua bin2cc changed binary data")
