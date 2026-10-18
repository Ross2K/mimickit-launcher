/* Tiny Windows starter: finds a pythonw.exe (venv) and runs SCRIPT_NAME next to this .exe.
   Build: see build.sh (clang-cl + lld-link, xwin SDK).
   Copyright (c) 2026 Ross2K. SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <wchar.h>
#include <stdio.h>

#ifndef SCRIPT_NAME
#define SCRIPT_NAME L"mimickit_launcher.py"
#endif
#ifndef APP_TITLE
#define APP_TITLE L"MimicKit Launcher"
#endif

static wchar_t g_dir[MAX_PATH];

static int exists(const wchar_t *p) { DWORD a = GetFileAttributesW(p); return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY); }

/* read "key": "value" (JSON string, \\ and \" unescaped) from a UTF-8 file */
static int json_str(const wchar_t *file, const char *key, wchar_t *out, int outlen)
{
    HANDLE h = CreateFileW(file, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, 0, OPEN_EXISTING, 0, 0);
    if (h == INVALID_HANDLE_VALUE) return 0;
    char buf[65536]; DWORD n = 0; ReadFile(h, buf, sizeof(buf) - 1, &n, 0); CloseHandle(h); buf[n] = 0;
    char pat[64]; _snprintf(pat, sizeof(pat), "\"%s\"", key); pat[63] = 0;
    char *p = strstr(buf, pat); if (!p) return 0;
    p = strchr(p + strlen(pat), ':'); if (!p) return 0;
    while (*++p == ' ' || *p == '\t' || *p == '\r' || *p == '\n');
    if (*p != '"') return 0;
    char val[2048]; int k = 0;
    for (++p; *p && *p != '"' && k < (int)sizeof(val) - 1; ++p) {
        if (*p == '\\' && p[1]) { ++p; val[k++] = (*p == 'n') ? '\n' : *p; }
        else val[k++] = *p;
    }
    val[k] = 0; if (!k) return 0;
    return MultiByteToWideChar(CP_UTF8, 0, val, -1, out, outlen) > 0;
}

/* venv folder or python(w).exe path -> pythonw.exe path */
static int from_venv(const wchar_t *v, wchar_t *out)
{
    wchar_t t[MAX_PATH];
    if (!v || !*v) return 0;
    if (exists(v)) {                      /* a python.exe / pythonw.exe */
        wcsncpy(t, v, MAX_PATH - 1); t[MAX_PATH - 1] = 0;
        wchar_t *b = wcsrchr(t, L'\\'); if (!b) b = wcsrchr(t, L'/');
        if (b) { wcscpy(b + 1, L"pythonw.exe"); if (exists(t)) { wcscpy(out, t); return 1; } }
        wcscpy(out, v); return 1;
    }
    _snwprintf(t, MAX_PATH, L"%s\\Scripts\\pythonw.exe", v); t[MAX_PATH - 1] = 0;
    if (exists(t)) { wcscpy(out, t); return 1; }
    return 0;
}

