
import io
import logging
import asyncio
import os
import re
import traceback
import magic
from typing import Optional, Union
from PIL import Image

from markdown import markdown
from nio import (
    AsyncClient,
    ErrorResponse,
    MatrixRoom,
    RoomCreateError,
    RoomCreateResponse,
    RoomSendResponse,
    RoomVisibility,
    RoomPreset,
    LocalProtocolError,
    SendRetryError,
    UploadResponse,
    RoomAvatarEvent,
    RoomSendError,
)

from bot_messenger.messages import BaseMessage, MediaMessage, MessageType, TextMessage

logger = logging.getLogger(__name__)


def is_user_in_room(room: MatrixRoom, mxid: str) -> bool:
    for user in room.users:
        if user == mxid:
            return True
    for user in room.invited_users:
        if user == mxid:
            return True
    return False

def is_room_private_msg(room: MatrixRoom, mxid: str) -> bool:
    if room.member_count == 2:
        return is_user_in_room(room, mxid)
    return False

def find_private_msg(client: AsyncClient, mxid: str) -> Union[MatrixRoom, None]:
    # Find if we already have a common room with user:
    msg_room = None
    for roomid in client.rooms:
        room = client.rooms[roomid]
        if is_room_private_msg(room, mxid):
            msg_room = room
            break

    if msg_room:
        logger.debug(
            f"Found existing DM for user {mxid} with roomID: {msg_room.room_id}"
        )
    return msg_room

async def create_private_room(
    client: AsyncClient, mxid: str, roomname: str
) -> Union[RoomCreateResponse, RoomCreateError, RoomAvatarEvent]:

    """
    :param mxid: user id to create a DM for
    :param roomname: The DM room name
    :return: the Room Response from room_create()
    """
    initial_state = [
        {
            "type": "m.room.power_levels",
            "content": {"users": {mxid: 100, client.user_id: 100}},
        }
    ]
    resp = await with_ratelimit(client.room_create)(
        visibility=RoomVisibility.private,
        name=roomname,
        is_direct=True,
        preset=RoomPreset.private_chat,
        initial_state=initial_state,
        invite={mxid},
    )
    if isinstance(resp, RoomCreateResponse):
        logger.debug(f"Created a new DM for user {mxid} with roomID: {resp.room_id}")
    elif isinstance(resp, RoomCreateError):
        logger.exception(
            f"Failed to create a new DM for user {mxid} with error: {resp.status_code}"
        )
    return resp

async def send_message_to_room(client: AsyncClient, message: BaseMessage):
    # Send the message based on the message type
    if message.message_type == MessageType.TEXT:
        textMessage: TextMessage = message
        content = textMessage.get_content()
        await send_text_to_room(client, textMessage.recipient_room_id, content)
    elif message.message_type == MessageType.MEDIA:
        mediaMessage: MediaMessage = message
        content = mediaMessage.get_content()
        msgtype = get_message_type(mediaMessage)
        
        if msgtype == "m.image":
            await send_image(client, mediaMessage.recipient_room_id, content, mediaMessage.message_length_in_bytes, mediaMessage.file_name)   
        else:
            await send_file(client, mediaMessage.recipient_room_id, content, mediaMessage.message_length_in_bytes, mediaMessage.file_name)
    else:
        logger.warning(f"Message type {message.message_type} not supported")


def get_message_type(message: MediaMessage):
    if re.match(
        "^.jpg$|^.jpeg$|^.gif$|^.png$|^.svg$",
        os.path.splitext(message.file_name)[1].lower(),
    ):
        return "m.image"
    else:
        return "m.file"
        

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

    if message.startswith("<html>"):
        content["format"] = "org.matrix.custom.html"
        message = message.replace('\n', '')
        content["formatted_body"] = message
        content["body"] = message
    elif markdown_convert:
        content["formatted_body"] = markdown(message)

    if reply_to_event_id:
        content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to_event_id}}

    try:
        return await with_ratelimit(client.room_send)(
                    room_id,
                    "m.room.message",
                    content,
                    ignore_unverified_devices=True
                    )
    except (SendRetryError, LocalProtocolError):
        logger.exception(f"Unable to send message response to {room_id}")

