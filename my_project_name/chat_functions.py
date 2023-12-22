import logging
import asyncio
from typing import Optional, Union

from markdown import markdown
from nio import (
    AsyncClient,
    ErrorResponse,
    MatrixRoom,
    MegolmEvent,
    Response,
    RoomCreateError,
    RoomCreateResponse,
    RoomSendResponse,
    RoomVisibility,
    RoomPreset,
    LocalProtocolError,
    SendRetryError,
)

logger = logging.getLogger(__name__)


async def find_or_create_private_msg(
        self, mxid: str, roomname: str
    ) -> Union[RoomCreateResponse, RoomCreateError]:
        """
        :param mxid: user id to create a DM for
        :param roomname: The DM room name
        :return: the Room Response from room_create()
        """
        # Find if we already have a common room with user:
        msg_room = None
        for croomid in self.client.rooms:
            roomobj = self.client.rooms[croomid]
            if roomobj.member_count == 2:
                for user in roomobj.users:
                    if user == mxid:
                        msg_room = roomobj
                for user in roomobj.invited_users:
                    if user == mxid:
                        msg_room = roomobj
        # Nope, let's create one
        if msg_room is None:
            msg_room = await self.client.room_create(
                visibility=RoomVisibility.private,
                name=roomname,
                is_direct=True,
                preset=RoomPreset.private_chat,
                invite={mxid},
            )
            if type(msg_room) == RoomCreateError:
                logger.error(f"Failed to create a room, exiting")
                await self.client.close()
            else:
                logger.debug(f"Created new room with id: {msg_room.room_id}")
        return msg_room


async def _send_task(self, room_id: str, send_method: staticmethod, content: str, type):
        """
        : Wait for new sync, until we receive the new room information
        : Send the message to the room
        """
        while self.client.rooms.get(room_id) is None:
            await self.client.synced.wait()
        while self.client.rooms[room_id].encrypted is False:
            await self.client.synced.wait()
        await send_method(room_id, content, type)

async def send_msg(mxid: str, content: str, message_type:str, room_id: str = None, roomname: str = "Notification"):
        """
        :Code from - https://github.com/vranki/hemppa/blob/dcd69da85f10a60a8eb51670009e7d6829639a2a/bot.py
        :param mxid: A Matrix user id to send the message to
        :param roomname: A Matrix room id to send the message to
        :param message: Text to be sent as message
        :return bool: Returns room id upon sending the message
        """

        # Sends private message to user. Returns true on success.
        if room_id is None:
            msg_room = await find_or_create_private_msg(mxid, roomname)
            if not msg_room or (type(msg_room) is RoomCreateError):
                logger.error(f"Unable to create room when trying to message {mxid}")
                return None
            room_id = msg_room.room_id

        """
        : A concurrency problem: creating a new room does not sync the local data about rooms.
        : In order to perform the sync, we must exit the callback.
        : Solution: use an asyncio task, that performs the sync.wait() and sends the message afterwards concurently with sync_forever().
        """
        #if message_type == 'text':
        asyncio.get_event_loop().create_task(
            _send_task(room_id, send_text_to_room, content, "")
        )
        #elif message_type =='image':
       #         asyncio.get_event_loop().create_task(
       #         self._send_task(room_id, self.send_file_to_room, content, "m.image")
       #         )
       # elif message_type =='file':
       #         asyncio.get_event_loop().create_task(
       #         self._send_task(room_id, self.send_file_to_room, content, "m.file")
               # )
        return room_id

async def send_text_to_room(
    client: AsyncClient,
    room_id: str,
    message: str,
    notice: bool = True,
    markdown_convert: bool = True,
    reply_to_event_id: Optional[str] = None,
) -> Union[RoomSendResponse, ErrorResponse]:
    """Send text to a matrix room.

    Args:
        client: The client to communicate to matrix with.

        room_id: The ID of the room to send the message to.

        message: The message content.

        notice: Whether the message should be sent with an "m.notice" message type
            (will not ping users).

        markdown_convert: Whether to convert the message content to markdown.
            Defaults to true.

        reply_to_event_id: Whether this message is a reply to another event. The event
            ID this is message is a reply to.

    Returns:
        A RoomSendResponse if the request was successful, else an ErrorResponse.
    """
    # Determine whether to ping room members or not
    msgtype = "m.notice" if notice else "m.text"

    content = {
        "msgtype": msgtype,
        #"format": "org.matrix.custom.html",
        "body": message,
    }

    if markdown_convert:
        content["formatted_body"] = markdown(message)

    if reply_to_event_id:
        content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to_event_id}}

    try:
        return await client.room_send(
            room_id,
            "m.room.message",
            content,
            ignore_unverified_devices=True,
        )
    except (SendRetryError, LocalProtocolError):
        logger.exception(f"Unable to send message response to {room_id}")


def make_pill(user_id: str, displayname: str = None) -> str:
    """Convert a user ID (and optionally a display name) to a formatted user 'pill'

    Args:
        user_id: The MXID of the user.

        displayname: An optional displayname. Clients like Element will figure out the
            correct display name no matter what, but other clients may not. If not
            provided, the MXID will be used instead.

    Returns:
        The formatted user pill.
    """
    if not displayname:
        # Use the user ID as the displayname if not provided
        displayname = user_id

    return f'<a href="https://matrix.to/#/{user_id}">{displayname}</a>'


async def react_to_event(
    client: AsyncClient,
    room_id: str,
    event_id: str,
    reaction_text: str,
) -> Union[Response, ErrorResponse]:
    """Reacts to a given event in a room with the given reaction text

    Args:
        client: The client to communicate to matrix with.

        room_id: The ID of the room to send the message to.

        event_id: The ID of the event to react to.

        reaction_text: The string to react with. Can also be (one or more) emoji characters.

    Returns:
        A nio.Response or nio.ErrorResponse if an error occurred.

    Raises:
        SendRetryError: If the reaction was unable to be sent.
    """
    content = {
        "m.relates_to": {
            "rel_type": "m.annotation",
            "event_id": event_id,
            "key": reaction_text,
        }
    }

    return await client.room_send(
        room_id,
        "m.reaction",
        content,
        ignore_unverified_devices=True,
    )


async def decryption_failure(self, room: MatrixRoom, event: MegolmEvent) -> None:
    """Callback for when an event fails to decrypt. Inform the user"""
    logger.error(
        f"Failed to decrypt event '{event.event_id}' in room '{room.room_id}'!"
        f"\n\n"
        f"Tip: try using a different device ID in your config file and restart."
        f"\n\n"
        f"If all else fails, delete your store directory and let the bot recreate "
        f"it (your reminders will NOT be deleted, but the bot may respond to existing "
        f"commands a second time)."
    )

    user_msg = (
        "Unable to decrypt this message. "
        "Check whether you've chosen to only encrypt to trusted devices."
    )

    await send_text_to_room(
        self.client,
        room.room_id,
        user_msg,
        reply_to_event_id=event.event_id,
    )
