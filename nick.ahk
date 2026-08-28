#Requires AutoHotkey v2.0
; Горячие клавиши для смены ника в Steam.
; Ctrl+Alt+1..4 — preset по индексу, Ctrl+Alt+0 — следующий по кругу.

SetNick(args) {
    TrayTip("Steam", "Меняю ник...")
    RunWait('cmd /c python "' A_ScriptDir '\steam_nick.py" ' args
            ' > "' A_Temp '\nick.log" 2>&1', , "Hide")
    out := Trim(FileRead(A_Temp "\nick.log", "UTF-8"))
    TrayTip("Steam", out != "" ? out : "Готово")
}

^!1:: SetNick("-p 0")
^!2:: SetNick("-p 1")
^!3:: SetNick("-p 2")
^!4:: SetNick("-p 3")
^!0:: SetNick("-c")
