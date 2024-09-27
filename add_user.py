import asyncio

from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorDatabase)
from passlib.context import CryptContext

from config import settings

MONGO_URL: str = settings.MONGO_URL
print(f"Connecting to MongoDB at {MONGO_URL}")

client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
db: AsyncIOMotorDatabase = client.get_default_database()
users_collection: AsyncIOMotorCollection = db["users"]


async def test_connection() -> None:
    """
    Test the connection to the MongoDB server and print server information.

    :raises Exception: If there is an error connecting to MongoDB.
    """
    try:
        server_info = await client.server_info()
        print("MongoDB Server Info:", server_info)
    except Exception as e:
        print("Error connecting to MongoDB:", e)


async def main() -> None:
    """
    Main function to test MongoDB connection and add a new user.

    Prompts the user for username, password, and admin status, then adds the user to the database.
    """
    await test_connection()

    pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

    async def add_user(username: str, password: str, is_admin: bool = False) -> None:
        """
        Add a new user to the MongoDB collection with hashed password.

        :param username: The username of the new user.
        :param password: The password of the new user.
        :param is_admin: Boolean flag indicating if the user is an admin.
        """
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
    username: str = input("Enter username: ")
    password: str = input("Enter temporary password: ")
    is_admin_input: str = input("Is admin? (y/n): ").lower()
    is_admin: bool = True if is_admin_input == "y" else False

    # Run add_user function
    await add_user(username, password, is_admin)


if __name__ == "__main__":
    # Run the main function using asyncio
    asyncio.run(main())
