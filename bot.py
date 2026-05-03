import os
import sys
import logging
import qrcode
import firebase_admin
from firebase_admin import credentials, db
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import *

# ---------------- LOGGING SETUP (Console + File) ----------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(console_handler)

logger.info("Bot starting...")

# ---------------- CONFIG VALIDATION ----------------
if not hasattr(sys.modules[__name__], 'CHANNELS') or len(CHANNELS) < 3:
    logger.error("CHANNELS must have at least 3 entries!")
    sys.exit(1)
for ch in CHANNELS:
    if not ch.startswith('@'):
        logger.error(f"CHANNEL entry '{ch}' does not start with '@'")
        sys.exit(1)

# WELCOME_IMAGE ab required nahi
required_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'DB_URL', 'TELEGRAPH_URL', 'UPI_ID', 'UPI_NAME', 'ADMIN_IDS', 'PAYMENT_CHANNEL']
for var in required_vars:
    if var not in dir():
        logger.error(f"Missing config variable: {var}")
        sys.exit(1)

logger.info("Config validation passed.")

# ---------------- FIREBASE SETUP ----------------
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})
    logger.info("Firebase initialized.")
except Exception as e:
    logger.error(f"Firebase init failed: {e}")
    sys.exit(1)

def get_user(uid):
    try:
        return db.reference(f"nexa/users/{uid}").get()
    except Exception as e:
        logger.error(f"get_user failed for {uid}: {e}")
        return None

def update_user(uid, data):
    try:
        db.reference(f"nexa/users/{uid}").update(data)
    except Exception as e:
        logger.error(f"update_user failed for {uid}: {e}")

def transaction_add_web_balance(uid, amt):
    def transact(current):
        if current is None:
            return amt
        return current + amt
    try:
        db.reference(f"nexa/users/{uid}/web_balance").transaction(transact)
        return True
    except Exception as e:
        logger.error(f"Transaction add failed: {e}")
        return False

def transaction_deduct_web_balance(uid, amt):
    def transact(current):
        if current is None or current < amt:
            raise ValueError("Insufficient balance")
        return current - amt
    try:
        db.reference(f"nexa/users/{uid}/web_balance").transaction(transact)
        return True
    except Exception as e:
        logger.error(f"Transaction deduct failed: {e}")
        return False

# ---------------- BOT INIT ----------------
app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_state = {}
pending_payments = {}
admin_state = {}

# ---------------- PING COMMAND ----------------
@app.on_message(filters.command("ping"))
async def ping(client, message):
    await message.reply("🏓 Pong! Bot is alive.")
    logger.info(f"Ping from {message.from_user.id}")

# ---------------- START ----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    uid = message.from_user.id
    logger.info(f"/start from {uid}")

    try:
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
                        db.reference(f"nexa/users/{ref_id}/bot_balance").set(ref_user["bot_balance"] + 0.25)
                        db.reference(f"nexa/users/{ref_id}/referrals").set(ref_user["referrals"] + 1)
                        await app.send_message(ref_id, "🎉 New referral! +₹0.25 in your bot balance.")
                        await message.reply(f"✅ You were referred by user {ref_id}")

        user = get_user(uid)
        if user and user.get("banned"):
            return await message.reply("⛔ You are banned from using this bot.")

        join_buttons = [
            [InlineKeyboardButton("📢 Join Channel 1", url=f"https://t.me/{CHANNELS[0][1:]}")],
            [InlineKeyboardButton("📢 Join Channel 2", url=f"https://t.me/{CHANNELS[1][1:]}")],
            [InlineKeyboardButton("📢 Join Channel 3", url=f"https://t.me/{CHANNELS[2][1:]}")],
            [InlineKeyboardButton("🔒 Private Group", url=PRIVATE_CHANNEL)],
            [InlineKeyboardButton("✅ Verify & Start", callback_data="verify")]
        ]
        await message.reply(
            "⚠️ Please join all channels first.",
            reply_markup=InlineKeyboardMarkup(join_buttons)
        )
        logger.info(f"/start handled for {uid}")

    except Exception as e:
        logger.error(f"Error in start handler for {uid}: {e}", exc_info=True)
        await message.reply("❌ An internal error occurred. Please try again later.")

