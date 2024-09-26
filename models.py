from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    username: str
    hashed_password: str
    is_active: bool = True
    is_admin: bool = False
    last_scrape_time: Optional[datetime] = None
    password_needs_reset: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
