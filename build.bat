@echo off
echo [*] Compilando zgrok.exe...
python -m PyInstaller --onefile --clean --name zgrok --paths client zgrok.py
if %ERRORLEVEL% EQU 0 (
    copy /Y dist\zgrok.exe zgrok.exe
    echo [OK] zgrok.exe gerado com sucesso!
) else (
    echo [!] Erro ao compilar zgrok.exe.
)
pause
