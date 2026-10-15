# Native Arras classroom workers for Windows

This kit runs native Windows Arras nodes, routers and MoonRay computations so
several workers can contribute to **one Houdini/Solaris image**. The artist PC
runs Houdini; the other PCs run the worker launcher and need no Houdini license.
One PC also runs the small upstream Python coordinator, `minicoord`.

Two native worker instances on one Windows PC have rendered real scalar and
vectorized MoonRay images, merged their results and processed geometry edits.
This validates local routing and rendering. **A second physical PC and the
school LAN have not been tested.** This is a preview pool for validation, not a
production farm scheduler. Distributed XPU, Cryptomatte and deep output need
their own validation; native deep products currently require a local worker.

Everything runs as the logged-in user. No service, admin installation, firewall
change or scheduled task is made. Keep the ordinary Houdini package and open
scenes; the client setup below uses separate preferences.

## Copy the software and assets

Extract this kit and the full **MoonRay-Houdini-21.0.729-Windows-20261015** portable
bundle onto each participating PC. Keep the kit's `native` directory intact:
it contains the updated Arras executables and libraries. The portable bundle
supplies the MoonRay computations, Python, shaders and runtime dependencies.
There is no need to run the Houdini installer on worker PCs, install Python,
download packages or build anything. Use local disk for the software.

Workers must read textures, geometry, volumes and OCIO configuration at the
**same paths** as the artist PC, for example an authorized shared project folder.
Arras transports scene updates, not the contents of external asset files.
Run workers under accounts that can already read that shared folder.

Copy `classroom.example.json` to `classroom.json`. Set `coordinator` to the
coordinator PC's LAN IPv4 address or hostname. Start with two render workers and
`vectorized` CPU mode. The default is four CPU threads and a 6 GB allocation per
render computation, plus 1 GB for merge and 256 MB for dispatch. A worker advertises
capacity for these roles and caps their aggregate memory plus 512 MB overhead.
The launcher leaves at least one logical CPU unused and stops when less than
6 GB of system RAM remains free. These limits use native Windows Job Objects.

Scene memory is needed on **each** render worker; RAM is not pooled. A low memory
allocation can cause missing geometry or allocation errors. Check `worker.log`
and lower subdivision or increase the configured budget if that happens.
The small Houdini validation explicitly uses mesh resolution 4; a default
high subdivision level can consume gigabytes even on a simple sphere.

## Start the coordinator

Open PowerShell in the kit folder, and set the extracted bundle location:

```powershell
$bundle = 'D:\MoonRay-Houdini-21.0.729-Windows-20261015'
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 coordinator -Bundle $bundle --config .\classroom.json --bind 192.168.1.10
```

Replace the example address with that PC's actual LAN IPv4 address. Defaults
bind to `127.0.0.1` for local tests; `0.0.0.0` is refused. The coordinator listens
on port 8888 by default. Leave its window open. Ctrl+C stops it and its pool.

Minicoord is an upstream demonstration coordinator with no authentication,
automatic failover or robust offline-node discovery. Use only the authorized,
restricted school network. Do not expose these ports to the internet.

## Start a worker on each participating PC

Run from the kit folder on each worker, with that worker's own local LAN address:

```powershell
$bundle = 'D:\MoonRay-Houdini-21.0.729-Windows-20261015'
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 worker -Bundle $bundle --config .\classroom.json --bind 192.168.1.11
```

The launcher prints its state/log folder and `Worker ready` once the native node
responds. Keep the window open; Ctrl+C stops the node and its children. HTTP
control uses port **8890**, message routing uses **8891**. Override with
`--http-port` / `--router-port` if necessary. `--duration 15` makes a short trial.
`--state-dir D:\mr-run1` selects a new short local folder if the user's temporary
directory exceeds Windows' Unix-socket path limit. Existing state folders are
never overwritten.

The coordinator must reach every worker's HTTP port. The artist PC and workers
must reach workers' routing ports. If Windows or the school network blocks those
connections, IT needs to allow them; this kit does not bypass restrictions.
An HTTP connectivity probe alone does not prove message routing works.

## Connect an isolated Houdini session

On the artist PC, check registration and create the client preferences:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 check -Bundle $bundle --config .\classroom.json --contact
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 prepare -Bundle $bundle --config .\classroom.json --output .\prepared-client
powershell -NoProfile -ExecutionPolicy Bypass -File .\LaunchHoudini.ps1 -Client .\prepared-client -HoudiniDirectory C:\Houdini21
```

The preferences target **Houdini 21.0.729**, enable **Use Remote Hosts**, set the
chosen **Remote Hosts** count and connect to the configured coordinator. Use a
new output directory when regenerating preferences after moving the software.
Start with a small scene and compare it to local rendering, then test camera,
light and material edits. Stop rendering before shutting down the worker pool.

If a computation exits, this kit ends its session so Houdini sees a disconnect
instead of waiting forever. Restart MoonRay after fixing the cause. A powered-off
PC may need the coordinator restarted to clear stale registration; automatic
worker recovery is not provided.

## Diagnostics and rebuilding

`Classroom.ps1 listen` and `probe` provide an explicit HTTP connectivity probe;
see `classroom.py --help`. `assets --file PATH --output assets.json` records hashes
of explicitly named assets; `check --assets assets.json` verifies them. There is
no network scan or automatic USD dependency collection.

`test_classroom.py` tests coordinator accounting, failure cleanup, session
templates and real HTTP endpoints. `test_native_pool.py` exercises actual native
workers, image merging, interactive geometry updates and optional Houdini/husk
renders. Run native tests through `building/windows/houdini/run_bounded.py`.
The Arras build also supplies networking, process and local-session regressions.

```powershell
& building/windows/Build-ArrasNode.ps1 -Jobs 4
python building/windows/classroom/package_classroom.py --wheels build/windows/classroom-wheels --native-bin build/windows/arras-node/bin --bundle PATH_TO_PORTABLE_BUNDLE --output build/windows/Arras-Classroom-Native
```

Packaging uses hash-pinned offline Python wheels, preserves dependency license
notices and verifies ZIP file hashes. See the
[upstream Arras documentation](https://docs.openmoonray.org/developer-reference/arras/distributed-arras/)
for the coordinator/node architecture.
