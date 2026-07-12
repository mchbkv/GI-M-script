import asyncio
import sys
import os
import re
import json
import warnings
import logging
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from pyrogram import Client, filters, idle, raw, utils
from pyrogram.raw import functions

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("Error: API_ID or API_HASH not found in .env file!")
    sys.exit(1)

app = Client("my_account", api_id=int(API_ID), api_hash=API_HASH)
STATE_FILE = Path("schedule_state.json")
MAX_SCHEDULED_MESSAGES = 100
MAX_SCHEDULE_AHEAD_SECONDS = 364 * 86400
AUTO_CLEAR_BEFORE_SEND = True
AUTO_FILL_TO_LIMIT = True
AUTO_REFRESH_ENABLED = True
AUTO_REFRESH_INTERVAL_SECONDS = 300
MAX_AUTO_FLOOD_WAIT_SECONDS = 60
WRITE_FORBIDDEN_MARKERS = (
    "CHAT_WRITE_FORBIDDEN",
    "USER_BANNED_IN_CHANNEL",
    "USER_RESTRICTED",
    "USER_KICKED",
    "CHANNEL_PRIVATE",
    "CHAT_ADMIN_REQUIRED",
    "PEER_ID_INVALID",
    "BANNED_RIGHTS"
)
SCHEDULE_STOP_MARKERS = (
    "SCHEDULE_DATE_TOO_LATE",
)
FLOOD_WAIT_RE = re.compile(r"(?:FLOOD_WAIT_(\d+)|wait of (\d+) seconds)")


def parse_time(time_str: str) -> int:
    total_seconds = 0
    days = re.search(r"(\d+)d", time_str)
    hours = re.search(r"(\d+)h", time_str)
    minutes = re.search(r"(\d+)m", time_str)

    if days: total_seconds += int(days.group(1)) * 86400
    if hours: total_seconds += int(hours.group(1)) * 3600
    if minutes: total_seconds += int(minutes.group(1)) * 60

    return total_seconds


def get_reply_header(message):
    raw_message = getattr(message, "_raw", None)
    return getattr(raw_message, "reply_to", None)


def is_forum_topic_message(message):
    reply_header = get_reply_header(message)
    chat = getattr(message, "chat", None)

    return bool(
        getattr(message, "is_topic_message", False)
        or getattr(reply_header, "forum_topic", False)
        or getattr(chat, "is_forum", False)
    )


def get_message_topic_id(message):
    reply_header = get_reply_header(message)
    topic_id = (
        getattr(message, "reply_to_top_message_id", None)
        or getattr(reply_header, "reply_to_top_id", None)
    )

    if topic_id is None and is_forum_topic_message(message):
        topic_id = (
            getattr(message, "reply_to_message_id", None)
            or getattr(reply_header, "reply_to_msg_id", None)
        )

    return topic_id


def get_topic_id(message, fallback_message=None):
    topic_id = get_message_topic_id(message)

    if topic_id is None and fallback_message is not None:
        topic_id = get_message_topic_id(fallback_message)

    return topic_id


def get_schedule_key(chat_id, topic_id):
    return f"{chat_id}:{topic_id or 0}"


def is_write_forbidden_error(error_text):
    return any(marker in error_text for marker in WRITE_FORBIDDEN_MARKERS)


def is_schedule_stop_error(error_text):
    return any(marker in error_text for marker in SCHEDULE_STOP_MARKERS)


