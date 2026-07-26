@echo off
title AtlasMind Agent Workbench Launcher

echo ==============================
echo   AtlasMind Agent Workbench
echo ==============================
echo.

cd /d "%~dp0"

echo [1/4] Starting Java backend (Spring Boot :18080) ...
start "AtlasMind-Agent-Server" cmd /k "title AtlasMind-Agent-Server && cd /d %~dp0agent-server && mvnw.cmd spring-boot:run"

echo [2/4] Starting admin app (Vite :15173) ...
start "AtlasMind-Agent-Admin" cmd /k "title AtlasMind-Agent-Admin && cd /d %~dp0agent-admin && npm run dev"

echo [3/4] Starting front app (Vite :15174) ...
start "AtlasMind-Agent-Front" cmd /k "title AtlasMind-Agent-Front && cd /d %~dp0agent-front && npm run dev"

echo [4/4] Starting Python AI service (FastAPI :18088) ...
start "AtlasMind-AI-Service" cmd /k "title AtlasMind-AI-Service && cd /d %~dp0tools\chat-assistant\backend && if exist .venv-ocr\Scripts\python.exe (.venv-ocr\Scripts\python.exe run.py) else (pip install -r requirements.txt -q && python run.py)"

echo.
echo ==============================
echo   Services launched:
echo     Java backend:   http://localhost:18080
echo     Admin app:      http://localhost:15173
echo     Front app:      http://localhost:15174
echo     AI service:     http://localhost:18088
echo ==============================
echo.
echo Close each window to stop the service.
pause
