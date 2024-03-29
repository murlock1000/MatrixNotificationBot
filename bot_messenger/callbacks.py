import asyncio
import logging

from nio import (
    AsyncClient,
    InviteMemberEvent,
    JoinError,
    MatrixRoom,
    RoomEncryptionEvent,
    RoomCreateResponse,
)

from bot_messenger.chat_functions import create_private_room, find_private_msg, send_message_to_room
from bot_messenger.config import Config
from bot_messenger.messages import BaseMessage
from bot_messenger.storage import Storage

logger = logging.getLogger(__name__)

DUPLICATES_CACHE_SIZE = 1000

class Callbacks:
    def __init__(self, client: AsyncClient, store: Storage, config: Config):
        """
        Args:
            client: nio client used to interact with matrix.

            store: Bot storage.

            config: Bot configuration parameters.
        """
        self.client = client
        self.store = store
        self.config = config
        
        self.received_events = []
        self.rooms_pending:dict[str, list[BaseMessage]] = {} # Room ids with encryption pending (room_id : [message])
        self.user_rooms_pending:dict[str, str] = {} # User ids with DMs encryption pending  (user_id : room_id)

    def trim_duplicates_caches(self):
        if len(self.received_events) > DUPLICATES_CACHE_SIZE:
            self.received_events = self.received_events[:DUPLICATES_CACHE_SIZE]
    
    def should_process(self, event_id: str) -> bool:
        logger.debug("Callback received event: %s", event_id)
        if event_id in self.received_events:
            logger.debug("Skipping %s as it's already processed", event_id)
            return False
        self.received_events.insert(0, event_id)
        return True
    
    async def notification(self, message:BaseMessage):
        """Send message to corresponding recipient type.

        Args:
            message: The message to send.
        """
        print("Sending message")
        print(message)
        # Check if message contains room_id recipient, otherwise find room with the corresponding recipient user_id
        if message.recipient_room_id is not None:
            await send_message_to_room(self.client, message)
        else:
            recipient_id = message.recipient_user_id
            if recipient_id in self.user_rooms_pending:
                pending_room_id = self.user_rooms_pending[recipient_id]
                message.recipient_room_id = pending_room_id
                self.rooms_pending[pending_room_id].append(message)
                return
            
            msg_room = find_private_msg(self.client, message.recipient_user_id)
            
            if msg_room is None:
                resp = await create_private_room(self.client, message.recipient_user_id, "Messenger room")
                if isinstance(resp, RoomCreateResponse):
                    recipient_room_id = resp.room_id
                    if recipient_room_id not in self.rooms_pending.keys():
                        self.rooms_pending[recipient_room_id] = []
                else:
                    logger.error(f"Failed to create room for {message.recipient_user_id}")
                    return
                
                message.recipient_room_id = recipient_room_id
                self.rooms_pending[recipient_room_id].append(message)
                return
            else:
                recipient_room_id = msg_room.room_id
                message.recipient_room_id = recipient_room_id
                logger.debug(f"Found existing room for {message.recipient_user_id}: {recipient_room_id}")
                await send_message_to_room(self.client, message)
                        
        #if sendTo is None:
        #    await send_text_to_room(self.client, self.config.notifications_room, msg)
        #else:
        #    if sendTo.startswith("@"):
               # await send_msg(self.client, sendTo, msg, "text")
        #    else:
        #        await send_text_to_room(self.client, sendTo, msg)

    async def room_encryption(self, room: MatrixRoom, event: RoomEncryptionEvent) -> None:
        """Callback for when an event signaling that encryption has been enabled in a room is received

        Args:
            room (nio.rooms.MatrixRoom): The room the event came from

            event (nio.events.room_events.RoomEncryptionEvent): The event
        """
        
        logger.warning(f"Room encryption enabled in room {room.room_id}")
        # Send all pending messages for the room when invited at least one user to the room (so encryption is initialized)
        if room.room_id in self.rooms_pending:
            for message in self.rooms_pending[room.room_id]:
                try:
                    logger.warn(f"Sending message to room {room.room_id}")
                    await send_message_to_room(self.client, message)
                except Exception as e:
                    logger.error(f"Error performing queued task after joining room: {e}")
            # Clear tasks
            self.rooms_pending.pop(room.room_id)
            self.user_rooms_pending.pop(message.recipient_user_id)
            
    async def invite(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        """Callback for when an invite is received. Join the room specified in the invite.

        Args:
            room: The room that we are invited to.

            event: The invite event.
        """
        logger.debug(f"Got invite to {room.room_id} from {event.sender}.")

        # Attempt to join 3 times before giving up
        for attempt in range(3):
            result = await self.client.join(room.room_id)
            if type(result) == JoinError:
                logger.error(
                    f"Error joining room {room.room_id} (attempt %d): %s",
                    attempt,
                    result.message,
                )
            else:
                break
        else:
            logger.error("Unable to join room: %s", room.room_id)

        # Successfully joined room
        logger.info(f"Joined {room.room_id}")

    async def invite_event_filtered_callback(
        self, room: MatrixRoom, event: InviteMemberEvent
    ) -> None:
        """
        Since the InviteMemberEvent is fired for every m.room.member state received
        in a sync response's `rooms.invite` section, we will receive some that are
        not actually our own invite event (such as the inviter's membership).
        This makes sure we only call `callbacks.invite` with our own invite events.
        """
        if event.state_key == self.client.user_id:
            # This is our own membership (invite) event
            await self.invite(room, event)