async def sleep_ms(delay_ms):
    deadzone = 50  # 50ms additional wait time.
    delay_s = (delay_ms + deadzone) / 1000

    await asyncio.sleep(delay_s)

def with_ratelimit(func):
    """
    Decorator for calling client methods with backoff, specified in server response if rate limited.
    """
    async def wrapper(*args, **kwargs):
        while True:
            logger.debug(f"waiting for response")
            response = await func(*args, **kwargs)
            logger.debug(f"Response: {response}")
            if isinstance(response, ErrorResponse):
                if response.status_code == "M_LIMIT_EXCEEDED":
                    await sleep_ms(response.retry_after_ms)
                else:
                    return response
            else:
                return response

    return wrapper



# Adapted methods from https://github.com/8go/matrix-commander/blob/master/matrix_commander/matrix_commander.py
async def send_file(client,     
        room_id: str,
        data: bytes,
        file_size: int,
        file_name: str
)-> Union[RoomSendResponse, ErrorResponse]:
    """Process file.

    Upload file to server and then send link to rooms.
    Works and tested for .pdf, .txt, .ogg, .wav.
    All these file types are treated the same.

    Do not use this function for images.
    Use the send_image() function for images.

    Matrix has types for audio and video (and image and file).
    See: "msgtype" == "m.image", m.audio, m.video, m.file

    Arguments:
    ---------
    client : Client
    message : MediaMessage

    This is a working example for a PDF file.
    It can be viewed or downloaded from:
    https://matrix.example.com/_matrix/media/r0/download/
        example.com/SomeStrangeUriKey
    {
        "type": "m.room.message",
        "sender": "@someuser:example.com",
        "content": {
            "body": "example.pdf",
            "info": {
                "size": 6301234,
                "mimetype": "application/pdf"
                },
            "msgtype": "m.file",
            "url": "mxc://example.com/SomeStrangeUriKey"
        },
        "origin_server_ts": 1595100000000,
        "unsigned": {
            "age": 1000,
            "transaction_id": "SomeTxId01234567"
        },
        "event_id": "$SomeEventId01234567789Abcdef012345678",
        "room_id": "!SomeRoomId:example.com"
    }

    """
    
    # # restrict to "txt", "pdf", "mp3", "ogg", "wav", ...
    # if not re.match("^.pdf$|^.txt$|^.doc$|^.xls$|^.mobi$|^.mp3$",
    #                os.path.splitext(file)[1].lower()):
    #    gs.log.debug(f"File {file} is not a permitted file type. Should be "
    #                 ".pdf, .txt, .doc, .xls, .mobi or .mp3 ... "
    #                 f"[{os.path.splitext(file)[1].lower()}]"
    #                 "This file is being dropped and NOT sent.")
    #    return

    # 'application/pdf' "plain/text" "audio/ogg"
    mime_type = magic.from_buffer(data, mime=True)
    # if ((not mime_type.startswith("application/")) and
    #        (not mime_type.startswith("plain/")) and
    #        (not mime_type.startswith("audio/"))):
    #    gs.log.debug(f"File {file} does not have an accepted mime type. "
    #                 "Should be something like application/pdf. "
    #                 f"Found mime type {mime_type}. "
    #                 "This file is being dropped and NOT sent.")
    #    return

    # first do an upload of file, see upload() documentation
    # http://matrix-nio.readthedocs.io/en/latest/nio.html#nio.AsyncClient.upload
    # then send URI of upload to room

    resp, decryption_keys = await client.upload(
        io.BytesIO(data),
        content_type=mime_type,  # application/pdf
        filename=file_name,
        filesize=file_size,
        encrypt=True,
    )
    if isinstance(resp, UploadResponse):
        logger.debug(
            f"File {file_name} of type {mime_type} and size {file_size} was uploaded successfully to server. "
            f"Response is: {resp.content_uri}"
        )
    else:
        logger.info(
            "Failed to upload file to server. "
            "Please retry. This could be temporary issue on "
            "your server. "
            "Sorry."
        )
        logger.info(
            f'file="{file_name}"; mime_type="{mime_type}"; '
            f'filessize="{file_size}"'
            f"Failed to upload: {resp}"
        )
        return

    # determine msg_type:
    if mime_type.startswith("audio/"):
        msg_type = "m.audio"
    elif mime_type.startswith("video/"):
        msg_type = "m.video"
    else:
        msg_type = "m.file"

    content = {
        "body": file_name,  # descriptive title
        "info": {
            "size": file_size,
            "mimetype": mime_type
        },
        "msgtype": msg_type,
        "file": {
            "url": resp.content_uri,
            "key": decryption_keys["key"],
            "iv": decryption_keys["iv"],
            "hashes": decryption_keys["hashes"],
            "v": decryption_keys["v"],
        },
    }

    try:
        resp = await with_ratelimit(client.room_send)(
            room_id,
            message_type="m.room.message",
            content=content,
            ignore_unverified_devices=True
        )
        if isinstance(resp, RoomSendError):
            logger.error(
                "E146: "
                "room_send failed with error "
                f"'{str(resp)}'."
            )
        logger.info(
            f'This file was sent: "{file_name}" to room "{resp.room_id}" '
            f'as event "{resp.event_id}".'
        )
        logger.debug(
            f'This file was sent: "{file_name}" to room "{room_id}". '
            f"Response: event_id={resp.event_id}, room_id={resp.room_id}, "
            f"full response: {str(resp)}. "
        )
    except Exception:
        logger.error("E147: " f"File send of file {file_name} failed. Sorry.")
        logger.debug("Here is the traceback.\n" + traceback.format_exc())


