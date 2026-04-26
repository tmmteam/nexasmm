import os
import qrcode
import firebase_admin
from firebase_admin import credentials, db
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import *

# ---------------- FIREBASE SETUP ----------------
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

def get_user(uid):
    return db.reference(f"users/{uid}").get()

def update_user(uid, data):
    db.reference(f"users/{uid}").update(data)

# ---------------- BOT INIT ----------------
app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# User states
user_state = {}          # tracks user's current step
pending_payments = {}    # uid -> {amount, admin_msgs, handled, handled_by, user_name}
admin_state = {}         # admin_id -> {action: "accept_amount", user_id}

# ---------------- START (force join) ----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    uid = message.from_user.id
    args = message.text.split()

    if not get_user(uid):
        update_user(uid, {
            "bot_balance": 0,
            "web_balance": 0,
            "referrals": 0,
            "banned": False
        })

        if len(args) > 1 and args[1].startswith("ref_"):
            ref_id = int(args[1].split("_")[1])
            if ref_id != uid:
                ref_user = get_user(ref_id)
                if ref_user:
                    db.reference(f"users/{ref_id}/bot_balance").set(ref_user["bot_balance"] + 0.25)
                    db.reference(f"users/{ref_id}/referrals").set(ref_user["referrals"] + 1)
                    await app.send_message(ref_id, "🎉 New referral! +₹0.25 in your bot balance.")
                    await message.reply(f"✅ You were referred by user {ref_id}")

    join_buttons = [
        [InlineKeyboardButton("📢 Join Channel 1", url=f"https://t.me/{CHANNELS[0][1:]}")],
        [InlineKeyboardButton("📢 Join Channel 2", url=f"https://t.me/{CHANNELS[1][1:]}")],
        [InlineKeyboardButton("📢 Join Channel 3", url=f"https://t.me/{CHANNELS[2][1:]}")],
        [InlineKeyboardButton("🔒 Private Group", url=PRIVATE_CHANNEL)],
        [InlineKeyboardButton("✅ Verify & Start", callback_data="verify")]
    ]
    await message.reply("⚠️ Please join all channels first.", reply_markup=InlineKeyboardMarkup(join_buttons))

# ---------------- VERIFY ----------------
@app.on_callback_query(filters.regex("verify"))
async def verify(client, cb):
    uid = cb.from_user.id
    for ch in CHANNELS:
        try:
            member = await app.get_chat_member(ch, uid)
            if member.status == "left":
                return await cb.answer("❌ You must join all channels!", show_alert=True)
        except:
            return await cb.answer("⚠️ Could not verify. Try again later.", show_alert=True)

    await cb.message.edit("✅ Verified! Welcome to the bot.", reply_markup=main_menu())

# ---------------- MAIN MENU (2 per row) ----------------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 SMM Services", web_app=WebAppInfo(url=WEB_URL)),
         InlineKeyboardButton("📦 Order Status", callback_data="order")],
        [InlineKeyboardButton("♻️ Add Fund", callback_data="add"),
         InlineKeyboardButton("💸 Withdraw", callback_data="wd")],
        [InlineKeyboardButton("💰 Refer & Earn", callback_data="ref"),
         InlineKeyboardButton("🪙 Earn Money", callback_data="earn")],
        [InlineKeyboardButton("💳 My Balance", callback_data="bal"),
         InlineKeyboardButton("📖 How to Use", callback_data="how")]
    ])

# ---------------- CALLBACK HANDLERS (menu buttons) ----------------
@app.on_callback_query(filters.regex("add"))
async def add_fund_start(client, cb):
    user_state[cb.from_user.id] = "add_amount"
    await cb.message.reply("💳 Enter the amount you want to add:")

@app.on_callback_query(filters.regex("ref"))
async def referral(client, cb):
    bot = await app.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{cb.from_user.id}"
    await cb.message.reply(f"🔗 Your referral link:\n{link}\n\nEarn ₹0.25 per referral!")

@app.on_callback_query(filters.regex("earn"))
async def earn_info(client, cb):
    await cb.message.reply("💰 Earn ₹500-700/day using our SMM methods. (Details here...)")

@app.on_callback_query(filters.regex("bal"))
async def balance(client, cb):
    user = get_user(cb.from_user.id)
    await cb.message.reply(f"🤖 **Bot Balance:** ₹{user['bot_balance']}\n🌐 **Web Balance:** ₹{user['web_balance']}")

@app.on_callback_query(filters.regex("wd"))
async def withdraw_start(client, cb):
    user_state[cb.from_user.id] = "wd"
    await cb.message.reply("💸 Enter the amount you want to withdraw (min ₹2):")

