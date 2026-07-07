import asyncio
import sys
import os
import re
import warnings
import logging
from datetime import datetime, timedelta

warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from pyrogram import Client, filters, raw, utils
from pyrogram.raw import functions

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("Error: API_ID or API_HASH not found in .env file!")
    sys.exit(1)

app = Client("my_account", api_id=int(API_ID), api_hash=API_HASH)


def parse_time(time_str: str) -> int:
    """Парсит строку вида 1d2h30m в секунды."""
    total_seconds = 0
    days = re.search(r"(\d+)d", time_str)
    hours = re.search(r"(\d+)h", time_str)
    minutes = re.search(r"(\d+)m", time_str)

    if days: total_seconds += int(days.group(1)) * 86400
    if hours: total_seconds += int(hours.group(1)) * 3600
    if minutes: total_seconds += int(minutes.group(1)) * 60

    return total_seconds


def get_topic_id(message, fallback_message=None):
    topic_id = getattr(message, "reply_to_top_message_id", None)

    if topic_id is None and fallback_message is not None:
        topic_id = getattr(fallback_message, "reply_to_top_message_id", None)

    return topic_id


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


async def schedule_recreated_message(client, peer, message, schedule_date, topic_id, media_group=None):
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

        await client.invoke(
            functions.messages.SendMultiMedia(
                peer=peer,
                multi_media=multi_media,
                top_msg_id=topic_id,
                schedule_date=schedule_timestamp
            )
        )
        return

    file_id = get_message_file_id(message)

    if file_id:
        text, entities = await parse_message_text(client, message)
        await client.invoke(
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
        await client.invoke(
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

    raise ValueError("unsupported protected message type")


@app.on_message(filters.me & filters.command("send", prefixes="."))
async def schedule_messages(client, message):
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
            await client.send_message("me", "Error: invalid time format.")
            return

    except ValueError:
        await message.delete()
        await client.send_message("me", "Error: format is .send <time> <count>")
        return

    target_msg = message.reply_to_message
    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.first_name or str(chat_id)
    topic_id = get_topic_id(message, target_msg)
    destination = chat_title if topic_id is None else f"{chat_title} / topic {topic_id}"

    await message.delete()

    report_msg = await client.send_message(
        "me",
        f"⏳ Scheduling {num} messages for chat **{destination}**..."
    )

    msg_ids = [target_msg.id]
    media_group = None

    if target_msg.media_group_id:
        try:
            media_group = await client.get_media_group(chat_id, target_msg.id)
            msg_ids = [m.id for m in media_group]
        except Exception as e:
            await client.send_message("me", f"Error fetching album: {e}")
            return

    peer = await client.resolve_peer(chat_id)
    from_peer = await client.resolve_peer(target_msg.chat.id)

    success_count = 0
    use_forward = True

    for i in range(1, num + 1):
        schedule_date = datetime.now() + timedelta(seconds=interval_seconds * i)

        try:
            if use_forward:
                random_ids = [client.rnd_id() for _ in msg_ids]

                await client.invoke(
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
                await schedule_recreated_message(client, peer, target_msg, schedule_date, topic_id, media_group)

            success_count += 1

        except Exception as e:
            error_text = str(e)
            if "SCHEDULE_TOO_MUCH" in error_text:
                await client.send_message("me", f"Telegram limit reached (100 msgs). Stopped.")
                break
            elif "CHAT_FORWARDS_RESTRICTED" in error_text and use_forward:
                use_forward = False

                try:
                    await schedule_recreated_message(client, peer, target_msg, schedule_date, topic_id, media_group)
                    success_count += 1
                    await client.send_message(
                        "me",
                        "Forwarding is restricted in this chat. Switched to resend mode for the remaining messages."
                    )
                except Exception as fallback_error:
                    await client.send_message("me", f"Fallback failed on step {i}: {fallback_error}")
            else:
                await client.send_message("me", f"Error on step {i}: {error_text}")

        if i % 20 == 0 and i < num:
            await client.edit_message_text(
                chat_id="me",
                message_id=report_msg.id,
                text=f"Scheduled {success_count}/{num}... Waiting 10s to avoid flood-wait."
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
        text=f"✅ Done. Successfully scheduled **{success_count}** messages in chat **{destination}**."
    )


@app.on_message(filters.me & filters.command("clear", prefixes="."))
async def clear_scheduled(client, message):
    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.first_name or str(chat_id)
    await message.delete()

    try:
        peer = await client.resolve_peer(chat_id)
        history = await client.invoke(functions.messages.GetScheduledHistory(peer=peer, hash=0))

        if not history.messages:
            await client.send_message("me", f"No scheduled messages found in chat **{chat_title}**.")
            return

        msg_ids = [msg.id for msg in history.messages]
        await client.invoke(functions.messages.DeleteScheduledMessages(peer=peer, id=msg_ids))
        await client.send_message("me", f"Deleted **{len(msg_ids)}** scheduled messages in chat **{chat_title}**.")

    except Exception as e:
        await client.send_message("me", f"Error while deleting: {e}")

if __name__ == "__main__":
    print("Userbot started! Waiting for commands...")
    app.run()
