@echo off
cd /d "%~dp0"
echo [*] Compilando zgrok.exe na pasta client...
python -m PyInstaller --onefile --clean --name zgrok --hidden-import colorama zgrok.py
if %ERRORLEVEL% EQU 0 (
    copy /Y dist\zgrok.exe zgrok.exe
    echo [OK] zgrok.exe gerado com sucesso em client\zgrok.exe!
) else (
    echo [!] Erro ao compilar zgrok.exe.
)
pause
