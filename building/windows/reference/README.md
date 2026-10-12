# Independent Linux RATS references

This job runs the published Linux MoonRay Snap revision 23 to generate reference
images for the Windows port. It does not build or run the Windows candidate.
`reference-lock.json` fixes the download checksum, renderer binary hashes,
RATS source revision and test-harness patch checksum. Renderer, shader, Hydra,
Arras and RATS revisions match the Windows port's bases; the two differing
component revisions contain build-system changes documented in the lock file's
component table and the port validation records.

The workflow is `.github/workflows/windows-port-reference.yml`. A push changing
these files on `codex/windows-reference-validation` starts the job on a standard
Ubuntu 24.04 GitHub-hosted runner. No Windows feature changes are required.
Publishing the prepared files and running the hosted workflow is a separate
action from preparing them locally.

`plan.json` initially selects `focus`: scalar/vector sphere and checkerboard,
plus the Hydra skinned-geometry scene. These five cases retain their upstream
scene inputs, dimensions, sample counts and 25 candidate renders per canonical.
The updater derives the comparison thresholds from those candidates.
Changing the scope to `all` runs all 645 enabled CPU/default cases in 16 jobs,
with at most four jobs running together. Every execution mode of a scene stays
in the same job because its thresholds share a `diff.json` file. The five
upstream-disabled cases remain excluded.

`rats-harness.patch` carries the Windows port's five RATS harness file changes:
argument-array handling, portable environment paths, optional Hydra selection,
corrected canonical mode keys/candidate scoring, and filesystem paths with spaces
in image/metadata comparisons. It does not change scene
inputs or renderer code. The canonical round-trip test checks 25 synthetic
candidates, selection of the lowest-error image, both default/scalar keys, and
acceptance/rejection behavior for pixels and metadata on Windows and Linux.
Synthetic fixtures are not reference renders.

Each job uploads `evidence/`, including CPU/OS details, the locked provenance,
source hashes, selected test names, command logs, CTest JUnit, canonical EXRs,
`diff.json` files and output hashes. Failures retain the available evidence and
partial output. Successful updates must also produce every declared image and
its mode-specific thresholds. Artifacts are retained for seven days. Generating
these references does not itself establish Windows image acceptance: the
Windows outputs still have to pass the corresponding RATS comparisons.

To run on an existing Ubuntu 24.04 x86-64 machine with AVX2, install Python 3.12,
Git/Git LFS, CMake, a C/C++ compiler, Make and `squashfs-tools`, then run:

```bash
python3 building/windows/reference/run_reference.py \
  --work "$PWD/linux-reference-output" --scope focus
```

The output directory must be new. The script extracts the verified Snap into
that directory with `unsquashfs`; it does not require installing or mounting the
Snap. `--configure-only` checks setup and test selection without generating
canonicals. `--snap-file` reuses a downloaded Snap after checksum verification.
`--runtime-root` reuses an existing extraction after checking the locked binary
hashes; this option is intended for local harness checks. The hosted workflow
always verifies and extracts the complete published package.

A local setup check in the existing software-emulated Linux VM verifies the
runner environment, pinned source checkout, LFS materialization, harness patch,
CMake configuration and five-case selection. Workflow validation and full-suite
shard coverage are checked separately. These checks do not substitute for
executing the job on a hosted runner or comparing its results with Windows.

Upstream reference-generation instructions:
https://github.com/OpenMoonRay/rats#rats-ctest-suite
