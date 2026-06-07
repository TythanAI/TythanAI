#!/bin/bash
echo "==================================="
echo "  BEATFORGE — Hip-Hop DAW"
echo "==================================="
echo ""

if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js не найден!"
    echo "Установи через: https://nodejs.org (версия 18+)"
    exit 1
fi

if [ ! -d "node_modules" ]; then
    echo "Устанавливаю зависимости (только первый раз)..."
    npm install
fi

echo "Запускаю BEATFORGE..."
npm run electron:dev
