import os
from datetime import datetime
from typing import Optional

import pandas as pd
from pymongo import MongoClient


def connect_to_mongodb(uri: str, db_name: str, collection_name: str):
    """
    Connect to MongoDB and return the collection.

    Args:
        uri (str): MongoDB connection URI.
        db_name (str): Name of the database.
        collection_name (str): Name of the collection.

    Returns:
        pymongo.collection.Collection: The MongoDB collection.
    """
    client = MongoClient(uri)
    db = client[db_name]
    collection = db[collection_name]
    return collection


def fetch_activities_from_db(
    collection,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    """
    Fetch activities from MongoDB within the specified date range.

    Args:
        collection (pymongo.collection.Collection): The MongoDB collection.
        start_date (datetime, optional): Start date for filtering.
        end_date (datetime, optional): End date for filtering.

    Returns:
        list: List of activity documents.
    """
    query = {}
    if start_date and end_date:
        query = {"date": {"$gte": start_date, "$lte": end_date}}
    elif start_date:
        query = {"date": {"$gte": start_date}}
    elif end_date:
        query = {"date": {"$lte": end_date}}
    else:
        pass  # Fetch all data

    activities_cursor = collection.find(query)
    activities_list = list(activities_cursor)
    return activities_list


def activities_to_dataframe(activities_list):
    """
    Convert activities list to pandas DataFrame.

    Args:
        activities_list (list): List of activity documents.

    Returns:
        pd.DataFrame: DataFrame containing the activities.
    """
    if not activities_list:
        return pd.DataFrame()  # Return empty DataFrame if no data

    # Normalize MongoDB documents to DataFrame
    df = pd.json_normalize(activities_list)

    # Ensure required columns are present
    expected_columns = ["moderator", "action", "date"]
    missing_columns = [col for col in expected_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing expected columns in data: {missing_columns}")

    return df


def extract_base_action(action: str) -> str:
    """
    Extracts the base action type from the action string.

    Args:
        action (str): The full action string.

    Returns:
        str: The base action type.
    """
    # Define possible base actions
    base_actions = [
        "Edytowano post",
        "Odrzucono post",
        "Odrzucono temat",
        "Połączono posty",
        "Usunięto post",
        "Usunięto zgłoszenie",
        "Zaakceptowano post",
        "Zamknięto zgłoszenie",
        "Wysłano ostrzeżenie",
        "Zablokowano użytkownika",
        "Przeniesiono temat",
    ]

    action = action.strip()
    for base_action in base_actions:
        if action.startswith(base_action):
            return base_action
    return "Inne akcje"  # For any other actions not listed


def preprocess_actions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Preprocesses the 'action' column to extract base action types.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: DataFrame with an updated 'Base Action' column.
    """
    df["Base Action"] = df["action"].apply(extract_base_action)
    df["Count"] = 1  # Add a Count column for aggregation
    return df


def summarize_activities_per_user(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarizes the total number of activities per moderator.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: DataFrame with total activities per moderator.
    """
    summary = df.groupby("Moderator")["Count"].sum().reset_index()
    summary = summary.rename(columns={"Count": "Total Activities"})
    # Sort by Total Activities descending
    summary = summary.sort_values(by="Total Activities", ascending=False)
    return summary


def summarize_all_actions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarizes the total number of each action type across all moderators.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: DataFrame with total counts per action type.
    """
    summary = df.groupby("Action Type")["Count"].sum().reset_index()
    summary = summary.rename(columns={"Count": "Total Count"})
    # Sort by Total Count descending
    summary = summary.sort_values(by="Total Count", ascending=False)
    return summary


def summarize_specific_activities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarizes specific actions performed by each moderator.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: DataFrame with specific actions per moderator.
    """
    specific_summary = (
        df.groupby(["Action Type", "Moderator"])["Count"].sum().reset_index()
    )
    # Sort for presentation
    specific_summary = specific_summary.sort_values(
        by=["Action Type", "Count", "Moderator"], ascending=[True, False, True]
    )
    return specific_summary


def generate_forum_table(
    df: pd.DataFrame, headers: list[str], columns: list[str]
) -> str:
    """
    Generate a forum-formatted table from a DataFrame.

    Args:
        df (pd.DataFrame): The DataFrame to convert.
        headers (list[str]): The list of headers for the table.
        columns (list[str]): The list of column names in the DataFrame to include.

    Returns:
        str: Forum-formatted table as a string.
    """
    table_str = "[table]\n"
    # Add header row if needed (commented out in the example)
    # table_str += "[tr]" + "".join(f"[td][b]{header}[/b][/td]" for header in headers) + "[/tr]\n"
    for _, row in df.iterrows():
        table_str += (
            "[tr]" + "".join(f"[td]{row[col]}[/td]" for col in columns) + "[/tr]\n"
        )
    table_str += "[/table]\n"
    return table_str


def generate_forum_list(df: pd.DataFrame, action_type: str) -> str:
    """
    Generate a forum-formatted list for a specific action type.

    Args:
        df (pd.DataFrame): DataFrame containing the action data.
        action_type (str): The action type to generate the list for.

    Returns:
        str: Forum-formatted list as a string.
    """
    list_str = f"[b]{action_type}:[/b]\n[list]\n"
    action_df = df[df["Action Type"] == action_type]
    for _, row in action_df.iterrows():
        list_str += f"[*]{row['Moderator']} - {int(row['Count'])}\n"
    list_str += "[/list]\n"
    return list_str


def main():
    # MongoDB connection parameters
    uri = os.environ.get("MONGO_URL", "mongodb://mongodb:27017/")
    db_name = os.environ.get("DB_NAME", "scraper_db")
    collection_name = "activities"

    # Connect to MongoDB
    collection = connect_to_mongodb(uri, db_name, collection_name)

    # Define date range if needed
    # start_date = datetime(2024, 10, 1)
    # end_date = datetime(2024, 10, 31)

    # Fetch activities from MongoDB
    activities_list = fetch_activities_from_db(
        collection
    )  # Add start_date, end_date if needed

    if not activities_list:
        print("No activities found.")
        return

    # Convert activities to DataFrame
    df = activities_to_dataframe(activities_list)

    # Preprocess the 'action' column to extract base action types
    df = preprocess_actions(df)

    # Rename columns for consistency
    df = df.rename(columns={"moderator": "Moderator", "Base Action": "Action Type"})

    # Generate Summaries
    total_activities_per_user = summarize_activities_per_user(df)
    total_actions = summarize_all_actions(df)
    specific_activities = summarize_specific_activities(df)

    # Generate Forum-Formatted Output
    forum_output = ""

    # Total Activities per Moderator
    forum_output += "[b]Całkowita liczba działań per Moderator[/b]\n"
    forum_output += generate_forum_table(
        total_activities_per_user,
        headers=["Moderator", "Total Activities"],
        columns=["Moderator", "Total Activities"],
    )
    forum_output += "\n"

    # Total Activities per Action Type
    forum_output += "[b]Całkowita liczba działań per Typ Akcji[/b]\n"
    forum_output += generate_forum_table(
        total_actions,
        headers=["Action Type", "Total Count"],
        columns=["Action Type", "Total Count"],
    )
    forum_output += "\n"

    # Specific Activities by Moderator
    # For each action type, generate a list
    action_types = total_actions["Action Type"].tolist()
    for action_type in action_types:
        forum_output += generate_forum_list(specific_activities, action_type)
        forum_output += "\n"

    # Save the forum output to a file
    output_dir = "results"
    os.makedirs(output_dir, exist_ok=True)
    forum_output_file = os.path.join(output_dir, "forum_summary.txt")
    with open(forum_output_file, "w", encoding="utf-8") as f:
        f.write(forum_output)
    print(f"Forum summary saved to '{forum_output_file}'.")

    # Here, we save the preprocessed DataFrame with 'Action Type'
    df.to_csv(
        os.path.join(output_dir, "activities_detailed.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    print("Detailed activities saved to 'activities_detailed.csv'.")


if __name__ == "__main__":
    main()
