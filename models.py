from pydantic import BaseModel
from typing import Optional
from datetime import datetime

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
