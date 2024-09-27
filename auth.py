import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param
from jose import JWTError, jwt
from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorDatabase)
from passlib.context import CryptContext

from config import (ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, MONGO_URL,
                    SECRET_KEY)
from models import User

# Password hashing
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
print(f"Connecting to MongoDB at {MONGO_URL}")

client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
db: AsyncIOMotorDatabase = client.get_default_database()
users_collection: AsyncIOMotorCollection = db["users"]


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.

    :param plain_password: The plain text password to verify.
    :param hashed_password: The hashed password to verify against.
    :return: True if the password matches, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)


async def get_password_hash(password: str) -> str:
    """
    Hash a password.

    :param password: The plain text password to hash.
    :return: The hashed password.
    """
    return pwd_context.hash(password)


async def get_user(username: str) -> Optional[User]:
    """
    Retrieve a user from the database by username.

    :param username: The username of the user to retrieve.
    :return: The User object if found, None otherwise.
    """
    user_data = await users_collection.find_one({"username": username})
    if user_data:
        return User(**user_data)
    return None


async def authenticate_user(username: str, password: str) -> Optional[User]:
    """
    Authenticate a user by username and password.

    :param username: The username of the user to authenticate.
    :param password: The plain text password of the user to authenticate.
    :return: The authenticated User object if credentials are valid, None otherwise.
    """
    user = await get_user(username)
    if not user or not await verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    :param data: The data to encode in the token.
    :param expires_delta: The time delta for the token expiration.
    :return: The encoded JWT token.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_token(request: Request) -> str:
    """
    Extract token from either header or cookie based on the request context..

    :param request: The request object.
    :return: The extracted token.
    :raises HTTPException: If the token is not found or invalid.
    """
    # Try to get the token from the Authorization header (for Swagger and API clients)
    authorization: Optional[str] = request.headers.get("Authorization")
    if authorization:
        scheme, param = get_authorization_scheme_param(authorization)
        if scheme.lower() == "bearer":
            return param

    # If no Authorization header is present, fallback to the cookie (for frontend)
    token: Optional[str] = request.cookies.get("access_token")
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


async def get_current_user(token: str = Depends(get_token)) -> User:
    """
    Get the current user from the token.
    Use `get_token` to extract the token from the request and verify it

    :param token: The JWT token.
    :return: The current User object.
    :raises HTTPException: If the token is invalid or the user is not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = await get_user(username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get the current active user.
    Check if the user is active and if they need to reset their password.

    :param current_user: The current User object.
    :return: The current active User object.
    :raises HTTPException: If the user is inactive or needs a password reset.
    """
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if current_user.password_needs_reset:
        raise HTTPException(
            status_code=403,
            detail="Password reset required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    For Admin access check. Get the current admin user.

    :param current_user: The current User object.
    :return: The current admin User object.
    :raises HTTPException: If the user is not an admin.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user


# A fallback in case it's needed to get the token explicitly from a cookie
async def get_token_from_cookie(request: Request) -> str:
    """
    Get the token explicitly from a cookie.

    :param request: The request object.
    :return: The extracted token.
    :raises HTTPException: If the token is not found or invalid.
    """
    token: Optional[str] = request.cookies.get("access_token")
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
