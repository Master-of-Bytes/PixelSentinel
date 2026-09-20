"""
Program Name: PixelSentinel Management (c) Larry Zande

Description: This program is used for group/album management for the PixelSentinel program. It's
a helper program that lets you add/remove groups, group members, and albums to control
who gets alert messages.

Date: 12/29/2024
V2: 9/13/2026 - Push alert system
"""
import os
import sys
import sqlite3
import secrets
import hashlib
import time

from datetime import datetime, timedelta, timezone

try:
    import pandas as pd
except ModuleNotFoundError:
    print(f"The module pandas is not found. Please install with 'pip install pandas.'")
    exit(1)
    
try:
    import qrcode
except ModuleNotFoundError:
    print(
        "The module qrcode is not found. "
        "Please install with 'pip install qrcode.'"
    )
    exit(1)

# Configuration
db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pixelsentinel.db')

ENROLLMENT_BASE_URL = (
    "https://zandecloud.synology.me:8443/enroll"
)

INVITE_LIFETIME_HOURS = 24
REMOVAL_LIFETIME_MINUTES = 15
REMOVAL_PUSH_TTL_SECONDS = 900
REMOVAL_ACK_WAIT_SECONDS = 15

def db_execute(query, params=(), fetch=False):
    connection = sqlite3.connect(db_file)
    connection.execute("PRAGMA foreign_keys = ON")
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        if fetch:
            return cursor.fetchall()
        connection.commit()
    except sqlite3.Error as e:
        connection.rollback()  # Rollback in case of error
        raise ValueError(f"An error occurred while executing the query: {query} : error: {e}")
    finally:
        cursor.close()
        connection.close()

def initialize_membership_tables():
    try:
        db_execute('''
            CREATE TABLE IF NOT EXISTS members (
                member_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );
        ''')

        db_execute('''
            CREATE TABLE IF NOT EXISTS member_groups (
                member_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,

                PRIMARY KEY (member_id, group_id),

                FOREIGN KEY (member_id)
                    REFERENCES members(member_id)
                    ON DELETE CASCADE,

                FOREIGN KEY (group_id)
                    REFERENCES groups(group_id)
                    ON DELETE CASCADE
            );
        ''')

    except ValueError as e:
        print(f"Error initializing membership tables: {e}")

def initialize_push_removal_tables():
    """
    Initialize database objects used for secure
    remote push-subscription removal.
    """

    try:

        db_execute(
            '''
            CREATE TABLE IF NOT EXISTS
                subscription_removals
            (
                removal_id INTEGER
                    PRIMARY KEY AUTOINCREMENT,

                subscription_id INTEGER
                    NOT NULL
                    UNIQUE,

                token_hash TEXT
                    NOT NULL
                    UNIQUE,

                requested_at TEXT
                    NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                expires_at TEXT
                    NOT NULL,

                attempt_count INTEGER
                    NOT NULL
                    DEFAULT 0,

                last_attempt_at TEXT,

                last_error TEXT,

                FOREIGN KEY (
                    subscription_id
                )
                    REFERENCES push_subscriptions(
                        subscription_id
                    )
                    ON DELETE CASCADE
            );
            '''
        )


        db_execute(
            '''
            CREATE INDEX IF NOT EXISTS
                idx_subscription_removals_subscription

            ON subscription_removals (
                subscription_id
            );
            '''
        )


    except ValueError as e:

        print(
            "Error initializing push removal "
            f"tables: {e}"
        )

# Main menu
def main_menu():
    while True:
        print('*' * 21)
        print('***** Main Menu *****')
        print('*' * 21)
        print('Select an option from menu:')
        print('\n Key  Menu Option:                 Description:')
        print('---  ------------                  ------------')
        print(' 1 - Add Group                   Adds a new group')
        print(' 2 - Remove Group                Removes a group')
        print(' 3 - Add Group Member            Adds a new member to a group')
        print(' 4 - Remove Group Member         Removes a member from a group')
        print(' 5 - Add Album                   Adds a new album')
        print(' 6 - Update Album/Group Link     Update the link between an album and a group')
        print(' 7 - Duplicate Album             Duplicate an existing album to a new group')
        print(' P - Push Management             Manage push enrollment and devices')
        print(' R - Create Report               Creates a system report')
        menu_choice = input('\nPress a key for item selection or press X to exit: ').strip().upper()

        # Case equivalent using a dictionary
        menu_actions = {
            '1': add_group,
            '2': remove_group,
            '3': add_group_member,
            '4': remove_group_member,
            '5': add_album,
            '6': update_album,
            '7': duplicate_album,
            'P': push_management_menu,
            'R': create_report
        }

        if menu_choice in menu_actions:
            menu_actions[menu_choice]()  # Call the appropriate function
        elif menu_choice == 'X':
            print("\nExiting the program.\n")
            break

# Add Group
def add_group():
    try:
        db_execute('''
        CREATE TABLE IF NOT EXISTS groups (
        group_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
        );
        ''')
    except ValueError as e:
        print(f"Error creating the table: {e}")
        return

    while True:
        group_name = input("Enter a name for the new group (or type 'X' to exit): ").strip()

        # Allow the user to exit
        if group_name.upper() == 'X':
            break

        try:
            # Check if the group name already exists
            existing_group = db_execute('''
                SELECT name FROM groups WHERE name = ?
                ''', (group_name,), fetch=True)

            if existing_group:
                print(f"The group name '{group_name}' already exists.\n")
            else:
                # Insert the group name
                db_execute('''
                    INSERT INTO groups (name)
                    VALUES (?)
                    ''', (group_name,))
                print(f"Group '{group_name}' added successfully.\n")
        except ValueError as e:
            print(f"Error interacting with the database: {e}")

# Get Groups
def get_groups_with_id_name():
    try:
        # List all groups with IDs
        existing_groups = db_execute('''
                SELECT group_id, name FROM groups
                ''', fetch=True)

        if not existing_groups:
            print("No groups found.\n")
            return
        else:
            return existing_groups
    except ValueError as e:
        print(f"Error interacting with the database: {e}")
        return

