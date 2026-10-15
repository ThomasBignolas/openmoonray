# MoonRay workstation project

- The user has asked that completed, validated Windows/Houdini integration work
  also be backed up to **their** GitHub: `ThomasBignolas/openmoonray`, branch
  `codex/windows-houdini`. Keep this backup current when finishing changes.
  The local `origin` points to official OpenMoonRay; do not publish there.
- Preserve the current checkout and open Houdini scenes. Use isolated packages
  and test preferences; do not close the user's Houdini session to load a DLL.
- Keep validation small unless the user requests a large-scene run. Leave at
  least one logical CPU free; use the existing bounded-process helper.
- Portable distribution and source backup instructions live in
  `building/windows/houdini/PORTABLE.md` and `building/windows/PUBLISHING.md`.
