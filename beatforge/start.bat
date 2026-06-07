@echo off
echo ===================================
echo   BEATFORGE — Hip-Hop DAW
echo ===================================
echo.

where node >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Node.js не найден!
    echo Скачай и установи: https://nodejs.org
    echo Минимальная версия: 18+
    pause
    exit /b 1
)

if not exist "node_modules" (
    echo Устанавливаю зависимости (только первый раз)...
    npm install
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] npm install завершился с ошибкой
        pause
        exit /b 1
    )
)

echo Запускаю BEATFORGE...
npm run electron:dev
