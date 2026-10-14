/* Portable Windows x64 launcher. Python and wheels are shipped beside it.
 * No downloader, credentials, registry changes, or installed Python needed.
 * Build: x86_64-w64-mingw32-gcc -municode -O2 -s -static-libgcc ...
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

static BOOL WINAPI control_handler(DWORD event) {
    /* Let the Python child handle Ctrl+C and cleanly close its workers. */
    return event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT;
}

static wchar_t *quoted(wchar_t *out, const wchar_t *argument) {
    *out++ = L'"';
    while (*argument) {
        size_t slashes = 0;
        while (*argument == L'\\') { ++slashes; ++argument; }
        if (*argument == L'"') {
            for (size_t i = 0; i < slashes * 2 + 1; ++i) *out++ = L'\\';
            *out++ = *argument++;
        } else if (!*argument) {
            for (size_t i = 0; i < slashes * 2; ++i) *out++ = L'\\';
        } else {
            for (size_t i = 0; i < slashes; ++i) *out++ = L'\\';
            *out++ = *argument++;
        }
    }
    *out++ = L'"';
    *out++ = L' ';
    return out;
}

int wmain(int argc, wchar_t **argv) {
    wchar_t root[32768], python[32768];
    DWORD length = GetModuleFileNameW(NULL, root, 32768);
    if (!length || length >= 32768) return 1;
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return 1;
    *slash = L'\0';
    if (wcslen(root) + 24 >= 32768) return 1;
    swprintf(python, 32768, L"%ls\\runtime\\python.exe", root);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        fwprintf(stderr, L"Please extract the complete ZIP first. Keep runtime and app beside this EXE.\n");
        return 1;
    }
    size_t size = 2 * wcslen(python) + 64;
    for (int i = 1; i < argc; ++i) size += 2 * wcslen(argv[i]) + 4;
    if (size > 32767) return 1;
    wchar_t *command = calloc(size, sizeof(wchar_t));
    if (!command) return 1;
    wchar_t *cursor = quoted(command, python);
    cursor = quoted(cursor, L"-u");
    cursor = quoted(cursor, L"-m");
    cursor = quoted(cursor, L"windows.entry");
    for (int i = 1; i < argc; ++i) cursor = quoted(cursor, argv[i]);
    *cursor = L'\0';
    SetEnvironmentVariableW(L"ALTRUAGENT_LAUNCHER_ROOT", root);
    SetConsoleCtrlHandler(control_handler, TRUE);
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    BOOL started = CreateProcessW(python, command, NULL, NULL, TRUE,
                                 CREATE_UNICODE_ENVIRONMENT, NULL, root, &startup, &process);
    free(command);
    if (!started) {
        fwprintf(stderr, L"Could not start bundled Python (Windows error %lu).\n", GetLastError());
        return 1;
    }
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD status = 1;
    GetExitCodeProcess(process.hProcess, &status);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return (int)status;
}
