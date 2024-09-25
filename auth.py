from datetime import datetime, timedelta
from typing import Optional
import os
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from motor.motor_asyncio import AsyncIOMotorClient

from models import User
from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES


# Password hashing
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/scraper_db")
print(f"Connecting to MongoDB at {MONGO_URL}")

client = AsyncIOMotorClient(MONGO_URL)
db = client.get_default_database()
users_collection = db["users"]

# async def test_connection():
#     try:
#         server_info = await client.server_info()  # Correctly await here
#         print("MongoDB Server Info:", server_info)
#     except Exception as e:
#         print("Error connecting to MongoDB:", e)
#
# # Ensure we properly await the connection check
# async def main():
#     await test_connection()
#
# main()

async def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

async def get_password_hash(password):
    return pwd_context.hash(password)

async def get_user(username: str):
    user_data = await users_collection.find_one({"username": username})
    if user_data:
        return User(**user_data)
    return None

async def authenticate_user(username: str, password: str):
    user = await get_user(username)
    if not user or not await verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = await get_user(username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    # Check if the user needs to reset their password
    if current_user.password_needs_reset:
        raise HTTPException(
            status_code=403,
            detail="Password reset required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user

async def get_current_admin_user(current_user: User = Depends(get_current_active_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user
