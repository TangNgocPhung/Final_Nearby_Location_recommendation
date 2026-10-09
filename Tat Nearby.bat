@echo off
REM Bam dup chuot vao file nay de tat toan bo Nearby.
REM Du lieu (database, cache...) nam trong Docker volume nen KHONG bi mat.
setlocal
title Nearby - dang tat
cd /d "%~dp0"

set "POSTGRES_PORT=5433"
set "ENV_FILES=--env-file config\development.env"
if exist ".env" set "ENV_FILES=%ENV_FILES% --env-file .env"

echo Dang tat cac dich vu Nearby...
docker compose %ENV_FILES% down
echo.
echo Da tat xong.
pause
