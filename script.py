import asyncio
import sys
import os
import re
from datetime import datetime, timedelta

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.raw import functions

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("Error: API_ID or API_HASH not found in .env file!")
    sys.exit(1)

app = Client("my_account", api_id=int(API_ID), api_hash=API_HASH)


def parse_time(time_str: str) -> int:
    """Parse a duration string like '1d2h30m' into total seconds.

    Supported units:
        d — days
        h — hours
        m — minutes

    Returns:
        int: Total duration in seconds, or 0 if the string is invalid.
    """
    total_seconds = 0
    days = re.search(r"(\d+)d", time_str)
    hours = re.search(r"(\d+)h", time_str)
    minutes = re.search(r"(\d+)m", time_str)

    if days:
        total_seconds += int(days.group(1)) * 86400
    if hours:
        total_seconds += int(hours.group(1)) * 3600
    if minutes:
        total_seconds += int(minutes.group(1)) * 60

    return total_seconds


@app.on_message(filters.me & filters.command("send", prefixes="."))
async def schedule_messages(client, message):
    """Schedule N copies of a replied-to message at a fixed interval.

    Usage (reply to a message):
        .send <interval> <count>

    Examples:
        .send 1h 5        — schedules 5 messages, one per hour
        .send 30m 10      — schedules 10 messages, one every 30 minutes
        .send 1d2h 3      — schedules 3 messages, every 26 hours

    Limits:
        Telegram allows at most 100 scheduled messages per chat.
        The script pauses for 10 seconds every 20 messages to avoid flood-wait.
    """
    if not message.reply_to_message:
        await message.delete()
        await client.send_message("me", "Error: you must reply to a message.")
        return

    try:
        _, time_str, num_str = message.text.split()
        num = int(num_str)
        interval_seconds = parse_time(time_str)

        if interval_seconds == 0:
            await message.delete()
            await client.send_message("me", "Error: invalid time format. Use combinations like 1d, 2h, 30m.")
            return

    except ValueError:
        await message.delete()
        await client.send_message("me", "Error: invalid command format. Usage: .send <interval> <count>")
        return

    target_msg = message.reply_to_message
    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.first_name or str(chat_id)

    await message.delete()

    report_msg = await client.send_message(
        "me",
        f"Scheduling {num} messages for chat **{chat_title}**..."
    )

    success_count = 0

    for i in range(1, num + 1):
        schedule_date = datetime.now() + timedelta(seconds=interval_seconds * i)

        try:
            if target_msg.media_group_id:
                await client.copy_media_group(
                    chat_id=chat_id,
                    from_chat_id=chat_id,
                    message_id=target_msg.id,
                    schedule_date=schedule_date
                )
            else:
                await client.copy_message(
                    chat_id=chat_id,
                    from_chat_id=chat_id,
                    message_id=target_msg.id,
                    schedule_date=schedule_date
                )
            success_count += 1

        except Exception as e:
            error_text = str(e)
            if "SCHEDULE_TOO_MUCH" in error_text:
                await client.send_message(
                    "me",
                    f"Telegram limit reached (100 scheduled messages) in chat **{chat_title}**. Stopped early."
                )
                break
            else:
                await client.send_message("me", f"Error on step {i}: {error_text}")

        if i % 20 == 0 and i < num:
            await client.edit_message_text(
                chat_id="me",
                message_id=report_msg.id,
                text=f"Scheduled {success_count}/{num}... Waiting 10 seconds to avoid flood-wait."
            )
            await asyncio.sleep(10)
            await client.edit_message_text(
                chat_id="me",
                message_id=report_msg.id,
                text=f"Continuing ({success_count}/{num})..."
            )

    await client.edit_message_text(
        chat_id="me",
        message_id=report_msg.id,
        text=f"Done. Successfully scheduled **{success_count}** messages in chat **{chat_title}**."
    )


@app.on_message(filters.me & filters.command("clear", prefixes="."))
async def clear_scheduled(client, message):
    """Delete all scheduled messages in the current chat.

    Usage:
        .clear

    Note:
        This command uses Telegram's raw API to fetch and bulk-delete
        all pending scheduled messages in the chat where it is sent.
    """
    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.first_name or str(chat_id)

    await message.delete()

    try:
        peer = await client.resolve_peer(chat_id)

        history = await client.invoke(
            functions.messages.GetScheduledHistory(peer=peer, hash=0)
        )

        if not history.messages:
            await client.send_message("me", f"No scheduled messages found in chat **{chat_title}**.")
            return

        msg_ids = [msg.id for msg in history.messages]
        await client.invoke(
            functions.messages.DeleteScheduledMessages(peer=peer, id=msg_ids)
        )

        await client.send_message("me", f"Deleted **{len(msg_ids)}** scheduled messages in chat **{chat_title}**.")

    except Exception as e:
        await client.send_message("me", f"Error while deleting: {e}")


if __name__ == "__main__":
    print("Userbot started! Waiting for commands...")
    app.run()