# Remove Group
def remove_group():
    while True:
        existing_groups = get_groups_with_id_name()  # Display current groups

        print("\nGroup ID     Name")
        print("--------     -----")
        for group_id, name in existing_groups:
            print(f"{group_id:<10} {name}")

        # Allow the user to remove a group
        try:
            group_id_to_remove = input("\nEnter the Group ID to remove (or type 'X' to cancel): ")

            if group_id_to_remove.strip().upper() == 'X':
                print("Group removal process canceled.\n")
                return

            # Check if the group ID exists in the database
            valid_group = db_execute('''
            SELECT group_id FROM groups WHERE group_id = ?
            ''', (group_id_to_remove,), fetch=True)

            if not valid_group:
                print(f"Group ID {group_id_to_remove} does not exist. Please enter a valid Group ID.\n")
                continue  # Prompt the user to try again

            # Attempt to remove the selected group
            db_execute('''
                DELETE FROM groups WHERE group_id = ?
                ''', (group_id_to_remove,))
            print(f"Group with ID {group_id_to_remove} removed successfully.\n")
        except ValueError as e:
            print(f"Error while removing the group: {e}")

# Add Group Member
def add_group_member():
    while True:
        existing_groups = get_groups_with_id_name()

        if not existing_groups:
            print("No groups found.\n")
            return

        print("\nGroup ID     Name")
        print("--------     ----")

        for group_id, name in existing_groups:
            print(f"{group_id:<12} {name}")

        group_id = input(
            "\nEnter the Group ID to add a member to "
            "(or type 'X' to cancel): "
        ).strip()

        if group_id.upper() == "X":
            print("Add group member process canceled.\n")
            return

        valid_group = db_execute(
            '''
            SELECT group_id
            FROM groups
            WHERE group_id = ?
            ''',
            (group_id,),
            fetch=True
        )

        if not valid_group:
            print(f"Group ID {group_id} does not exist.\n")
            continue

        members = get_all_members()

        print("\nExisting Members:")
        print("Member ID     Name")
        print("---------     ----")

        for member_id, name in members:
            print(f"{member_id:<13} {name}")

        print("\nN - Create a new member")

        choice = input(
            "\nEnter Member ID, N for new member, "
            "or X to cancel: "
        ).strip()

        if choice.upper() == "X":
            return

        if choice.upper() == "N":
            member_name = input(
                "Enter the new member's name: "
            ).strip()

            if not member_name:
                print("Member name cannot be empty.\n")
                continue

            # Prevent accidental duplicate people.
            duplicate = db_execute(
                '''
                SELECT member_id, name
                FROM members
                WHERE LOWER(name) = LOWER(?)
                ''',
                (member_name,),
                fetch=True
            )

            if duplicate:
                print(
                    f"\nA member named '{member_name}' already exists."
                )
                print(
                    "Use the existing Member ID instead of "
                    "creating another record.\n"
                )
                continue

            db_execute(
                '''
                INSERT INTO members (name)
                VALUES (?)
                ''',
                (member_name,)
            )

            result = db_execute(
                '''
                SELECT member_id
                FROM members
                WHERE name = ?
                ORDER BY member_id DESC
                LIMIT 1
                ''',
                (member_name,),
                fetch=True
            )

            member_id = result[0][0]

        else:
            if not choice.isdigit():
                print("Invalid Member ID.\n")
                continue

            member_id = int(choice)

            valid_member = db_execute(
                '''
                SELECT member_id, name
                FROM members
                WHERE member_id = ?
                ''',
                (member_id,),
                fetch=True
            )

            if not valid_member:
                print(f"Member ID {member_id} does not exist.\n")
                continue

            member_name = valid_member[0][1]

        existing_link = db_execute(
            '''
            SELECT member_id
            FROM member_groups
            WHERE member_id = ?
              AND group_id = ?
            ''',
            (member_id, group_id),
            fetch=True
        )

        if existing_link:
            print(
                f"\n{member_name} is already a member "
                f"of Group {group_id}.\n"
            )
            return

        db_execute(
            '''
            INSERT INTO member_groups (
                member_id,
                group_id
            )
            VALUES (?, ?)
            ''',
            (member_id, group_id)
        )

        print(
            f"\n{member_name} successfully added "
            f"to Group {group_id}.\n"
        )

        return

# Get Current members of a selected group
def get_members(group_id):
    try:
        existing_members = db_execute(
            '''
            SELECT
                members.member_id,
                members.name
            FROM members
            JOIN member_groups
                ON members.member_id = member_groups.member_id
            WHERE member_groups.group_id = ?
            ORDER BY members.name
            ''',
            (group_id,),
            fetch=True
        )

        return existing_members or []

    except ValueError as e:
        print(f"Error interacting with the database: {e}")
        return []

# Get all members
def get_all_members():
    try:
        members = db_execute(
            '''
            SELECT member_id, name
            FROM members
            ORDER BY name
            ''',
            fetch=True
        )

        return members or []

    except ValueError as e:
        print(f"Error retrieving members: {e}")
        return []

# Push Notification Management Menu
def push_management_menu():
    while True:

        print()
        print('*' * 32)
        print('***** Push Management Menu *****')
        print('*' * 32)

        print(
            '\n Key  Menu Option:                 '
            'Description:'
        )

        print(
            '---  ------------                  '
            '------------'
        )

        print(
            ' 1 - Create Enrollment Invite     '
            'Creates a private device invite'
        )

        print(
            ' 2 - Manage Pending Invites       '
            'Lists and revokes unused invites'
        )

        print(
            ' 3 - Registered Devices           '
            'Lists registered push devices'
        )

        print(
            ' 4 - Enable/Disable Device        '
            'Changes device notification status'
        )

        print(
            ' 5 - Remove Device                '
            'Remotely removes a push device'
        )

        print(
            ' X - Return to Main Menu          '
            'Returns to the main menu'
        )

        menu_choice = input(
            '\nPress a key for item selection: '
        ).strip().upper()

        if menu_choice == '1':

            create_enrollment_invite()

        elif menu_choice == '2':

            manage_pending_invites()

        elif menu_choice == '3':

            registered_devices()

        elif menu_choice == '4':

            manage_device_status()

        elif menu_choice == '5':

            remove_registered_device()

        elif menu_choice == 'X':

            return

