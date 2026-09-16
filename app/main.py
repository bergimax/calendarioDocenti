from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, engine
from app.routes import availability, setup, schedule, chat, dati, auth

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    debug=settings.DEBUG
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(setup.router, prefix="/api", tags=["setup"])
app.include_router(availability.router, prefix="/api", tags=["availability"])
app.include_router(schedule.router, prefix="/api", tags=["schedule"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(dati.router, prefix="/api", tags=["dati"])
app.include_router(auth.router, prefix="/api", tags=["auth"])


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
