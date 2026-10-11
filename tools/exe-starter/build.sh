#!/bin/sh
# Build the starter .exe files (32-bit, runs on any 64-bit Windows) with clang-cl + lld-link + xwin SDK.
set -e
XWIN=${XWIN:-/tmp/xwinsdk}; cd "$(dirname "$0")"; mkdir -p out
INC="-imsvc $XWIN/crt/include -imsvc $XWIN/sdk/include/ucrt -imsvc $XWIN/sdk/include/um -imsvc $XWIN/sdk/include/shared"
printf '1 ICON "icon.ico"\n' > icon.rc
llvm-rc $INC /fo out/icon.res icon.rc 2>/dev/null || llvm-rc /fo out/icon.res icon.rc
build() { # out.exe script title [default venv]
  D=""; [ -n "$4" ] && D="/DDEFAULT_VENV=L\"$4\""
  clang-cl-19 --target=i686-pc-windows-msvc /O2 /MT /D_CRT_SECURE_NO_WARNINGS /DUNICODE /D_UNICODE /W3 $INC "/DSCRIPT_NAME=L\"$2\"" "/DAPP_TITLE=L\"$3\"" $D /c launcher.c /Foout/launcher.obj
  lld-link /subsystem:windows /entry:wWinMainCRTStartup /machine:x86 "/out:out/$1" out/launcher.obj out/icon.res \
    /libpath:$XWIN/crt/lib/x86 /libpath:$XWIN/sdk/lib/um/x86 /libpath:$XWIN/sdk/lib/ucrt/x86 kernel32.lib user32.lib shell32.lib
  rm -f out/launcher.obj
}
build "MimicKit Launcher.exe" mimickit_launcher.py "MimicKit Launcher"

ls -la out
