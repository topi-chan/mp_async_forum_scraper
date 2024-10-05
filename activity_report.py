import pandas as pd


def read_activity_csv(file_path: str) -> pd.DataFrame:
    """
    Reads the activity summary CSV file.

    Args:
        file_path (str): Path to the CSV file.

    Returns:
        pd.DataFrame: DataFrame containing the activity data.
    """
    try:
        df = pd.read_csv(file_path)
        # Ensure the columns are as expected
        expected_columns = ["Moderator", "Action", "Count"]
        if not all(column in df.columns for column in expected_columns):
            raise ValueError(f"CSV file must contain columns: {expected_columns}")
        return df
    except Exception as e:
        print(f"Error reading the CSV file: {e}")
        exit(1)


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
    Preprocesses the 'Action' column to extract base action types.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: DataFrame with an updated 'Base Action' column.
    """
    df["Base Action"] = df["Action"].apply(extract_base_action)
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
    summary = summary.rename(columns={"Count": "Total Count"})
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
        index="Moderator",
        columns="Base Action",
        values="Count",
        aggfunc="sum",
        fill_value=0,
    )
    pivot = pivot.reset_index()
    return pivot


def summarize_specific_activities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarizes specific actions performed by each moderator.

    Args:
        df (pd.DataFrame): DataFrame containing the activity data.

    Returns:
        pd.DataFrame: DataFrame with specific actions per moderator.
    """
    specific_summary = df.groupby(["Moderator", "Action"])["Count"].sum().reset_index()
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
    # Path to your CSV file
    csv_file_path = "activity_summary.csv"  # Update this path if necessary

    # Read the CSV file
    df = read_activity_csv(csv_file_path)

    # Preprocess the 'Action' column to extract base action types
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

    # Save the Markdown Tables to Files (Optional)
    save_markdown(markdown_total_activities, "total_activities_per_user.md")
    save_markdown(markdown_total_actions, "total_actions.md")
    save_markdown(markdown_actions_per_user, "actions_per_user.md")
    save_markdown(markdown_specific_activities, "specific_activities_by_moderator.md")

    # Additionally, save the detailed activities to a CSV file if needed
    # Here, we save the preprocessed DataFrame with 'Base Action'
    df.to_csv("activities_detailed.csv", index=False, encoding="utf-8-sig")
    print("Detailed activities saved to 'activities_detailed.csv'.")


if __name__ == "__main__":
    main()
