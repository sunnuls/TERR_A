
import os
import logging
from google_sheets_manager import initialize_google_sheets, is_initialized, check_and_create_next_month_sheet

# Setup logging
logging.basicConfig(level=logging.INFO)

print("Checking environment variables...")
print(f"OAUTH_CLIENT_JSON: {os.getenv('OAUTH_CLIENT_JSON', 'oauth_client.json')}")
print(f"TOKEN_JSON_PATH: {os.getenv('TOKEN_JSON_PATH', 'token.json')}")
print(f"DRIVE_FOLDER_ID: {os.getenv('DRIVE_FOLDER_ID', 'Not Set')}")

print("\nInitializing Google Sheets...")
try:
    success = initialize_google_sheets()
    print(f"Initialization success: {success}")
    print(f"Is initialized: {is_initialized()}")
    
    if success:
        print("\nChecking next month sheet creation...")
        created, msg = check_and_create_next_month_sheet()
        print(f"Created: {created}, Message: {msg}")
        
except Exception as e:
    print(f"Error during initialization: {e}")
