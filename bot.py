import random
import string
import qrcode
import firebase_admin
from firebase_admin import credentials, db
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import *

# ------------------ FIREBASE ------------------
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'YOUR_FIREBASE_DB_URL'
})

def get_user(user_id):
    ref = db.reference(f"users/{user_id}")
    return ref.get()

def update_user(user_id, data):
    ref = db.reference(f"users/{user_id}")
    ref.update(data)

# ------------------ BOT ------------------
app = Client("smm_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------ START ------------------
@app.on_message(filters.command("start"))
async def start(client, message):
    user_id = message.from_user.id
    args = message.text.split(" ")

    if not get_user(user_id):
        update_user(user_id, {
            "bot_balance": 0,
            "web_balance": 0,
            "referrals": 0,
            "banned": False
        })

        # referral
        if len(args) > 1 and args[1].startswith("ref_"):
            ref_id = int(args[1].split("_")[1])
            if ref_id != user_id:
                ref_user = get_user(ref_id)
                if ref_user:
                    db.reference(f"users/{ref_id}/bot_balance").set(ref_user["bot_balance"] + 0.25)
                    db.reference(f"users/{ref_id}/referrals").set(ref_user["referrals"] + 1)

                    await client.send_message(ref_id, "🎉 You referred a new user! +₹0.25")

    buttons = [
        [InlineKeyboardButton("📢 Join Channel 1", url=f"https://t.me/{CHANNELS[0][1:]}")],
        [InlineKeyboardButton("📢 Join Channel 2", url=f"https://t.me/{CHANNELS[1][1:]}")],
        [InlineKeyboardButton("📢 Join Channel 3", url=f"https://t.me/{CHANNELS[2][1:]}")],
        [InlineKeyboardButton("🔒 Private Channel", url=PRIVATE_CHANNEL)],
        [InlineKeyboardButton("✅ Verify & Start", callback_data="verify")]
    ]

    await message.reply("Join all channels to continue", reply_markup=InlineKeyboardMarkup(buttons))

# ------------------ VERIFY ------------------
@app.on_callback_query(filters.regex("verify"))
async def verify(client, callback_query):
    user_id = callback_query.from_user.id

    for ch in CHANNELS:
        member = await client.get_chat_member(ch, user_id)
        if member.status == "left":
            return await callback_query.answer("Join all channels!", show_alert=True)

    await callback_query.message.edit("✅ Verified!", reply_markup=main_menu())

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Social Media Services", url=WEB_APP_URL)],
        [InlineKeyboardButton("♻️ Add Fund", callback_data="addfund")],
        [InlineKeyboardButton("💰 Refer & Earn", callback_data="refer")],
        [InlineKeyboardButton("🪙 Earn Money", callback_data="earn")],
        [InlineKeyboardButton("📦 Order Status", callback_data="order")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("💳 My Balance", callback_data="balance")],
        [InlineKeyboardButton("📖 How to Use", callback_data="how")]
    ])

# ------------------ ADD FUND ------------------
user_states = {}

@app.on_callback_query(filters.regex("addfund"))
async def addfund(client, callback_query):
    user_states[callback_query.from_user.id] = "amount"
    await callback_query.message.reply("Enter amount:")

@app.on_message(filters.text)
async def handle_amount(client, message):
    user_id = message.from_user.id

    if user_states.get(user_id) == "amount":
        amount = message.text

        upi_link = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amount}&cu=INR"
        qr = qrcode.make(upi_link)
        file = f"{user_id}.png"
        qr.save(file)

        user_states[user_id] = "screenshot"

        await message.reply_photo(file, caption=f"Pay ₹{amount} and send screenshot")

    elif user_states.get(user_id) == "screenshot":
        await app.send_photo(PAYMENT_CHANNEL, message.photo.file_id,
                             caption=f"Payment from {message.from_user.mention}")
        await app.send_photo(ADMIN_ID, message.photo.file_id,
                             caption=f"Payment from {message.from_user.mention}")
        user_states[user_id] = None
        await message.reply("✅ Sent for verification")

# ------------------ REFER ------------------
@app.on_callback_query(filters.regex("refer"))
async def refer(client, callback_query):
    user_id = callback_query.from_user.id
    link = f"https://t.me/{(await app.get_me()).username}?start=ref_{user_id}"

    await callback_query.message.reply(f"Your link:\n{link}\nEarn ₹0.25 per refer")

# ------------------ BALANCE ------------------
@app.on_callback_query(filters.regex("balance"))
async def balance(client, callback_query):
    user = get_user(callback_query.from_user.id)

    await callback_query.message.reply(
        f"🤖 Bot: ₹{user['bot_balance']}\n🌐 Web: ₹{user['web_balance']}"
    )

# ------------------ WITHDRAW ------------------
@app.on_callback_query(filters.regex("withdraw"))
async def withdraw(client, callback_query):
    user_states[callback_query.from_user.id] = "withdraw"
    await callback_query.message.reply("Enter amount (min ₹2):")

@app.on_message(filters.text)
async def withdraw_amount(client, message):
    user_id = message.from_user.id

    if user_states.get(user_id) == "withdraw":
        amount = float(message.text)
        user = get_user(user_id)

        if user["bot_balance"] < amount or amount < 2:
            return await message.reply("❌ Not enough balance")

        await app.send_message(PAYMENT_CHANNEL,
                               f"Withdraw Request\nUser: {user_id}\nAmount: ₹{amount}")
        await app.send_message(ADMIN_ID,
                               f"Withdraw Request\nUser: {user_id}\nAmount: ₹{amount}")

        user_states[user_id] = None
        await message.reply("✅ Request sent")

# ------------------ COUPON ------------------
@app.on_message(filters.command("gen") & filters.user(ADMIN_ID))
async def gen_coupon(client, message):
    amount = int(message.command[1])
    code = "NEXA" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

    db.reference(f"coupons/{code}").set({"amount": amount, "used": False})

    await message.reply(f"Code: {code} ₹{amount}")

@app.on_message(filters.command("redeem"))
async def redeem(client, message):
    code = message.command[1]
    ref = db.reference(f"coupons/{code}")
    data = ref.get()

    if not data or data["used"]:
        return await message.reply("Invalid code")

    user = get_user(message.from_user.id)
    db.reference(f"users/{message.from_user.id}/bot_balance").set(user["bot_balance"] + data["amount"])
    ref.update({"used": True})

    await message.reply(f"✅ ₹{data['amount']} added")

# ------------------ ADMIN ------------------
@app.on_message(filters.command("addfunds") & filters.user(ADMIN_ID))
async def addfunds(client, message):
    uid = int(message.command[1])
    amount = float(message.command[2])

    user = get_user(uid)
    db.reference(f"users/{uid}/web_balance").set(user["web_balance"] + amount)

    await app.send_message(uid, f"✅ ₹{amount} added to web balance")

# ------------------ RUN ------------------
app.run()
