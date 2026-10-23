# PixelSentinel
PixelSentinel is a Python 3 program that lets you set up and manage alerts for 'shared' photos on a Synology NAS.
I created this because Synology Photos does not have a way to alert users that new photos have been uploaded.
PixelSentinel does not use the Synology APIs so the system will continue to work when updating the Photos app or your NAS operating system.

# Preparing your NAS
To run PixelSentinel you first need to install some third-party packages from synocommunity.
1. Go to https://synocommunity.com/ and follow the easy install

 ![image](https://github.com/user-attachments/assets/1645b7b5-6c86-4dac-a45f-080b8e732875)

2. After you install the synocommunity package list go back to the Package Center on your NAS and look for and install the following:
   git, python 3.14
3. Setup SSH on your NAS: https://kb.synology.com/en-nz/DSM/tutorial/How_to_login_to_DSM_with_root_permission_via_SSH_Telnet
Remember to change the SSH Port from 22.

# Getting PixelSentinel and setup
1. SSH into your NAS (ssh youradminaccount@yournasip -p ##)
2. Move to the user home folder where you want to store PixelSentinel and git clone the code: ` https://github.com/Master-of-Bytes/PixelSentinel.git`

## Setup and first run
1. Move into the PixelSentinel folder and create a .env file with the following format:
```
SHARED_PHOTOS=/volume1/photo
REQUIREMENTS_CHECKED='0'
SENDER_EMAIL='YOUR NAME <youremail@gmail.com>'
SMTP_USER=youremail@gmail.com
APP_PASS=xxxxxxxxx # Set up an app password in your Google account
PORT=465
SMTP_SERVER=smtp.gmail.com
ADMIN_ALERT_EMAIL=youremail@gmail.com
VAPID_PUBLIC_KEY=public key value
VAPID_PRIVATE_KEY=path to private key
VAPID_SUBJECT=mailto:youremail@gmail.com
```
2. Run: `sh setup.sh`
3. To manually run PixelSentinel, move to the PixelSentinel folder and run: `sh sentinel_start.sh`
If this is the first program run, it will also run sentinelmanage.py so you can set up your groups and group members and update or add albums. **NOTE: do not set up a task in Task Scheduler until after you manually run `sentinel_start.sh` and the program completes first time setup.**

# Creating new albums
1. Create a folder on your NAS in Synology Photos
2. Set folder permissions on the new folder in Synology Photos
3. SSH into your NAS, move to the PixelSentinel folder, then run: `sh sentinelmanage_start.sh`
4. Pick option 5 to add a new album
5. Add your files to the folder on your NAS
6. Run sentinel_start.sh manually to alert users or wait for the next task run

# Auto alerting with Task Scheduler
1. On your NAS go to Control Panel > Task Scheduler and create a Scheduled Task > User defined Script
2. Set the following for each tab:
## General:

 ![image](https://github.com/user-attachments/assets/2f20e4c5-a049-4454-9bac-f456570854bc)

## Schedule:

![image](https://github.com/user-attachments/assets/c5f41ee6-be6c-4809-8ddf-75e8af37827a)

You can update the start time to whatever time you would like.

## Task Settings:

![image](https://github.com/user-attachments/assets/5b1c9fb8-dd24-4255-bfa8-f3758be522fc)

## Troubleshooting: DSM Task Scheduler failure emails not arriving

PixelSentinel's `.env` SMTP settings are for **application-generated administrator alerts**. **Synology DSM Task Scheduler** uses **DSM's own email sender configuration** for task run-detail emails. A working PixelSentinel SMTP configuration does not automatically configure DSM notifications.

If **Send Test Email** works but a Task Scheduler task does not send its run details, check the following:

1. Open **DSM → Control Panel → Notification → Email → Sender → Set Up**.
2. For Gmail, configure the sender (using a dedicated sending account if desired):
   - **Service provider:** `Custom SMTP server`
   - **SMTP server:** `smtp.gmail.com`
   - **SMTP port:** `587` (SMTP with TLS; port `465` with SSL/TLS is another supported setup)
   - **Authentication required:** enabled
   - **Username:** the Gmail sending address
   - **Password:** a Google **app password** (enable Google 2-Step Verification as required)
   - **Secure connection (SSL/TLS) required:** enabled
   - **Verify the SSL/TLS certificate:** enabled
   - **Sender name:** e.g., `PixelSentinel DSM`
   - **Sender email:** the same Gmail sending address
3. Save the sender configuration. Back on **Notification → Email**, make sure **Sender email** displays the configured address rather than `-`.
4. Edit the appropriate DSM task under **Control Panel → Task Scheduler → Task Settings**. Enable **Send run details by email**, enter the **intended recipient address**, and optionally select **Send run details only when the script terminates abnormally**.
5. Test the recipient using a temporary user-defined DSM task, with **failure-only emails** enabled and the following harmless script:

   ```sh
   #!/bin/sh
   echo "ERROR: PixelSentinel controlled DSM notification test."
   exit 1
   ```

   Run it manually. A nonzero exit code is intentional; confirm the expected email arrives at the **task's recipient address**, then remove the temporary test task.

**Privacy:** Keep DSM Task Scheduler's global **Save output results** disabled.
