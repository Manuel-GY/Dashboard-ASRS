@echo off
IF EXIST venv\Scripts\activate.bat GOTO activate
echo Creando entorno virtual...
python -m venv venv

:activate
echo Activando entorno virtual...
call venv\Scripts\activate.bat

echo Instalando dependencias del Dashboard ASRS...
pip install -r requirements.txt >nul 2>&1

echo.
echo Iniciando Servidor Web ASRS...
python serve.py
pause
