from fastapi import APIRouter
from app.api.v1 import health, auth, user, documents, collections

api_router = APIRouter()

# v1 routes
api_router.include_router(health.router, prefix="/health", tags=["health"])

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

api_router.include_router(user.router, prefix="/users", tags=["Users"])

api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])

api_router.include_router(
    collections.router, prefix="/collections", tags=["Collections"]
)
