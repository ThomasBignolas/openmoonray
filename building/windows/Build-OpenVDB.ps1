# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([int]$Jobs = 8)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path.Replace('\', '/')
$archive = "$repo/build/downloads/openvdb-10.0.1-source.zip"
$source = "$repo/build/dependency-sources/openvdb-10.0.1"
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -UseBasicParsing 'https://github.com/AcademySoftwareFoundation/openvdb/archive/refs/tags/v10.0.1.zip' -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne
    '48C2CFA9853B58FA86282DF1F83F0E99D07858CC03EB2BA8227DC447A830100A') {
    throw 'OpenVDB source checksum mismatch.'
}
if (-not (Test-Path -LiteralPath "$source/CMakeLists.txt")) {
    Expand-Archive -LiteralPath $archive -DestinationPath "$repo/build/dependency-sources" -Force
}
$ErrorActionPreference = 'Continue'
& cmake -S $source -B "$repo/build/windows/openvdb" -G Ninja `
    -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$repo/build/deps-extra" `
    "-DCMAKE_TOOLCHAIN_FILE=$repo/build/tools/vcpkg/scripts/buildsystems/vcpkg.cmake" `
    "-DVCPKG_INSTALLED_DIR=$repo/build/deps" -DVCPKG_MANIFEST_MODE=OFF `
    "-DTBB_ROOT=$repo/build/tools/tbb" "-DTBB_DIR=$repo/build/tools/tbb/cmake" `
    "-DTBB_LIBRARYDIR=$repo/build/tools/tbb/lib/intel64/vc14" `
    "-DCMAKE_PREFIX_PATH=$repo/build/tools/tbb" `
    -DOPENVDB_BUILD_BINARIES=OFF -DOPENVDB_BUILD_UNITTESTS=OFF `
    -DOPENVDB_BUILD_PYTHON_MODULE=OFF -DOPENVDB_CORE_STATIC=OFF -DOPENVDB_CORE_SHARED=ON `
    -DUSE_BLOSC=ON -DUSE_ZLIB=ON -DUSE_LOG4CPLUS=OFF
if ($LASTEXITCODE -ne 0) { throw 'OpenVDB configuration failed.' }
& cmake --build "$repo/build/windows/openvdb" --parallel $Jobs
if ($LASTEXITCODE -ne 0) { throw 'OpenVDB build failed.' }
& cmake --install "$repo/build/windows/openvdb"
if ($LASTEXITCODE -ne 0) { throw 'OpenVDB installation failed.' }
