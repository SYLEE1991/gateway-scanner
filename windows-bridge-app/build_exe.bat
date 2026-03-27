@echo off
echo === Gateway Scanner EXE Builder ===
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building EXE...
pyinstaller --onefile --windowed --name GatewayScanner main.py

echo.
if exist dist\GatewayScanner.exe (
    echo Build successful!
    echo Output: dist\GatewayScanner.exe
) else (
    echo Build failed.
)

pause
