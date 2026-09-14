from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.events import router as events_router
from app.db.database import Base, engine
from app.models.event import Event
from app.models.session import Session
from app.api.sessions import router as sessions_router


Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="Ambient Agent API",
    version="0.1.0",
)


# 개발 단계에서는 Chrome Extension 요청 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(events_router)
app.include_router(sessions_router)


@app.get("/")
def root():
    return {
        "service": "ambient-agent",
        "status": "running",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
    }


@app.get("/health/db")
def database_health():
    with engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT current_database(), current_user"
            )
        ).fetchone()

    return {
        "status": "ok",
        "database": result[0],
        "user": result[1],
    }