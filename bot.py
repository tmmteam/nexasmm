import random
import string
import qrcode
import firebase_admin
from firebase_admin import credentials, db
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import *

# FIREBASE
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': DB_URL
})

def get_user(uid):
    ref = db.reference(f"users/{uid}")
    return ref.get()

def update_user(uid, data):
    db.reference(f"users/{uid}").update(data)

# BOT
app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_state = {}

# START
@app.on_message(filters.command("start"))
async def start(client, message):
    uid = message.from_user.id

    if not get_user(uid):
        update_user(uid, {
            "bot_balance": 0,
            "web_balance": 0,
            "referrals": 0,
            "banned": False
        })

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Social Media Services", web_app=WebAppInfo(url=WEB_URL))],
        [InlineKeyboardButton("♻️ Add Fund", callback_data="add")],
        [InlineKeyboardButton("💰 Refer", callback_data="ref")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="wd")],
        [InlineKeyboardButton("💳 Balance", callback_data="bal")]
    ])

    await message.reply("Welcome 🔥", reply_markup=kb)

# ADD FUND
@app.on_callback_query(filters.regex("add"))
async def add(client, cb):
    user_state[cb.from_user.id] = "amount"
    await cb.message.reply("Enter amount:")

@app.on_message(filters.text)
async def handler(client, msg):
    uid = msg.from_user.id

    if user_state.get(uid) == "amount":
        amt = msg.text

        upi = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amt}&cu=INR"
        qr = qrcode.make(upi)
        qr.save("qr.png")

        user_state[uid] = "ss"

        await msg.reply_photo("qr.png", caption=f"Pay ₹{amt} and send screenshot")

    elif user_state.get(uid) == "ss":
        await app.send_photo(PAYMENT_CHANNEL, msg.photo.file_id,
                             caption=f"{uid} payment SS")
        await msg.reply("Sent to admin")
        user_state[uid] = None

# REFER
@app.on_callback_query(filters.regex("ref"))
async def ref(client, cb):
    uid = cb.from_user.id
    bot = await app.get_me()

    link = f"https://t.me/{bot.username}?start=ref_{uid}"
    await cb.message.reply(f"Refer link:\n{link}")

# BALANCE
@app.on_callback_query(filters.regex("bal"))
async def bal(client, cb):
    user = get_user(cb.from_user.id)
    await cb.message.reply(f"Bot: ₹{user['bot_balance']}\nWeb: ₹{user['web_balance']}")

# WITHDRAW
@app.on_callback_query(filters.regex("wd"))
async def wd(client, cb):
    user_state[cb.from_user.id] = "wd_amt"
    await cb.message.reply("Enter amount:")

@app.on_message(filters.text)
async def wd_handler(client, msg):
    uid = msg.from_user.id

    if user_state.get(uid) == "wd_amt":
        amt = float(msg.text)
        user = get_user(uid)

        if user["bot_balance"] < amt or amt < 2:
            return await msg.reply("Invalid")

        await app.send_message(ADMIN_ID, f"Withdraw {uid} ₹{amt}")
        await msg.reply("Request sent")
        user_state[uid] = None

# ADMIN ADD FUNDS
@app.on_message(filters.command("addfunds") & filters.user(ADMIN_ID))
async def addf(client, msg):
    uid = int(msg.command[1])
    amt = float(msg.command[2])

    user = get_user(uid)
    db.reference(f"users/{uid}/web_balance").set(user["web_balance"] + amt)

    await app.send_message(uid, f"₹{amt} added")

app.run()