# ---------------- VERIFY (NO IMAGE) ----------------
@app.on_callback_query(filters.regex("verify"))
async def verify(client, cb):
    uid = cb.from_user.id
    user = get_user(uid)
    if user and user.get("banned"):
        await cb.answer("You are banned!", show_alert=True)
        return

    for ch in CHANNELS:
        try:
            member = await app.get_chat_member(ch, uid)
            if member.status == "left":
                return await cb.answer("❌ You must join all channels!", show_alert=True)
        except:
            return await cb.answer("⚠️ Could not verify. Try again later.", show_alert=True)

    # Direct welcome text, no photo
    await cb.message.reply(
        f"✅ Welcome! You're verified now.\n\n📖 Full guide & info: {TELEGRAPH_URL}",
        reply_markup=main_menu(uid)
    )
    await cb.message.delete()

# ---------------- MAIN MENU ----------------
def main_menu(uid):
    buttons = [
        [InlineKeyboardButton("🚀 SMM Services", web_app=WebAppInfo(url=WEB_URL)),
         InlineKeyboardButton("📦 Order Status", callback_data="order")],
        [InlineKeyboardButton("♻️ Add Fund", callback_data="add"),
         InlineKeyboardButton("💸 Withdraw", callback_data="wd")],
        [InlineKeyboardButton("💰 Refer & Earn", callback_data="ref"),
         InlineKeyboardButton("🪙 Earn Money", callback_data="earn")],
        [InlineKeyboardButton("💳 My Balance", callback_data="bal"),
         InlineKeyboardButton("📖 How to Use", callback_data="how")]
    ]
    if uid in ADMIN_IDS:
        buttons.append([InlineKeyboardButton("🛡 Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

# ---------------- MENU CALLBACKS ----------------
@app.on_callback_query(filters.regex("add"))
async def add_fund_start(client, cb):
    uid = cb.from_user.id
    user = get_user(uid)
    if user and user.get("banned"):
        return await cb.answer("You are banned!", show_alert=True)
    user_state[uid] = "add_amount"
    await cb.message.reply("💳 **Enter the amount you want to add:**", parse_mode="markdown")

@app.on_callback_query(filters.regex("ref"))
async def referral(client, cb):
    bot = await app.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{cb.from_user.id}"
    await cb.message.reply(
        f"🔗 **Your referral link:**\n`{link}`\n\nEarn ₹0.25 per referral!",
        parse_mode="markdown"
    )

@app.on_callback_query(filters.regex("earn"))
async def earn_info(client, cb):
    await cb.message.reply("💰 Earn ₹500-700/day using our SMM methods. (Details here...)", parse_mode="markdown")

@app.on_callback_query(filters.regex("bal"))
async def balance(client, cb):
    user = get_user(cb.from_user.id)
    bot_bal = user.get("bot_balance", 0) if user else 0
    web_bal = user.get("web_balance", 0) if user else 0
    await cb.message.reply(
        f"🤖 **Bot Balance:** ₹{bot_bal}\n🌐 **Web Balance:** ₹{web_bal}",
        parse_mode="markdown"
    )

@app.on_callback_query(filters.regex("wd"))
async def withdraw_start(client, cb):
    uid = cb.from_user.id
    user = get_user(uid)
    if user and user.get("banned"):
        return await cb.answer("You are banned!", show_alert=True)
    user_state[uid] = "wd"
    await cb.message.reply("💸 **Enter amount to withdraw (min ₹2):**", parse_mode="markdown")

@app.on_callback_query(filters.regex("order"))
async def order_status(client, cb):
    await cb.message.reply("📦 Order status will be available soon via the web app.", parse_mode="markdown")

@app.on_callback_query(filters.regex("how"))
async def how_to_use(client, cb):
    await cb.message.reply(
        "📖 **How to Use**\n\n"
        "1. Add funds using UPI.\n"
        "2. Buy SMM services from the Web App.\n"
        "3. Check order status & balance here.\n"
        "4. Withdraw when balance reaches ₹2.",
        parse_mode="markdown"
    )

# ---------------- ADMIN PANEL ----------------
@app.on_callback_query(filters.regex("admin_panel"))
async def admin_panel(client, cb):
    if cb.from_user.id not in ADMIN_IDS:
        return await cb.answer("⛔ Unauthorized", show_alert=True)

    buttons = [
        [InlineKeyboardButton("📄 User List", callback_data="admin_userlist"),
         InlineKeyboardButton("📋 Bot Logs", callback_data="admin_logs")],
        [InlineKeyboardButton("💰 Add Funds", callback_data="admin_addfunds"),
         InlineKeyboardButton("💸 Deduct Funds", callback_data="admin_deduct")],
        [InlineKeyboardButton("🔨 Ban User", callback_data="admin_ban"),
         InlineKeyboardButton("🔓 Unban User", callback_data="admin_unban")],
        [InlineKeyboardButton("⬅ Back to Menu", callback_data="admin_back")]
    ]
    await cb.message.edit("🛡 **Admin Panel**", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="markdown")

@app.on_callback_query(filters.regex("admin_back"))
async def admin_back(client, cb):
    await cb.message.edit("✅ Main Menu", reply_markup=main_menu(cb.from_user.id), parse_mode="markdown")

@app.on_callback_query(filters.regex("admin_userlist"))
async def admin_userlist(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔")
    users_ref = db.reference("nexa/users").get()
    if not users_ref:
        return await cb.message.reply("No users found.")
    lines = []
    for uid, data in users_ref.items():
        lines.append(f"UID: {uid} | Bot: ₹{data.get('bot_balance',0)} | Web: ₹{data.get('web_balance',0)} | Refs: {data.get('referrals',0)} | Banned: {data.get('banned',False)}")
    text = "\n".join(lines)
    if len(text) > 4000:
        with open("userlist.txt", "w") as f:
            f.write(text)
        await cb.message.reply_document("userlist.txt", caption="📄 User List")
        os.remove("userlist.txt")
    else:
        await cb.message.reply(f"**User List:**\n{text}", parse_mode="markdown")

@app.on_callback_query(filters.regex("admin_logs"))
async def admin_logs(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔")
    try:
        await cb.message.reply_document(LOG_FILE, caption="📋 Bot Logs")
    except:
        await cb.message.reply("Log file not found.", parse_mode="markdown")

@app.on_callback_query(filters.regex("admin_addfunds"))
async def admin_addfunds_start(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔")
    admin_state[cb.from_user.id] = {"action": "addfunds_input"}
    await cb.message.reply("✍️ **Enter `user_id amount`** (e.g. `9389373 50`):", parse_mode="markdown")

@app.on_callback_query(filters.regex("admin_deduct"))
async def admin_deduct_start(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔")
    admin_state[cb.from_user.id] = {"action": "deduct_input"}
    await cb.message.reply("✍️ **Enter `user_id amount` to deduct:**", parse_mode="markdown")

@app.on_callback_query(filters.regex("admin_ban"))
async def admin_ban_start(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔")
    admin_state[cb.from_user.id] = {"action": "ban_input"}
    await cb.message.reply("✍️ **Enter user ID to ban:**", parse_mode="markdown")

@app.on_callback_query(filters.regex("admin_unban"))
async def admin_unban_start(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔")
    admin_state[cb.from_user.id] = {"action": "unban_input"}
    await cb.message.reply("✍️ **Enter user ID to unban:**", parse_mode="markdown")

# ---------------- ADD FUND QR / PAYMENT FLOW ----------------
@app.on_callback_query(filters.regex(r"pay_done_(\d+)"))
async def pay_done(client, cb):
    uid = int(cb.matches[0].group(1))
    if uid != cb.from_user.id:
        return await cb.answer("⛔ This is not for you.", show_alert=True)
    user_state[uid] = "awaiting_ss"
    await cb.message.delete()
    await app.send_message(uid, "📸 **Send a screenshot of your successful payment.**", parse_mode="markdown")

@app.on_callback_query(filters.regex(r"pay_cancel_(\d+)"))
async def pay_cancel(client, cb):
    uid = int(cb.matches[0].group(1))
    if uid != cb.from_user.id:
        return await cb.answer("⛔ This is not for you.", show_alert=True)
    user_state.pop(uid, None)
    await cb.message.delete()
    await app.send_message(uid, "❌ Payment cancelled.", parse_mode="markdown")

@app.on_message(filters.photo)
async def handle_screenshot(client, msg):
    uid = msg.from_user.id
    if user_state.get(uid) != "awaiting_ss":
        return
    payment = pending_payments.pop(uid, None)
    if not payment:
        await msg.reply("⚠️ Session expired. Please start add fund again.", parse_mode="markdown")
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

    admin_msg_ids = {}
    for admin_id in ADMIN_IDS:
        try:
            sent = await app.send_photo(admin_id, msg.photo.file_id,
                                        caption=caption, reply_markup=buttons, parse_mode="markdown")
            admin_msg_ids[admin_id] = sent.id
        except Exception as e:
            logger.error(f"Failed to send to admin {admin_id}: {e}")

    pending_payments[uid] = {
        "amount": amount,
        "admin_msgs": admin_msg_ids,
        "handled": False,
        "handled_by": None,
        "user_name": name
    }
    await msg.reply("⏳ Your payment is being verified. We'll update you shortly.", parse_mode="markdown")
    user_state.pop(uid, None)

@app.on_callback_query(filters.regex(r"accept_(\d+)"))
async def accept_payment(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    uid = int(cb.matches[0].group(1))
    payment = pending_payments.get(uid)
    if not payment or payment["handled"]:
        return await cb.answer("⚠️ Already handled or expired.", show_alert=True)

    payment["handled"] = True
    payment["handled_by"] = cb.from_user.id
    admin_state[cb.from_user.id] = {"action": "accept_amount", "user_id": uid}
    await cb.answer("Enter amount the user paid.", show_alert=True)
    await app.send_message(cb.from_user.id, f"✍️ **Enter the exact amount paid by user {uid}:**", parse_mode="markdown")

@app.on_callback_query(filters.regex(r"reject_(\d+)"))
async def reject_payment(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    uid = int(cb.matches[0].group(1))
    payment = pending_payments.get(uid)
    if not payment or payment["handled"]:
        return await cb.answer("⚠️ Already handled.", show_alert=True)

    payment["handled"] = True
    for admin_id, msg_id in payment.get("admin_msgs", {}).items():
        try:
            await app.edit_message_caption(admin_id, msg_id,
                caption=cb.message.caption.markdown + "\n\n❌ **Rejected by admin**",
                parse_mode="markdown")
            await app.edit_message_reply_markup(admin_id, msg_id, reply_markup=None)
        except: pass
    await app.send_message(uid, "❌ Your payment has been rejected. Please try again.", parse_mode="markdown")
    pending_payments.pop(uid, None)
    await cb.answer("Rejected!")

@app.on_message(filters.text & filters.user(ADMIN_IDS))
async def admin_text_handler(client, msg):
    admin_id = msg.from_user.id
    state = admin_state.get(admin_id)

    if not state:
        return await msg.continue_propagation()

    action = state["action"]

    if action == "accept_amount":
        uid = state["user_id"]
        payment = pending_payments.get(uid)
        if not payment:
            del admin_state[admin_id]
            return await msg.reply("⚠️ Payment request no longer exists.", parse_mode="markdown")
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("❌ Invalid amount. Enter a number.", parse_mode="markdown")

        if not transaction_add_web_balance(uid, amt):
            return await msg.reply("❌ Transaction failed. Try again.", parse_mode="markdown")

        for admin_id_iter, msg_id_iter in payment.get("admin_msgs", {}).items():
            try:
                await app.edit_message_caption(admin_id_iter, msg_id_iter,
                    caption=f"✅ **Accepted by admin {admin_id}**\nAmount: ₹{amt}",
                    parse_mode="markdown")
                await app.edit_message_reply_markup(admin_id_iter, msg_id_iter, reply_markup=None)
            except: pass

        try:
            await app.send_message(PAYMENT_CHANNEL,
                f"✅ **Payment Verified**\n👤 User: {payment['user_name']} ({uid})\n💵 Amount: ₹{amt}",
                parse_mode="markdown")
        except Exception as e:
            logger.error(f"Channel post failed: {e}")

        await app.send_message(uid,
            f"✅ Your payment of ₹{amt} has been approved!\nFunds added to your Web Balance.",
            parse_mode="markdown")

        pending_payments.pop(uid, None)
        admin_state.pop(admin_id, None)
        await msg.reply("✅ Done.", parse_mode="markdown")
        return

    elif action == "addfunds_input":
        parts = msg.text.strip().split()
        if len(parts) != 2:
            return await msg.reply("❌ Format: `user_id amount` (e.g. `12345 50`)", parse_mode="markdown")
        try:
            uid = int(parts[0])
            amt = float(parts[1])
        except:
            return await msg.reply("❌ Invalid numbers.", parse_mode="markdown")
        user = get_user(uid)
        if not user:
            return await msg.reply("User not found.", parse_mode="markdown")
        if transaction_add_web_balance(uid, amt):
            try:
                await app.send_message(uid, f"✅ Admin added ₹{amt} to your Web Balance.", parse_mode="markdown")
            except: pass
            await msg.reply(f"✅ ₹{amt} added to user {uid}.", parse_mode="markdown")
        else:
            await msg.reply("❌ Failed to add funds.", parse_mode="markdown")
        del admin_state[admin_id]
        return

    elif action == "deduct_input":
        parts = msg.text.strip().split()
        if len(parts) != 2:
            return await msg.reply("❌ Format: `user_id amount`", parse_mode="markdown")
        try:
            uid = int(parts[0])
            amt = float(parts[1])
        except:
            return await msg.reply("❌ Invalid numbers.", parse_mode="markdown")
        user = get_user(uid)
        if not user:
            return await msg.reply("User not found.", parse_mode="markdown")
        if user.get("web_balance", 0) < amt:
            return await msg.reply("❌ Insufficient balance.", parse_mode="markdown")
        if transaction_deduct_web_balance(uid, amt):
            try:
                await app.send_message(uid, f"⚠️ Admin deducted ₹{amt} from your Web Balance.", parse_mode="markdown")
            except: pass
            await msg.reply(f"✅ ₹{amt} deducted from user {uid}.", parse_mode="markdown")
        else:
            await msg.reply("❌ Deduction failed.", parse_mode="markdown")
        del admin_state[admin_id]
        return

    elif action == "ban_input":
        try:
            uid = int(msg.text.strip())
        except:
            return await msg.reply("❌ Invalid user ID.", parse_mode="markdown")
        user = get_user(uid)
        if not user:
            return await msg.reply("User not found.", parse_mode="markdown")
        update_user(uid, {"banned": True})
        dm_buttons = []
        for adm in ADMIN_IDS:
            dm_buttons.append(InlineKeyboardButton(f"📩 Admin {adm}", url=f"tg://user?id={adm}"))
        try:
            await app.send_message(uid,
                "⛔ You have been banned from using this bot.\nContact admins:",
                reply_markup=InlineKeyboardMarkup([dm_buttons]),
                parse_mode="markdown")
        except: pass
        await msg.reply(f"✅ User {uid} banned.", parse_mode="markdown")
        del admin_state[admin_id]
        return

    elif action == "unban_input":
        try:
            uid = int(msg.text.strip())
        except:
            return await msg.reply("❌ Invalid user ID.", parse_mode="markdown")
        update_user(uid, {"banned": False})
        await msg.reply(f"✅ User {uid} unbanned.", parse_mode="markdown")
        del admin_state[admin_id]
        return

    else:
        pass

# ---------------- USER TEXT HANDLER (add amount, withdraw) ----------------
@app.on_message(filters.text)
async def user_text_handler(client, msg):
    uid = msg.from_user.id
    user = get_user(uid)
    if user and user.get("banned"):
        return await msg.reply("⛔ You are banned. Contact admin.", parse_mode="markdown")

    state = user_state.get(uid)

    if state == "add_amount":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("❌ Please enter a valid number.", parse_mode="markdown")

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
            caption=f"💳 **Scan the QR to pay ₹{amt}.**\nThen press **Done** and upload screenshot.",
            reply_markup=buttons,
            parse_mode="markdown"
        )
        os.remove(file_path)
        user_state[uid] = "qr_sent"

    elif state == "wd":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("❌ Invalid amount.", parse_mode="markdown")
        if amt < 2:
            return await msg.reply("❌ Minimum withdrawal is ₹2.", parse_mode="markdown")
        user = get_user(uid)
        if user.get("bot_balance", 0) < amt:
            return await msg.reply("❌ Insufficient bot balance.", parse_mode="markdown")
        await app.send_message(PAYMENT_CHANNEL,
            f"🚨 **Withdrawal Request**\n👤 User ID: {uid}\n💸 Amount: ₹{amt}",
            parse_mode="markdown")
        await msg.reply("✅ Withdrawal request sent. You will be notified when processed.", parse_mode="markdown")
        user_state.pop(uid, None)

    elif state == "awaiting_ss":
        await msg.reply("📸 Please send a **photo** (screenshot), not text.", parse_mode="markdown")

# ---------------- RUN ----------------
logger.info("Bot is now running.")
app.run()
