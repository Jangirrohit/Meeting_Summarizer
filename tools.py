## imports 
from langchain_google_community import CalendarToolkit
from langchain_google_community.calendar.create_event import CalendarCreateEvent
from langchain_google_community import GmailToolkit
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
import os
 



## Google authentication setup
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]

creds = None
# Load existing token
if os.path.exists("token.json"):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)

# If not valid → login again
if not creds or not creds.valid:
    flow = InstalledAppFlow.from_client_secrets_file(
        "credentials.json",
        SCOPES
    )
    creds = flow.run_local_server(port=0)

    # Save token
    with open("token.json", "w") as token:
        token.write(creds.to_json())



## Google Tools 
Cal_toolkit = CalendarToolkit(credentials=creds)
Cal_tools = Cal_toolkit.get_tools()

GM_toolkit = GmailToolkit(credentials=creds)
GM_tools = GM_toolkit.get_tools()
tools= Cal_tools+GM_tools




