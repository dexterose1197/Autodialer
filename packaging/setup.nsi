Target amd64-unicode
!include "x64.nsh"
!include "FileFunc.nsh"

Name "AutoDialer"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\AutoDialer"
RequestExecutionLevel user
SetCompressor /SOLID lzma
AutoCloseWindow true
BrandingText "AutoDialer · IVR simulator"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "AutoDialer"
VIAddVersionKey "CompanyName" "AutoDialer"
VIAddVersionKey "FileDescription" "AutoDialer offline installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "See included third-party license files"

Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Function .onInit
    ${IfNot} ${RunningX64}
        MessageBox MB_ICONSTOP "AutoDialer requires Windows x64."
        Abort
    ${EndIf}
FunctionEnd

Section "AutoDialer"
    SetShellVarContext current
    SetOutPath "$INSTDIR"
    File /r "${STAGING}\*"
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    CreateDirectory "$SMPROGRAMS\AutoDialer"
    CreateShortCut "$SMPROGRAMS\AutoDialer\AutoDialer.lnk" "$INSTDIR\python\python.exe" '-m autodialer.launcher --model-dir "$INSTDIR\models\whisper-tiny.en"'
    CreateShortCut "$SMPROGRAMS\AutoDialer\AutoDialer - Android access (private network).lnk" "$INSTDIR\python\python.exe" '-m autodialer.launcher --lan --model-dir "$INSTDIR\models\whisper-tiny.en"'
    CreateShortCut "$SMPROGRAMS\AutoDialer\AutoDialer - Fixture demo.lnk" "$INSTDIR\python\python.exe" "-m autodialer.launcher --fixture-transcripts"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoDialer" "DisplayName" "AutoDialer"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoDialer" "DisplayVersion" "${VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoDialer" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoDialer" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoDialer" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoDialer" "NoRepair" 1
SectionEnd

Function .onInstSuccess
    IfSilent done
    SetOutPath "$INSTDIR"
    Exec '"$INSTDIR\python\python.exe" -m autodialer.launcher --model-dir "$INSTDIR\models\whisper-tiny.en"'
done:
FunctionEnd

Section "Uninstall"
    SetShellVarContext current
    Delete "$SMPROGRAMS\AutoDialer\AutoDialer.lnk"
    Delete "$SMPROGRAMS\AutoDialer\AutoDialer - Android access (private network).lnk"
    Delete "$SMPROGRAMS\AutoDialer\AutoDialer - Fixture demo.lnk"
    RMDir "$SMPROGRAMS\AutoDialer"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoDialer"
    RMDir /r "$INSTDIR\python"
    RMDir /r "$INSTDIR\models\whisper-tiny.en"
    RMDir "$INSTDIR\models"
    Delete "$INSTDIR\README.md"
    Delete "$INSTDIR\ARCHITECTURE.md"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir "$INSTDIR"
SectionEnd
