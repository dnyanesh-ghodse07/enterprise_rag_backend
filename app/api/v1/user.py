from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.schemas.user import UserResponse
from app.services.user_service import UserService

router = APIRouter()

@router.get(
  '/', 
  response_model=list[UserResponse], 
  status_code=status.HTTP_200_OK,
  summary="Get all users",
  description="Get all users under tenant for the admin"
  )
async def get_users(
  user: CurrentUser,
  db: AsyncSession = Depends(get_session),
) -> list[UserResponse]:
  service = UserService(db)
  result = await service.get_users(user)
  return result