# Remove Group Member
def remove_group_member():
    while True:
        existing_groups = get_groups_with_id_name()

        if not existing_groups:
            print("No groups found.\n")
            return

        print("\nGroup ID     Name")
        print("--------     ----")

        for group_id, name in existing_groups:
            print(f"{group_id:<12} {name}")

        member_group = input(
            "\nEnter the Group ID to remove a member from "
            "(or type 'X' to cancel): "
        ).strip()

        if member_group.upper() == "X":
            return

        valid_group = db_execute(
            '''
            SELECT group_id
            FROM groups
            WHERE group_id = ?
            ''',
            (member_group,),
            fetch=True
        )

        if not valid_group:
            print(f"Group ID {member_group} does not exist.\n")
            continue

        existing_members = get_members(member_group)

        if not existing_members:
            print("\nNo members are assigned to this group.\n")
            return

        print("\nMember ID     Name")
        print("---------     ----")

        for member_id, name in existing_members:
            print(f"{member_id:<13} {name}")

        member_id = input(
            "\nEnter Member ID to remove from this group "
            "(or X to cancel): "
        ).strip()

        if member_id.upper() == "X":
            return

        valid_member = db_execute(
            '''
            SELECT members.name
            FROM member_groups
            JOIN members
                ON member_groups.member_id = members.member_id
            WHERE member_groups.member_id = ?
              AND member_groups.group_id = ?
            ''',
            (member_id, member_group),
            fetch=True
        )

        if not valid_member:
            print(
                f"Member ID {member_id} is not in "
                f"Group {member_group}.\n"
            )
            continue

        member_name = valid_member[0][0]

        db_execute(
            '''
            DELETE FROM member_groups
            WHERE member_id = ?
              AND group_id = ?
            ''',
            (member_id, member_group)
        )

        print(
            f"\n{member_name} removed from "
            f"Group {member_group}.\n"
        )

        return

# Add a new album
def add_album():
    while True:
        try:
            new_album_name = input("\nEnter the name of the new album to add (or type 'X' to cancel): ")

            if new_album_name.strip().upper() == 'X':
                print("Add album process canceled.\n")
                break

            # Check if the new album exists in the database
            invalid_album = db_execute( '''
                            SELECT name FROM albums WHERE name = ?
                            ''', (new_album_name,), fetch=True)

            if invalid_album:
                print(f"Album {new_album_name} already exists. Please try again.\n")
                continue  # Prompt the user to try again
            else:
                existing_groups = get_groups_with_id_name()  # Display current groups
                print("\nGroup ID     Name")
                print("--------     -----")
                for group_id, name in existing_groups:
                    print(f"{group_id:<10} {name}")
            album_group = input("\nEnter the Group ID for the new album (or type 'X' to cancel): ")

            if album_group.strip().upper() == 'X':
                print("Add album process canceled.\n")
                return

            # Check if the group ID exists in the database
            valid_group = db_execute( '''
                            SELECT group_id FROM groups WHERE group_id = ?
                            ''', (album_group,), fetch=True)

            if not valid_group:
                print(f"Group ID {album_group} does not exist. Please enter a valid Group ID.\n")
                continue  # Prompt the user to try again

            # Insert the new album into the albums table
            db_execute( '''
            INSERT INTO albums (name, group_id)
            VALUES (?, ?)
            ''', (new_album_name, album_group,))
            print(f"Album {new_album_name} added successfully to group {album_group}.\n")
            break
        except ValueError as e:
            print(f"Error while adding the new album: {e}")

# Get current albums with group names
def get_albums_with_group():
    # Fetch existing album names with group name
    albums = db_execute('''
            SELECT albums.album_id, albums.name, groups.name
            FROM albums
            JOIN groups ON groups.group_id = albums.group_id
            ORDER BY albums.name ASC
            ''', fetch=True)
    return albums

def get_albums_with_id():
    # Fetch existing album names with their id
    albums = db_execute('''
            SELECT album_id, name
            FROM albums
            ORDER BY albums.name ASC
            ''', fetch=True)
    return albums

