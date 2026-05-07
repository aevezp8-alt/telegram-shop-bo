import random
import json
import os
import asyncio
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TOKEN = "8679806194:AAH35zUFUYhnHWnL210bRwrcTsD_p3ZZM9A"

BALANCE_FILE = "balances.json"
BONUS_FILE = "bonuses.json"

def load_balances():
    if os.path.exists(BALANCE_FILE):
        with open(BALANCE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_balances(balances):
    with open(BALANCE_FILE, "w") as f:
        json.dump(balances, f)

def get_balance(user_id):
    return load_balances().get(str(user_id), 0)

def set_balance(user_id, amount):
    balances = load_balances()
    balances[str(user_id)] = amount
    save_balances(balances)

def add_balance(user_id, amount):
    set_balance(user_id, get_balance(user_id) + amount)

BONUS_AMOUNT = 2500

def load_bonuses():
    if os.path.exists(BONUS_FILE):
        with open(BONUS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_bonuses(bonuses):
    with open(BONUS_FILE, "w") as f:
        json.dump(bonuses, f)

def can_claim_bonus(user_id):
    bonuses = load_bonuses()
    return bonuses.get(str(user_id)) != str(date.today())

def mark_bonus_claimed(user_id):
    bonuses = load_bonuses()
    bonuses[str(user_id)] = str(date.today())
    save_bonuses(bonuses)

# ====== МИНЫ ======

active_games = {}

def create_game(bet):
    size = 5
    total_cells = size * size
    mines = 6
    mine_positions = set(random.sample(range(total_cells), mines))
    board = [{"is_mine": i in mine_positions, "revealed": False} for i in range(total_cells)]
    return {"board": board, "bet": bet, "revealed_count": 0, "size": size, "mines": mines, "game_over": False}

def get_multiplier(revealed_count, mines, total_cells):
    safe_cells = total_cells - mines
    if revealed_count == 0:
        return 1.0
    multiplier = 1.0
    for i in range(revealed_count):
        multiplier *= (total_cells - i) / (safe_cells - i)
    return round(multiplier * 0.97, 2)

def build_keyboard(game_state, user_id):
    size = game_state["size"]
    board = game_state["board"]
    keyboard = []
    for row in range(size):
        keyboard_row = []
        for col in range(size):
            idx = row * size + col
            cell = board[idx]
            text = ("💥" if cell["is_mine"] else " ") if cell["revealed"] else "❓"
            keyboard_row.append(InlineKeyboardButton(text, callback_data=f"mine_{user_id}_{idx}"))
        keyboard.append(keyboard_row)
    if not game_state["game_over"]:
        mult = get_multiplier(game_state["revealed_count"], game_state["mines"], size * size)
        winnings = int(game_state["bet"] * mult)
        keyboard.append([InlineKeyboardButton(f"💰 Забрать выигрыш ({winnings} монет)", callback_data=f"cashout_{user_id}")])
    return InlineKeyboardMarkup(keyboard)

# ====== РУЛЕТКА ======
# Ставки хранятся ГЛОБАЛЬНО по chat_id — можно ставить в любое время
# chat_id -> {"bets": [{"user_id", "username", "type", "from", "to", "amount"}], "spinning": bool}

RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34}
BLACK_NUMBERS = {n for n in range(1, 35) if n not in RED_NUMBERS}
STICKER_PACK = "IrisAdvanceRoulette"
LOG_FILE = "roulette_log.json"

roulette_bets = {}   # chat_id -> list of bets (постоянно, до запуска)
spinning_chats = set()  # chat_id где сейчас крутится

def load_log(chat_id):
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            data = json.load(f)
        return data.get(str(chat_id), [])
    return []

def save_log(chat_id, entries):
    data = {}
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            data = json.load(f)
    data[str(chat_id)] = entries[-10:]  # храним последние 10
    with open(LOG_FILE, "w") as f:
        json.dump(data, f)

def add_log(chat_id, number, color):
    entries = load_log(chat_id)
    entries.append({"number": number, "color": color})
    save_log(chat_id, entries)

def parse_range(text):
    try:
        parts = text.split("-")
        if len(parts) == 2:
            a, b = int(parts[0]), int(parts[1])
            if 1 <= a <= 34 and 1 <= b <= 34 and a <= b:
                return a, b
    except:
        pass
    return None

async def launch_roulette(chat_id, context: ContextTypes.DEFAULT_TYPE):
    bets = roulette_bets.pop(chat_id, [])
    spinning_chats.discard(chat_id)

    result = random.randint(1, 34)
    result_color = "red" if result in RED_NUMBERS else "black"
    result_color_text = "🔴 Красное" if result_color == "red" else "⚫️ Чёрное"

    try:
        sticker_set = await context.bot.get_sticker_set(STICKER_PACK)
        sticker = random.choice(sticker_set.stickers)
        sticker_msg = await context.bot.send_sticker(chat_id=chat_id, sticker=sticker.file_id)
    except:
        sticker_msg = None

    await asyncio.sleep(5)
    if sticker_msg:
        try:
            await sticker_msg.delete()
        except:
            pass

    winners = []
    losers = []

    for bet in bets:
        uid = bet["user_id"]
        uname = bet["username"]
        amount = bet["amount"]
        btype = bet["type"]

        if btype == "range":
            won = bet["from"] <= result <= bet["to"]
            if won:
                rsize = bet["to"] - bet["from"] + 1
                mult = 34.0 if rsize == 1 else 10.0 if rsize <= 3 else 5.0 if rsize <= 6 else 3.0 if rsize <= 10 else 2.0 if rsize <= 17 else 1.5
                winnings = int(amount * mult)
                add_balance(uid, winnings)
                winners.append((uname, amount, winnings))
            else:
                losers.append((uname, amount))

        elif btype == "red":
            won = result_color == "red"
            if won:
                winnings = amount * 2
                add_balance(uid, winnings)
                winners.append((uname, amount, winnings))
            else:
                losers.append((uname, amount))

        elif btype == "black":
            won = result_color == "black"
            if won:
                winnings = amount * 2
                add_balance(uid, winnings)
                winners.append((uname, amount, winnings))
            else:
                losers.append((uname, amount))

    add_log(chat_id, result, result_color)

    lines = [f"🎰 Выпало: <b>{result}</b> {result_color_text}\n"]
    for uname, _, won_amt in winners:
        lines.append(f'<tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji> {uname} +{won_amt}')
    for uname, bet_amt in losers:
        lines.append(f'<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji> {uname} -{bet_amt}')

    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="HTML")

