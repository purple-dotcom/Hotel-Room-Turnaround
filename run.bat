@echo off
cd /d "%~dp0"
if not exist venv (
    py -3.14 -m venv venv
)
call .\venv\Scripts\activate.bat
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000