@echo off
IF NOT EXIST venv (
    echo Creando entorno virtual (venv)...
    python -m venv venv
)

echo Activando entorno virtual...
call venv\Scripts\activate.bat

echo Instalando dependencias del Dashboard ASRS...
pip install -r requirements.txt >nul 2>&1

echo.
echo Iniciando Servidor Web ASRS...
python serve.py
pause