def get_name(user):
    name = (user.first_name or "")
    if user.last_name:
        name += f" {user.last_name}"
    return name.strip() or user.username or "Игрок"

def is_group(update: Update):
    return update.message.chat.type in ("group", "supergroup")

def is_private(update: Update):
    return update.message.chat.type == "private"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return
    user_id = update.message.from_user.id
    args = context.args
    if not args:
        await update.message.reply_text("❌ Пример: /4061 10000")
        return
    try:
        amount = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Сумма должна быть числом!")
        return
    add_balance(user_id, amount)
    await update.message.reply_text(
        f"✅ Выдано <b>{amount}</b> монет!\n💰 Баланс: <b>{get_balance(user_id)}</b> монет",
        parse_mode="HTML"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        return

    msg = update.message
    text = msg.text.strip() if msg.text else ""
    user = msg.from_user
    user_id = user.id
    username = get_name(user)
    text_lower = text.lower()
    chat_id = msg.chat.id

    # БАЛАНС
    if text_lower == "б":
        balance = get_balance(user_id)
        keyboard = None
        if can_claim_bonus(user_id):
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Получить бонус (2500)", callback_data=f"bonus_{user_id}")]])
        await msg.reply_text(
            f'<tg-emoji emoji-id="5280818098960611598">🤑</tg-emoji> <b>{username}</b>\nБаланс: <b>{balance}</b> монет',
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    # МИНЫ
    if text_lower.startswith("мины "):
        parts = text.split()
        if len(parts) < 2:
            return
        try:
            bet = int(parts[1])
        except ValueError:
            return
        balance = get_balance(user_id)
        if bet <= 0 or bet > balance:
            await msg.reply_text(f"❌ Недостаточно средств! Баланс: {balance} монет")
            return
        set_balance(user_id, balance - bet)
        game = create_game(bet)
        active_games[user_id] = game
        keyboard = build_keyboard(game, user_id)
        await msg.reply_text(
            f"💣 <b>{username}</b>, минное поле!\n"
            f"💰 Ставка: {bet}\n"
            f"📈 Выигрыш: x1.0 | {bet} монет\n"
            f"⚠️ Мин: {game['mines']}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    # ПЕРЕДАЧА
    if text_lower.startswith("п "):
        if not msg.reply_to_message:
            await msg.reply_text("❌ Ответь на сообщение получателя!")
            return
        parts = text.split()
        if len(parts) < 2:
            return
        try:
            amount = int(parts[1])
        except ValueError:
            return
        if amount <= 0:
            return
        sender_balance = get_balance(user_id)
        if amount > sender_balance:
            await msg.reply_text(f"❌ Недостаточно средств! Баланс: {sender_balance} монет")
            return
        target = msg.reply_to_message.from_user
        target_name = get_name(target)
        set_balance(user_id, sender_balance - amount)
        add_balance(target.id, amount)
        await msg.reply_text(
            f'<tg-emoji emoji-id="5456149049214249060">🥰</tg-emoji> <b>{username}</b> передал <b>{amount}</b> монет → <b>{target_name}</b>\n'
            f"💰 Ваш баланс: {get_balance(user_id)} монет",
            parse_mode="HTML"
        )
        return

    # ЛОГ
    if text_lower == "лог":
        entries = load_log(chat_id)
        if not entries:
            await msg.reply_text("📋 Лог пуст — ещё не было раундов!")
            return
        lines = ["📋 <b>Последние раунды:</b>\n"]
        for e in reversed(entries):
            emoji = "🔴" if e["color"] == "red" else "⚫️"
            lines.append(f"{e['number']}{emoji}")
        await msg.reply_text("\n".join(lines), parse_mode="HTML")
        return

    # РУЛЕТКА: ОТМЕНА СТАВОК
    if text_lower == "отмена":
        if chat_id in spinning_chats:
            await msg.reply_text("❌ Раунд уже идёт, отменить нельзя!")
            return
        bets = roulette_bets.get(chat_id, [])
        user_bets = [b for b in bets if b["user_id"] == user_id]
        if not user_bets:
            await msg.reply_text("❌ У тебя нет активных ставок!")
            return
        refund = sum(b["amount"] for b in user_bets)
        roulette_bets[chat_id] = [b for b in bets if b["user_id"] != user_id]
        add_balance(user_id, refund)
        await msg.reply_text(
            f'<tg-emoji emoji-id="5456149049214249060">🥰</tg-emoji> <b>{username}</b>, ставки отменены!\n'
            f"💰 Возвращено: <b>{refund}</b> монет",
            parse_mode="HTML"
        )
        return

    # РУЛЕТКА: ГО — запуск
    if text_lower == "го":
        if chat_id in spinning_chats:
            await msg.reply_text("❌ Раунд уже идёт!")
            return
        bets = roulette_bets.get(chat_id, [])
        if not bets:
            await msg.reply_text("❌ Нет ставок!")
            return
        spinning_chats.add(chat_id)
        asyncio.create_task(launch_roulette(chat_id, context))
        return

    # РУЛЕТКА: СТАВКА КРАСНОЕ
    if text_lower.startswith("к "):
        if chat_id in spinning_chats:
            await msg.reply_text("❌ Раунд уже идёт, подожди!")
            return
        parts = text.split()
        if len(parts) < 2:
            return
        try:
            amount = int(parts[1])
        except ValueError:
            return
        if amount <= 0:
            return
        balance = get_balance(user_id)
        if amount > balance:
            await msg.reply_text(f"❌ Недостаточно средств! Баланс: {balance} монет")
            return
        set_balance(user_id, balance - amount)
        roulette_bets.setdefault(chat_id, []).append({
            "user_id": user_id, "username": username,
            "type": "red", "from": None, "to": None, "amount": amount
        })
        await msg.reply_text(
            f'<tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji> <b>{username}</b>, ставка принята!\n'
            f"🔴 Красное — <b>{amount}</b> монет",
            parse_mode="HTML"
        )
        return

    # РУЛЕТКА: СТАВКА ЧЁРНОЕ
    if text_lower.startswith("ч "):
        if chat_id in spinning_chats:
            await msg.reply_text("❌ Раунд уже идёт, подожди!")
            return
        parts = text.split()
        if len(parts) < 2:
            return
        try:
            amount = int(parts[1])
        except ValueError:
            return
        if amount <= 0:
            return
        balance = get_balance(user_id)
        if amount > balance:
            await msg.reply_text(f"❌ Недостаточно средств! Баланс: {balance} монет")
            return
        set_balance(user_id, balance - amount)
        roulette_bets.setdefault(chat_id, []).append({
            "user_id": user_id, "username": username,
            "type": "black", "from": None, "to": None, "amount": amount
        })
        await msg.reply_text(
            f'<tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji> <b>{username}</b>, ставка принята!\n'
            f"⚫️ Чёрное — <b>{amount}</b> монет",
            parse_mode="HTML"
        )
        return

    # РУЛЕТКА: СТАВКА ДИАПАЗОН
    parts = text.split()
    if len(parts) == 2:
        rng = parse_range(parts[0])
        if rng:
            if chat_id in spinning_chats:
                await msg.reply_text("❌ Раунд уже идёт, подожди!")
                return
            try:
                amount = int(parts[1])
            except ValueError:
                return
            if amount <= 0:
                return
            balance = get_balance(user_id)
            if amount > balance:
                await msg.reply_text(f"❌ Недостаточно средств! Баланс: {balance} монет")
                return
            set_balance(user_id, balance - amount)
            roulette_bets.setdefault(chat_id, []).append({
                "user_id": user_id, "username": username,
                "type": "range", "from": rng[0], "to": rng[1], "amount": amount
            })
            await msg.reply_text(
                f'<tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji> <b>{username}</b>, ставка принята!\n'
                f"🎯 <b>{rng[0]}-{rng[1]}</b> — <b>{amount}</b> монет",
                parse_mode="HTML"
            )
            return

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    clicker_id = query.from_user.id
    clicker_name = get_name(query.from_user)

    await query.answer()

    if data.startswith("bonus_"):
        owner_id = int(data.split("_")[1])
        if clicker_id != owner_id:
            await query.answer("❌ Это не твой баланс!", show_alert=True)
            return
        if not can_claim_bonus(owner_id):
            await query.answer("❌ Бонус уже получен сегодня!", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=None)
            return
        add_balance(owner_id, BONUS_AMOUNT)
        mark_bonus_claimed(owner_id)
        balance = get_balance(owner_id)
        await query.edit_message_text(
            f"🎁 <b>{clicker_name}</b> получил бонус <b>{BONUS_AMOUNT}</b> монет!\n"
            f"💰 Баланс: <b>{balance}</b> монет",
            parse_mode="HTML"
        )
        return

    if data.startswith("mine_"):
        parts = data.split("_")
        owner_id = int(parts[1])
        cell_idx = int(parts[2])

        if clicker_id != owner_id:
            await query.answer("❌ Это не твоя игра!", show_alert=True)
            return
        if owner_id not in active_games:
            await query.answer("❌ Игра не найдена!", show_alert=True)
            return

        game = active_games[owner_id]
        if game["game_over"]:
            await query.answer("Игра завершена!", show_alert=True)
            return

        cell = game["board"][cell_idx]
        if cell["revealed"]:
            await query.answer("Уже открыта!", show_alert=True)
            return

        cell["revealed"] = True
        size = game["size"]

        if cell["is_mine"]:
            game["game_over"] = True
            for c in game["board"]:
                if c["is_mine"]:
                    c["revealed"] = True
            keyboard = build_keyboard(game, owner_id)
            await query.edit_message_text(
                f'<tg-emoji emoji-id="5438274168422409988">😐</tg-emoji> <b>{clicker_name}</b>, взорвался на мине!\n'
                f"❌ Потеряно: {game['bet']} монет",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            del active_games[owner_id]
        else:
            game["revealed_count"] += 1
            safe_cells = size * size - game["mines"]
            if game["revealed_count"] >= safe_cells:
                mult = get_multiplier(game["revealed_count"], game["mines"], size * size)
                winnings = int(game["bet"] * mult)
                add_balance(owner_id, winnings)
                game["game_over"] = True
                keyboard = build_keyboard(game, owner_id)
                await query.edit_message_text(
                    f'<tg-emoji emoji-id="5458394638505223612">😉</tg-emoji> <b>{clicker_name}</b>, победа!\n'
                    f"💰 Выигрыш: <b>{winnings}</b> монет (x{mult})",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                del active_games[owner_id]
            else:
                mult = get_multiplier(game["revealed_count"], game["mines"], size * size)
                winnings = int(game["bet"] * mult)
                keyboard = build_keyboard(game, owner_id)
                await query.edit_message_text(
                    f"💣 <b>{clicker_name}</b>, минное поле\n"
                    f"💰 Ставка: {game['bet']}\n"
                    f"📈 Выигрыш: x{mult} | {winnings} монет",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )

    elif data.startswith("cashout_"):
        owner_id = int(data.split("_")[1])
        if clicker_id != owner_id:
            await query.answer("❌ Это не твоя игра!", show_alert=True)
            return
        if owner_id not in active_games:
            await query.answer("❌ Игра не найдена!", show_alert=True)
            return
        game = active_games[owner_id]
        if game["revealed_count"] == 0:
            await query.answer("❌ Сначала открой хотя бы одну клетку!", show_alert=True)
            return
        size = game["size"]
        mult = get_multiplier(game["revealed_count"], game["mines"], size * size)
        winnings = int(game["bet"] * mult)
        add_balance(owner_id, winnings)
        game["game_over"] = True
        keyboard = build_keyboard(game, owner_id)
        await query.edit_message_text(
            f'<tg-emoji emoji-id="5458394638505223612">😉</tg-emoji> <b>{clicker_name}</b> забрал выигрыш!\n'
            f"🏆 Получено: <b>{winnings}</b> монет (x{mult})",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        del active_games[owner_id]

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("4061", handle_admin_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
