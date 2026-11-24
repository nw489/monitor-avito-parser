' Hidden startup for Avito Monitor - no command prompt window
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = "D:\avito-monitor"
shell.CurrentDirectory = scriptDir

' Устанавливаем зависимости
shell.Run "cmd /c cd /d """ & scriptDir & """ && pip install -r requirements.txt", 0, True

' Запускаем сервер полностью скрыто
shell.Run "cmd /c cd /d """ & scriptDir & """ && python main.py", 0, False

' Ждём, пока сервер поднимется
WScript.Sleep 5000

' Открываем браузер
shell.Run "http://localhost:8000", 1, False