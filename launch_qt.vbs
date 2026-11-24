Option Explicit
Dim shell, fs, root, python, code, args, output
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
python = fs.BuildPath(root, ".venv-qt\Scripts\pythonw.exe")
If Not fs.FileExists(python) Then
    MsgBox "The Qt environment is missing. Follow docs\QT_PROTOTYPE.md to run setup_qt.bat with an existing Python installation.", vbExclamation, "Chromatogram Viewer"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
args = " -m gcviewer.desktop"
If WScript.Arguments.Named.Exists("smoke-output") Then
    output = WScript.Arguments.Named.Item("smoke-output")
    If InStr(output, Chr(34)) > 0 Then WScript.Quit 2
    args = args & " --smoke-output " & Chr(34) & output & Chr(34)
End If
code = shell.Run(Chr(34) & python & Chr(34) & args, 0, True)
If code <> 0 Then
    MsgBox "Chromatogram Viewer exited with code " & code & ". Check %LOCALAPPDATA%\ChromatogramViewer\qt-startup.log or use the debug command in docs\QT_PROTOTYPE.md.", vbExclamation, "Chromatogram Viewer"
End If
