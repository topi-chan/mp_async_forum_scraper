from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    username: str
    hashed_password: str
    is_active: bool = True
    is_admin: bool = False
    last_scrape_time: Optional[datetime] = None
    last_mods_scrape_time: Optional[datetime] = None  # Add this line
    password_needs_reset: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class Activity(BaseModel):
    moderator: str
    action: str
    details: str
    date: datetime
    mods_scope: str  # 'active' or 'all' TODO: Change to Enum, check if necessary