async def send_image(client,     
        room_id: str,
        data: bytes,
        file_size: int,
        file_name: str):
    """Process image.

    Arguments:
    ---------
    client : Client
    rooms : list
        list of room_id-s
    image : str
        file name of image from --image argument

    This is a working example for a JPG image.
    It can be viewed or downloaded from:
    https://matrix.example.com/_matrix/media/r0/download/
        example.com/SomeStrangeUriKey
    {
        "type": "m.room.message",
        "sender": "@someuser:example.com",
        "content": {
            "body": "someimage.jpg",
            "info": {
                "size": 5420,
                "mimetype": "image/jpeg",
                "thumbnail_info": {
                    "w": 100,
                    "h": 100,
                    "mimetype": "image/jpeg",
                    "size": 2106
                },
                "w": 100,
                "h": 100,
                "thumbnail_url": "mxc://example.com/SomeStrangeThumbnailUriKey"
            },
            "msgtype": "m.image",
            "url": "mxc://example.com/SomeStrangeUriKey"
        },
        "origin_server_ts": 12345678901234576,
        "unsigned": {
            "age": 268
        },
        "event_id": "$skdhGJKhgyr548654YTr765Yiy58TYR",
        "room_id": "!JKHgyHGfytHGFjhgfY:example.com"
    }

    """

    # "bmp", "gif", "jpg", "jpeg", "png", "pbm", "pgm", "ppm", "xbm", "xpm",
    # "tiff", "webp", "svg",

    # svg files are not shown in Element, hence send SVG files as files with -f
    if not re.match(
        "^.jpg$|^.jpeg$|^.gif$|^.png$|^.svg$",
        os.path.splitext(file_name)[1].lower(),
    ):
        logger.warning(
            f"Image file {file_name} is not an image file. Should be "
            ".jpg, .jpeg, .gif, or .png. "
            f"Found [{os.path.splitext(file_name)[1].lower()}]. "
            "This image is being dropped and NOT sent."
        )
        return

    # 'application/pdf' "image/jpeg"
    # svg mime-type is "image/svg+xml"
    mime_type = magic.from_buffer(data, mime=True)

    logger.debug(f"Image file mime-type is {mime_type}")
    if not mime_type.startswith("image/"):
        logger.warning(
            f"Image file {file_name} does not have an image mime type. "
            "Should be something like image/jpeg. "
            f"Found mime type {mime_type}. "
            "This image is being dropped and NOT sent."
        )
        return

    if mime_type.startswith("image/svg"):
        logger.warning(
            "There is a bug in Element preventing previews of SVG images. "
            "Alternatively you may send SVG files as files via -f."
        )
        width = 100  # in pixel
        height = 100
        # Python blurhash package does not work on SVG
        # blurhash: some random colorful image
        blurhash = "ULH_C:0HGF}B.$k:PLVG8z}$4;o?~IQ:9$yB"
        blurhash = None  # shows turning circle forever in Element due to bug
    else:
        im = Image.open(io.BytesIO(data))  # this will fail for SVG files
        (width, height) = im.size  # im.size returns (width,height) tuple
        blurhash = None

    # first do an upload of image, see upload() documentation
    # http://matrix-nio.readthedocs.io/en/latest/nio.html#nio.AsyncClient.upload
    # then send URI of upload to room
    # Note that encrypted upload works even with unencrypted/plain rooms; the
    # decryption keys will not be protected, obviously, but no special
    # treatment is required.

    resp, decryption_keys = await client.upload(
        io.BytesIO(data),
        content_type=mime_type,  # image/jpeg
        filename=file_name,
        filesize=file_size,
        encrypt=True,
    )
    if isinstance(resp, UploadResponse):
        logger.debug(
            "Image was uploaded successfully to server. "
            f"Response is: {str(resp)}"
        )
    else:
        logger.info(
            "Failed to upload file to server. "
            "Please retry. This could be temporary issue on "
            "your server. "
            "Sorry."
        )
        logger.info(
            f'file="{file_name}"; mime_type="{mime_type}"; '
            f'filessize="{file_size}"'
            f"Failed to upload: {resp}"
        )
        return

    # TODO compute thumbnail, upload thumbnail to Server
    # TODO add thumbnail info to `content`

    content = {
        "body": file_name,  # descriptive title
        "info": {
            "size": file_size,
            "mimetype": mime_type,
            # "thumbnail_info": None,  # TODO
            "w": width,  # width in pixel
            "h": height,  # height in pixel
            # "thumbnail_url": None,  # TODO
            "xyz.amorgan.blurhash": blurhash
            # "thumbnail_file": None,
        },
        "msgtype": "m.image",
        "file": {
            "url": resp.content_uri,
            "key": decryption_keys["key"],
            "iv": decryption_keys["iv"],
            "hashes": decryption_keys["hashes"],
            "v": decryption_keys["v"],
        },
    }

    try:
        resp = await with_ratelimit(client.room_send)(
            room_id,
            message_type="m.room.message",
            content=content,
            ignore_unverified_devices=True
        )
        if isinstance(resp, RoomSendError):
            logger.error(
                "E148: "
                "room_send failed with error "
                f"'{str(resp)}'."
            )
            # gs.err_count += 1 # not needed, will raise exception
            # in following line of code
        logger.info(
            f'This image file was sent: "{file_name}" '
            f'to room "{resp.room_id}" '
            f'as event "{resp.event_id}".'
        )
        logger.debug(
            f'This image file was sent: "{file_name}" '
            f'to room "{room_id}". '
            f"Response: event_id={resp.event_id}, room_id={resp.room_id}, "
            f"full response: {str(resp)}. "
        )
    except Exception:
        logger.error("E149: " f"Image send of file {file_name} failed. Sorry.")
        logger.debug("Here is the traceback.\n" + traceback.format_exc())