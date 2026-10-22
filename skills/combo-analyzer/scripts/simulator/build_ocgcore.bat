@echo off
REM Build ygopro-core into ocgcore.dll without premake5.
REM
REM Usage:
REM   build_ocgcore.bat <source-dir> <output-dir>
REM
REM The source dir must contain the ygopro-core .cpp/.h files plus lua/src/*.c.
REM Use the Lua v5.4.7 tag from https://github.com/lua/lua
REM (ygopro-core supports both 5.3 and 5.4).
REM
REM Only cl.exe / lib.exe / link.exe are used, all from an installed Visual Studio.

setlocal enabledelayedexpansion

if "%~1"=="" (
  echo Usage: %~nx0 ^<source-dir^> ^<output-dir^>
  exit /b 1
)
set "SRC=%~1"
set "OUT=%~2"
if "%OUT%"=="" set "OUT=%~dp0build"

REM Locate vcvars64.bat through vswhere instead of hardcoding the install path
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
  echo vswhere.exe not found; is Visual Studio installed?
  exit /b 1
)
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
if not defined VSPATH (
  echo No Visual Studio installation with the C++ toolchain was found
  exit /b 1
)
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
if errorlevel 1 (
  echo Failed to initialise the MSVC environment
  exit /b 1
)

set "LOG=%OUT%\build.log"
if not exist "%OUT%" mkdir "%OUT%"
if not exist "%OUT%\obj" mkdir "%OUT%\obj"
if not exist "%OUT%\objlua" mkdir "%OUT%\objlua"
if exist "%LOG%" del "%LOG%"

echo === lua === >> "%LOG%"
pushd "%OUT%\objlua"
for %%f in ("%SRC%\lua\src\*.c") do (
  set "NAME=%%~nf"
  set "SKIP="
  REM linit 由解释器自己接管；lutf8lib 不能跳过——mycard 版 ocgcore 的
REM interpreter 会显式调用 luaopen_utf8（脚本里的 utf8.* 依赖它）。
REM lua.c / luac.c / onelua.c 是命令行入口，lbitlib/lcorolib/ldblib/loadlib/
REM loslib/ltests 是引擎用不到的标准库。
for %%s in (lbitlib lcorolib ldblib linit loadlib loslib ltests lua luac onelua) do (
    if /I "!NAME!"=="%%s" set "SKIP=1"
  )
  if not defined SKIP (
    cl /nologo /c /TP /MT /O2 /I "%SRC%\lua" /FI luaconf-customize.h "%%f" /Fo"!NAME!.obj" >> "%LOG%" 2>&1
    if errorlevel 1 echo LUA_FAIL %%f >> "%LOG%"
  )
)
lib /nologo /OUT:"%OUT%\lua.lib" *.obj >> "%LOG%" 2>&1
if errorlevel 1 echo LIB_LUA_FAIL >> "%LOG%"
popd

echo === ocgcore === >> "%LOG%"
pushd "%OUT%\obj"
for %%f in ("%SRC%\*.cpp") do (
  cl /nologo /c /std:c++17 /EHsc /MT /O2 /DWIN32 /D_WIN32 /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS /utf-8 /DOCGCORE_EXPORT_FUNCTIONS /I "%SRC%" /I "%SRC%\lua\src" "%%f" /Fo"%%~nf.obj" >> "%LOG%" 2>&1
  if errorlevel 1 echo CPP_FAIL %%f >> "%LOG%"
)
if exist "%SRC%\RNG" (
  for %%f in ("%SRC%\RNG\*.cpp") do (
    cl /nologo /c /std:c++17 /EHsc /MT /O2 /DWIN32 /D_WIN32 /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS /utf-8 /DOCGCORE_EXPORT_FUNCTIONS /I "%SRC%" /I "%SRC%\lua\src" "%%f" /Fo"rng_%%~nf.obj" >> "%LOG%" 2>&1
    if errorlevel 1 echo CPP_FAIL %%f >> "%LOG%"
  )
)
link /nologo /DLL /OUT:"%OUT%\ocgcore.dll" *.obj "%OUT%\lua.lib" >> "%LOG%" 2>&1
if errorlevel 1 echo LINK_FAIL >> "%LOG%"
popd

echo === done === >> "%LOG%"
if exist "%OUT%\ocgcore.dll" (echo BUILD_OK: %OUT%\ocgcore.dll) else (echo BUILD_FAILED: see %LOG%)