@app.on_callback_query(filters.regex("order"))
async def order_status(client, cb):
    await cb.message.reply("📦 Order status will be available soon via the web app.")

@app.on_callback_query(filters.regex("how"))
async def how_to_use(client, cb):
    await cb.message.reply(
        "📖 **How to Use**\n\n"
        "1. Add funds using UPI.\n"
        "2. Buy SMM services from the Web App.\n"
        "3. Check order status & balance here.\n"
        "4. Withdraw when balance reaches ₹2."
    )

# ---------------- ADD FUND: DONE / CANCEL buttons after QR ----------------
@app.on_callback_query(filters.regex(r"pay_done_(\d+)"))
async def pay_done(client, cb):
    uid = int(cb.matches[0].group(1))
    if uid != cb.from_user.id:
        return await cb.answer("⛔ This is not for you.", show_alert=True)

    user_state[uid] = "awaiting_ss"
    await cb.message.delete()
    await app.send_message(uid, "📸 Please send a screenshot of your successful payment.")

@app.on_callback_query(filters.regex(r"pay_cancel_(\d+)"))
async def pay_cancel(client, cb):
    uid = int(cb.matches[0].group(1))
    if uid != cb.from_user.id:
        return await cb.answer("⛔ This is not for you.", show_alert=True)

    user_state.pop(uid, None)
    await cb.message.delete()
    await app.send_message(uid, "❌ Payment cancelled.")

# ---------------- SCREENSHOT HANDLER -> admins DM ----------------
@app.on_message(filters.photo)
async def handle_screenshot(client, msg):
    uid = msg.from_user.id
    if user_state.get(uid) != "awaiting_ss":
        return

    payment = pending_payments.pop(uid, None)
    if not payment:
        await msg.reply("⚠️ Session expired. Please start add fund again.")
        user_state.pop(uid, None)
        return

    amount = payment["amount"]
    try:
        user_info = await app.get_users(uid)
        name = user_info.first_name or f"User{uid}"
    except:
        name = f"User{uid}"

    caption = (
        f"💰 **New Payment Request**\n"
        f"👤 User: {name} ({uid})\n"
        f"💵 Amount: ₹{amount}\n\n"
        f"Please verify and click:"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Accept", callback_data=f"accept_{uid}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_{uid}")]
    ])

    # Send to each admin's DM
    admin_msg_ids = {}
    for admin_id in ADMIN_IDS:
        try:
            sent = await app.send_photo(admin_id, msg.photo.file_id,
                                        caption=caption, reply_markup=buttons)
            admin_msg_ids[admin_id] = sent.id
        except Exception as e:
            print(f"Failed to send to admin {admin_id}: {e}")

    pending_payments[uid] = {
        "amount": amount,
        "admin_msgs": admin_msg_ids,
        "handled": False,
        "handled_by": None,
        "user_name": name
    }

    await msg.reply("⏳ Your payment is being verified. We'll update you shortly.")
    user_state.pop(uid, None)

# ---------------- ADMIN ACCEPT / REJECT CALLBACKS ----------------
@app.on_callback_query(filters.regex(r"accept_(\d+)"))
async def admin_accept(client, cb):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer("⛔ Unauthorized", show_alert=True)

    uid = int(cb.matches[0].group(1))
    payment = pending_payments.get(uid)
    if not payment:
        return await cb.answer("⚠️ Request expired or already handled.", show_alert=True)
    if payment["handled"]:
        return await cb.answer("⚠️ Already handled by another admin.", show_alert=True)

    payment["handled"] = True
    payment["handled_by"] = cb.from_user.id

    admin_state[cb.from_user.id] = {"action": "accept_amount", "user_id": uid}
    await cb.answer("Please enter the amount the user paid.", show_alert=True)
    await app.send_message(cb.from_user.id, f"✍️ Enter the exact amount paid by user {uid}:")

@app.on_callback_query(filters.regex(r"reject_(\d+)"))
async def admin_reject(client, cb):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer("⛔ Unauthorized", show_alert=True)

    uid = int(cb.matches[0].group(1))
    payment = pending_payments.get(uid)
    if not payment:
        return await cb.answer("⚠️ Request already handled.", show_alert=True)
    if payment["handled"]:
        return await cb.answer("⚠️ Already handled by another admin.", show_alert=True)

    payment["handled"] = True
    payment["handled_by"] = cb.from_user.id
    payment["status"] = "rejected"

    for admin_id, msg_id in payment.get("admin_msgs", {}).items():
        try:
            await app.edit_message_caption(
                admin_id, msg_id,
                caption=cb.message.caption.markdown + "\n\n❌ **Rejected by admin**"
            )
            await app.edit_message_reply_markup(admin_id, msg_id, reply_markup=None)
        except:
            pass

    await app.send_message(uid, "❌ Your payment has been rejected. Please try again.")
    pending_payments.pop(uid, None)
    await cb.answer("Rejected!")

