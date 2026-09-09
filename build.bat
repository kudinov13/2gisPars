@echo off
chcp 65001 >nul 2>&1
echo ============================================
echo   Сборка 2GIS Parser в EXE
echo ============================================
echo.

REM Устанавливаем pyinstaller если нет
pip install pyinstaller >nul 2>&1

REM Очищаем старую сборку
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist 2GISParser.spec del 2GISParser.spec

echo [1/4] Сборка EXE через PyInstaller...
python -m PyInstaller --noconfirm --onedir --windowed --name "2GISParser" --add-data "static;static" --add-data "sources;sources" --add-data "analyzers;analyzers" --hidden-import "flask_cors" --hidden-import "openpyxl" --hidden-import "lxml" --hidden-import "bs4" --hidden-import "webview" --hidden-import "webview.platforms.edgechromium" --hidden-import "webview.platforms.winforms" --collect-all "playwright" desktop_app.py

if errorlevel 1 (
    echo.
    echo ОШИБКА: Сборка провалилась!
    pause
    exit /b 1
)

echo [2/4] Копирование Playwright браузеров (Chromium)...
REM Копируем браузеры Playwright рядом с EXE
set "PW_SRC=%LOCALAPPDATA%\ms-playwright"
set "PW_DST=dist\2GISParser\ms-playwright"

if not exist "%PW_DST%" mkdir "%PW_DST%"

REM Копируем только chromium (нужен для headless-скрапинга)
xcopy "%PW_SRC%\chromium-1208" "%PW_DST%\chromium-1208\" /E /I /Y /Q >nul 2>&1
if exist "%PW_SRC%\chromium_headless_shell-1208" (
    xcopy "%PW_SRC%\chromium_headless_shell-1208" "%PW_DST%\chromium_headless_shell-1208\" /E /I /Y /Q >nul 2>&1
)
if exist "%PW_SRC%\.links" (
    xcopy "%PW_SRC%\.links" "%PW_DST%\.links\" /E /I /Y /Q >nul 2>&1
)

echo [3/4] Проверка структуры...
if not exist "dist\2GISParser\2GISParser.exe" (
    echo ОШИБКА: EXE не найден после сборки!
    pause
    exit /b 1
)
if not exist "dist\2GISParser\static\index.html" (
    echo ОШИБКА: static/index.html не найден в сборке!
    pause
    exit /b 1
)
if not exist "dist\2GISParser\ms-playwright\chromium-1208" (
    echo ВНИМАНИЕ: Chromium не найден в сборке! Сканирование не будет работать.
)

echo [4/4] Готово!
echo.
echo ============================================
echo   Сборка завершена!
echo   Папка: dist\2GISParser\
echo   EXE:   dist\2GISParser\2GISParser.exe
echo.
echo   Чтобы отправить сотруднику:
echo   1. Заархивируй папку dist\2GISParser в ZIP
echo   2. Отправь ZIP файл
echo   3. Сотрудник распаковывает и запускает 2GISParser.exe
echo ============================================
echo.
pause
