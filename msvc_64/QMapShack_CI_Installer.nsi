Unicode true

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "WordFunc.nsh"

!define APP_NAME "QMapShack"
!define APP_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\QMapShack"

Name "${APP_NAME}"
OutFile "${PROJECT_ROOT}\${INSTALLER_NAME}"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define MUI_ICON "${PROJECT_ROOT}\msvc_64\QMapShack.ico"
!define MUI_UNICON "${PROJECT_ROOT}\msvc_64\QMapShack.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\qmapshack.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch QMapShack"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PROJECT_ROOT}\LICENSE"
!insertmacro MUI_PAGE_LICENSE "${PROJECT_ROOT}\msvc_64\LICENSE_Gisinternals.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetRegView 64
  ReadRegStr $0 HKLM "Software\${APP_NAME}" "Install_Dir"
  StrCmp $0 "" done
  StrCpy $INSTDIR $0
done:
FunctionEnd

Section "-Visual C++ runtime"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "${PROJECT_ROOT}\dist\vc_redist.x64.exe"

  ; Avoid running the redistributable again when a suitable x64 runtime exists.
  ReadRegDWORD $0 HKLM "Software\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Installed"
  ${If} $0 == 1
    ReadRegStr $1 HKLM "Software\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Version"
    StrCpy $1 $1 "" 1 ; remove the leading 'v'
    ${GetFileVersion} "$PLUGINSDIR\vc_redist.x64.exe" $2
    ${IfNot} ${Errors}
      ${VersionCompare} $1 $2 $0
      ${If} $0 != 2
        DetailPrint "Visual C++ x64 runtime $1 is already installed."
        Goto runtime_done
      ${EndIf}
    ${EndIf}
  ${EndIf}

  StrCpy $1 "/passive"
  IfSilent 0 +2
    StrCpy $1 "/quiet"
  DetailPrint "Visual C++ runtime log: $TEMP\QMapShack-vc_redist.x64.log"
  ClearErrors
  ExecWait '"$PLUGINSDIR\vc_redist.x64.exe" /install $1 /norestart /log "$TEMP\QMapShack-vc_redist.x64.log"' $0
  IfErrors runtime_failed
  ${If} $0 == 3010
    SetRebootFlag true
  ${ElseIf} $0 != 0
  ${AndIf} $0 != 1638 ; a newer runtime is already installed
    Goto runtime_failed
  ${EndIf}
  Goto runtime_done
runtime_failed:
  MessageBox MB_OK|MB_ICONSTOP "Could not install the Visual C++ runtime (error $0). See $TEMP\QMapShack-vc_redist.x64.log."
  SetErrorLevel 1
  Abort
runtime_done:
SectionEnd

Section "Install"
  SetRegView 64
  SetShellVarContext all
  SetOutPath "$INSTDIR"
  ; Remove plugins from older GDAL builds before installing matching binaries.
  RMDir /r "$INSTDIR\gdalplugins"
  File /r /x vc_redist.x64.exe "${PROJECT_ROOT}\dist\*"
  File "${PROJECT_ROOT}\msvc_64\QMapShack.ico"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  FileOpen $0 "$INSTDIR\gdal_shell.bat" w
  FileWrite $0 '@echo off$\r$\n'
  FileWrite $0 'set "PATH=%~dp0;%PATH%"$\r$\n'
  FileWrite $0 'set "GDAL_DATA=%~dp0data"$\r$\n'
  FileWrite $0 'set "GDAL_DRIVER_PATH=%~dp0gdalplugins"$\r$\n'
  FileWrite $0 'set "PROJ_DATA=%~dp0share\proj"$\r$\n'
  FileWrite $0 'cd /d "%USERPROFILE%"$\r$\n'
  FileClose $0

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\qmapshack.exe" "" "$INSTDIR\QMapShack.ico"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\QMapTool.lnk" "$INSTDIR\qmaptool.exe" "" "$INSTDIR\QMapTool.ico"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\QMapShack Help.lnk" "$INSTDIR\assistant.exe" '-collectionFile "$INSTDIR\doc\HTML\QMSHelp.qhc"'
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\QMapTool Help.lnk" "$INSTDIR\assistant.exe" '-collectionFile "$INSTDIR\doc\HTML\QMTHelp.qhc"'
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\GDAL shell.lnk" "$SYSDIR\cmd.exe" '/k ""$INSTDIR\gdal_shell.bat""' "$INSTDIR\gdalicon.ico"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Third-party notices.lnk" "$INSTDIR\3rdparty.txt"

  WriteRegStr HKLM "Software\${APP_NAME}" "Install_Dir" "$INSTDIR"
  WriteRegStr HKLM "${APP_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${APP_KEY}" "DisplayIcon" "$INSTDIR\QMapShack.ico"
  WriteRegStr HKLM "${APP_KEY}" "Publisher" "QMapShack contributors"
  WriteRegStr HKLM "${APP_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${APP_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${APP_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetRegView 64
  SetShellVarContext all
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\QMapTool.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\QMapShack Help.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\QMapTool Help.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\GDAL shell.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Third-party notices.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  DeleteRegKey HKLM "${APP_KEY}"
  DeleteRegKey HKLM "Software\${APP_NAME}"
  RMDir /r "$INSTDIR"
SectionEnd
