import random
import json
import os
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TOKEN = "8679806194:AAH35zUFUYhnHWnL210bRwrcTsD_p3ZZM9A"

BALANCE_FILE = "balances.json"
BONUS_FILE = "bonuses.json"

# ====== РАБОТА С БАЛАНСОМ ======

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

# ====== ЕЖЕДНЕВНЫЙ БОНУС ======

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
    last = bonuses.get(str(user_id))
    return last != str(date.today())

def mark_bonus_claimed(user_id):
    bonuses = load_bonuses()
    bonuses[str(user_id)] = str(date.today())
    save_bonuses(bonuses)

# ====== ИГРА ======

active_games = {}

def create_game(bet):
    size = 5
    total_cells = size * size
    mines = 6
    mine_positions = set(random.sample(range(total_cells), mines))
    board = [{"is_mine": i in mine_positions, "revealed": False} for i in range(total_cells)]
    return {
        "board": board,
        "bet": bet,
        "revealed_count": 0,
        "size": size,
        "mines": mines,
        "game_over": False,
        "won": False
    }

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

            if cell["revealed"]:
                if cell["is_mine"]:
                    text = "💥"
                else:
                    text = " "
            else:
                text = "❓"

            keyboard_row.append(InlineKeyboardButton(text, callback_data=f"mine_{user_id}_{idx}"))
        keyboard.append(keyboard_row)

    if not game_state["game_over"]:
        multiplier = get_multiplier(game_state["revealed_count"], game_state["mines"], size * size)
        winnings = int(game_state["bet"] * multiplier)
        keyboard.append([
            InlineKeyboardButton(
                f"💰 Забрать выигрыш ({winnings} монет)",
                callback_data=f"cashout_{user_id}"
            )
        ])

    return InlineKeyboardMarkup(keyboard)

def get_name(user):
    name = (user.first_name or "")
    if user.last_name:
        name += f" {user.last_name}"
    return name.strip() or user.username or "Игрок"

def is_group(update: Update) -> bool:
    return update.message.chat.type in ("group", "supergroup")

def is_private(update: Update) -> bool:
    return update.message.chat.type == "private"

