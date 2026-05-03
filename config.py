# config.py

# ===================== TELEGRAM BOT =====================
API_ID = 12345678                     # my.telegram.org se API ID
API_HASH = "your_api_hash_here"      # API hash
BOT_TOKEN = "123456:ABC-DEF1234gh"   # @BotFather se token

# ===================== FIREBASE =====================
DB_URL = "https://your-project.firebaseio.com"  # Realtime Database URL

# ===================== CHANNELS (Verification) =====================
# Username @ ke saath (e.g., "@nexachannel1")
CHANNELS = [
    "@channel1",  # Join Channel 1
    "@channel2",  # Join Channel 2
    "@channel3",  # Join Channel 3
]

PRIVATE_CHANNEL = "https://t.me/+abcdefg"  # Private group/channel join link

# ===================== PAYMENT =====================
UPI_ID = "youremail@upi"    # UPI ID (e.g., "example@axl")
UPI_NAME = "Your Name"      # UPI display name

# Payment approval logs yahan jaayenge (channel/group numeric ID)
# Negative for supergroups/channels
PAYMENT_CHANNEL = -1001234567890

# ===================== WEBAPP =====================
WEB_URL = "https://your-frontend-url.vercel.app"  # Mini App URL

# ===================== ADMINS =====================
ADMIN_IDS = [7549407961, 5311223486]  # Admin Telegram user IDs

# ===================== WELCOME =====================
WELCOME_IMAGE = "welcome.jpg"  # Bot folder mein yeh image rakhna
TELEGRAPH_URL = "https://telegra.ph/Your-Guide-04-26"

# ===================== LOGS =====================
LOG_FILE = "bot.log"  # Bot logs yahan save honge