def get_batch_limit(message_count):
    return max(1, MAX_SCHEDULED_MESSAGES // max(1, message_count))


def get_date_limit(interval_seconds):
    return MAX_SCHEDULE_AHEAD_SECONDS // interval_seconds


def limit_schedule_count(requested_count, message_count, interval_seconds):
    message_limit = get_batch_limit(message_count)
    date_limit = get_date_limit(interval_seconds)
    hard_limit = min(message_limit, date_limit)

    if requested_count is None:
        requested_count = message_limit

    return min(requested_count, hard_limit), requested_count, hard_limit


def get_flood_wait_seconds(error):
    value = getattr(error, "value", None)

    if isinstance(value, int):
        return value

    match = FLOOD_WAIT_RE.search(str(error))

    if not match:
        return None

    seconds = next((group for group in match.groups() if group), None)

    return int(seconds) if seconds else None


async def invoke_with_flood_wait(client, query):
    try:
        return await client.invoke(query)
    except Exception as e:
        wait_seconds = get_flood_wait_seconds(e)

        if wait_seconds is None or wait_seconds > MAX_AUTO_FLOOD_WAIT_SECONDS:
            raise

        await asyncio.sleep(wait_seconds + 1)
        return await client.invoke(query)


def load_schedule_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_schedule_state(state):
    tmp_file = STATE_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(STATE_FILE)


def remove_schedule_config(chat_id, topic_id):
    state = load_schedule_state()
    if topic_id is None:
        keys = [key for key, config in state.items() if config.get("chat_id") == chat_id]
        for key in keys:
            state.pop(key, None)
        removed = bool(keys)
    else:
        removed = state.pop(get_schedule_key(chat_id, topic_id), None) is not None

    save_schedule_state(state)

    return removed


def mark_schedule_disabled(config, error_text):
    state = load_schedule_state()
    key = get_schedule_key(config["chat_id"], config.get("topic_id"))

    if key in state:
        state[key]["enabled"] = False
        state[key]["disabled_reason"] = error_text
        state[key]["disabled_at"] = datetime.now().isoformat(timespec="seconds")
        save_schedule_state(state)


def save_schedule_config(chat_id, topic_id, destination, interval_text, interval_seconds, count, target_msg):
    state = load_schedule_state()
    state[get_schedule_key(chat_id, topic_id)] = {
        "chat_id": chat_id,
        "topic_id": topic_id,
        "destination": destination,
        "interval_text": interval_text,
        "interval_seconds": interval_seconds,
        "count": count,
        "source_chat_id": target_msg.chat.id,
        "message_id": target_msg.id,
        "message_link": getattr(target_msg, "link", None),
        "enabled": True,
        "updated_at": datetime.now().isoformat(timespec="seconds")
    }
    save_schedule_state(state)


def get_message_file_id(message):
    for field in ("photo", "video", "document", "audio", "animation", "voice", "video_note", "sticker"):
        media = getattr(message, field, None)

        if media and getattr(media, "file_id", None):
            return media.file_id

    return None


async def parse_message_text(client, message):
    text = message.text or message.caption or ""
    entities = message.entities if message.text else message.caption_entities
    parsed = await utils.parse_text_entities(client, text, None, entities)

    return parsed["message"], parsed["entities"] or None


async def schedule_recreated_message(client, chat_id, peer, message, schedule_date, topic_id, media_group=None):
    schedule_timestamp = int(schedule_date.timestamp())

    if media_group:
        multi_media = []

        for media_message in media_group:
            file_id = get_message_file_id(media_message)

            if not file_id:
                raise ValueError("this media group contains an unsupported message type")

            text, entities = await parse_message_text(client, media_message)
            multi_media.append(
                raw.types.InputSingleMedia(
                    media=utils.get_input_media_from_file_id(file_id),
                    random_id=client.rnd_id(),
                    message=text,
                    entities=entities
                )
            )

        await invoke_with_flood_wait(
            client,
            functions.messages.SendMultiMedia(
                peer=peer,
                multi_media=multi_media,
                top_msg_id=topic_id,
                schedule_date=schedule_timestamp
            )
        )
        return

    try:
        await client.copy_message(
            chat_id=chat_id,
            from_chat_id=message.chat.id,
            message_id=message.id,
            reply_to_message_id=topic_id,
            schedule_date=schedule_date
        )
        return
    except Exception as copy_error:
        if "SCHEDULE_DATE_TOO_LATE" in str(copy_error):
            raise

    file_id = get_message_file_id(message)

    if file_id:
        text, entities = await parse_message_text(client, message)
        await invoke_with_flood_wait(
            client,
            functions.messages.SendMedia(
                peer=peer,
                media=utils.get_input_media_from_file_id(file_id),
                message=text,
                random_id=client.rnd_id(),
                top_msg_id=topic_id,
                entities=entities,
                schedule_date=schedule_timestamp
            )
        )
        return

    if message.text:
        text, entities = await parse_message_text(client, message)
        await invoke_with_flood_wait(
            client,
            functions.messages.SendMessage(
                peer=peer,
                message=text,
                random_id=client.rnd_id(),
                top_msg_id=topic_id,
                entities=entities,
                schedule_date=schedule_timestamp
            )
        )
        return

    raise ValueError(f"unsupported protected message type; copy fallback failed: {copy_error}")


def parse_send_command(command_text):
    try:
        parts = command_text.split()
        if len(parts) == 2 and AUTO_FILL_TO_LIMIT:
            _, time_str = parts
            num = None
        elif len(parts) == 3:
            _, time_str, num_str = parts
            num = int(num_str)
        else:
            raise ValueError

        interval_seconds = parse_time(time_str)

        if interval_seconds == 0:
            raise ValueError("invalid time format")

    except ValueError:
        if AUTO_FILL_TO_LIMIT:
            raise ValueError("format is .send <time> or .send <time> <count>")
        raise ValueError("format is .send <time> <count>")

    if num is not None and num < 1:
        raise ValueError("count must be greater than 0")

    return time_str, interval_seconds, num


async def get_message_batch(client, chat_id, target_msg):
    msg_ids = [target_msg.id]
    media_group = None

    if target_msg.media_group_id:
        try:
            media_group = await client.get_media_group(chat_id, target_msg.id)
            msg_ids = [m.id for m in media_group]
        except Exception as e:
            raise RuntimeError(f"Error fetching album: {e}") from e

    return msg_ids, media_group


async def notify_manual_update(client, destination, config, error_text):
    message_link = config.get("message_link") or f"message id {config['message_id']}"
    await client.send_message(
        "me",
        "Update failed. Please schedule this message manually.\n"
        f"Chat: {destination}\n"
        f"Message: {message_link}\n"
        f"Interval: {config['interval_text']}\n"
        f"Count: {config['count']}\n"
        f"Error: {error_text}"
    )


def get_raw_message_topic_id(message):
    reply_header = getattr(message, "reply_to", None)

    if not reply_header:
        return None

    topic_id = getattr(reply_header, "reply_to_top_id", None)

    if topic_id is None and getattr(reply_header, "forum_topic", False):
        topic_id = getattr(reply_header, "reply_to_msg_id", None)

    return topic_id


def filter_scheduled_messages(messages, topic_id):
    if topic_id is None:
        return messages

    return [msg for msg in messages if get_raw_message_topic_id(msg) == topic_id]


async def get_scheduled_messages(client, peer, topic_id=None):
    history = await invoke_with_flood_wait(
        client,
        functions.messages.GetScheduledHistory(peer=peer, hash=0)
    )
    return filter_scheduled_messages(history.messages, topic_id)


async def delete_scheduled_messages(client, peer, topic_id=None):
    messages = await get_scheduled_messages(client, peer, topic_id)

    if not messages:
        return 0

    msg_ids = [msg.id for msg in messages]
    await invoke_with_flood_wait(
        client,
        functions.messages.DeleteScheduledMessages(peer=peer, id=msg_ids)
    )

    return len(msg_ids)


async def schedule_batch(client, chat_id, peer, from_peer, target_msg, msg_ids, media_group, topic_id,
                         interval_seconds, count, report_msg, stop_on_error=False, error_callback=None):

    success_count = 0
    use_forward = True
    failed_error = None

    for i in range(1, count + 1):
        schedule_date = datetime.now() + timedelta(seconds=interval_seconds * i)

        try:
            if use_forward:
                random_ids = [client.rnd_id() for _ in msg_ids]

                await invoke_with_flood_wait(
                    client,
                    functions.messages.ForwardMessages(
                        from_peer=from_peer,
                        to_peer=peer,
                        id=msg_ids,
                        random_id=random_ids,
                        top_msg_id=topic_id,
                        schedule_date=int(schedule_date.timestamp()),
                        drop_author=True
                    )
                )
            else:
                await schedule_recreated_message(client, chat_id, peer, target_msg, schedule_date, topic_id, media_group)

            success_count += 1

        except Exception as e:
            error_text = str(e)
            if "SCHEDULE_TOO_MUCH" in error_text:
                failed_error = error_text
                await client.send_message("me", f"Telegram limit reached (100 msgs). Stopped.")
                if error_callback:
                    await error_callback(error_text)
                break
            elif "CHAT_FORWARDS_RESTRICTED" in error_text and use_forward:
                use_forward = False

                try:
                    await schedule_recreated_message(client, chat_id, peer, target_msg, schedule_date, topic_id, media_group)
                    success_count += 1
                    await client.send_message(
                        "me",
                        "Forwarding is restricted in this chat. Switched to resend mode for the remaining messages."
                    )
                except Exception as fallback_error:
                    failed_error = str(fallback_error)
                    await client.send_message("me", f"Fallback failed on step {i}: {fallback_error}")
                    if error_callback:
                        await error_callback(failed_error)
                    if stop_on_error:
                        break
            else:
                failed_error = error_text
                await client.send_message("me", f"Error on step {i}: {error_text}")
                if error_callback:
                    await error_callback(error_text)
                if stop_on_error or is_schedule_stop_error(error_text):
                    break

        if report_msg and i % 20 == 0 and i < count:
            await client.edit_message_text(
                chat_id="me",
                message_id=report_msg.id,
                text=f"Scheduled {success_count}/{count}... Waiting 10s to avoid flood-wait."
            )
            await asyncio.sleep(10)
            await client.edit_message_text(
                chat_id="me",
                message_id=report_msg.id,
                text=f"Continuing ({success_count}/{count})..."
            )

    return success_count, failed_error


async def schedule_from_config(client, config, report_msg=None, stop_on_error=True):
    peer = await client.resolve_peer(config["chat_id"])
    target_msg = await client.get_messages(config["source_chat_id"], config["message_id"])
    msg_ids, media_group = await get_message_batch(client, config["source_chat_id"], target_msg)
    from_peer = await client.resolve_peer(target_msg.chat.id)
    count, _, _ = limit_schedule_count(config["count"], len(msg_ids), config["interval_seconds"])

    if count < 1:
        raise ValueError("interval is too long to schedule within Telegram's one-year limit")

    async def report_update_error(error_text):
        await notify_manual_update(client, config["destination"], config, error_text)

    return await schedule_batch(
        client=client,
        chat_id=config["chat_id"],
        peer=peer,
        from_peer=from_peer,
        target_msg=target_msg,
        msg_ids=msg_ids,
        media_group=media_group,
        topic_id=config.get("topic_id"),
        interval_seconds=config["interval_seconds"],
        count=count,
        report_msg=report_msg,
        stop_on_error=stop_on_error,
        error_callback=report_update_error
    )


async def auto_refresh_config(client, config):
    if not config.get("enabled", True):
        return

    try:
        peer = await client.resolve_peer(config["chat_id"])
        scheduled_messages = await get_scheduled_messages(client, peer, config.get("topic_id"))

        if scheduled_messages:
            return

        success_count, failed_error = await schedule_from_config(client, config, stop_on_error=True)

        if failed_error:
            if is_write_forbidden_error(failed_error):
                mark_schedule_disabled(config, failed_error)
            return

        await client.send_message(
            "me",
            f"Auto-refreshed **{success_count}** scheduled messages for chat **{config['destination']}**."
        )

    except Exception as e:
        error_text = str(e)
        if is_write_forbidden_error(error_text):
            mark_schedule_disabled(config, error_text)
            await client.send_message(
                "me",
                f"Auto-refresh disabled for chat **{config['destination']}**: {error_text}"
            )
        else:
            await notify_manual_update(client, config["destination"], config, error_text)


async def auto_refresh_loop(client):
    while True:
        await asyncio.sleep(AUTO_REFRESH_INTERVAL_SECONDS)

        if not AUTO_REFRESH_ENABLED:
            continue

        for config in load_schedule_state().values():
            await auto_refresh_config(client, config)


@app.on_message(filters.me & filters.command("send", prefixes="."))
async def schedule_messages(client, message):
    if not message.reply_to_message:
        await message.delete()
        await client.send_message("me", "Error: you must reply to a message.")
        return

    try:
        time_str, interval_seconds, num = parse_send_command(message.text)
    except ValueError as e:
        await message.delete()
        await client.send_message("me", f"Error: {e}")
        return

    target_msg = message.reply_to_message
    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.first_name or str(chat_id)
    topic_id = get_topic_id(message, target_msg)
    destination = chat_title if topic_id is None else f"{chat_title} / topic {topic_id}"

    await message.delete()

    report_msg = await client.send_message(
        "me",
        (
            f"⏳ Scheduling messages for chat **{destination}**..."
            if num is None else
            f"⏳ Scheduling {num} messages for chat **{destination}**..."
        )
    )

    try:
        msg_ids, media_group = await get_message_batch(client, chat_id, target_msg)
        peer = await client.resolve_peer(chat_id)
        from_peer = await client.resolve_peer(target_msg.chat.id)
    except Exception as e:
        await client.send_message("me", str(e))
        return

    requested_count = None if num is None else num
    num, original_num, hard_limit = limit_schedule_count(requested_count, len(msg_ids), interval_seconds)

    if num < 1:
        await client.edit_message_text(
            chat_id="me",
            message_id=report_msg.id,
            text=(
                f"Cannot schedule messages for chat **{destination}**: "
                "the interval is longer than Telegram's one-year scheduling limit."
            )
        )
        return

    if requested_count is None:
        await client.edit_message_text(
            chat_id="me",
            message_id=report_msg.id,
            text=f"⏳ Scheduling up to {num} message batches for chat **{destination}**..."
        )
    elif num < original_num:
        await client.send_message(
            "me",
            (
                f"Requested **{original_num}** batches for chat **{destination}**, "
                f"but Telegram limits this interval to **{hard_limit}**. Scheduling **{num}**."
            )
        )

    deleted_count = 0
    if AUTO_CLEAR_BEFORE_SEND:
        try:
            deleted_count = await delete_scheduled_messages(client, peer, topic_id)
        except Exception as e:
            await client.send_message("me", f"Error while auto-clearing scheduled messages: {e}")
            return

    success_count, _ = await schedule_batch(
        client=client,
        chat_id=chat_id,
        peer=peer,
        from_peer=from_peer,
        target_msg=target_msg,
        msg_ids=msg_ids,
        media_group=media_group,
        topic_id=topic_id,
        interval_seconds=interval_seconds,
        count=num,
        report_msg=report_msg
    )

    if success_count:
        save_schedule_config(chat_id, topic_id, destination, time_str, interval_seconds, num, target_msg)

    await client.edit_message_text(
        chat_id="me",
        message_id=report_msg.id,
        text=(
            f"✅ Done. Successfully scheduled **{success_count}** messages in chat **{destination}**."
            + (f" Auto-cleared **{deleted_count}** old scheduled messages." if deleted_count else "")
        )
    )


@app.on_message(filters.me & filters.command("update", prefixes="."))
async def update_scheduled(client, message):
    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.first_name or str(chat_id)
    topic_id = get_topic_id(message)
    destination = chat_title if topic_id is None else f"{chat_title} / topic {topic_id}"
    config = load_schedule_state().get(get_schedule_key(chat_id, topic_id))

    await message.delete()

    if not config:
        await client.send_message("me", f"No saved .send settings found for chat **{destination}**.")
        return

    report_msg = await client.send_message("me", f"⏳ Updating scheduled messages for chat **{destination}**...")

    try:
        peer = await client.resolve_peer(chat_id)
        deleted_count = await delete_scheduled_messages(client, peer, topic_id)
        success_count, failed_error = await schedule_from_config(client, config, report_msg=report_msg)

        if failed_error:
            if is_write_forbidden_error(failed_error):
                mark_schedule_disabled(config, failed_error)
            await client.edit_message_text(
                chat_id="me",
                message_id=report_msg.id,
                text=(
                    f"Update stopped for chat **{destination}**. "
                    f"Deleted **{deleted_count}**, scheduled **{success_count}**. "
                    "Manual details were sent above."
                )
            )
        else:
            await client.edit_message_text(
                chat_id="me",
                message_id=report_msg.id,
                text=(
                    f"✅ Update done for chat **{destination}**. "
                    f"Deleted **{deleted_count}**, scheduled **{success_count}**."
                )
            )

    except Exception as e:
        if is_write_forbidden_error(str(e)):
            mark_schedule_disabled(config, str(e))
        await notify_manual_update(client, destination, config, str(e))
        await client.edit_message_text(
            chat_id="me",
            message_id=report_msg.id,
            text=f"Update failed for chat **{destination}**. Manual details were sent above."
        )


@app.on_message(filters.me & filters.command("clear", prefixes="."))
async def clear_scheduled(client, message):
    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.first_name or str(chat_id)
    topic_id = get_topic_id(message)
    destination = chat_title if topic_id is None else f"{chat_title} / topic {topic_id}"
    await message.delete()

    try:
        peer = await client.resolve_peer(chat_id)
        deleted_count = await delete_scheduled_messages(client, peer, topic_id)
        removed_config = remove_schedule_config(chat_id, topic_id)
        if not deleted_count and not removed_config:
            await client.send_message("me", f"No scheduled messages found in chat **{destination}**.")
            return

        await client.send_message(
            "me",
            f"Deleted **{deleted_count}** scheduled messages in chat **{destination}**. "
            f"Auto-refresh {'disabled' if removed_config else 'was not enabled'}."
        )

    except Exception as e:
        await client.send_message("me", f"Error while deleting: {e}")

async def main():
    await app.start()
    refresh_task = asyncio.create_task(auto_refresh_loop(app))

    try:
        print("Userbot started! Waiting for commands...")
        await idle()
    finally:
        refresh_task.cancel()
        await app.stop()


if __name__ == "__main__":
    app.run(main())
