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
        "Wysłano ostrzeżenie użytkownikowi",
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
    summary = df.groupby("moderator")["Count"].sum().reset_index()
    summary = summary.rename(
        columns={"moderator": "Moderator", "Count": "Total Activities"}
    )
    return summary


def summarize_all_actions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarizes the total number of each action type across all moderators.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: DataFrame with total counts per action type.
    """
    summary = df.groupby("Base Action")["Count"].sum().reset_index()
    summary = summary.rename(
        columns={"Base Action": "Action Type", "Count": "Total Count"}
    )
    return summary


def summarize_actions_per_user(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarizes the number of each action type performed by each moderator.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: Pivot table with action types as columns and moderators as rows.
    """
    pivot = df.pivot_table(
        index="moderator",
        columns="Base Action",
        values="Count",
        aggfunc="sum",
        fill_value=0,
    )
    pivot = pivot.reset_index()
    pivot = pivot.rename(columns={"moderator": "Moderator"})
    return pivot


def summarize_specific_activities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarizes specific actions performed by each moderator.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: DataFrame with specific actions per moderator.
    """
    specific_summary = df.groupby(["moderator", "action"])["Count"].sum().reset_index()
    specific_summary = specific_summary.rename(
        columns={"moderator": "Moderator", "action": "Action"}
    )
    return specific_summary


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    """
    Converts a DataFrame to a Markdown-formatted table without using 'tabulate'.

    Args:
        df (pd.DataFrame): The DataFrame to convert.

    Returns:
        str: Markdown-formatted table as a string.
    """
    # Convert DataFrame to list of lists
    data = df.values.tolist()
    # Get the headers
    headers = df.columns.tolist()

    # Calculate the width of each column
    col_widths = [len(str(header)) for header in headers]
    for row in data:
        for idx, item in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(item)))

    # Create the header row
    header_row = (
        "| "
        + " | ".join(
            [f"{headers[i].ljust(col_widths[i])}" for i in range(len(headers))]
        )
        + " |"
    )
    # Create the separator row
    separator_row = (
        "|-" + "-|-".join(["-" * col_widths[i] for i in range(len(headers))]) + "-|"
    )
    # Create the data rows
    data_rows = []
    for row in data:
        data_row = (
            "| "
            + " | ".join(
                [f"{str(row[i]).ljust(col_widths[i])}" for i in range(len(row))]
            )
            + " |"
        )
        data_rows.append(data_row)

    # Combine all rows
    markdown_table = "\n".join([header_row, separator_row] + data_rows)
    return markdown_table


def save_markdown(markdown_str: str, file_name: str):
    """
    Saves a Markdown string to a file.

    Args:
        markdown_str (str): The Markdown content.
        file_name (str): The name of the file to save.
    """
    try:
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(markdown_str)
        print(f"Markdown table saved to '{file_name}'.")
    except Exception as e:
        print(f"Error saving Markdown file: {e}")


def main():
    # MongoDB connection parameters
    uri = os.environ.get("MONGO_URL", "mongodb://mongodb:27017/")
    db_name = os.environ.get("DB_NAME", "scraper_db")
    collection_name = "activities"

    # Connect to MongoDB
    collection = connect_to_mongodb(uri, db_name, collection_name)

    # Define date range if needed
    # start_date = datetime(2024, 11, 1)
    # end_date = datetime(2024, 11, 8)

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

    # Generate Summaries
    total_activities_per_user = summarize_activities_per_user(df)
    total_actions = summarize_all_actions(df)
    actions_per_user = summarize_actions_per_user(df)
    specific_activities = summarize_specific_activities(df)

    # Convert Summaries to Markdown
    markdown_total_activities = dataframe_to_markdown(total_activities_per_user)
    markdown_total_actions = dataframe_to_markdown(total_actions)
    markdown_actions_per_user = dataframe_to_markdown(actions_per_user)
    markdown_specific_activities = dataframe_to_markdown(specific_activities)

    # Display the Markdown Tables
    print("\n### Total Activities per Moderator\n")
    print(markdown_total_activities)

    print("\n### Total Counts per Action Type\n")
    print(markdown_total_actions)

    print("\n### Actions per Moderator\n")
    print(markdown_actions_per_user)

    print("\n### Specific Activities by Moderator\n")
    print(markdown_specific_activities)

    # Save the Markdown Tables to Text Files
    output_dir = "results"
    os.makedirs(output_dir, exist_ok=True)
    save_markdown(
        markdown_total_activities,
        os.path.join(output_dir, "total_activities_per_user.txt"),
    )
    save_markdown(markdown_total_actions, os.path.join(output_dir, "total_actions.txt"))
    save_markdown(
        markdown_actions_per_user, os.path.join(output_dir, "actions_per_user.txt")
    )
    save_markdown(
        markdown_specific_activities,
        os.path.join(output_dir, "specific_activities_by_moderator.txt"),
    )

    # Additionally, save the detailed activities to a CSV file if needed
    # Here, we save the preprocessed DataFrame with 'Base Action'
    df.to_csv(
        os.path.join(output_dir, "activities_detailed.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    print("Detailed activities saved to 'activities_detailed.csv'.")


if __name__ == "__main__":
    main()
