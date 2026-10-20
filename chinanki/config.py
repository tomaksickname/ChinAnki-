"""
Central config: paths, constants, environment.
"""
import os
from pathlib import Path

# ---------- Paths ----------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STORIES_DIR = ROOT / "stories"
AUDIO_DIR = ROOT / "audio"
AUDIO_WORDS_DIR = AUDIO_DIR / "words"
AUDIO_STORIES_DIR = AUDIO_DIR / "stories"
APP_DIR = ROOT / "app"

FREQ_LIST_PATH = DATA_DIR / "frequency_list_v4_final.json"
SRS_STATE_PATH = DATA_DIR / "srs_state.json"

# ---------- Server ----------

PORT = int(os.environ.get("CHINANKI_PORT", "8765"))
HOST = "127.0.0.1"

# ---------- DeepSeek ----------

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# ---------- TTS ----------

TTS_BACKEND = os.environ.get("TTS_BACKEND", "macsay")
MACSAY_VOICE = os.environ.get("MACSAY_VOICE", "Tingting")

AZURE_TTS_KEY = os.environ.get("AZURE_TTS_KEY", "")
AZURE_TTS_REGION = os.environ.get("AZURE_TTS_REGION", "")
AZURE_TTS_VOICE = os.environ.get("AZURE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")

# ---------- SRS ----------

PHASE1_BOUND = 1000

DEFAULT_NEW_PER_DAY = 10
MAX_NEW_PER_DAY = 10
DEFAULT_FREE_OFFSET = 0
MAX_FREE_OFFSET = 2000

SRS_CONFIG = {
    "learning_steps_minutes": [1, 10, 30],
    "graduating_interval_days": 1,
    "easy_interval_days": 4,
    "starting_ease": 2.5,
    "easy_bonus": 1.3,
    "interval_modifier": 1.0,
    "hard_interval_multiplier": 1.2,
    "min_ease_factor": 1.3,
    "max_ease_factor": 3.0,
    "leech_threshold": 8,
    "leech_action": "suspend",
}

# ---------- Story ----------

DEFAULT_LENGTH = 300
DEFAULT_RANGE_PCT = 15
TOPIC_CHIP_COUNT = 8
MAX_RETRIES = 3

# Prompt-size control. Only a small slice of the pool is sent to the model.
NEW_CANDIDATE_POOL = 60      # how many NEW candidates to offer the model
FREE_GLUE_SIZE = 300         # how many top-ranked words to send as FREE glue
NEW_CANDIDATE_SEARCH_BOUND = 400   # only sample NEW from first N un-introduced

# ---------- Ensure dirs ----------

def ensure_dirs() -> None:
    for d in (DATA_DIR, STORIES_DIR, AUDIO_WORDS_DIR, AUDIO_STORIES_DIR):
        d.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_dirs()
    print(f"ROOT              = {ROOT}")
    print(f"FREQ_LIST         = {FREQ_LIST_PATH}")
    print(f"SRS_STATE         = {SRS_STATE_PATH}")
    print(f"PHASE1_BOUND      = {PHASE1_BOUND}")
    print(f"DEFAULT_NEW_PER_DAY = {DEFAULT_NEW_PER_DAY}")
    print(f"DEFAULT_LENGTH    = {DEFAULT_LENGTH}")
    print(f"NEW_CANDIDATE_POOL = {NEW_CANDIDATE_POOL}")
    print(f"FREE_GLUE_SIZE    = {FREE_GLUE_SIZE}")
    print(f"TTS_BACKEND       = {TTS_BACKEND}")
    print(f"DEEPSEEK_KEY      = {'set' if DEEPSEEK_API_KEY else 'MISSING'}")
