import random
import string
import qrcode
import firebase_admin
from firebase_admin import credentials, db
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import *

# ---------------- FIREBASE ----------------
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': DB_URL
})

def get_user(uid):
    return db.reference(f"users/{uid}").get()

def update_user(uid, data):
    db.reference(f"users/{uid}").update(data)

# ---------------- BOT ----------------
app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_state = {}

# ---------------- START ----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    uid = message.from_user.id
    args = message.text.split()

    # create user
    if not get_user(uid):
        update_user(uid, {
            "bot_balance": 0,
            "web_balance": 0,
            "referrals": 0,
            "banned": False
        })

        # referral
        if len(args) > 1 and args[1].startswith("ref_"):
            ref_id = int(args[1].split("_")[1])
            if ref_id != uid:
                ref_user = get_user(ref_id)
                if ref_user:
                    db.reference(f"users/{ref_id}/bot_balance").set(ref_user["bot_balance"] + 0.25)
                    db.reference(f"users/{ref_id}/referrals").set(ref_user["referrals"] + 1)

                    await app.send_message(ref_id, "🎉 You referred a new user! +₹0.25")
                    await message.reply(f"You got referred by {ref_id}")

    # join buttons
    buttons = [
        [InlineKeyboardButton("📢 Join 1", url=f"https://t.me/{CHANNELS[0][1:]}")],
        [InlineKeyboardButton("📢 Join 2", url=f"https://t.me/{CHANNELS[1][1:]}")],
        [InlineKeyboardButton("📢 Join 3", url=f"https://t.me/{CHANNELS[2][1:]}")],
        [InlineKeyboardButton("🔒 Private", url=PRIVATE_CHANNEL)],
        [InlineKeyboardButton("✅ Verify & Start", callback_data="verify")]
    ]

    await message.reply("⚠️ Join all channels first", reply_markup=InlineKeyboardMarkup(buttons))

# ---------------- VERIFY ----------------
@app.on_callback_query(filters.regex("verify"))
async def verify(client, cb):
    uid = cb.from_user.id

    for ch in CHANNELS:
        member = await app.get_chat_member(ch, uid)
        if member.status == "left":
            return await cb.answer("Join all channels!", show_alert=True)

    await cb.message.edit("✅ Verified!", reply_markup=main_menu())

# ---------------- MENU ----------------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Social Media Services", web_app=WebAppInfo(url=WEB_URL))],
        [InlineKeyboardButton("♻️ Add Fund", callback_data="add")],
        [InlineKeyboardButton("💰 Refer & Earn", callback_data="ref")],
        [InlineKeyboardButton("🪙 Earn Money", callback_data="earn")],
        [InlineKeyboardButton("📦 Order Status", callback_data="order")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="wd")],
        [InlineKeyboardButton("💳 My Balance", callback_data="bal")],
        [InlineKeyboardButton("📖 How to Use", callback_data="how")]
    ])

# ---------------- ADD FUND ----------------
@app.on_callback_query(filters.regex("add"))
async def add(client, cb):
    user_state[cb.from_user.id] = "amount"
    await cb.message.reply("💳 Enter amount:")

@app.on_message(filters.text)
async def handler(client, msg):
    uid = msg.from_user.id

    # ADD FUND
    if user_state.get(uid) == "amount":
        amt = msg.text

        upi = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amt}&cu=INR"
        qr = qrcode.make(upi)
        file = f"{uid}.png"
        qr.save(file)

        user_state[uid] = "ss"

        await msg.reply_photo(file, caption=f"Pay ₹{amt} then send screenshot")

    elif user_state.get(uid) == "ss":
        await app.send_photo(PAYMENT_CHANNEL, msg.photo.file_id,
                             caption=f"💰 Payment\nUser: {uid}")
        await app.send_photo(ADMIN_ID, msg.photo.file_id,
                             caption=f"💰 Payment\nUser: {uid}")

        user_state[uid] = None
        await msg.reply("✅ Sent for verification")

# ---------------- REFER ----------------
@app.on_callback_query(filters.regex("ref"))
async def ref(client, cb):
    uid = cb.from_user.id
    bot = await app.get_me()

    link = f"https://t.me/{bot.username}?start=ref_{uid}"
    await cb.message.reply(f"🔗 {link}\nEarn ₹0.25 per refer")

# ---------------- EARN ----------------
@app.on_callback_query(filters.regex("earn"))
async def earn(client, cb):
    await cb.message.reply("💰 Earn ₹500-700/day using SMM methods (your full text here)")

# ---------------- BALANCE ----------------
@app.on_callback_query(filters.regex("bal"))
async def bal(client, cb):
    user = get_user(cb.from_user.id)

    await cb.message.reply(
        f"🤖 Bot Balance: ₹{user['bot_balance']}\n🌐 Web Balance: ₹{user['web_balance']}"
    )

# ---------------- WITHDRAW ----------------
@app.on_callback_query(filters.regex("wd"))
async def wd(client, cb):
    user_state[cb.from_user.id] = "wd"
    await cb.message.reply("Enter amount (min ₹2):")

@app.on_message(filters.text)
async def wd_handler(client, msg):
    uid = msg.from_user.id

    if user_state.get(uid) == "wd":
        amt = float(msg.text)
        user = get_user(uid)

        if user["bot_balance"] < amt or amt < 2:
            return await msg.reply("❌ Invalid amount")

        await app.send_message(PAYMENT_CHANNEL,
                               f"🚨 Withdraw\nUser: {uid}\n₹{amt}")
        await app.send_message(ADMIN_ID,
                               f"🚨 Withdraw\nUser: {uid}\n₹{amt}")

        user_state[uid] = None
        await msg.reply("✅ Request sent")

# ---------------- COUPON ----------------
@app.on_message(filters.command("gen") & filters.user(ADMIN_ID))
async def gen(client, msg):
    amt = int(msg.command[1])
    code = "NEXA" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

    db.reference(f"coupons/{code}").set({"amount": amt, "used": False})

    await msg.reply(f"🎟 Code: {code}\n₹{amt}")

@app.on_message(filters.command("redeem"))
async def redeem(client, msg):
    code = msg.command[1]
    ref = db.reference(f"coupons/{code}")
    data = ref.get()

    if not data or data["used"]:
        return await msg.reply("❌ Invalid")

    user = get_user(msg.from_user.id)
    db.reference(f"users/{msg.from_user.id}/bot_balance").set(user["bot_balance"] + data["amount"])
    ref.update({"used": True})

    await msg.reply(f"✅ ₹{data['amount']} added")

# ---------------- ADMIN ----------------
@app.on_message(filters.command("addfunds") & filters.user(ADMIN_ID))
async def addfunds(client, msg):
    uid = int(msg.command[1])
    amt = float(msg.command[2])

    user = get_user(uid)
    db.reference(f"users/{uid}/web_balance").set(user["web_balance"] + amt)

    await app.send_message(uid, f"✅ ₹{amt} added")

# ---------------- RUN ----------------
app.run()