static int find_python(wchar_t *py, wchar_t *tried, int triedlen)
{
    wchar_t v[MAX_PATH], cfg[MAX_PATH], mk[MAX_PATH], t[MAX_PATH];
    tried[0] = 0;
#define TRY(desc, path) do { _snwprintf(tried + wcslen(tried), triedlen - wcslen(tried), L"  - %s: %s\n", desc, path); } while (0)
    if (GetEnvironmentVariableW(L"MIMICKIT_LAUNCHER_PYTHON", v, MAX_PATH) && from_venv(v, py)) return 1;
    /* settings files: next to the exe (older GUI) and %APPDATA%\mimickit-launcher (launcher) */
    const wchar_t *cfgs[2] = { L"%s\\gui_settings.json", 0 };
    wchar_t appdata[MAX_PATH] = L"";
    if (SUCCEEDED(SHGetFolderPathW(0, CSIDL_APPDATA, 0, 0, appdata))) cfgs[1] = L"%s\\mimickit-launcher\\settings.json";
    for (int i = 0; i < 2; ++i) {
        if (!cfgs[i]) continue;
        _snwprintf(cfg, MAX_PATH, cfgs[i], i == 0 ? g_dir : appdata); cfg[MAX_PATH - 1] = 0;
        if (json_str(cfg, "venv", v, MAX_PATH)) { TRY(L"venv from settings", v); if (from_venv(v, py)) return 1; }
        if (json_str(cfg, "mimickit", mk, MAX_PATH)) {
            const wchar_t *sub[4] = { L"%s\\.venv", L"%s\\venv", L"%s\\..\\venv", L"%s\\..\\.venv" };
            for (int j = 0; j < 4; ++j) { _snwprintf(t, MAX_PATH, sub[j], mk); t[MAX_PATH - 1] = 0; TRY(L"next to MimicKit", t); if (from_venv(t, py)) return 1; }
        }
    }
#ifdef DEFAULT_VENV
    TRY(L"default", DEFAULT_VENV); if (from_venv(DEFAULT_VENV, py)) return 1;
#endif
    if (SearchPathW(0, L"pythonw.exe", 0, MAX_PATH, py, 0)) return 1;
    if (SearchPathW(0, L"pyw.exe", 0, MAX_PATH, py, 0)) return 1;
    TRY(L"PATH", L"pythonw.exe / pyw.exe not found");
    return 0;
}

int WINAPI wWinMain(HINSTANCE hi, HINSTANCE hp, PWSTR cmd, int show)
{
    (void)hi; (void)hp; (void)cmd; (void)show;
    GetModuleFileNameW(0, g_dir, MAX_PATH);
    wchar_t *s = wcsrchr(g_dir, L'\\'); if (s) *s = 0;
    wchar_t script[MAX_PATH], py[MAX_PATH], tried[4096], msg[6000];
    _snwprintf(script, MAX_PATH, L"%s\\%s", g_dir, SCRIPT_NAME); script[MAX_PATH - 1] = 0;
    if (!exists(script)) {
        _snwprintf(msg, 6000, L"Can't find %s next to this .exe:\n%s\n\nKeep the .exe in the same folder as the .py file.", SCRIPT_NAME, script);
        MessageBoxW(0, msg, APP_TITLE, MB_ICONERROR); return 1;
    }
    if (!find_python(py, tried, 4096)) {
        _snwprintf(msg, 6000, L"Couldn't find Python (pythonw.exe).\n\nLooked in:\n%s\n"
            L"Fix: install MimicKit's venv (see README), or set the environment variable\n"
            L"MIMICKIT_LAUNCHER_PYTHON to your venv's Scripts\\pythonw.exe, then start again.", tried);
        MessageBoxW(0, msg, APP_TITLE, MB_ICONERROR); return 1;
    }
    wchar_t cl[3 * MAX_PATH];
    _snwprintf(cl, 3 * MAX_PATH, L"\"%s\" \"%s\"", py, script); cl[3 * MAX_PATH - 1] = 0;
    STARTUPINFOW si; PROCESS_INFORMATION pi; ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si);
    if (!CreateProcessW(py, cl, 0, 0, FALSE, 0, 0, g_dir, &si, &pi)) {
        _snwprintf(msg, 6000, L"Couldn't start:\n%s\n\nWindows error %lu.", cl, GetLastError());
        MessageBoxW(0, msg, APP_TITLE, MB_ICONERROR); return 1;
    }
    /* if it dies right away (missing tkinter/matplotlib, syntax error...), say so */
    if (WaitForSingleObject(pi.hProcess, 4000) == WAIT_OBJECT_0) {
        DWORD code = 0; GetExitCodeProcess(pi.hProcess, &code);
        if (code != 0) {
            _snwprintf(msg, 6000, L"The launcher closed right away (exit code %lu).\n\nPython used:\n%s\n\n"
                L"To see the error, open a Command Prompt in this folder and run:\n\"%s\" \"%s\"\n"
                L"(use python.exe instead of pythonw.exe). Usually tkinter or matplotlib is missing:\n"
                L"pip install matplotlib", code, py, py, script);
            MessageBoxW(0, msg, APP_TITLE, MB_ICONWARNING);
        }
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}
