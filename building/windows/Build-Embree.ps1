# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([int]$Jobs = 8)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path.Replace('\', '/')
$revision = '341ef8c45d1ae072ead1ab65cd76e88b03d9302c'
$archive = "$repo/build/downloads/embree-4.2.0-source.zip"
$source = "$repo/build/dependency-sources/embree-$revision"
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -UseBasicParsing "https://github.com/RenderKit/embree/archive/$revision.zip" -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne
    'AA8966376E8B828C374DC3B9B653E522F35B4DBE3CA91D898A2C40B95E93DEAC') {
    throw 'Embree source checksum mismatch.'
}
if (-not (Test-Path -LiteralPath "$source/CMakeLists.txt")) {
    Expand-Archive -LiteralPath $archive -DestinationPath "$repo/build/dependency-sources" -Force
}
$ErrorActionPreference = 'Continue'
& cmake -S $source -B "$repo/build/windows/embree" -G Ninja `
    -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$repo/build/deps-extra" `
    "-DTBB_ROOT=$repo/build/tools/tbb" "-DTBB_DIR=$repo/build/tools/tbb/cmake" `
    "-DEMBREE_ISPC_EXECUTABLE=$repo/build/tools/ispc-v1.21.0-windows/bin/ispc.exe" `
    -DEMBREE_ISPC_SUPPORT=ON -DEMBREE_RAY_MASK=ON -DEMBREE_IGNORE_INVALID_RAYS=ON `
    -DEMBREE_MAX_ISA=AVX2 -DEMBREE_TUTORIALS=OFF -DEMBREE_SYCL_SUPPORT=OFF `
    -DEMBREE_TASKING_SYSTEM=TBB -DBUILD_SHARED_LIBS=ON
if ($LASTEXITCODE -ne 0) { throw 'Embree configuration failed.' }
& cmake --build "$repo/build/windows/embree" --parallel $Jobs
if ($LASTEXITCODE -ne 0) { throw 'Embree build failed.' }
& cmake --install "$repo/build/windows/embree"
if ($LASTEXITCODE -ne 0) { throw 'Embree installation failed.' }
