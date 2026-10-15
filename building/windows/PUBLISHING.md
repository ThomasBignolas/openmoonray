# Personal GitHub backup

Publish validated Windows/Houdini work to
`ThomasBignolas/openmoonray`, branch `codex/windows-houdini`.
The user explicitly requested this ongoing backup on October 15, 2026.
The local `origin` still names the official upstream repository. Keep uploads
on the user's fork, preserving existing branches and unrelated work.

The project contains 20 pinned submodules. A root-only commit does not preserve
edits inside them. This branch therefore includes the root Windows scripts and
an exact source archive under `building/windows/snapshots/`, with a manifest,
all submodule changes, base revisions and SHA-256 verification. The archive's
`APPLY.txt` explains restoration to a separate clean upstream checkout. Its
patches are checked against their recorded bases by `package_source_changes.py`.
Snapshots are generated under the ignored `build/` directory. Uploaded snapshot
blobs are not copied into this working checkout's source tree, avoiding recursive
inclusion of old archives in later snapshots.

Before updating the branch, create a new source archive, verify it, and include
the current root source files plus that archive and its verification report.
Advance the branch from its current remote head with a lease; do not force over
someone else's changes. Verify the uploaded tree/blob hashes afterward.
Never substitute a root-only source upload for the submodule archive.

The connected GitHub tools can upload files even when the local Git credential
manager is not signed in. Do not put credentials in scripts or repository files.
Compiled runtimes, render caches, test images, and personal environment files
stay out of Git history. Portable binary ZIPs are separate artifacts; see
[the transfer guide](houdini/PORTABLE.md).
