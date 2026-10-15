# Arras classroom preparation for Windows

This kit prepares several school PCs to contribute to **one Houdini viewport**.
It is a preparation kit, not a working Windows render farm yet. The Windows
runtime includes the real MoonRay render, dispatch and merge computations, but
does **not** yet include a ported `arras4_node.exe` / `arras4_noderouter.exe`.
The coordinator and diagnostics can run now; a real two-PC render remains the
next validation milestone after that native worker port.

```text
Houdini viewport <---- merged progressive image
       |                         ^
       v                         |
 scene dispatch ----> MoonRay workers on PC A and PC B

minicoord: allocates workers and starts/stops the Arras session
```

The user has school permission to run programs as a normal user. Everything in
this kit runs in the foreground from an extracted folder; it installs no service,
scheduled task, firewall rule or machine-wide environment setting. Keep the normal
Houdini package and current open scenes as they are.

## Files and requirements

Use this kit beside the extracted **MoonRay-Houdini-21.0.729** portable bundle.
The bundle supplies Python 3.11; this kit supplies pinned coordinator dependencies
and their licenses, so school PCs need no Python/pip installation or internet.
Copy binaries to each PC's local disk for startup; project assets can live on an
authorized shared folder. All workers must read the same textures, geometry,
volumes and OCIO config at the **same paths**. Arras sends scene updates; it does
not automatically copy those external files.

The kit uses the upstream Python `minicoord`, not DreamWorks' internal Java
coordinator. Minicoord is intended for small demonstrations and lacks production
authentication, resilient scheduling and complete node-failure recovery. Run it
only on the school's authorized, restricted network. It binds to loopback unless
you explicitly select a local LAN IPv4 address; it refuses `0.0.0.0`.

## Prepare and inspect

Open PowerShell in this kit folder. Adjust the bundle location:

```powershell
$bundle = 'D:\MoonRay-Houdini-21.0.729-Windows-20261015'
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 check -Bundle $bundle
```

`check` reports the native node/router files as missing and exits with code 2.
This is the expected result for the current bundle, not a successful distributed
render. It also calculates a proposed CPU budget leaving at least one logical
CPU free. No other PC is contacted without an explicit `--contact` or `probe`.

Copy `classroom.example.json` to `classroom.json`. For the later LAN run, replace
`coordinator` with the chosen coordinator PC's hostname or IPv4 address. Start
with two render workers and CPU vectorized mode. The default advertised budget
is four worker threads, with 6 GB requested per render computation, plus 1 GB for
merge and 256 MB for dispatch where those run. These are allocation requests;
Windows process-level limits still need implementing in the native worker port.
Leave memory for Windows, Houdini and other applications on each worker PC.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 prepare -Bundle $bundle --config .\classroom.json --output .\prepared-client
```

This creates isolated Houdini preferences, viewport settings and `hd_single` /
`hd_multi` session definitions. Remote sessions inherit each worker's environment,
instead of sending absolute paths from the artist PC. The original bundle and
normal Houdini preferences are not changed. Outputs must be new directories.
Regenerate the client folder after moving it or the bundle.

Do not switch a working viewport over yet: `prepared-client/readiness.json`
lists the remaining prerequisites. After native workers pass their own tests,
the prepared preferences will connect to `HDMOONRAY_STACK=url-http://HOST:8888`,
with **Use Remote Hosts** enabled and the chosen **Remote Hosts** count. Starting
Houdini with `HOUDINI_USER_PREF_DIR` pointing to `prepared-client/prefs21.0` and
`HOUDINI_NO_ENV_FILE=1` keeps this trial separate from normal sessions.

## Coordinator trial on this PC

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 coordinator -Bundle $bundle --config .\classroom.json --duration 0
```

Stop with Ctrl+C. For a later authorized LAN trial add `--bind YOUR_LOCAL_IPV4`.
The chosen interface must belong to this PC; `coordinator` in the JSON must name
that same machine for clients. In a second PowerShell window:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 check -Bundle $bundle --config .\classroom.json --contact --output .\readiness.json
```

With no native workers, the coordinator correctly reports zero nodes. The kit
does not register fake workers or represent an HTTP response as a render result.

## Two-PC network check, when a second PC is available

On PC A, use its actual LAN address (example below must be replaced):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 listen -Bundle $bundle --bind 192.168.1.10 --port 8889 --duration 120
```

On PC B:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 probe -Bundle $bundle --url http://192.168.1.10:8889/moonray-network-probe
```

Then swap A and B to check both directions. The listener automatically stops
after two minutes, exposes only a fixed diagnostic response, and never executes
commands or serves files. It is not an Arras worker. No network range is scanned.
If it fails, report the exact addresses and port to school IT; do not disable the
firewall. A successful probe proves only that port and direction are reachable.
Arras also needs worker HTTP and router TCP connections between nodes and the
client. Upstream Node chooses dynamic ports; bounded/configurable Windows node
ports and a real bidirectional routing test remain part of the native port work.
No administrator access is needed to run these tools, but network policy may
require an IT-managed exception before actual distributed rendering can work.

## Check shared assets

Create a manifest of explicitly selected project dependencies, then run `check`
with it on each PC. For example:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 assets -Bundle $bundle --file '\\school-share\project\textures\wall.tx' --file '\\school-share\project\config.ocio' --output .\assets.json
powershell -NoProfile -ExecutionPolicy Bypass -File .\Classroom.ps1 check -Bundle $bundle --assets .\assets.json
```

Hashes catch files that exist under the same name but have different contents.
This checks only explicitly listed files, not automatic USD dependency discovery.

## Validation and remaining native work

`test_classroom.py` exercises real coordinator/probe HTTP on loopback, failed
allocation accounting, successful allocation/release with simulated nodes,
remote template topology, asset differences and request timeouts. The simulated
nodes never run a computation; these tests do not prove multi-PC rendering.

Next native work is to port upstream Node/router process startup and socket
inheritance to Windows, replace its POSIX signal/resource handling, enforce CPU
and memory budgets with Windows Job Objects, expose predictable network ports,
and validate worker exit/recovery and cleanup. Then run a small real two-PC
viewport render, change camera/light/materials, compare against local rendering,
and measure time to first pixel and update latency. Test XPU after CPU routing
works; distributed Cryptomatte/deep output remain separately unvalidated.

The coordinator changes in this snapshot prevent failed tentative allocations
from consuming live resources, clamp variable core requests to free capacity,
discard allocation-rejected sessions, and add deadlines to outgoing worker HTTP.
They do not make the upstream demonstration coordinator production-grade.

To rebuild this kit from the repository, use a Python 3.11 environment with pip:

```powershell
python -m pip download --only-binary=:all: --require-hashes -r building/windows/classroom/requirements-lock.txt --dest build/windows/classroom-wheels
python building/windows/classroom/package_classroom.py --wheels build/windows/classroom-wheels --output build/windows/classroom-kit
```

See [upstream distributed Arras documentation](https://docs.openmoonray.org/developer-reference/arras/distributed-arras/)
for the coordinator/node architecture and shared filesystem requirements.