# ====== ОБРАБОТЧИКИ ======

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

    # Баланс
    if text_lower == "б":
        balance = get_balance(user_id)

        # Кнопка бонуса — активная или заблокированная
        if can_claim_bonus(user_id):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Получить бонус (2500)", callback_data=f"bonus_{user_id}")]
            ])
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏰ Бонус уже получен — приходи завтра", callback_data=f"bonus_unavailable_{user_id}")]
            ])

        await msg.reply_text(
            f'<tg-emoji emoji-id="5280818098960611598">🤑</tg-emoji> <b>{username}</b>\nБаланс: <b>{balance}</b> монет',
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    # Мины
    if text_lower.startswith("мины "):
        parts = text.split()
        if len(parts) < 2:
            await msg.reply_text("❌ Пример: Мины 200")
            return
        try:
            bet = int(parts[1])
        except ValueError:
            await msg.reply_text("❌ Ставка должна быть числом!")
            return

        balance = get_balance(user_id)
        if bet <= 0:
            await msg.reply_text("❌ Ставка должна быть больше 0!")
            return
        if bet > balance:
            await msg.reply_text(f"❌ Недостаточно средств! Баланс: {balance} монет")
            return

        set_balance(user_id, balance - bet)
        game = create_game(bet)
        active_games[user_id] = game

        keyboard = build_keyboard(game, user_id)
        await msg.reply_text(
            f"💣 <b>{username}</b>, вы начали игру минное поле!\n"
            f"💰 Ставка: {bet}\n"
            f"📈 Выигрыш: x1.0 | {bet} монет\n"
            f"⚠️ Мин на поле: {game['mines']}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    # Передача монет
    if text_lower.startswith("п "):
        if not msg.reply_to_message:
            await msg.reply_text("❌ Ответь на сообщение человека, которому хочешь передать монеты!")
            return
        parts = text.split()
        if len(parts) < 2:
            await msg.reply_text("❌ Пример: п 500")
            return
        try:
            amount = int(parts[1])
        except ValueError:
            await msg.reply_text("❌ Сумма должна быть числом!")
            return
        if amount <= 0:
            await msg.reply_text("❌ Сумма должна быть больше 0!")
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

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    clicker_id = query.from_user.id
    clicker_name = get_name(query.from_user)

    # Кнопка недоступного бонуса
    if data.startswith("bonus_unavailable_"):
        await query.answer("❌ Бонус уже получен сегодня! Приходи завтра.", show_alert=True)
        return

    await query.answer()

    # Бонус
    if data.startswith("bonus_"):
        owner_id = int(data.split("_")[1])
        if clicker_id != owner_id:
            await query.answer("❌ Это не твой баланс!", show_alert=True)
            return
        if not can_claim_bonus(owner_id):
            await query.answer("❌ Бонус уже получен сегодня! Приходи завтра.", show_alert=True)
            # Меняем кнопку на заблокированную
            new_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏰ Бонус уже получен — приходи завтра", callback_data=f"bonus_unavailable_{owner_id}")]
            ])
            await query.edit_message_reply_markup(reply_markup=new_keyboard)
            return

        add_balance(owner_id, BONUS_AMOUNT)
        mark_bonus_claimed(owner_id)
        balance = get_balance(owner_id)

        # После получения — меняем кнопку на заблокированную
        new_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏰ Бонус уже получен — приходи завтра", callback_data=f"bonus_unavailable_{owner_id}")]
        ])
        await query.edit_message_text(
            f"🎁 <b>{clicker_name}</b> получил ежедневный бонус <b>{BONUS_AMOUNT}</b> монет!\n"
            f"💰 Баланс: <b>{balance}</b> монет\n"
            f"⏰ Следующий бонус доступен завтра",
            parse_mode="HTML",
            reply_markup=new_keyboard
        )
        return

    # Открытие клетки
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
            await query.answer("Игра уже завершена!", show_alert=True)
            return

        cell = game["board"][cell_idx]
        if cell["revealed"]:
            await query.answer("Эта клетка уже открыта!", show_alert=True)
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
                f'<tg-emoji emoji-id="5438274168422409988">😐</tg-emoji> <b>{clicker_name}</b>, ВЫ ВЗОРВАЛИСЬ НА МИНЕ!\n'
                f"❌ Ставка {game['bet']} монет потеряна!",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            del active_games[owner_id]
        else:
            game["revealed_count"] += 1
            safe_cells = size * size - game["mines"]

            if game["revealed_count"] >= safe_cells:
                multiplier = get_multiplier(game["revealed_count"], game["mines"], size * size)
                winnings = int(game["bet"] * multiplier)
                add_balance(owner_id, winnings)
                game["game_over"] = True
                keyboard = build_keyboard(game, owner_id)
                await query.edit_message_text(
                    f'<tg-emoji emoji-id="5458394638505223612">😉</tg-emoji> <b>{clicker_name}</b>, ВЫ ПОБЕДИЛИ!\n'
                    f"💰 Выигрыш: <b>{winnings}</b> монет (x{multiplier})",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                del active_games[owner_id]
            else:
                multiplier = get_multiplier(game["revealed_count"], game["mines"], size * size)
                winnings = int(game["bet"] * multiplier)
                keyboard = build_keyboard(game, owner_id)
                await query.edit_message_text(
                    f"💣 <b>{clicker_name}</b>, минное поле\n"
                    f"💰 Ставка: {game['bet']}\n"
                    f"📈 Выигрыш: x{multiplier} | {winnings} монет\n"
                    f"✅ Открыто: {game['revealed_count']} клеток",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )

    # Забрать выигрыш
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
        multiplier = get_multiplier(game["revealed_count"], game["mines"], size * size)
        winnings = int(game["bet"] * multiplier)
        add_balance(owner_id, winnings)
        game["game_over"] = True
        keyboard = build_keyboard(game, owner_id)
        await query.edit_message_text(
            f'<tg-emoji emoji-id="5458394638505223612">😉</tg-emoji> <b>{clicker_name}</b> забрал выигрыш!\n'
            f"🏆 Получено: <b>{winnings}</b> монет (x{multiplier})\n"
            f"✅ Открыто клеток: {game['revealed_count']}",
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
