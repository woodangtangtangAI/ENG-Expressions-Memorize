import os
import datetime

# API Keys
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# Paths
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
INDEX_FILE = os.path.join(DATA_DIR, "expressions_index.json")
RUN_LOG_FILE = os.path.join(DATA_DIR, "run_log.json")

# Excel Database File
EXCEL_FILENAME = os.path.join(DATA_DIR, "english_expressions_db.xlsx")

# Targets
MAX_EXPRESSIONS = 2000
DAILY_TARGET = 100

# Deduplication
FUZZY_MATCH_THRESHOLD = 0.85

# Gemini API Configuration
GEMINI_MODEL = "gemini-2.0-flash"
API_CALL_DELAY = 10  # seconds between Gemini API calls
API_MAX_RETRIES = 3

# Source Configuration
SOURCES = {
    "CNBC": {
        "rss_urls": [
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        ],
        "target_count": 25,
        "type": "news"
    },
    "BBC_Business": {
        "rss_urls": [
            "https://feeds.bbci.co.uk/news/business/rss.xml",
        ],
        "target_count": 25,
        "type": "news"
    },
    "HBR": {
        "rss_urls": [
            "https://hbr.org/feed",
        ],
        "target_count": 10,
        "type": "business"
    },
    "Friends": {
        "base_url": "https://transcripts.foreverdreaming.org/viewforum.php?f=6",
        "target_count": 40,
        "type": "transcript"
    }
}
}
