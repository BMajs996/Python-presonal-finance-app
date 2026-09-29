import uvicorn

from backend.app.core.config import settings

if __name__ == "__main__":
    if settings.environment == "production":
        raise SystemExit("Use python -m backend.app.serve for production; run.py is development-only")
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)
