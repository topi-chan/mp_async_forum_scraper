import asyncio

from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

from config import settings

MONGO_URL = settings.MONGO_URL
print(f"Connecting to MongoDB at {MONGO_URL}")

client = AsyncIOMotorClient(MONGO_URL)
db = client.get_default_database()
users_collection = db["users"]


async def test_connection():
    try:
        server_info = await client.server_info()
        print("MongoDB Server Info:", server_info)
    except Exception as e:
        print("Error connecting to MongoDB:", e)


# Ensure to properly await for the connection check
async def main():
    await test_connection()

    pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

    async def add_user(username, password, is_admin=False):
        hashed_password = pwd_context.hash(password)
        user_data = {
            "username": username,
            "hashed_password": hashed_password,
            "is_active": True,
            "is_admin": is_admin,
            "last_scrape_time": None,
            "password_needs_reset": True,  # Set to True for new users
        }
        await users_collection.insert_one(user_data)
        print(f"User {username} added successfully.")

    # Get input from the user
    username = input("Enter username: ")
    password = input("Enter temporary password: ")
    is_admin_input = input("Is admin? (y/n): ").lower()
    is_admin = True if is_admin_input == "y" else False

    # Run add_user function
    await add_user(username, password, is_admin)


if __name__ == "__main__":
    # Run the main function using asyncio
    asyncio.run(main())
