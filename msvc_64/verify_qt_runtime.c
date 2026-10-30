// Run outside PowerShell so its already-loaded DLLs cannot affect Qt's imports.
// Build with /MT so this probe does not preload a shared MSVC runtime either.
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <tlhelp32.h>

#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

static int report_error(const wchar_t *operation, DWORD error) {
  wchar_t message[1024] = L"";
  FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, NULL, error, 0, message,
                (DWORD)(sizeof(message) / sizeof(message[0])), NULL);
  fwprintf(stderr, L"%ls failed (Win32 error %lu): %ls\n", operation, error, message);
  if (error == ERROR_PROC_NOT_FOUND) {
    fwprintf(stderr, L"A dependency was found but does not export a required entry point. Check DLL versions.\n");
  } else if (error == ERROR_MOD_NOT_FOUND) {
    fwprintf(stderr, L"A required DLL is missing from the deployment or Windows system directory.\n");
  }
  return 1;
}

static void print_loaded_modules(void) {
  HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, GetCurrentProcessId());
  if (snapshot == INVALID_HANDLE_VALUE) {
    return;
  }
  MODULEENTRY32W entry = {0};
  entry.dwSize = sizeof(entry);
  if (Module32FirstW(snapshot, &entry)) {
    wprintf(L"Loaded modules:\n");
    do {
      wprintf(L"  %ls\n", entry.szExePath);
    } while (Module32NextW(snapshot, &entry));
  }
  CloseHandle(snapshot);
}

static const void *image_at(const BYTE *image, DWORD size, ULONGLONG rva, size_t length) {
  return rva <= size && length <= size - rva ? image + (size_t)rva : NULL;
}

static const char *image_string(const BYTE *image, DWORD size, ULONGLONG rva) {
  const char *value = image_at(image, size, rva, 1);
  return value && memchr(value, '\0', size - (size_t)rva) ? value : NULL;
}

// Windows unloads a failed load's dependencies before returning error 127.
// Inspect its native imports afterwards, loading each dependency separately to
// report the missing name/ordinal and the DLL Windows actually selected.
// This is diagnostic only: it cannot turn the original failed load into a pass.
static void diagnose_imports(const wchar_t *path, DWORD search_flags) {
  HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
  if (file == INVALID_HANDLE_VALUE) {
    report_error(L"Open DLL for import diagnostics", GetLastError());
    return;
  }
  // Map RVAs as an image without resolving imports or running DLL entry points.
  HANDLE mapping = CreateFileMappingW(file, NULL, PAGE_READONLY | SEC_IMAGE_NO_EXECUTE, 0, 0, NULL);
  DWORD error = GetLastError();
  CloseHandle(file);
  if (!mapping) {
    report_error(L"Map DLL for import diagnostics", error);
    return;
  }
  const BYTE *image = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0);
  if (!image) {
    report_error(L"Read DLL for import diagnostics", GetLastError());
    CloseHandle(mapping);
    return;
  }

  // SEC_IMAGE_NO_EXECUTE has already validated the staged PE image's headers.
  const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)image;
  const IMAGE_NT_HEADERS *nt = (const IMAGE_NT_HEADERS *)(image + dos->e_lfanew);
  const DWORD size = nt->OptionalHeader.SizeOfImage;
  const IMAGE_DATA_DIRECTORY imports = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
  const IMAGE_IMPORT_DESCRIPTOR *descriptors = image_at(image, size, imports.VirtualAddress, imports.Size);
  unsigned int failures = 0;
  if (nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR_MAGIC || !imports.VirtualAddress || !descriptors) {
    fwprintf(stderr, L"No readable native import table in %ls.\n", path);
    goto cleanup;
  }

  wprintf(L"Checking direct imports of %ls:\n", path);
  fflush(stdout);
  for (size_t i = 0; i < imports.Size / sizeof(*descriptors) && descriptors[i].Name; ++i) {
    const IMAGE_IMPORT_DESCRIPTOR *descriptor = &descriptors[i];
    const char *name = image_string(image, size, descriptor->Name);
    ULONGLONG rva = descriptor->OriginalFirstThunk ? descriptor->OriginalFirstThunk : descriptor->FirstThunk;
    if (!name || !rva) {
      fwprintf(stderr, L"Invalid import descriptor in %ls.\n", path);
      ++failures;
      break;
    }
    HMODULE dependency = LoadLibraryExA(name, NULL, search_flags);
    if (!dependency) {
      fwprintf(stderr, L"Dependency load failed: %ls -> %hs (Win32 error %lu)\n", path, name, GetLastError());
      ++failures;
      continue;
    }
    wchar_t dependency_path[32768] = L"";
    GetModuleFileNameW(dependency, dependency_path, (DWORD)(sizeof(dependency_path) / sizeof(dependency_path[0])));
    const IMAGE_THUNK_DATA *thunk;
    while ((thunk = image_at(image, size, rva, sizeof(*thunk))) && thunk->u1.AddressOfData) {
      const BOOL ordinal_import = IMAGE_SNAP_BY_ORDINAL(thunk->u1.Ordinal) != 0;
      const WORD ordinal = (WORD)IMAGE_ORDINAL(thunk->u1.Ordinal);
      const char *symbol = ordinal_import ? MAKEINTRESOURCEA(ordinal)
          : image_string(image, size, thunk->u1.AddressOfData + offsetof(IMAGE_IMPORT_BY_NAME, Name));
      if (!symbol) {
        fwprintf(stderr, L"Invalid import name in %ls.\n", path);
        ++failures;
        break;
      }
      if (!GetProcAddress(dependency, symbol)) {
        fwprintf(stderr, L"Missing import: %ls -> %hs!", path, name);
        if (ordinal_import) {
          fwprintf(stderr, L"#%u", (unsigned int)ordinal);
        } else {
          fwprintf(stderr, L"%hs", symbol);
        }
        fwprintf(stderr, L" (loaded %ls)\n", dependency_path);
        ++failures;
      }
      rva += sizeof(*thunk);
    }
    FreeLibrary(dependency);
  }
  if (!failures) {
    wprintf(L"No unresolved direct imports found; the load failure may be in a transitive dependency.\n");
  }

