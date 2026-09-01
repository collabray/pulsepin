import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import admin, auth, dispatch, hospitals, triage, ws
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pulsepin")

settings = get_settings()
settings.require_production_safety()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "AI-assisted symptom triage, capability-matched facility routing, "
        "and verified emergency dispatch."
    ),
    version="1.0.0",
    docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(triage.router, prefix=settings.API_V1_PREFIX)
app.include_router(hospitals.router, prefix=settings.API_V1_PREFIX)
app.include_router(dispatch.router, prefix=settings.API_V1_PREFIX)
app.include_router(admin.router, prefix=settings.API_V1_PREFIX)
app.include_router(admin.user_router, prefix=settings.API_V1_PREFIX)
app.include_router(ws.router)

# --- Security headers (defense in depth alongside the WAF/reverse-proxy
# layer — see infra/traefik/. App-level headers ensure protection even if
# a deployment temporarily runs without the proxy in front, e.g. in CI.) ---
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self)"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error."},
    )


@app.get("/health", tags=["health"])
def health_check():
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
        "live_dispatch_enabled": settings.ENABLE_LIVE_DISPATCH,
    }
