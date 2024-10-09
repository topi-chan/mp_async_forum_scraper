import asyncio
import os
from datetime import datetime, timedelta

import aiohttp
import aiohttp_socks
import pandas as pd
from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorDatabase)

from config import FORUM_PASSWORD, FORUM_USERNAME, MONGO_URL, TOR_PROXY_URL
from logged_scrape import LoggedInForumScraper
from models import Activity

# Initialize MongoDB client and collections
print(f"Connecting to MongoDB at {MONGO_URL}")

client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
db: AsyncIOMotorDatabase = client.get_default_database()
activities_collection: AsyncIOMotorCollection = db["activities"]
users_collection: AsyncIOMotorCollection = db["users"]


# Ensure unique index on ('moderator', 'action', 'details', 'date')
async def ensure_indexes():
    await activities_collection.create_index(
        [("moderator", 1), ("action", 1), ("details", 1), ("date", 1)],
        unique=True,
        name="unique_activity_index",
    )


# Call this function at the start
asyncio.run(ensure_indexes())


async def save_activities_from_csv_to_db(csv_file_path: str, mods_scope: str):
    """
    Read activities from CSV file and save to the database.

    :param csv_file_path: Path to the activities.csv file.
    :param mods_scope: 'active' or 'all' to indicate the scope of mods.
    """
    if not os.path.exists(csv_file_path):
        return

    df = pd.read_csv(csv_file_path)

    # Convert date strings to datetime objects
    df["date"] = pd.to_datetime(df["Date"])
    df.drop(columns=["Date"], inplace=True)

    # Prepare list of activity dictionaries
    activities = []
    for _, row in df.iterrows():
        activity = {
            "moderator": row["Moderator"],
            "action": row["Action"],
            "details": row["Details"],
            "date": row["date"],
            "mods_scope": mods_scope,
        }
        activities.append(activity)

    if not activities:
        return

    # Insert activities with upsert
    for activity in activities:
        await activities_collection.update_one(
            {
                "moderator": activity["moderator"],
                "action": activity["action"],
                "details": activity["details"],
                "date": activity["date"],
            },
            {"$setOnInsert": activity},
            upsert=True,
        )


async def fetch_activities_from_db(
    start_date: datetime, end_date: datetime
) -> list[Activity]:
    """
    Fetch activities from the database for a given date range.

    :param start_date: Start date.
    :param end_date: End date.
    :return: List of Activity objects.
    """
    cursor = activities_collection.find(
        {"date": {"$gte": start_date, "$lte": end_date}}
    )
    activities = []
    async for document in cursor:
        activities.append(Activity(**document))
    return activities


async def fetch_active_mods() -> list[str]:
    """
    Fetch the list of currently active moderators using LoggedInForumScraper.

    :return: List of moderator usernames.
    """
    # Create an instance of LoggedInForumScraper
    scraper = LoggedInForumScraper(username=FORUM_USERNAME, password=FORUM_PASSWORD)
    connector = aiohttp_socks.ProxyConnector.from_url(TOR_PROXY_URL)
    async with aiohttp.ClientSession(connector=connector) as session:
        logged_in = await scraper.login(session)
        if not logged_in:
            raise Exception("Failed to login to the forum.")

        # Fetch group members (active moderators)
        await scraper.get_group_members(session, group_id=scraper.group_id)

    # Extract usernames from the scraper's members list
    active_mods = [member[0] for member in scraper.members]
    return active_mods


async def get_missing_date_ranges(
    start_date: datetime, end_date: datetime
) -> list[tuple[datetime, datetime]]:
    """
    Determine the missing date ranges that need to be scraped.

    :param start_date: The start date of the user-requested range.
    :param end_date: The end date of the user-requested range.
    :return: A list of (start_date, end_date) tuples representing missing date ranges.
    """
    # Fetch existing dates from the database
    existing_dates_cursor = activities_collection.find(
        {"date": {"$gte": start_date, "$lte": end_date}}, {"_id": 0, "date": 1}
    )
    existing_dates = set()
    async for doc in existing_dates_cursor:
        existing_dates.add(doc["date"].date())

    # Create a set of all dates in the requested range
    total_dates = set(
        (start_date + timedelta(days=x)).date()
        for x in range((end_date - start_date).days + 1)
    )

    # Determine missing dates
    missing_dates = sorted(total_dates - existing_dates)

    if not missing_dates:
        return []

    # Group missing dates into continuous ranges
    missing_date_ranges = []
    range_start = missing_dates[0]
    range_end = missing_dates[0]

    for current_date in missing_dates[1:]:
        if current_date == range_end + timedelta(days=1):
            # Dates are continuous
            range_end = current_date
        else:
            # Gap detected, save the current range
            missing_date_ranges.append(
                (
                    datetime.combine(range_start, datetime.min.time()),
                    datetime.combine(range_end, datetime.max.time()),
                )
            )
            # Start a new range
            range_start = current_date
            range_end = current_date

    # Add the last range
    missing_date_ranges.append(
        (
            datetime.combine(range_start, datetime.min.time()),
            datetime.combine(range_end, datetime.max.time()),
        )
    )

    return missing_date_ranges
