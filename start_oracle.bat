@echo off
echo Starting Oracle Backend on port 8000...
echo.
echo If this doesn't work, try:  uvicorn src.main:app --host 0.0.0.0 --port 8000
echo.
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
pause
