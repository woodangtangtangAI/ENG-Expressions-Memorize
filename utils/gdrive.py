import os
import json
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from utils.logger import setup_logger

logger = setup_logger('gdrive')

# Google Drive Target Folder IDs
FOLDER_IDS = {
    "01_Database": "1h7BwiJ_c5I_IK1xISe5P0zYeIFh-BGJ2",
    "02_Daily_Sheets": "13mbN_zciYmIw3IEyJ9-fUODhCD81P44k",
    "03_Print_PDF": "1aWBulIqn-wkhbmIUcLf8hmCjBUtBijZu"
}

def get_drive_service():
    """Build Google Drive API client using credentials from env (supports both SA and OAuth)."""
    creds_json = os.environ.get("GOOGLE_USER_CREDENTIALS")
    if not creds_json:
        logger.warning("GOOGLE_USER_CREDENTIALS environment variable not found. Skipping Google Drive sync.")
        return None
    
    try:
        creds_data = json.loads(creds_json)
        scopes = ['https://www.googleapis.com/auth/drive']
        
        if "refresh_token" in creds_data:
            from google.oauth2.credentials import Credentials
            creds = Credentials(
                token=creds_data.get('token'),
                refresh_token=creds_data.get('refresh_token'),
                token_uri=creds_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=creds_data.get('client_id'),
                client_secret=creds_data.get('client_secret'),
                scopes=scopes
            )
            logger.info("🔐 Loaded OAuth user credentials for Google Drive sync.")
        else:
            from google.oauth2.service_account import Credentials as SACredentials
            creds = SACredentials.from_service_account_info(creds_data, scopes=scopes)
            logger.info("🔑 Loaded Service Account credentials for Google Drive sync.")
            
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Failed to initialize Google Drive service: {e}")
        return None

def find_file_in_folder(service, filename, folder_id):
    """Find a file by name inside a specific Google Drive folder."""
    query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
    try:
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        return files[0]['id'] if files else None
    except Exception as e:
        logger.error(f"Error searching for file {filename} in drive: {e}")
        return None

def upload_file_to_drive(service, local_path, folder_name, mime_type):
    """Upload or update a local file to a specific Google Drive folder."""
    if not os.path.exists(local_path):
        logger.warning(f"Local file does not exist, skipping upload: {local_path}")
        return False

    folder_id = FOLDER_IDS.get(folder_name)
    if not folder_id:
        logger.error(f"Invalid drive folder name: {folder_name}")
        return False

    filename = os.path.basename(local_path)
    existing_file_id = find_file_in_folder(service, filename, folder_id)

    try:
        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
        
        if existing_file_id:
            # Update existing file
            service.files().update(
                fileId=existing_file_id,
                media_body=media
            ).execute()
            logger.info(f"🔄 Updated existing file in Drive: {folder_name}/{filename}")
        else:
            # Create new file
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            logger.info(f"📤 Uploaded new file to Drive: {folder_name}/{filename}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload {filename} to {folder_name}: {e}")
        return False

def sync_data_to_gdrive():
    """Sync all daily generated outputs to Google Drive (Cloud)."""
    service = get_drive_service()
    if not service:
        return

    logger.info("⚡ Starting Cloud Google Drive Direct Sync...")
    date_str = datetime.date.today().strftime('%Y-%m-%d')
    
    # Files to sync
    files_to_sync = [
        # (local_path, folder_name, mime_type)
        (
            os.path.join("data", "01_Database", "english_expressions_db.xlsx"),
            "01_Database",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        (
            os.path.join("data", "01_Database", "expressions_index.json"),
            "01_Database",
            "application/json"
        ),
        (
            os.path.join("data", "01_Database", "run_log.json"),
            "01_Database",
            "application/json"
        ),
        (
            os.path.join("data", "02_Daily_Sheets", f"Expressions_{date_str}.xlsx"),
            "02_Daily_Sheets",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        (
            os.path.join("data", "03_Print_PDF", f"Study_Note_{date_str}.docx"),
            "03_Print_PDF",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    ]

    success_count = 0
    for local_path, folder_name, mime_type in files_to_sync:
        if upload_file_to_drive(service, local_path, folder_name, mime_type):
            success_count += 1

    logger.info(f"✨ Cloud Sync Completed: {success_count}/{len(files_to_sync)} files synchronized.")
