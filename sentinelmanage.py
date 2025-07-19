"""
Program Name: PixelSentinel Management (c) Larry Zande

Description: This program is used for group/album management for the PixelSentinel program. It's
a helper program that lets you add/remove groups, group members, and albums to control
who gets alert messages.

Date: 12/29/2024
"""
import os
import sqlite3
import re

try:
    import pandas as pd
except ModuleNotFoundError:
    print(f"The module pandas is not found. Please install with 'pip install pandas.'")
    exit(1)

# Configuration
db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pixelsentinel.db')

def db_execute(query, params=(), fetch=False):
    connection = sqlite3.connect(db_file)
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
            # Remove all members from the selected group
            db_execute('''
                            DELETE FROM members WHERE group_id = ?
                            ''', (group_id_to_remove,))
            print(f"All members removed from Group {group_id_to_remove} successfully.\n")
            # Attempt to remove the selected group
            db_execute('''
                DELETE FROM groups WHERE group_id = ?
                ''', (group_id_to_remove,))
            print(f"Group with ID {group_id_to_remove} removed successfully.\n")
        except ValueError as e:
            print(f"Error while removing the group: {e}")


# Check email
def get_valid_email():
    email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'

    while True:
        user_input = input("Enter the member's email: ")

        # Check if input is a valid email
        if re.match(email_pattern, user_input):
            return user_input
        else:
            print("Invalid input. Please enter a valid email address.")


# Add Group Member
def add_group_member():
    try:
        db_execute('''
        CREATE TABLE IF NOT EXISTS members (
        member_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        group_id INTEGER,
        FOREIGN KEY (group_id) REFERENCES groups (group_id) ON DELETE CASCADE
        );
        ''')
    except ValueError as e:
        print(f"Error creating the table: {e}")
        return

    while True:
        existing_groups = get_groups_with_id_name()  # Display current groups

        print("\nGroup ID     Name")
        print("--------     -----")
        for group_id, name in existing_groups:
            print(f"{group_id:<10} {name}")

        try:
            group_id = input("\nEnter the Group ID to add a member to (or type 'X' to cancel): ")

            if group_id.strip().upper() == 'X':
                print("Add group member process canceled.\n")
                break

            # Check if the group ID exists in the database
            valid_group = db_execute('''
                SELECT group_id FROM groups WHERE group_id = ?
                ''', (group_id,), fetch=True)

            if not valid_group:
                print(f"Group ID {group_id} does not exist. Please enter a valid Group ID.\n")
                continue  # Prompt the user to try again

            # Proceed with adding a member to the group
            member_name = input("Enter the member's name: ")
            email = get_valid_email()
            print(f"Adding member {member_name} with email {email} to group {group_id}...\n")

            # Insert the member into the members table
            db_execute('''
                INSERT INTO members (name, email, group_id)
                VALUES (?, ?, ?)
                ''', (member_name, email, group_id))

            print(f"Member {member_name} added successfully to group {group_id}.\n")
            break
        except ValueError as e:
            print(f"Error while adding the member to the group: {e}")

# Get Current members of a selected group
def get_members(group_id):
    try:
        # List all members with IDs
        existing_members = db_execute('''
                    SELECT member_id, name FROM members WHERE group_id = ?
                    ''', (group_id,), fetch=True)

        if not existing_members:
            print("No members found in group.\n")
            return
        else:
            return existing_members
    except ValueError as e:
        print(f"Error interacting with the database: {e}")
        return

# Remove Group Member
def remove_group_member():
    while True:
        existing_groups = get_groups_with_id_name()  # Display current groups

        print("\nGroup ID     Name")
        print("--------     -----")
        for group_id, name in existing_groups:
            print(f"{group_id:<10} {name}")

        # Allow the user to remove a group member
        try:
            member_group = input("\nEnter the Group ID to remove a member from (or type 'X' to cancel): ")

            if member_group.strip().upper() == 'X':
                print("Member removal process canceled.\n")
                return

            # Check if the group ID exists in the database
            valid_group = db_execute('''
                SELECT group_id FROM groups WHERE group_id = ?
                ''', (member_group,), fetch=True)

            if not valid_group:
                print(f"Group ID {member_group} does not exist. Please enter a valid Group ID.\n")
                continue  # Prompt the user to try again

            # Display current members of the selected group
            existing_members = get_members(member_group)
            print("\nMember ID     Name")
            print("--------     -----")
            for member_id, name in existing_members:
                print(f"{member_id:<10} {name}")

            member_id = input("\nEnter the Member ID of the member to remove (or type 'X' to cancel): ")

            if member_id.strip().upper() == 'X':
                print("Member removal process canceled.\n")
                return

            # Check if the member ID exists in the database
            valid_member = db_execute('''
                SELECT member_id FROM members WHERE member_id = ? AND group_id = ?
                ''', (member_id, member_group), fetch=True)

            if not valid_member:
                print(f"Member ID {member_id} does not exist in Group ID {member_group}.\n")
                continue  # Prompt the user to try again

            # Remove the user from the selected group
            db_execute('''
                DELETE FROM members WHERE member_id = ? AND group_id = ?
                ''', (member_id, member_group))
            print(f"Member with ID {member_id} removed successfully from Group ID {member_group}.\n")
            break  # Exit the loop after successful removal

        except ValueError as e:
            print(f"Error while removing member from group: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

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
            group_members = db_execute('''
                            SELECT name, email from members WHERE group_id = ?
                ''', (group_id,), fetch=True)
            headers = ["Member Name", "Member Email"]
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

def main():
    main_menu()

if __name__ == "__main__":
    main()