# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([int]$Jobs = 8, [switch]$ConfigureOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path.Replace('\', '/')
$deps = "$repo/build/deps/x64-windows"
$python = "$deps/tools/python3/python.exe"
$source = "$repo/build/dependency-sources/usd-23.08"
$archive = "$repo/build/downloads/usd-23.08-source.zip"
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -UseBasicParsing 'https://github.com/PixarAnimationStudios/OpenUSD/archive/10b62439e9242a55101cf8b200f2c7e02420e1b0.zip' -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne
    '2EB5DC8185CDB920BA06CD70F4311CA2CDDB74F42F86970D6CE01B5E977A83C8') {
    throw 'USD source checksum mismatch.'
}
if (-not (Test-Path -LiteralPath "$source/CMakeLists.txt")) {
    & $python "$PSScriptRoot/Extract-Source.py" $archive $source
    if ($LASTEXITCODE -ne 0) { throw 'USD extraction failed.' }
}
& $python "$PSScriptRoot/Patch-USD.py" $source
if ($LASTEXITCODE -ne 0) { throw 'USD Windows export patch failed.' }
$env:PATH = "$deps/bin;$repo/build/tools/tbb/bin/intel64/vc14;$env:PATH"
$ErrorActionPreference = 'Continue'
& cmake -S $source -B "$repo/build/windows/usd" -G Ninja `
    -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$repo/build/deps-extra" `
    "-DCMAKE_TOOLCHAIN_FILE=$repo/build/tools/vcpkg/scripts/buildsystems/vcpkg.cmake" `
    "-DVCPKG_INSTALLED_DIR=$repo/build/deps" -DVCPKG_MANIFEST_MODE=OFF `
    "-DCMAKE_PREFIX_PATH=$deps;$repo/build/tools/tbb" `
    "-DPython3_EXECUTABLE=$python" "-DPython3_ROOT_DIR=$deps/tools/python3" `
    "-DTBB_ROOT_DIR=$repo/build/tools/tbb" -DTBB_USE_DEBUG_BUILD=OFF `
    "-DTBB_tbb_LIBRARY_RELEASE=$repo/build/tools/tbb/lib/intel64/vc14/tbb.lib" `
    "-DTBB_tbb_LIBRARY_DEBUG=$repo/build/tools/tbb/lib/intel64/vc14/tbb_debug.lib" `
    "-DOPENSUBDIV_OSDCPU_LIBRARY=$deps/lib/osdCPU.lib" `
    "-DOPENSUBDIV_OSDGPU_LIBRARY=$deps/lib/osdGPU.lib" `
    -DBoost_NO_BOOST_CMAKE=OFF -DPXR_ENABLE_PYTHON_SUPPORT=ON `
    -DPXR_BUILD_IMAGING=ON -DPXR_BUILD_USD_IMAGING=ON `
    -DPXR_ENABLE_GL_SUPPORT=ON -DPXR_ENABLE_PTEX_SUPPORT=OFF `
    -DPXR_ENABLE_OPENVDB_SUPPORT=OFF -DPXR_BUILD_USDVIEW=OFF `
    -DPXR_BUILD_TESTS=OFF -DPXR_BUILD_EXAMPLES=OFF -DPXR_BUILD_TUTORIALS=OFF `
    -DPXR_BUILD_USD_TOOLS=ON
if ($LASTEXITCODE -ne 0) { throw 'USD configuration failed.' }
if ($ConfigureOnly) { return }
& cmake --build "$repo/build/windows/usd" --parallel $Jobs
if ($LASTEXITCODE -ne 0) { throw 'USD build failed.' }
& cmake --install "$repo/build/windows/usd"
if ($LASTEXITCODE -ne 0) { throw 'USD installation failed.' }
