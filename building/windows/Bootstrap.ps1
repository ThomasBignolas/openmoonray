# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([switch]$SkipLibraries)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$repo = (Resolve-Path "$PSScriptRoot/../..").Path
$toolsDir = Join-Path $repo 'build/tools'
$downloads = Join-Path $repo 'build/downloads'
New-Item -ItemType Directory -Force $toolsDir, $downloads | Out-Null

function Get-CheckedArchive($Url, $Name, $Hash, $ExpectedFile) {
    $archive = Join-Path $downloads $Name
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -UseBasicParsing $Url -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $Hash) {
        throw "Checksum mismatch for $archive"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $toolsDir $ExpectedFile))) {
        Expand-Archive -LiteralPath $archive -DestinationPath $toolsDir -Force
    }
}

Get-CheckedArchive 'https://github.com/ispc/ispc/releases/download/v1.21.0/ispc-v1.21.0-windows.zip' `
    'ispc-v1.21.0-windows.zip' 'B8823C03C050152AEAE19594160D9A1A00E21817FC0CD86F21BE2B4F22AB17BF' `
    'ispc-v1.21.0-windows/bin/ispc.exe'
Get-CheckedArchive 'https://github.com/uxlfoundation/oneTBB/releases/download/v2020.3/tbb-2020.3-win.zip' `
    'tbb-2020.3-win.zip' 'CDA37EED5209746A79C88A658F8C1BF3782F58BD9F9F6BA0DA3A16624A9BFAA1' `
    'tbb/include/tbb/tbb.h'
Get-CheckedArchive 'https://github.com/RenderKit/oidn/releases/download/v2.3.3/oidn-2.3.3.x64.windows.zip' `
    'oidn-2.3.3.x64.windows.zip' '30E41F6FE648536EF5657B45BCCD2B27C6CAED6461C832BDE4949B0F965BE0E0' `
    'oidn-2.3.3.x64.windows/include/OpenImageDenoise/oidn.hpp'

# New enough to detect VS 17.14; library versions are pinned separately.
$flexArchive = Join-Path $downloads 'win_flex_bison-2.5.25.zip'
if (-not (Test-Path -LiteralPath $flexArchive)) {
    Invoke-WebRequest -UseBasicParsing 'https://github.com/lexxmark/winflexbison/releases/download/v2.5.25/win_flex_bison-2.5.25.zip' -OutFile $flexArchive
}
if ((Get-FileHash -LiteralPath $flexArchive -Algorithm SHA256).Hash -ne
    '8D324B62BE33604B2C45AD1DD34AB93D722534448F55A16CA7292DE32B6AC135') {
    throw 'WinFlexBison archive checksum mismatch.'
}
if (-not (Test-Path -LiteralPath "$toolsDir/winflexbison/win_bison.exe")) {
    Expand-Archive -LiteralPath $flexArchive -DestinationPath "$toolsDir/winflexbison" -Force
}

$vcpkgRevision = '0699a19d0c6386247ce50d4dedbb8217d484d536'
$vcpkg = Join-Path $toolsDir 'vcpkg'
if (-not (Test-Path -LiteralPath "$vcpkg/.git")) {
    & git clone https://github.com/microsoft/vcpkg.git $vcpkg
    if ($LASTEXITCODE -ne 0) { throw 'vcpkg clone failed.' }
}
$current = & git -C $vcpkg rev-parse HEAD
if ($current -ne $vcpkgRevision) {
    & git -C $vcpkg fetch origin $vcpkgRevision
    if ($LASTEXITCODE -ne 0) { throw 'vcpkg fetch failed.' }
    & git -C $vcpkg checkout --detach $vcpkgRevision
    if ($LASTEXITCODE -ne 0) { throw 'vcpkg checkout failed.' }
}
if (-not (Test-Path -LiteralPath "$vcpkg/vcpkg.exe")) {
    & "$vcpkg/bootstrap-vcpkg.bat" -disableMetrics
    if ($LASTEXITCODE -ne 0) { throw 'vcpkg bootstrap failed.' }
}

# Boost 1.83's vcpkg helper normalizes vc141/142/143 import library names,
# but misses the vc144 name emitted for MSVC 19.4x. Patch a pinned copy of
# the helper port, leaving the vcpkg checkout and installed packages alone.
$overlay = Join-Path $repo 'build/windows/ports'
$boostOverlay = Join-Path $overlay 'boost-modular-build-helper'
New-Item -ItemType Directory -Force $boostOverlay | Out-Null
$portArchive = Join-Path $downloads 'boost-modular-build-helper.tar'
& git -C $vcpkg archive --format=tar "--output=$portArchive" 95d209e069cf1a82d48fa32cef7a7c39edc33c22
if ($LASTEXITCODE -ne 0) { throw 'The pinned Boost port requires full vcpkg Git history.' }
& tar -xf $portArchive -C $boostOverlay
if ($LASTEXITCODE -ne 0) { throw 'Boost helper extraction failed.' }
$helper = Join-Path $boostOverlay 'boost-modular-build.cmake'
$contents = [IO.File]::ReadAllText($helper)
$contents = $contents.Replace('string(REPLACE "-vc143-"', 'string(REGEX REPLACE "-vc14[3-9]-"')
[IO.File]::WriteAllText($helper, $contents)
Copy-Item -LiteralPath "$vcpkg/LICENSE.txt" -Destination "$boostOverlay/LICENSE.txt"

# OIIO 2.4 advertises IOProxy support but bypasses it for multipart/deep EXRs.
# Use the OpenEXR stream constructor so Windows delete-on-close output works.
$oiioOverlay = Join-Path $overlay 'openimageio'
New-Item -ItemType Directory -Force $oiioOverlay | Out-Null
$oiioPortArchive = Join-Path $downloads 'openimageio-port.tar'
& git -C $vcpkg archive --format=tar "--output=$oiioPortArchive" 76cadb5ec79b57f840f2dae9dc39501b027f6a9f
if ($LASTEXITCODE -ne 0) { throw 'The pinned OpenImageIO port requires full vcpkg Git history.' }
& tar -xf $oiioPortArchive -C $oiioOverlay
if ($LASTEXITCODE -ne 0) { throw 'OpenImageIO port extraction failed.' }
Copy-Item -LiteralPath "$PSScriptRoot/patches/oiio-multipart-ioproxy.patch" -Destination $oiioOverlay
$oiioPort = Join-Path $oiioOverlay 'portfile.cmake'
$oiioPortContents = [IO.File]::ReadAllText($oiioPort)
$oiioPortContents = $oiioPortContents.Replace('    PATCHES', "    PATCHES`n        oiio-multipart-ioproxy.patch")
[IO.File]::WriteAllText($oiioPort, $oiioPortContents)
if (-not $SkipLibraries) {
    $ErrorActionPreference = 'Continue'
    & "$vcpkg/vcpkg.exe" install "--x-manifest-root=$PSScriptRoot" `
        "--x-install-root=$repo/build/deps" "--overlay-ports=$overlay" `
        "--vcpkg-root=$vcpkg" --triplet=x64-windows --disable-metrics
    if ($LASTEXITCODE -ne 0) { throw 'Windows dependency build failed.' }
}
