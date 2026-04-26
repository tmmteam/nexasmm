import os
import logging
import qrcode
import firebase_admin
from firebase_admin import credentials, db
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import *

# ---------------- LOGGING SETUP ----------------
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------- FIREBASE SETUP ----------------
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})

def get_user(uid):
    try:
        return db.reference(f"users/{uid}").get()
    except Exception as e:
        logger.error(f"get_user failed for {uid}: {e}")
        return None

def update_user(uid, data):
    try:
        db.reference(f"users/{uid}").update(data)
    except Exception as e:
        logger.error(f"update_user failed for {uid}: {e}")

def transaction_add_web_balance(uid, amt):
    def transact(current):
        if current is None:
            return amt
        return current + amt
    try:
        db.reference(f"users/{uid}/web_balance").transaction(transact)
        return True
    except Exception as e:
        logger.error(f"Transaction failed: {e}")
        return False

def transaction_deduct_web_balance(uid, amt):
    def transact(current):
        if current is None or current < amt:
            raise ValueError("Insufficient balance")
        return current - amt
    try:
        db.reference(f"users/{uid}/web_balance").transaction(transact)
        return True
    except Exception as e:
        logger.error(f"Transaction failed: {e}")
        return False

# ---------------- BOT INIT ----------------
app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# States
user_state = {}          # normal users
pending_payments = {}    # uid -> {amount, admin_msgs, handled, handled_by, user_name}
admin_state = {}         # admin panel flows

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

    # Check if banned
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
    await message.reply("⚠️ Please join all channels first.", reply_markup=InlineKeyboardMarkup(join_buttons))

# ---------------- VERIFY ----------------
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

    # Welcome image + telegraph link
    try:
        await cb.message.reply_photo(
            photo=WELCOME_IMAGE,
            caption=f"✅ Welcome! You're verified now.\n\n📖 Full guide & info: {TELEGRAPH_URL}",
            reply_markup=main_menu(uid)
        )
        await cb.message.delete()  # old join message remove
    except:
        # fallback
        await cb.message.edit("✅ Verified! Welcome to the bot.", reply_markup=main_menu(uid))

# ---------------- MAIN MENU (with admin button if admin) ----------------
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

