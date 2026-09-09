from fastapi import HTTPException, status
from sqlalchemy import select

from app.models.user import User, UserRole
from app.schemas.user import UserResponse


class UserService:
  """
  USER SERVICE
  """
  def __init__(self, db: AsyncSession):
    self.db = db

  async def get_users(self, user):
    # is user admin
    if user.role != UserRole.ADMIN:
      raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have enough permission",
      )

    result = await self.db.execute(
      select(User).where(User.tenant_id == user.tenant_id)
    )
    users = result.scalars().all()
    return [UserResponse.model_validate(user) for user in users]