# ---------------- ADMIN AMOUNT INPUT (after accept) ----------------
@app.on_message(filters.text & filters.user(ADMIN_IDS))
async def admin_amount_input(client, msg):
    admin_id = msg.from_user.id
    state = admin_state.get(admin_id)
    if not state or state["action"] != "accept_amount":
        return

    uid = state["user_id"]
    payment = pending_payments.get(uid)
    if not payment:
        del admin_state[admin_id]
        return await msg.reply("⚠️ Payment request no longer exists.")

    try:
        amt = float(msg.text)
    except:
        return await msg.reply("❌ Invalid amount. Please enter a number.")

    # Update web balance
    user = get_user(uid)
    update_user(uid, {"web_balance": user["web_balance"] + amt})

    # Edit admin DMs
    for admin_id_iter, msg_id_iter in payment.get("admin_msgs", {}).items():
        try:
            await app.edit_message_caption(
                admin_id_iter, msg_id_iter,
                caption=f"✅ **Accepted by admin {admin_id}**\n"
                        f"Amount: ₹{amt}"
            )
            await app.edit_message_reply_markup(admin_id_iter, msg_id_iter, reply_markup=None)
        except:
            pass

    # Log to payment channel
    try:
        await app.send_message(
            PAYMENT_CHANNEL,
            f"✅ **Payment Verified**\n"
            f"👤 User: {payment['user_name']} ({uid})\n"
            f"💵 Amount: ₹{amt}"
        )
    except Exception as e:
        print("Failed to send to payment channel:", e)

    # Notify user
    await app.send_message(uid, f"✅ Your payment of ₹{amt} has been approved!\nFunds added to your Web Balance.")

    # Cleanup
    pending_payments.pop(uid, None)
    admin_state.pop(admin_id, None)
    await msg.reply("✅ Done.")

# ---------------- TEXT HANDLER (add amount / withdraw) ----------------
@app.on_message(filters.text)
async def text_handler(client, msg):
    uid = msg.from_user.id
    state = user_state.get(uid)

    # Add fund: entering amount
    if state == "add_amount":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("❌ Please enter a valid number.")

        # Generate QR code with EXACT amount user entered
        upi_string = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amt}&cu=INR"
        qr = qrcode.make(upi_string)
        file_path = f"qr_{uid}.png"
        qr.save(file_path)

        pending_payments[uid] = {"amount": amt, "admin_msgs": {}, "handled": False, "user_name": ""}

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Done", callback_data=f"pay_done_{uid}"),
             InlineKeyboardButton("❌ Cancel", callback_data=f"pay_cancel_{uid}")]
        ])

        await msg.reply_photo(
            photo=file_path,
            caption=f"💳 Scan the QR to pay ₹{amt}.\nThen press **Done** and upload screenshot.",
            reply_markup=buttons
        )
        os.remove(file_path)
        user_state[uid] = "qr_sent"

    # Withdraw amount input
    elif state == "wd":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("❌ Invalid amount.")

        user = get_user(uid)
        if amt < 2:
            return await msg.reply("❌ Minimum withdrawal is ₹2.")
        if user["bot_balance"] < amt:
            return await msg.reply("❌ Insufficient bot balance.")

        await app.send_message(
            PAYMENT_CHANNEL,
            f"🚨 **Withdrawal Request**\n"
            f"👤 User ID: {uid}\n"
            f"💸 Amount: ₹{amt}"
        )
        await msg.reply("✅ Withdrawal request sent. You will be notified when processed.")
        user_state.pop(uid, None)

    elif state == "awaiting_ss":
        await msg.reply("📸 Please send a **photo** (screenshot), not text.")
    else:
        pass

# ---------------- ADMIN DIRECT FUND ADD (backup) ----------------
@app.on_message(filters.command("addfunds") & filters.user(ADMIN_IDS))
async def add_funds_direct(client, msg):
    try:
        uid = int(msg.command[1])
        amt = float(msg.command[2])
    except:
        return await msg.reply("Usage: /addfunds <user_id> <amount>")

    user = get_user(uid)
    if not user:
        return await msg.reply("User not found.")
    update_user(uid, {"web_balance": user["web_balance"] + amt})
    await app.send_message(uid, f"✅ ₹{amt} added to your balance by admin.")
    await msg.reply("✅ Done.")

# ---------------- RUN ----------------
app.run()
