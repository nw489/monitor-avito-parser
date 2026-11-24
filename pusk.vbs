Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /k cd /d D:/avito-monitor && py main.py", 1, False
WScript.Sleep 5000
WshShell.Run "http://localhost:8000", 1, False