cleanup:
  UnmapViewOfFile(image);
  CloseHandle(mapping);
}

int wmain(int argc, wchar_t **argv) {
  if (argc < 3 || argc > 4) {
    fwprintf(stderr, L"Usage: verify_qt_runtime.exe <absolute deployment directory> <DLL name> [export]\n");
    return 1;
  }

  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX);
  // Exclude the host application's directory, the working directory, and PATH.
  const DWORD search_flags = LOAD_LIBRARY_SEARCH_USER_DIRS | LOAD_LIBRARY_SEARCH_SYSTEM32;
  if (!SetDefaultDllDirectories(search_flags)) {
    return report_error(L"SetDefaultDllDirectories", GetLastError());
  }
  if (!AddDllDirectory(argv[1])) {
    return report_error(L"AddDllDirectory", GetLastError());
  }

  wchar_t path[32768];
  if (swprintf_s(path, sizeof(path) / sizeof(path[0]), L"%ls\\%ls", argv[1], argv[2]) < 0) {
    fwprintf(stderr, L"Deployment path is too long.\n");
    return 1;
  }
  wprintf(L"Loading %ls\n", path);
  fflush(stdout);
  HMODULE module = LoadLibraryExW(path, NULL, search_flags);
  if (!module) {
    DWORD error = GetLastError();
    print_loaded_modules();
    report_error(path, error);
    diagnose_imports(path, search_flags);
    return 1;
  }

  if (argc == 4) {
    char symbol[1024];
    if (!WideCharToMultiByte(CP_UTF8, 0, argv[3], -1, symbol, (int)sizeof(symbol), NULL, NULL)) {
      return report_error(L"Convert export name", GetLastError());
    }
    if (!GetProcAddress(module, symbol)) {
      DWORD error = GetLastError();
      fwprintf(stderr, L"Missing export: %ls\n", argv[3]);
      print_loaded_modules();
      return report_error(L"GetProcAddress", error);
    }
    wprintf(L"Resolved export: %ls\n", argv[3]);
  }

  print_loaded_modules();
  FreeLibrary(module);
  wprintf(L"DLL imports resolved successfully.\n");
  return 0;
}
