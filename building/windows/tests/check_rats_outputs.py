"""Validate outputs from a completed RATS render run, without canonical images.

The manifest is CTest --show-only=json-v1 for the matching 'update' selection.
Its declared outputs and additional EXRs written during this run are read;
no update command is executed.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--manifest", required=True, type=Path)
parser.add_argument("--junit", required=True, type=Path)
parser.add_argument("--report", required=True, type=Path)
args = parser.parse_args()

# Optional PATH entries may be stale or belong to inaccessible user directories.
dll_handles = []
if os.name == "nt":
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            try:
                dll_handles.append(os.add_dll_directory(entry))
            except OSError:
                pass
from OpenImageIO import ImageBuf, ImageBufAlgo

raw = args.manifest.read_bytes()
manifest = json.loads(raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"))
suite = ET.parse(args.junit).getroot()
started = datetime.fromisoformat(suite.attrib["timestamp"]).timestamp()
completed = {case.attrib["name"]: case for case in suite.findall("testcase")}
images = {}
cases = []
errors = []
skipped = []
failed = []
for test in manifest["tests"]:
    name = test["name"].replace("update-", "render-", 1)
    if name not in completed:
        errors.append(f"No CTest result for {name}")
        continue
    case = completed[name]
    if case.find("skipped") is not None or case.attrib.get("status") in ("notrun", "disabled"):
        skipped.append(name)
        continue
    if case.find("failure") is not None:
        failed.append(name)
        continue
    properties = {p["name"]: p["value"] for p in test["properties"]}
    directory = Path(properties["WORKING_DIRECTORY"])
    command = test["command"]
    expected = [command[i + 1] for i, arg in enumerate(command) if arg == "--canonicals"]
    case_images = []
    if not expected:
        errors.append(f"No declared output images for {name}")
    # Some upstream cases only compare the flat beauty while also writing deep
    # images or other AOVs. Inspect those new files as well, without accepting
    # an old file as a substitute for a missing declared output.
    expected += sorted(p.name for p in directory.glob("*.exr")
                       if p.name not in expected and p.stat().st_mtime >= started - 2)
    for filename in expected:
        path = directory / filename
        key = str(path.resolve())
        case_images.append(key)
        if key in images:
            continue
        result = {"path": key, "parts": [], "errors": []}
        images[key] = result
        try:
            if path.stat().st_mtime < started - 2:
                raise RuntimeError("Output predates this render run")
            image = ImageBuf(str(path))
            count = image.nsubimages
            if count < 1:
                raise RuntimeError(image.geterror() or "No readable image parts")
            for index in range(count):
                part = ImageBuf(str(path), index, 0)
                if not part.read():
                    raise RuntimeError(part.geterror() or f"Could not read part {index}")
                spec = part.spec()
                if min(spec.width, spec.height, spec.nchannels) < 1:
                    raise RuntimeError(f"Empty image part {index}")
                stats = ImageBufAlgo.computePixelStats(part)
                if part.has_error:
                    raise RuntimeError(part.geterror())
                nonfinite = []
                packed = []
                for channel, nan, inf in zip(spec.channelnames, stats.nancount, stats.infcount):
                    if nan or inf:
                        entry = {"channel": channel, "nan": nan, "inf": inf}
                        # DcxSpMask8 stores the 64-bit subpixel mask as two float
                        # bit patterns. Those channels are not numeric samples.
                        if spec.deep and channel in ("deepabuf.sp1", "deepabuf.sp2"):
                            packed.append(entry)
                        else:
                            nonfinite.append(entry)
                result["parts"].append({"part": index, "width": spec.width,
                                        "height": spec.height, "deep": spec.deep,
                                        "channels": list(spec.channelnames),
                                        "nonfinite_numeric_channels": nonfinite,
                                        "packed_subpixel_mask_counts": packed})
                if nonfinite:
                    result["errors"].append(f"Non-finite numeric samples in part {index}: {nonfinite}")
        except (OSError, RuntimeError) as error:
            result["errors"].append(str(error))
        errors.extend(f"{path}: {error}" for error in result["errors"])
    cases.append({"test": name, "images": case_images})
    if len(cases) % 50 == 0:
        print(f"Checked {len(cases)} render cases, {len(images)} files", flush=True)

report = {"junit": str(args.junit), "manifest": str(args.manifest),
          "render_cases_checked": len(cases), "image_files_checked": len(images),
          "image_parts_checked": sum(len(i["parts"]) for i in images.values()),
          "skipped": skipped, "failed_render_cases": failed, "errors": errors,
          "trusted_reference_comparison": False, "cases": cases, "images": list(images.values())}
args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(f"Checked {len(cases)} cases, {len(images)} images, {report['image_parts_checked']} parts; "
      f"{len(skipped)} skipped, {len(failed)} render failures, {len(errors)} output errors")
for error in errors:
    print(error, file=sys.stderr)
sys.exit(1 if errors or failed else 0)