# Update Album/Group linkage
def update_album():
    current_albums = get_albums_with_group()

    # Define headers
    headers = ['Album ID', 'Album Name', 'Group Name']

    # Create DataFrame
    df = pd.DataFrame(current_albums, columns=headers)

    # Show the full DataFrame
    pd.set_option('display.max_rows', None)  # To display all rows
    pd.set_option('display.max_columns', None)  # To display all columns
    pd.set_option('display.width', None)  # To adjust the width to the terminal size
    pd.set_option('display.max_colwidth', None)  # To show full column content

    # Print the DataFrame without the index and with equal column spacing
    while True:
        print("\nExisting Albums:")
        print(df.to_string(index=False, col_space=20))

        # Allow the user to update an album/group linkage
        try:
            album_to_update = input("\nEnter the Album ID to update (or type 'X' to cancel): ")

            if album_to_update.strip().upper() == 'X':
                print("Update album process canceled.\n")
                return

            # Check if the album ID exists in the database
            valid_album = db_execute('''
                    SELECT album_id FROM albums WHERE album_id = ?
                    ''', (album_to_update,), fetch=True)

            if not valid_album:
                print(f"Album ID {album_to_update} does not exist. Please enter a valid Album ID.\n")
                continue  # Prompt the user to try again

            # Display current groups
            existing_groups = get_groups_with_id_name()  # Display current groups

            print("\nGroup ID     Name")
            print("--------     -----")
            for group_id, name in existing_groups:
                print(f"{group_id:<10} {name}")

            new_group_id = input("\nEnter the  new Group ID for the album (or type 'X' to cancel): ")

            if new_group_id.strip().upper() == 'X':
                print("Update album process canceled.\n")
                return

            # Check if the group ID exists in the database
            valid_id = db_execute('''
                        SELECT group_id FROM groups WHERE group_id = ?
                        ''', (new_group_id), fetch=True)

            if not valid_id:
                print(f"Group ID {new_group_id} does not exist.\n")
                continue  # Prompt the user to try again

            # Update the selected album group
            db_execute('''
                        UPDATE albums SET group_id = ? WHERE album_id = ?
                        ''', (new_group_id, album_to_update))
            print(f"Album with ID {album_to_update} successfully updated with Group ID {new_group_id}.\n")
            break  # Exit the loop after successful

        except ValueError as e:
            print(f"Error while updating album group id: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

def duplicate_album():
    current_albums = get_albums_with_id()

    # Define headers
    headers = ['Album ID', 'Album Name']

    # Create DataFrame
    df = pd.DataFrame(current_albums, columns=headers)

    # Show the full DataFrame
    pd.set_option('display.max_rows', None)  # To display all rows
    pd.set_option('display.max_columns', None)  # To display all columns
    pd.set_option('display.width', None)  # To adjust the width to the terminal size
    pd.set_option('display.max_colwidth', None)  # To show full column content

    # Print the DataFrame without the index and with equal column spacing
    while True:
        print("\nExisting Albums:")
        print(df.to_string(index=False, col_space=20))

        # Allow the user to duplicate an album with a new group linkage
        try:
            album_to_duplicate = input("\nEnter the Album ID to duplicate (or type 'X' to cancel): ").strip()

            if album_to_duplicate.upper() == 'X':
                print("Duplicate album process canceled.\n")
                return

            # Check if the album ID exists in the database
            valid_album = db_execute(
                '''
                SELECT album_id FROM albums WHERE album_id = ?
                ''',
                (album_to_duplicate,),
                fetch=True
            )

            if not valid_album:
                print(f"Album ID {album_to_duplicate} does not exist. Please enter a valid Album ID.\n")
                continue

            # Fetch the album name
            album_name_result = db_execute(
                '''
                SELECT name FROM albums WHERE album_id = ?
                ''',
                (album_to_duplicate,),
                fetch=True
            )

            if not album_name_result:
                print("Failed to retrieve album name. Please try again.")
                continue

            album_name = album_name_result[0][0]

            existing_groups = get_groups_with_id_name()  # Display current groups

            print("\nGroup ID     Name")
            print("--------     -----")
            for group_id, name in existing_groups:
                print(f"{group_id:<10} {name}")

            new_group_id = input("\nEnter the new Group ID for the album (or type 'X' to cancel): ").strip()

            if new_group_id.upper() == 'X':
                print("Duplicate album process canceled.\n")
                return

            # Check if the group ID exists in the database
            valid_group = db_execute(
                '''
                SELECT group_id FROM groups WHERE group_id = ?
                ''',
                (new_group_id,),
                fetch=True
            )

            if not valid_group:
                print(f"Group ID {new_group_id} does not exist. Please enter a valid Group ID.\n")
                continue

            # Duplicate the selected album
            db_execute(
                '''
                INSERT INTO albums (name, group_id)
                VALUES (?, ?)
                ''',
                (album_name, new_group_id)
            )
            print(f"Album '{album_name}' successfully duplicated with Group ID {new_group_id}.\n")
            break

        except ValueError as e:
            print(f"Error while duplicating album: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

# Get total files
def get_total_files():
    try:
        result = db_execute(
            '''
            SELECT COUNT(*) FROM files
            ''',
            fetch=True
        )

        # Extract the count from the result (fetchall() returns a list of tuples)
        total_files_count = result[0][0] if result else 0  # Handle empty results

        # Format the count with commas
        formatted_total_files = f"{total_files_count:,}"

        return formatted_total_files
    except Exception as e:
        print(f"Error retrieving data: {e}")

# Get all group and member info
def get_all_group_membership():
    try:
        member_table = ""
        all_group_ids = db_execute(
            '''
            SELECT group_id FROM groups
            ''',
            fetch=True
        )
        # Extract group_ids using list comprehension
        group_ids_list = [group[0] for group in all_group_ids]
        for group_id in group_ids_list:
            group_name = db_execute('''
                            SELECT name from groups WHERE group_id = ?
                ''', (group_id,), fetch=True)
            group_name = f'<h1 style="text-align:center;">{group_name[0][0]}</h1>'

            # Get members of each group and convert to html
            group_members = db_execute(
                '''
                SELECT members.name
                FROM members
                JOIN member_groups
                    ON members.member_id = member_groups.member_id
                WHERE member_groups.group_id = ?
                ORDER BY members.name
                ''',
                (group_id,),
                fetch=True
            )

            headers = ["Member Name"]
            df = pd.DataFrame(group_members, columns=headers)
            member_table += group_name + df.to_html(index=False, border=1, justify="center")
        return member_table
    except Exception as e:
        print(f"Error retrieving data: {e}")

# Format and save report
def format_save_report(total_files,groups,membership,albums):
    # Save to an HTML file
    html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>PixelSentinel System Report</title>
            <style>
                body {{
                background-color: rgb(13 18 23);
                line-height: 1.452;
                color: #c7c7c7;
                }}
                table {{
                    width: 80%;
                    margin: 20px auto;
                    border-collapse: collapse;
                    font-family: Arial, sans-serif;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: center;
                    color: #c7c7c7;
                }}
                th {{
                    background-color: rgb(13 18 23);
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
        <br>
            <h1 style="text-align:center;">PixelSentinel System Report</h1>
            <br>
            {total_files}
            <br>
            <h1 style="text-align:center;">Group Information</h1>
            {groups}
            <br>
            <h1 style="text-align:center;">Membership Information</h1>
            {membership}
            <br>
            <h1 style="text-align:center;">Album Information</h1>
            {albums}
        </body>
        </html>
        """
    with open("PixelSentinelReport.html", "w", encoding="utf-8") as file:
        file.write(html_content)

# Creates a report
def create_report():
    # Get total files
    total_files = get_total_files()
    files_header = ["Total Files"]

    # Create a list for data frame
    data = [[total_files]]
    df = pd.DataFrame(data, columns=files_header)
    total_files_html = df.to_html(index=False, border=1, justify="center")

    # Create table of existing groups
    existing_groups = get_groups_with_id_name()
    group_headers = ["Group ID", "Group Name"]
    df = pd.DataFrame(existing_groups, columns=group_headers)
    existing_groups_html = df.to_html(index=False, border=1, justify="center")

    # Create table for each group with members
    membership_info_html = get_all_group_membership()

    # Create table of existing albums with group linkage
    existing_albums = get_albums_with_group()
    album_headers = ["Album ID","Album Name","Group Name"]
    df = pd.DataFrame(existing_albums,columns=album_headers)
    df = df.drop("Album ID", axis=1)
    existing_albums_html = df.to_html(index=False, border=1, justify="center")

    # Format and save the report
    format_save_report(total_files_html,existing_groups_html,membership_info_html,existing_albums_html)
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    print(f'System report saved to {report_path} with file name PixelSentinelReport.html')

def clear_sensitive_terminal():
    """
    Best-effort clearing of sensitive enrollment
    information from the terminal.

    ANSI-capable terminals will also be asked to clear
    their scrollback buffer.
    """

    if os.name == "nt":

        os.system("cls")

    else:

        sys.stdout.write(
            "\033[3J"
            "\033[2J"
            "\033[H"
        )

        sys.stdout.flush()
        
def display_enrollment_qr(
    member_name,
    enrollment_url,
    expires_at
):
    """
    Display a private PixelSentinel enrollment QR code
    directly in the terminal.

    The QR code is generated in memory and written only
    to stdout. No PNG, JPEG, SVG, or temporary image
    file is created.
    """

    qr = qrcode.QRCode(
        version=None,
        error_correction=
            qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=2
    )

    qr.add_data(
        enrollment_url
    )

    qr.make(
        fit=True
    )

    clear_sensitive_terminal()

    print()
    print('=' * 60)
    print('PIXELSENTINEL PRIVATE ENROLLMENT')
    print('=' * 60)

    print()
    print(
        f"Member: {member_name}"
    )

    print(
        f"Invite expires: {expires_at}"
    )

    print()
    print(
        "Scan this QR code with the device "
        "being enrolled:"
    )
    print()


    try:

        qr.print_ascii(
            out=sys.stdout,
            tty=True
        )

    except OSError:

        # Fallback for terminals that do not identify
        # themselves as a TTY.
        qr.print_ascii(
            out=sys.stdout,
            invert=True
        )


    print()
    print(
        "This QR code contains a private "
        "PixelSentinel enrollment credential."
    )

    print(
        "Do not photograph, screenshot, or share it."
    )


    while True:

        choice = input(
            "\nPress U to display the private URL, "
            "or press Enter when finished: "
        ).strip().upper()


        if choice == "":

            break


        if choice == "U":

            print()
            print("Private enrollment URL:")
            print()
            print(enrollment_url)
            print()

            input(
                "Press Enter when finished..."
            )

            break


        print(
            "Invalid selection. "
            "Press U or Enter."
        )


    clear_sensitive_terminal()

def create_enrollment_invite():
    """
    Create a single-use PixelSentinel enrollment invite.

    The raw token exists only long enough to display the
    enrollment QR/URL.

    Only the SHA-256 token hash is stored in SQLite.
    """

    members = get_all_members()

    if not members:

        print(
            "\nNo members are available.\n"
        )

        return


    while True:

        print()
        print("Existing Members:")
        print()
        print("Member ID     Name")
        print("---------     ----")

        for member_id, name in members:

            print(
                f"{member_id:<13} {name}"
            )


        choice = input(
            "\nEnter the Member ID to create "
            "an enrollment invite for "
            "(or X to cancel): "
        ).strip()


        if choice.upper() == "X":

            print(
                "\nEnrollment invite creation "
                "canceled.\n"
            )

            return


        if not choice.isdigit():

            print(
                "\nInvalid Member ID.\n"
            )

            continue


        member_id = int(
            choice
        )


        member = db_execute(
            '''
            SELECT
                member_id,
                name
            FROM members
            WHERE member_id = ?
            ''',
            (member_id,),
            fetch=True
        )


        if not member:

            print(
                f"\nMember ID {member_id} "
                "does not exist.\n"
            )

            continue


        member_name = member[0][1]

        break


    # Generate the private enrollment credential.
    token = secrets.token_urlsafe(
        32
    )


    # Store only a one-way SHA-256 representation.
    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


    expires_at = (
        datetime.now(
            timezone.utc
        )
        + timedelta(
            hours=INVITE_LIFETIME_HOURS
        )
    ).isoformat()


    connection = None
    invite_id = None


    try:

        connection = sqlite3.connect(
            db_file,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )


        cursor = connection.execute(
            '''
            INSERT INTO member_invites (
                member_id,
                token_hash,
                expires_at
            )
            VALUES (?, ?, ?)
            ''',
            (
                member_id,
                token_hash,
                expires_at
            )
        )


        invite_id = cursor.lastrowid

        connection.commit()


    except sqlite3.Error:

        if connection is not None:

            connection.rollback()


        print()
        print(
            "Unable to create the enrollment invite."
        )
        print()

        return


    finally:

        if connection is not None:

            connection.close()


    enrollment_url = (
        f"{ENROLLMENT_BASE_URL}/{token}"
    )


    try:

        display_enrollment_qr(
            member_name,
            enrollment_url,
            expires_at
        )


    except KeyboardInterrupt:

        clear_sensitive_terminal()

        print()
        print(
            "Enrollment display closed."
        )

        print(
            "The invitation remains active until "
            "it is used, expires, or is revoked."
        )
        print()

        return


    except Exception:

        clear_sensitive_terminal()

        # If PixelSentinel could not display the
        # credential at all, revoke the newly-created
        # invitation because the raw token cannot be
        # recovered later.

        try:

            db_execute(
                '''
                UPDATE member_invites
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE invite_id = ?
                  AND used_at IS NULL
                  AND revoked_at IS NULL
                ''',
                (invite_id,)
            )

        except ValueError:

            pass


        print()
        print(
            "The enrollment credential could not "
            "be displayed."
        )

        print(
            "The new invitation was revoked."
        )
        print()

        return


    finally:

        # Python cannot guarantee secure memory wiping
        # of immutable string objects, but PixelSentinel
        # deliberately stops retaining references to
        # the raw credential after display.
        token = None
        enrollment_url = None


    print()
    print(
        f"Enrollment invite {invite_id} "
        f"created for {member_name}."
    )

    print(
        "The private credential will not "
        "be displayed again."
    )
    print()

def get_pending_invites():
    """
    Return enrollment invitations that have not been
    successfully consumed.

    Raw tokens, token hashes, enrollment URLs, and QR
    data are deliberately excluded.
    """

    try:

        invites = db_execute(
            '''
            SELECT
                member_invites.invite_id,
                member_invites.member_id,
                members.name,
                member_invites.created_at,
                member_invites.expires_at,
                member_invites.revoked_at,

                CASE

                    WHEN member_invites.revoked_at
                         IS NOT NULL
                    THEN 'REVOKED'

                    WHEN datetime(
                        member_invites.expires_at
                    ) <= CURRENT_TIMESTAMP
                    THEN 'EXPIRED'

                    ELSE 'ACTIVE'

                END AS invite_status

            FROM member_invites

            JOIN members
                ON member_invites.member_id =
                   members.member_id

            WHERE member_invites.used_at IS NULL

            ORDER BY
                member_invites.created_at DESC,
                member_invites.invite_id DESC
            ''',
            fetch=True
        )

        return invites or []

    except ValueError as e:

        print(
            f"Error retrieving pending invites: {e}"
        )

        return []

def display_pending_invites(
    invites
):
    """
    Display non-consumed enrollment invitations.
    """

    print()
    print("Pending Enrollment Invites:")
    print()

    print(
        f"{'Invite ID':<11}"
        f"{'Member ID':<11}"
        f"{'Member':<20}"
        f"{'Status':<10}"
        f"{'Created':<22}"
        f"{'Expires':<32}"
    )

    print(
        f"{'-' * 9:<11}"
        f"{'-' * 9:<11}"
        f"{'-' * 18:<20}"
        f"{'-' * 8:<10}"
        f"{'-' * 20:<22}"
        f"{'-' * 30:<32}"
    )

    for (
        invite_id,
        member_id,
        member_name,
        created_at,
        expires_at,
        revoked_at,
        invite_status
    ) in invites:

        print(
            f"{invite_id:<11}"
            f"{member_id:<11}"
            f"{member_name:<20}"
            f"{invite_status:<10}"
            f"{created_at:<22}"
            f"{expires_at:<32}"
        )

def revoke_enrollment_invite(
    invite_id
):
    """
    Revoke an enrollment invite only if it has not
    already been used or revoked.

    Returns True only when a row was actually changed.
    """

    connection = None

    try:

        connection = sqlite3.connect(
            db_file,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )

        cursor = connection.execute(
            '''
            UPDATE member_invites

            SET revoked_at =
                CURRENT_TIMESTAMP

            WHERE invite_id = ?
              AND used_at IS NULL
              AND revoked_at IS NULL

            RETURNING invite_id
            ''',
            (invite_id,)
        )

        result = cursor.fetchone()

        if result is None:

            connection.rollback()

            return False

        connection.commit()

        return True

    except sqlite3.Error:

        if connection is not None:

            connection.rollback()

        print(
            "\nUnable to revoke the enrollment invite.\n"
        )

        return False

    finally:

        if connection is not None:

            connection.close()

def manage_pending_invites():
    """
    List non-consumed enrollment invites and allow an
    administrator to revoke an unused invitation.

    Raw tokens cannot be recovered or redisplayed.
    """

    while True:

        invites = get_pending_invites()

        if not invites:

            print(
                "\nNo pending enrollment invites found.\n"
            )

            return


        display_pending_invites(
            invites
        )


        print()
        print(
            "R - Revoke an enrollment invite"
        )

        print(
            "X - Return to Push Management"
        )


        choice = input(
            "\nSelect an option: "
        ).strip().upper()


        if choice == "X":

            return


        if choice != "R":

            print(
                "\nInvalid selection.\n"
            )

            continue


        invite_choice = input(
            "\nEnter the Invite ID to revoke "
            "(or X to cancel): "
        ).strip()


        if invite_choice.upper() == "X":

            continue


        if not invite_choice.isdigit():

            print(
                "\nInvalid Invite ID.\n"
            )

            continue


        invite_id = int(
            invite_choice
        )


        # Look only among pending invites.
        selected_invite = None

        for invite in invites:

            if invite[0] == invite_id:

                selected_invite = invite

                break


        if selected_invite is None:

            print(
                "\nThat Invite ID is not a "
                "pending enrollment invite.\n"
            )

            continue


        (
            invite_id,
            member_id,
            member_name,
            created_at,
            expires_at,
            revoked_at,
            invite_status
        ) = selected_invite


        if invite_status == "REVOKED":

            print(
                "\nThat enrollment invite is "
                "already revoked.\n"
            )

            continue


        if invite_status == "EXPIRED":

            print()
            print(
                "That enrollment invite has "
                "already expired."
            )

            print(
                "It can no longer be used for "
                "device enrollment."
            )
            print()

            continue


        print()
        print(
            "Enrollment Invite:"
        )

        print(
            f"  Invite ID: {invite_id}"
        )

        print(
            f"  Member:    {member_name}"
        )

        print(
            f"  Status:    {invite_status}"
        )

        print(
            f"  Expires:   {expires_at}"
        )

        print()

        confirm = input(
            "Revoke this enrollment invite? "
            "(Y/N): "
        ).strip().upper()


        if confirm != "Y":

            print(
                "\nInvite was not revoked.\n"
            )

            continue


        revoked = revoke_enrollment_invite(
            invite_id
        )


        if revoked:

            print()
            print(
                f"Enrollment invite {invite_id} "
                f"for {member_name} was revoked."
            )

            print(
                "It can no longer be used for "
                "device enrollment."
            )
            print()

        else:

            print()
            print(
                "The enrollment invite could not "
                "be revoked."
            )

            print(
                "It may already have been used or "
                "changed by another process."
            )
            print()

def get_registered_devices():
    """
    Return registered PixelSentinel push devices.
    """

    try:

        devices = db_execute(
            '''
            SELECT
                push_subscriptions.subscription_id,
                members.member_id,
                members.name,
                push_subscriptions.device_label,
                push_subscriptions.platform,
                push_subscriptions.enabled,
                push_subscriptions.failure_count,
                push_subscriptions.created_at,
                push_subscriptions.last_success_at

            FROM push_subscriptions

            JOIN members
                ON push_subscriptions.member_id =
                   members.member_id

            ORDER BY
                members.name COLLATE NOCASE,
                push_subscriptions.subscription_id
            ''',
            fetch=True
        )

        return devices or []

    except ValueError as e:

        print(
            f"Error retrieving registered devices: {e}"
        )

        return []

def display_registered_devices(devices):
    """
    Display registered PixelSentinel push devices.
    """

    print()
    print("Registered PixelSentinel Devices:")
    print()

    print(
        f"{'Sub ID':<8}"
        f"{'Member ID':<11}"
        f"{'Member':<18}"
        f"{'Device':<20}"
        f"{'Platform':<11}"
        f"{'Enabled':<10}"
        f"{'Failures':<10}"
        f"{'Created':<21}"
        f"{'Last Success':<21}"
    )

    print(
        f"{'-' * 6:<8}"
        f"{'-' * 9:<11}"
        f"{'-' * 16:<18}"
        f"{'-' * 18:<20}"
        f"{'-' * 9:<11}"
        f"{'-' * 8:<10}"
        f"{'-' * 8:<10}"
        f"{'-' * 19:<21}"
        f"{'-' * 19:<21}"
    )

    for (
        subscription_id,
        member_id,
        member_name,
        device_label,
        platform,
        enabled,
        failure_count,
        created_at,
        last_success_at
    ) in devices:

        enabled_text = (
            "Yes"
            if enabled
            else "No"
        )

        device_text = (
            device_label
            or "Unknown"
        )

        platform_text = (
            platform
            or "other"
        )

        created_text = (
            created_at
            or "-"
        )

        success_text = (
            last_success_at
            or "-"
        )

        print(
            f"{subscription_id:<8}"
            f"{member_id:<11}"
            f"{member_name:<18}"
            f"{device_text:<20}"
            f"{platform_text:<11}"
            f"{enabled_text:<10}"
            f"{failure_count:<10}"
            f"{created_text:<21}"
            f"{success_text:<21}"
        )

def registered_devices():
    """
    Read-only registered device view.
    """

    devices = get_registered_devices()

    if not devices:

        print(
            "\nNo registered PixelSentinel "
            "devices found.\n"
        )

        input(
            "Press Enter to return to "
            "Push Management..."
        )

        return


    display_registered_devices(devices)

    print()
    print("This is a read-only device view.")

    input(
        "\nPress Enter to return to "
        "Push Management..."
    )

def get_registered_device(
    subscription_id
):
    """
    Return one registered device
    """

    try:

        result = db_execute(
            '''
            SELECT
                push_subscriptions.subscription_id,
                push_subscriptions.member_id,
                members.name,
                push_subscriptions.device_label,
                push_subscriptions.platform,
                push_subscriptions.enabled,
                push_subscriptions.failure_count,
                push_subscriptions.created_at,
                push_subscriptions.last_success_at

            FROM push_subscriptions

            JOIN members
                ON push_subscriptions.member_id =
                   members.member_id

            WHERE push_subscriptions.subscription_id = ?
            ''',
            (subscription_id,),
            fetch=True
        )

        if not result:

            return None

        return result[0]

    except ValueError as e:

        print(
            f"Error retrieving registered device: {e}"
        )

        return None
def set_registered_device_enabled(
    subscription_id,
    enabled
):
    """
    Enable or disable a registered push subscription.

    The subscription itself is preserved.

    Returns True only when the requested subscription
    exists and the update succeeds.
    """

    if enabled not in (
        True,
        False
    ):

        return False


    connection = None

    try:

        connection = sqlite3.connect(
            db_file,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )


        cursor = connection.execute(
            '''
            UPDATE push_subscriptions

            SET
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP

            WHERE subscription_id = ?

            RETURNING subscription_id
            ''',
            (
                1 if enabled else 0,
                subscription_id
            )
        )


        result = cursor.fetchone()


        if result is None:

            connection.rollback()

            return False


        connection.commit()

        return True


    except sqlite3.Error:

        if connection is not None:

            connection.rollback()


        print()
        print(
            "Unable to update the registered device."
        )
        print()

        return False


    finally:

        if connection is not None:

            connection.close()
            
def manage_device_status():
    """
    Enable or disable an existing PixelSentinel
    push device without deleting its subscription.
    """

    while True:

        devices = get_registered_devices()


        if not devices:

            print()
            print(
                "No registered PixelSentinel "
                "devices found."
            )
            print()

            return


        display_registered_devices(
            devices
        )


        subscription_choice = input(
            "\nEnter the Subscription ID to manage "
            "(or X to return): "
        ).strip()


        if subscription_choice.upper() == "X":

            return


        if not subscription_choice.isdigit():

            print()
            print(
                "Invalid Subscription ID."
            )
            print()

            continue


        subscription_id = int(
            subscription_choice
        )


        device = get_registered_device(
            subscription_id
        )


        if device is None:

            print()
            print(
                f"Subscription ID {subscription_id} "
                "does not exist."
            )
            print()

            continue


        (
            subscription_id,
            member_id,
            member_name,
            device_label,
            platform,
            enabled,
            failure_count,
            created_at,
            last_success_at
        ) = device


        current_status = (
            "Enabled"
            if enabled
            else "Disabled"
        )


        print()
        print("Selected Device:")
        print()
        print(
            f"  Subscription ID: {subscription_id}"
        )
        print(
            f"  Member:          {member_name}"
        )
        print(
            f"  Member ID:       {member_id}"
        )
        print(
            f"  Device:          {device_label or 'Unknown'}"
        )
        print(
            f"  Platform:        {platform or 'other'}"
        )
        print(
            f"  Current Status:  {current_status}"
        )
        print()


        if enabled:

            print(
                "D - Disable this device"
            )

        else:

            print(
                "E - Enable this device"
            )


        print(
            "X - Cancel"
        )


        action = input(
            "\nSelect an action: "
        ).strip().upper()


        if action == "X":

            continue


        if enabled and action == "D":

            print()
            print(
                "Disabling this device will stop "
                "PixelSentinel photo alerts from "
                "being sent to it."
            )

            print(
                "The device registration will remain "
                "stored and can be enabled again later."
            )
            print()


            confirm = input(
                "Disable this device? (Y/N): "
            ).strip().upper()


            if confirm != "Y":

                print()
                print(
                    "Device was not disabled."
                )
                print()

                continue


            updated = (
                set_registered_device_enabled(
                    subscription_id,
                    False
                )
            )


            if updated:

                print()
                print(
                    f"Subscription {subscription_id} "
                    "was disabled successfully."
                )
                print()

            else:

                print()
                print(
                    "The device status could not "
                    "be changed."
                )
                print()


        elif (
            not enabled
            and action == "E"
        ):

            updated = (
                set_registered_device_enabled(
                    subscription_id,
                    True
                )
            )


            if updated:

                print()
                print(
                    f"Subscription {subscription_id} "
                    "was enabled successfully."
                )
                print()

            else:

                print()
                print(
                    "The device status could not "
                    "be changed."
                )
                print()


        else:

            print()
            print(
                "Invalid selection."
            )
            print()

def get_push_subscription_delivery_data(
    subscription_id
):
    """
    Retrieve the internal Web Push information required
    to send a removal command.

    These values must never be displayed or logged.
    """

    try:

        result = db_execute(
            '''
            SELECT
                subscription_id,
                endpoint,
                p256dh,
                auth

            FROM push_subscriptions

            WHERE subscription_id = ?
            ''',
            (
                subscription_id,
            ),
            fetch=True
        )


        if not result:

            return None


        (
            subscription_id,
            endpoint,
            p256dh,
            auth
        ) = result[0]


        return {
            "subscription_id":
                subscription_id,

            "endpoint":
                endpoint,

            "keys": {
                "p256dh":
                    p256dh,

                "auth":
                    auth
            }
        }


    except ValueError:

        return None

def create_subscription_removal_transaction(
    subscription_id
):
    """
    Create a one-time remote removal transaction.

    Only the SHA-256 removal-token hash is stored.
    The push subscription is immediately disabled.
    """

    removal_token = secrets.token_urlsafe(
        32
    )


    token_hash = hashlib.sha256(
        removal_token.encode(
            "utf-8"
        )
    ).hexdigest()


    expires_at = (
        datetime.now(
            timezone.utc
        )
        + timedelta(
            minutes=
                REMOVAL_LIFETIME_MINUTES
        )
    ).isoformat()


    connection = None


    try:

        connection = sqlite3.connect(
            db_file,
            timeout=5
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 5000"
        )

        connection.execute(
            "BEGIN IMMEDIATE"
        )


        subscription = connection.execute(
            '''
            SELECT subscription_id

            FROM push_subscriptions

            WHERE subscription_id = ?
            ''',
            (
                subscription_id,
            )
        ).fetchone()


        if subscription is None:

            connection.rollback()

            return None


        connection.execute(
            '''
            INSERT INTO subscription_removals (
                subscription_id,
                token_hash,
                expires_at,
                attempt_count,
                last_attempt_at,
                last_error
            )

            VALUES (?, ?, ?, 0, NULL, NULL)

            ON CONFLICT(subscription_id)

            DO UPDATE SET
                token_hash =
                    excluded.token_hash,

                requested_at =
                    CURRENT_TIMESTAMP,

                expires_at =
                    excluded.expires_at,

                attempt_count =
                    0,

                last_attempt_at =
                    NULL,

                last_error =
                    NULL
            ''',
            (
                subscription_id,
                token_hash,
                expires_at
            )
        )


        connection.execute(
            '''
            UPDATE push_subscriptions

            SET
                enabled = 0,
                updated_at =
                    CURRENT_TIMESTAMP

            WHERE subscription_id = ?
            ''',
            (
                subscription_id,
            )
        )


        connection.commit()


        return removal_token


    except sqlite3.Error:

        if connection is not None:

            connection.rollback()


        return None


    finally:

        if connection is not None:

            connection.close()
def record_removal_attempt(
    subscription_id
):
    """
    Record that PixelSentinel attempted to send a
    removal command.
    """

    try:

        db_execute(
            '''
            UPDATE subscription_removals

            SET
                attempt_count =
                    attempt_count + 1,

                last_attempt_at =
                    CURRENT_TIMESTAMP,

                last_error =
                    NULL

            WHERE subscription_id = ?
            ''',
            (
                subscription_id,
            )
        )


    except ValueError:

        pass

def record_removal_send_failure(
    subscription_id
):
    """
    Record only a generic removal delivery failure.

    Provider responses are deliberately not stored.
    """

    try:

        db_execute(
            '''
            UPDATE subscription_removals

            SET last_error =
                'push_send_failed'

            WHERE subscription_id = ?
            ''',
            (
                subscription_id,
            )
        )


    except ValueError:

        pass

def send_subscription_removal_command(
    subscription_id,
    removal_token
):
    """
    Send the encrypted browser-removal command.

    Push credentials and provider errors are never
    displayed by sentinelmanage.
    """

    subscription = (
        get_push_subscription_delivery_data(
            subscription_id
        )
    )


    if subscription is None:

        return False


    record_removal_attempt(
        subscription_id
    )


    payload = {
        "type":
            "subscription_removal",

        "removal_token":
            removal_token
    }


    try:

        import pixelsentinel_web


        pixelsentinel_web.send_web_push(
            subscription,
            payload,
            ttl=
                REMOVAL_PUSH_TTL_SECONDS
        )


        return True


    except Exception:

        record_removal_send_failure(
            subscription_id
        )

        return False

def wait_for_subscription_removal(
    subscription_id
):
    """
    Wait briefly for the browser to acknowledge the
    remote unsubscribe operation.

    Returns True when the push_subscriptions row has
    disappeared.
    """

    deadline = (
        time.monotonic()
        + REMOVAL_ACK_WAIT_SECONDS
    )


    while time.monotonic() < deadline:

        try:

            result = db_execute(
                '''
                SELECT subscription_id

                FROM push_subscriptions

                WHERE subscription_id = ?
                ''',
                (
                    subscription_id,
                ),
                fetch=True
            )


            if not result:

                return True


        except ValueError:

            return False


        time.sleep(
            1
        )


    return False

def remove_registered_device():
    """
    Begin secure remote removal of a PixelSentinel
    push device.

    Local deletion occurs only after the browser
    acknowledges successful unsubscribe.
    """

    devices = get_registered_devices()


    if not devices:

        print()
        print(
            "No registered PixelSentinel "
            "devices found."
        )
        print()

        return


    display_registered_devices(
        devices
    )


    choice = input(
        "\nEnter the Subscription ID to remove "
        "(or X to cancel): "
    ).strip()


    if choice.upper() == "X":

        print()
        print(
            "Device removal canceled."
        )
        print()

        return


    if not choice.isdigit():

        print()
        print(
            "Invalid Subscription ID."
        )
        print()

        return


    subscription_id = int(
        choice
    )


    device = get_registered_device(
        subscription_id
    )


    if device is None:

        print()
        print(
            f"Subscription ID {subscription_id} "
            "does not exist."
        )
        print()

        return


    (
        subscription_id,
        member_id,
        member_name,
        device_label,
        platform,
        enabled,
        failure_count,
        created_at,
        last_success_at
    ) = device


    print()
    print("=" * 60)
    print("REMOVE PIXELSENTINEL DEVICE")
    print("=" * 60)
    print()

    print(
        f"Subscription ID: {subscription_id}"
    )

    print(
        f"Member:          {member_name}"
    )

    print(
        f"Member ID:       {member_id}"
    )

    print(
        f"Device:          "
        f"{device_label or 'Unknown'}"
    )

    print(
        f"Platform:        "
        f"{platform or 'other'}"
    )

    print()

    print(
        "WARNING:"
    )

    print(
        "This will remotely unsubscribe this "
        "browser from PixelSentinel push alerts."
    )

    print()

    print(
        "To use this device again, it must be "
        "enrolled with a new invitation."
    )

    print()


    confirm = input(
        "Type REMOVE to continue: "
    ).strip()


    if confirm != "REMOVE":

        print()
        print(
            "Device removal canceled."
        )
        print()

        return


    removal_token = (
        create_subscription_removal_transaction(
            subscription_id
        )
    )


    if removal_token is None:

        print()
        print(
            "Unable to create the secure "
            "device-removal request."
        )
        print()

        return


    sent = (
        send_subscription_removal_command(
            subscription_id,
            removal_token
        )
    )


    # Stop intentionally retaining our reference to
    # the raw removal credential.
    removal_token = None


    if not sent:

        print()
        print(
            "PixelSentinel could not send the "
            "device-removal command."
        )

        print(
            "The device has been disabled and the "
            "removal remains pending."
        )

        print(
            "No local subscription record was deleted."
        )
        print()

        return


    print()
    print(
        "Removal command sent."
    )

    print(
        "Waiting for the device to confirm "
        "remote unsubscribe..."
    )


    removed = (
        wait_for_subscription_removal(
            subscription_id
        )
    )


    if removed:

        print()
        print(
            f"Subscription {subscription_id} "
            "was removed successfully."
        )

        print(
            "The browser confirmed that its "
            "push subscription was unsubscribed."
        )
        print()


    else:

        print()
        print(
            "The removal command was accepted by "
            "the push service."
        )

        print(
            "The browser has not yet acknowledged "
            "the unsubscribe operation."
        )

        print(
            "The device remains disabled and is "
            "marked as pending removal."
        )
        print()

def main():
    initialize_membership_tables()
    initialize_push_removal_tables()    
    main_menu()

if __name__ == "__main__":
    main()
