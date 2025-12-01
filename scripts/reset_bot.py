# scripts/reset_bot.py
import sys
import os
import sqlite3
import logging

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_sheets_manager import delete_all_files_in_folder, initialize_google_sheets

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports_whatsapp.db")

def reset_database():
    logging.info(f"🗑 Clearing database: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        logging.warning("⚠️ Database file not found.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # List of tables to clear
        tables = [
            "users", 
            "reports", 
            "brigadier_reports", 
            "google_exports", 
            "brigadier_google_exports", 
            "monthly_sheets",
            "reminder_status"
        ]
        
        for table in tables:
            try:
                c.execute(f"DELETE FROM {table}")
                logging.info(f"✅ Table '{table}' cleared.")
            except sqlite3.OperationalError:
                logging.warning(f"⚠️ Table '{table}' not found (skipping).")
        
        conn.commit()
        logging.info("✅ Database tables cleared.")
        
        # Vacuum to reclaim space (must be outside transaction)
        # c.execute("VACUUM") 
        # logging.info("🧹 Database vacuumed.")
        
        conn.close()
        logging.info("✅ Database reset complete.")
        
    except Exception as e:
        logging.error(f"❌ Database reset failed: {e}")

def reset_google_drive():
    logging.info("🗑 Clearing Google Drive folder...")
    try:
        if initialize_google_sheets():
            count, msg = delete_all_files_in_folder()
            logging.info(f"✅ Google Drive reset: {msg}")
        else:
            logging.error("❌ Failed to initialize Google Sheets (check token).")
    except Exception as e:
        logging.error(f"❌ Google Drive reset failed: {e}")

if __name__ == "__main__":
    print("WARNING: This will delete ALL data (Users, Reports, Google Drive files).")
    print("Are you sure? (Type 'yes' to confirm)")
    
    # For automation, we assume 'yes' if passed as arg, otherwise interactive
    if len(sys.argv) > 1 and sys.argv[1] == "--force":
        confirm = "yes"
    else:
        # In non-interactive environments, this might block. 
        # But since I'm running it via run_command, I can't easily interact.
        # I'll use --force flag in the run_command.
        confirm = input("> ")
        
    if confirm.lower() == "yes":
        reset_database()
        reset_google_drive()
        print("Reset complete.")
    else:
        print("Cancelled.")