# ---------------- CALLBACK HANDLERS (menu buttons) ----------------
@app.on_callback_query(filters.regex("add"))
async def add_fund_start(client, cb):
    uid = cb.from_user.id
    user = get_user(uid)
    if user and user.get("banned"):
        return await cb.answer("You are banned!", show_alert=True)
    user_state[uid] = "add_amount"
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
    uid = cb.from_user.id
    user = get_user(uid)
    if user and user.get("banned"):
        return await cb.answer("You are banned!", show_alert=True)
    user_state[uid] = "wd"
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
    await cb.message.edit("🛡 **Admin Panel**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex("admin_back"))
async def admin_back(client, cb):
    await cb.message.edit("✅ Main Menu", reply_markup=main_menu(cb.from_user.id))

# Admin: User list
@app.on_callback_query(filters.regex("admin_userlist"))
async def admin_userlist(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    users_ref = db.reference("users").get()
    if not users_ref:
        await cb.message.reply("No users found.")
        return
    lines = []
    for uid, data in users_ref.items():
        lines.append(f"UID: {uid} | Bot: ₹{data.get('bot_balance',0)} | Web: ₹{data.get('web_balance',0)} | Refs: {data.get('referrals',0)} | Banned: {data.get('banned',False)}")
    text = "\n".join(lines)
    if len(text) > 4000:
        filename = "userlist.txt"
        with open(filename, "w") as f:
            f.write(text)
        await cb.message.reply_document(filename, caption="📄 User List")
        os.remove(filename)
    else:
        await cb.message.reply(f"**User List:**\n{text}")

# Admin: Bot logs
@app.on_callback_query(filters.regex("admin_logs"))
async def admin_logs(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    try:
        await cb.message.reply_document(LOG_FILE, caption="📋 Bot Logs")
    except:
        await cb.message.reply("Log file not found.")

# Admin: Add Funds (manual)
@app.on_callback_query(filters.regex("admin_addfunds"))
async def admin_addfunds_start(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    admin_state[cb.from_user.id] = {"action": "addfunds_uid"}
    await cb.message.reply("Enter user ID:")

# Admin: Deduct Funds
@app.on_callback_query(filters.regex("admin_deduct"))
async def admin_deduct_start(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    admin_state[cb.from_user.id] = {"action": "deduct_uid"}
    await cb.message.reply("Enter user ID:")

# Admin: Ban
@app.on_callback_query(filters.regex("admin_ban"))
async def admin_ban_start(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    admin_state[cb.from_user.id] = {"action": "ban_uid"}
    await cb.message.reply("Enter user ID to ban:")

# Admin: Unban
@app.on_callback_query(filters.regex("admin_unban"))
async def admin_unban_start(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    admin_state[cb.from_user.id] = {"action": "unban_uid"}
    await cb.message.reply("Enter user ID to unban:")

# ---------------- HANDLE ADMIN TEXT INPUTS (two-step flows) ----------------
@app.on_message(filters.text & filters.user(ADMIN_IDS))
async def admin_text_handler(client, msg):
    admin_id = msg.from_user.id
    state = admin_state.get(admin_id)

    # Ignore if admin is also in user_state (e.g., payment flow) but admin text handler catches first because of user filter? 
    # Actually admins are also users, but the order of handlers matters. We have separate admin text handler for admin-specific flows. 
    # We'll manage by checking state only for admin actions.
    if not state:
        return  # not in admin panel flow, could be user text (like add fund) -> ignore here

    action = state.get("action")
    if action == "addfunds_uid":
        try:
            uid = int(msg.text)
        except:
            return await msg.reply("Invalid user ID. Enter numeric ID.")
        state["user_id"] = uid
        state["action"] = "addfunds_amount"
        await msg.reply(f"User ID: {uid}\nNow enter amount to add:")
        return

    if action == "addfunds_amount":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("Invalid amount.")
        uid = state["user_id"]
        user = get_user(uid)
        if not user:
            del admin_state[admin_id]
            return await msg.reply("User not found.")
        # Transaction add
        if transaction_add_web_balance(uid, amt):
            try:
                await app.send_message(uid, f"✅ Admin added ₹{amt} to your Web Balance.")
            except:
                pass
            await msg.reply(f"✅ ₹{amt} added to user {uid}.")
        else:
            await msg.reply("❌ Failed to update balance.")
        del admin_state[admin_id]
        return

    if action == "deduct_uid":
        try:
            uid = int(msg.text)
        except:
            return await msg.reply("Invalid user ID.")
        state["user_id"] = uid
        state["action"] = "deduct_amount"
        await msg.reply(f"User ID: {uid}\nNow enter amount to deduct:")
        return

    if action == "deduct_amount":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("Invalid amount.")
        uid = state["user_id"]
        user = get_user(uid)
        if not user:
            del admin_state[admin_id]
            return await msg.reply("User not found.")
        if user.get("web_balance", 0) < amt:
            return await msg.reply("❌ Insufficient web balance.")
        if transaction_deduct_web_balance(uid, amt):
            try:
                await app.send_message(uid, f"⚠️ Admin deducted ₹{amt} from your Web Balance.")
            except:
                pass
            await msg.reply(f"✅ ₹{amt} deducted from user {uid}.")
        else:
            await msg.reply("❌ Failed to deduct (maybe balance too low).")
        del admin_state[admin_id]
        return

    if action == "ban_uid":
        try:
            uid = int(msg.text)
        except:
            return await msg.reply("Invalid user ID.")
        user = get_user(uid)
        if not user:
            return await msg.reply("User not found.")
        update_user(uid, {"banned": True})
        # Send ban message to user with admin DM links
        try:
            dm_buttons = []
            for adm in ADMIN_IDS:
                dm_buttons.append(InlineKeyboardButton(f"📩 Admin {adm}", url=f"tg://user?id={adm}"))
            await app.send_message(uid,
                "⛔ You have been banned from using this bot.\nContact admins:",
                reply_markup=InlineKeyboardMarkup([dm_buttons])
            )
        except:
            pass
        await msg.reply(f"✅ User {uid} banned.")
        del admin_state[admin_id]
        return

    if action == "unban_uid":
        try:
            uid = int(msg.text)
        except:
            return await msg.reply("Invalid user ID.")
        update_user(uid, {"banned": False})
        await msg.reply(f"✅ User {uid} unbanned.")
        del admin_state[admin_id]
        return

# ---------------- ADD FUND: USER QR & SCREENSHOT FLOW (existing) ----------------
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

    admin_msg_ids = {}
    for admin_id in ADMIN_IDS:
        try:
            sent = await app.send_photo(admin_id, msg.photo.file_id,
                                        caption=caption, reply_markup=buttons)
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
    await msg.reply("⏳ Your payment is being verified. We'll update you shortly.")
    user_state.pop(uid, None)

# ---------------- ADMIN PAYMENT APPROVAL / REJECTION ----------------
@app.on_callback_query(filters.regex(r"accept_(\d+)"))
async def admin_accept(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    uid = int(cb.matches[0].group(1))
    payment = pending_payments.get(uid)
    if not payment or payment["handled"]:
        return await cb.answer("⚠️ Already handled or expired.", show_alert=True)

    payment["handled"] = True
    payment["handled_by"] = cb.from_user.id
    admin_state[cb.from_user.id] = {"action": "accept_amount", "user_id": uid}
    await cb.answer("Enter amount the user paid.", show_alert=True)
    await app.send_message(cb.from_user.id, f"✍️ Enter the exact amount paid by user {uid}:")

@app.on_callback_query(filters.regex(r"reject_(\d+)"))
async def admin_reject(client, cb):
    if cb.from_user.id not in ADMIN_IDS: return await cb.answer("⛔", show_alert=True)
    uid = int(cb.matches[0].group(1))
    payment = pending_payments.get(uid)
    if not payment or payment["handled"]:
        return await cb.answer("⚠️ Already handled.", show_alert=True)

    payment["handled"] = True
    payment["handled_by"] = cb.from_user.id
    for admin_id, msg_id in payment.get("admin_msgs", {}).items():
        try:
            await app.edit_message_caption(admin_id, msg_id,
                caption=cb.message.caption.markdown + "\n\n❌ **Rejected by admin**")
            await app.edit_message_reply_markup(admin_id, msg_id, reply_markup=None)
        except: pass
    await app.send_message(uid, "❌ Your payment has been rejected. Please try again.")
    pending_payments.pop(uid, None)
    await cb.answer("Rejected!")

# ---------------- ADMIN AMOUNT INPUT AFTER ACCEPT (for payment) ----------------
@app.on_message(filters.text & filters.user(ADMIN_IDS))
async def admin_amount_input(client, msg):
    admin_id = msg.from_user.id
    state = admin_state.get(admin_id)
    if not state or state["action"] != "accept_amount":
        return  # let other admin_text_handler handle it, but this filter already fired. We'll check.
    # This handler might clash with the previous admin_text_handler. We'll merge them.
    # We'll move this logic into the main admin_text_handler with additional check.
    pass  # We'll handle inside admin_text_handler below (modified)

# We'll combine both admin text handlers into one with a clear flow.
# Let's rewrite a single unified admin handler.

@app.on_message(filters.text & filters.user(ADMIN_IDS))
async def unified_admin_text_handler(client, msg):
    admin_id = msg.from_user.id
    state = admin_state.get(admin_id)

    if not state:
        return

    action = state.get("action")

    # Payment accept amount entry
    if action == "accept_amount":
        uid = state["user_id"]
        payment = pending_payments.get(uid)
        if not payment:
            del admin_state[admin_id]
            return await msg.reply("⚠️ Payment request no longer exists.")
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("❌ Invalid amount. Please enter a number.")

        # Update balance with transaction
        if not transaction_add_web_balance(uid, amt):
            return await msg.reply("❌ Transaction failed. Try again.")

        for admin_id_iter, msg_id_iter in payment.get("admin_msgs", {}).items():
            try:
                await app.edit_message_caption(admin_id_iter, msg_id_iter,
                    caption=f"✅ **Accepted by admin {admin_id}**\nAmount: ₹{amt}")
                await app.edit_message_reply_markup(admin_id_iter, msg_id_iter, reply_markup=None)
            except: pass

        try:
            await app.send_message(PAYMENT_CHANNEL,
                f"✅ **Payment Verified**\n👤 User: {payment['user_name']} ({uid})\n💵 Amount: ₹{amt}")
        except Exception as e:
            logger.error(f"Channel post failed: {e}")

        await app.send_message(uid, f"✅ Your payment of ₹{amt} has been approved!\nFunds added to your Web Balance.")

        pending_payments.pop(uid, None)
        admin_state.pop(admin_id, None)
        await msg.reply("✅ Done.")
        return

    # Admin fund operations (add/deduct/ban/unban)
    if action == "addfunds_uid":
        try:
            uid = int(msg.text)
        except:
            return await msg.reply("Invalid user ID.")
        state["user_id"] = uid
        state["action"] = "addfunds_amount"
        await msg.reply(f"User ID: {uid}\nNow enter amount to add:")
        return

    if action == "addfunds_amount":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("Invalid amount.")
        uid = state["user_id"]
        user = get_user(uid)
        if not user:
            del admin_state[admin_id]
            return await msg.reply("User not found.")
        if transaction_add_web_balance(uid, amt):
            try:
                await app.send_message(uid, f"✅ Admin added ₹{amt} to your Web Balance.")
            except: pass
            await msg.reply(f"✅ ₹{amt} added to user {uid}.")
        else:
            await msg.reply("❌ Failed to update balance.")
        del admin_state[admin_id]
        return

    if action == "deduct_uid":
        try:
            uid = int(msg.text)
        except:
            return await msg.reply("Invalid user ID.")
        state["user_id"] = uid
        state["action"] = "deduct_amount"
        await msg.reply(f"User ID: {uid}\nNow enter amount to deduct:")
        return

    if action == "deduct_amount":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("Invalid amount.")
        uid = state["user_id"]
        user = get_user(uid)
        if not user:
            del admin_state[admin_id]
            return await msg.reply("User not found.")
        if user.get("web_balance", 0) < amt:
            return await msg.reply("❌ Insufficient web balance.")
        if transaction_deduct_web_balance(uid, amt):
            try:
                await app.send_message(uid, f"⚠️ Admin deducted ₹{amt} from your Web Balance.")
            except: pass
            await msg.reply(f"✅ ₹{amt} deducted from user {uid}.")
        else:
            await msg.reply("❌ Deduction failed.")
        del admin_state[admin_id]
        return

    if action == "ban_uid":
        try:
            uid = int(msg.text)
        except:
            return await msg.reply("Invalid user ID.")
        user = get_user(uid)
        if not user:
            return await msg.reply("User not found.")
        update_user(uid, {"banned": True})
        dm_buttons = []
        for adm in ADMIN_IDS:
            dm_buttons.append(InlineKeyboardButton(f"📩 Admin {adm}", url=f"tg://user?id={adm}"))
        try:
            await app.send_message(uid,
                "⛔ You have been banned from using this bot.\nContact admins:",
                reply_markup=InlineKeyboardMarkup([dm_buttons]))
        except: pass
        await msg.reply(f"✅ User {uid} banned.")
        del admin_state[admin_id]
        return

    if action == "unban_uid":
        try:
            uid = int(msg.text)
        except:
            return await msg.reply("Invalid user ID.")
        update_user(uid, {"banned": False})
        await msg.reply(f"✅ User {uid} unbanned.")
        del admin_state[admin_id]
        return

# ---------------- USER TEXT HANDLER (add amount, withdraw) ----------------
@app.on_message(filters.text)
async def user_text_handler(client, msg):
    uid = msg.from_user.id
    # Bypass if admin and already handled by admin handler? But admin handler runs first due to user filter. 
    # However, this handler will still catch admin texts if admin_state not set, but that's fine – admins can use normal user flows.
    user = get_user(uid)
    if user and user.get("banned"):
        return await msg.reply("⛔ You are banned. Contact admin.")

    state = user_state.get(uid)

    if state == "add_amount":
        try:
            amt = float(msg.text)
        except:
            return await msg.reply("❌ Please enter a valid number.")

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
        await app.send_message(PAYMENT_CHANNEL,
            f"🚨 **Withdrawal Request**\n👤 User ID: {uid}\n💸 Amount: ₹{amt}")
        await msg.reply("✅ Withdrawal request sent. You will be notified when processed.")
        user_state.pop(uid, None)

    elif state == "awaiting_ss":
        await msg.reply("📸 Please send a **photo** (screenshot), not text.")

    else:
        pass

# ---------------- RUN ----------------
app.run()
