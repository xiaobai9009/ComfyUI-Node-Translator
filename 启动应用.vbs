Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 优先使用内置的 pythonw.exe
If fso.FileExists(currentDir & "\python\pythonw.exe") Then
    pythonPath = chr(34) & currentDir & "\python\pythonw.exe" & chr(34)
Else
    pythonPath = "pythonw.exe"
End If

' 运行 main.py，0 表示隐藏窗口
WshShell.Run pythonPath & " " & chr(34) & currentDir & "\main.py" & chr(34), 0, False
Set WshShell = Nothing
