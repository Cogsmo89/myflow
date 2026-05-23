' Robust myflow launcher: waits for OneDrive to make the venv accessible,
' clears stale lock files, logs all decisions for debugging.

Option Explicit
Dim sh, fso, projectDir, pythonExe, cmd, logPath, lockPath
Dim attempt, maxAttempts, ok

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectDir = "C:\myflow_app"
' venv is OUTSIDE OneDrive so imports never block on Files-On-Demand sync
pythonExe  = "C:\myflow_venv\Scripts\pythonw.exe"
logPath    = sh.ExpandEnvironmentStrings("%APPDATA%") & "\myflow\startup.log"
lockPath   = sh.ExpandEnvironmentStrings("%APPDATA%") & "\myflow\myflow.lock"

Dim logDir : logDir = sh.ExpandEnvironmentStrings("%APPDATA%") & "\myflow"
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)

Sub WriteLog(msg)
    On Error Resume Next
    Dim f
    Set f = fso.OpenTextFile(logPath, 8, True)  ' 8=append, create if missing
    f.WriteLine Now & "  " & msg
    f.Close
    On Error Goto 0
End Sub

WriteLog "----- launcher starting -----"

' Kill any orphan myflow processes from a previous boot, hung-from-sleep, or
' a hand-launched run from a terminal. We identify them strictly by the
' command line containing "-m myflow.main" so we never touch unrelated Python.
Dim wmi, procs, p, killed
killed = 0
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery( _
    "SELECT ProcessId, CommandLine FROM Win32_Process " & _
    "WHERE (Name = 'python.exe' OR Name = 'pythonw.exe')")
For Each p In procs
    If Not IsNull(p.CommandLine) Then
        If InStr(p.CommandLine, "myflow.main") > 0 Or InStr(p.CommandLine, "run_myflow.py") > 0 Then
            sh.Run "taskkill /F /PID " & p.ProcessId, 0, True
            killed = killed + 1
        End If
    End If
Next
On Error Goto 0
If killed > 0 Then
    WriteLog "killed " & killed & " orphan myflow process(es)"
    WScript.Sleep 1500  ' let the OS settle
End If

' Stale lock cleanup. The Python side uses msvcrt.locking on this file; if
' a previous instance died without releasing, the file persists but the OS
' lock is gone, so deleting it here lets the fresh process re-acquire cleanly.
On Error Resume Next
If fso.FileExists(lockPath) Then
    fso.DeleteFile lockPath, True
    If Err.Number = 0 Then
        WriteLog "removed stale lock file"
    Else
        WriteLog "could not remove lock (probably held by live instance): " & Err.Description
        Err.Clear
    End If
End If
On Error Goto 0

' Wait until pythonw.exe is accessible. OneDrive Files-On-Demand or sync can
' delay availability at logon. Poll every 5s for up to 5 minutes.
maxAttempts = 60
attempt = 0
ok = False
Do While attempt < maxAttempts
    If fso.FileExists(pythonExe) Then
        ok = True
        Exit Do
    End If
    attempt = attempt + 1
    WriteLog "pythonw.exe not accessible, waiting (" & attempt & "/" & maxAttempts & ")"
    WScript.Sleep 5000
Loop

If Not ok Then
    WriteLog "ERROR: pythonw.exe never appeared at " & pythonExe
    WScript.Quit 1
End If

WriteLog "pythonw.exe found at " & pythonExe
cmd = """" & pythonExe & """ ""C:\myflow_app\run_myflow.py"""
sh.CurrentDirectory = projectDir
sh.Run cmd, 0, False  ' 0=hidden, False=don't wait
WriteLog "launched: " & cmd
