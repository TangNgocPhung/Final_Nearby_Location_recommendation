@echo off
REM Bam dup chuot vao file nay de bat toan bo Nearby.
REM   1. Bat Docker Desktop neu chua chay, cho engine san sang
REM   2. Bat Ollama neu chua chay - chatbot, thuyet minh, dich giao dien can no
REM   3. docker compose up ca stack, build lai image neu code da doi
REM   4. Cho gateway tra loi roi tu mo trinh duyet
REM
REM Chi dung ky tu ASCII: cmd.exe doc file .bat theo code page cua console,
REM tieng Viet co dau se thanh ky tu rac.
setlocal
title Nearby - dang khoi dong
cd /d "%~dp0"

set "URL=http://localhost:8081"
set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"

REM Cong 5432 tren may nay dang bi Postgres cai san tren Windows chiem. Dua
REM cong host cua database Docker sang 5433 de khoi tranh nhau; ben trong
REM mang Docker backend van goi database:5432 nen khong anh huong gi.
set "POSTGRES_PORT=5433"

echo ============================================
echo   NEARBY - khoi dong toan bo he thong
echo ============================================
echo.

REM ---------- 1. Docker Desktop ----------
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
echo [1/4] Docker chua chay - dang bat Docker Desktop...
if not exist "%DOCKER_EXE%" goto no_docker
start "" "%DOCKER_EXE%"
set /a TRIES=0
:wait_docker
set /a TRIES+=1
if %TRIES% gtr 90 goto docker_timeout
ping -n 3 127.0.0.1 >nul
docker info >nul 2>&1
if errorlevel 1 goto wait_docker
:docker_ready
echo [1/4] Docker da san sang.

REM ---------- 2. Ollama ----------
curl.exe -s -o nul --max-time 2 http://localhost:11434/api/version
if not errorlevel 1 goto ollama_ready
if not exist "%OLLAMA_EXE%" goto ollama_missing
echo [2/4] Dang bat Ollama...
start "" "%OLLAMA_EXE%"
goto ollama_done
:ollama_missing
echo [2/4] Khong tim thay Ollama - chatbot AI va thuyet minh se tat, phan con lai van chay.
goto ollama_done
:ollama_ready
echo [2/4] Ollama da chay.
:ollama_done

REM ---------- 3. Docker compose ----------
echo [3/4] Dang bat cac dich vu - lan dau hoac khi code doi co the mat vai phut...
set "ENV_FILES=--env-file config\development.env"
if exist ".env" set "ENV_FILES=%ENV_FILES% --env-file .env"
docker compose %ENV_FILES% up -d --build
if errorlevel 1 goto compose_failed

REM ---------- 4. Cho gateway roi mo trinh duyet ----------
echo [4/4] Cho giao dien san sang...
set /a TRIES=0
:wait_gateway
set /a TRIES+=1
if %TRIES% gtr 90 goto gateway_timeout
curl.exe -s -f -o nul --max-time 3 %URL%/health
if not errorlevel 1 goto open_browser
ping -n 3 127.0.0.1 >nul
goto wait_gateway

:open_browser
echo.
echo ============================================
echo   XONG! Dang mo %URL%
echo ============================================
echo   Giao dien : %URL%
echo   API docs  : http://localhost:8000/docs
echo   Tai khoan admin dev: admin / xem config\development.env
echo.
echo   Muon tat he thong: bam dup "Tat Nearby.bat"
echo.
start "" "%URL%"
title Nearby - dang chay
pause
exit /b 0

:no_docker
echo.
echo LOI: Khong tim thay Docker Desktop tai:
echo   %DOCKER_EXE%
echo Hay cai Docker Desktop roi chay lai file nay.
pause
exit /b 1

:docker_timeout
echo.
echo LOI: Docker Desktop khong san sang sau 3 phut.
echo Mo Docker Desktop bang tay, doi bieu tuong chuyen sang "running" roi chay lai file nay.
pause
exit /b 1

:compose_failed
echo.
echo LOI: docker compose that bai - xem thong bao loi o tren.
pause
exit /b 1

:gateway_timeout
echo.
echo Canh bao: sau 3 phut giao dien van chua tra loi.
echo Cac container co the van dang khoi dong. Xem trang thai bang lenh:
echo   docker compose -p nearby-dev ps
echo Van mo trinh duyet thu...
start "" "%URL%"
pause
exit /b 1
