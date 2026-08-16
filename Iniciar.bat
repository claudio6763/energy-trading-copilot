@echo off
REM ===================================================================
REM  Energy Trading Copilot - iniciar com duplo clique (Windows)
REM  Faz tudo: ambiente, dependencias, banco, dados e abre o navegador.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Energy Trading Copilot

echo.
echo   ===============================================
echo    ENERGY TRADING COPILOT
echo   ===============================================
echo.

REM --- 1. Encontrar o Python -----------------------------------------
set PY=
py -3.12 --version >nul 2>&1 && set PY=py -3.12
if not defined PY ( py -3 --version >nul 2>&1 && set PY=py -3 )
if not defined PY ( python --version >nul 2>&1 && set PY=python )

if not defined PY (
    echo   [ERRO] Python nao encontrado.
    echo.
    echo   Instale o Python 3.12 em https://www.python.org/downloads/
    echo   IMPORTANTE: marque "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)
echo   [1/5] Python encontrado.

REM --- 2. Ambiente virtual -------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   [2/5] Criando ambiente virtual ^(primeira vez, ~1 min^)...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   [ERRO] Falha ao criar o ambiente virtual.
        pause
        exit /b 1
    )
) else (
    echo   [2/5] Ambiente virtual ja existe.
)
set VENV_PY=.venv\Scripts\python.exe

REM --- 3. Dependencias -----------------------------------------------
%VENV_PY% -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo   [3/5] Instalando dependencias ^(primeira vez, 2-4 min^)...
    %VENV_PY% -m pip install --upgrade pip --quiet
    %VENV_PY% -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo   [ERRO] Falha ao instalar dependencias.
        echo   Verifique sua conexao com a internet.
        pause
        exit /b 1
    )
) else (
    echo   [3/5] Dependencias ja instaladas.
)

REM --- 4. Configuracao e banco ---------------------------------------
if not exist ".env" copy ".env.example" ".env" >nul
echo   [4/5] Preparando banco de dados...
%VENV_PY% scripts\init_db.py
if errorlevel 1 (
    echo   [ERRO] Falha ao criar o banco.
    echo   Se a pasta estiver no OneDrive ou em rede, mova o projeto
    echo   para um disco local ^(ex: C:\projetos\^).
    pause
    exit /b 1
)

REM Popula dados demonstrativos apenas na primeira execucao.
%VENV_PY% -c "import sys,sqlite3,pathlib; sys.path[:0]=['.','src']; from src.database.connection import connect; c=connect(); n=c.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0]; c.close(); sys.exit(0 if n>0 else 1)" >nul 2>&1
if errorlevel 1 (
    echo         Carregando dados demonstrativos...
    %VENV_PY% scripts\seed_demo.py
)

REM --- 5. Abrir a aplicacao ------------------------------------------
echo   [5/5] Abrindo no navegador...
echo.
echo   ---------------------------------------------------
echo    Endereco: http://localhost:8501
echo    Para encerrar: feche esta janela ou tecle Ctrl+C
echo   ---------------------------------------------------
echo.
%VENV_PY% -m streamlit run app.py

echo.
echo   Aplicacao encerrada.
pause
