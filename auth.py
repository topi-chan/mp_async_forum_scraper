import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

from config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY, settings
from models import User

# Password hashing
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
MONGO_URL = settings.MONGO_URL
print(f"Connecting to MongoDB at {MONGO_URL}")

client = AsyncIOMotorClient(MONGO_URL)
db = client.get_default_database()
users_collection = db["users"]


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


# Extract token from either header or cookie based on the request context.
async def get_token(request: Request):
    # Try to get the token from the Authorization header (for Swagger and API clients)
    authorization: str = request.headers.get("Authorization")
    if authorization:
        scheme, param = get_authorization_scheme_param(authorization)
        if scheme.lower() == "bearer":
            return param

    # If no Authorization header is present, fallback to the cookie (for frontend)
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Ensure the token follows the Bearer schema
    scheme, param = get_authorization_scheme_param(token)
    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return param


# Use `get_token` to extract the token from the request and verify it
async def get_current_user(token: str = Depends(get_token)):
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


# Check if the user is active and if they need to reset their password
async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if current_user.password_needs_reset:
        raise HTTPException(
            status_code=403,
            detail="Password reset required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


# Admin access check
async def get_current_admin_user(current_user: User = Depends(get_current_active_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user


# A fallback in case we need to get the token explicitly from a cookie
async def get_token_from_cookie(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        logging.warning("Token not found in cookies")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Log the token for debugging
    logging.info(f"Token found in cookie: {token}")
    scheme, param = get_authorization_scheme_param(token)
    if scheme.lower() != "bearer":
        logging.warning("Invalid authentication scheme")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return param
