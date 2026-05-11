' Elpis — Double-click launcher for Windows (no terminal window)
' This script finds Python and runs gui.py silently.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Try venv Python first, then system Python
venvPy = scriptDir & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(venvPy) Then
    py = venvPy
Else
    ' Try py launcher, then python
    On Error Resume Next
    WshShell.Run "py --version", 0, True
    If Err.Number = 0 Then
        py = "py -3"
    Else
        py = "pythonw"
    End If
    On Error GoTo 0
End If

guiScript = scriptDir & "\gui.py"
WshShell.CurrentDirectory = scriptDir
WshShell.Run py & " """ & guiScript & """", 0, False
