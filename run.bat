@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo Creating virtual environment...
  python3.13 -m venv .venv 2>nul || python -m venv .venv
)

call ".venv\Scripts\activate.bat" || (
  echo Failed to activate virtual environment.
  exit /b 1
)

pip install -r requirements.txt || (
  echo Failed to install dependencies.
  exit /b 1
)

python -m src.app