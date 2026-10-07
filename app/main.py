from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, engine, ensure_admin_role_column, ensure_assegnazione_singola_column
from app.routes import availability, setup, schedule, chat, dati, auth, soft_weights

# Create tables
Base.metadata.create_all(bind=engine)


ensure_admin_role_column()
ensure_assegnazione_singola_column()

# Initialize FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    debug=settings.DEBUG
)

# CORS middleware. allow_credentials is False because auth is a bearer
# token in the Authorization header (see app/security.py), not a cookie -
# "*" + credentialed CORS is both unnecessary and a browser-rejected/unsafe
# combination, so don't turn allow_credentials back on without switching to
# cookie-based sessions first.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(setup.router, prefix="/api", tags=["setup"])
app.include_router(availability.router, prefix="/api", tags=["availability"])
app.include_router(schedule.router, prefix="/api", tags=["schedule"])
app.include_router(soft_weights.router, prefix="/api", tags=["soft-weights"])
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
