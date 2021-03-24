import logging

from nio import (
    AsyncClient,
    InviteMemberEvent,
    JoinError,
    MatrixRoom,
    MegolmEvent,
    RoomGetEventError,
    RoomMessageText,
    RoomSendResponse,
    LocalProtocolError,
    UnknownEvent,
)

from star_bot.bot_commands import Command
from star_bot.chat_functions import make_pill, react_to_event, send_text_to_room
from star_bot.config import Config
from star_bot.message_responses import Message
from star_bot.storage import Storage

logger = logging.getLogger(__name__)


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
        self.command_prefix = config.command_prefix

    async def _reaction(
        self, room: MatrixRoom, event: UnknownEvent, reacted_to_id: str
    ) -> None:
        """A reaction was sent to one of our messages. Let's send a reply acknowledging it.

        Args:
            room: The room the reaction was sent in.

            event: The reaction event.

            reacted_to_id: The event ID that the reaction points to.
        """

        if isinstance(event, MegolmEvent):
            logger.debug("The event wasn't decrypted for some raisin")
            return

        logger.debug(f"Got reaction to {room.room_id} from {event.sender}.")

        # Get the original event that was reacted to
        event_response = await self.client.room_get_event(room.room_id, reacted_to_id)
        if isinstance(event_response, RoomGetEventError):
            logger.warning(
                "Error getting event that was reacted to (%s)", reacted_to_id
            )
            return
        reacted_to_event = event_response.event
        if isinstance(reacted_to_event, MegolmEvent):
            logger.debug("The reacted to event wasn't decrypted for some raisin")
            return

        # Ignore other users' reactions
        if event.sender != self.client.user:
            return

        # Don't react to my reactions in the star room
        if room.room_id == self.config.star_room_id:
            return

        reaction_content = (
            event.source.get("content", {}).get("m.relates_to", {}).get("key")
        )

        if reaction_content != '⭐️':
            return

        pill = make_pill(reacted_to_event.sender)
        while True:
            logger.info("Are we in the room?")
            logger.info(self.config.star_room_id in self.client.rooms)
            if self.config.star_room_id not in self.client.rooms:
                logger.info("We weren't in the room, bailing")
                break
            logger.info(self.client.rooms[self.config.star_room_id])
            try:
                result = await send_text_to_room(
                    self.client,
                    self.config.star_room_id,
                    f"<a href=\"https://matrix.to/#/{room.room_id}\">{room.display_name}</a>—{pill}: {reacted_to_event.body} [->](https://matrix.to/#/{room.room_id}/{reacted_to_event.event_id}?via=lant.uk)",
                    notice=False
                )
                logger.info(result)
                return
            except LocalProtocolError as e:
                logger.error(e)
                await self.client.sync()


    async def unknown(self, room: MatrixRoom, event: UnknownEvent) -> None:
        """Callback for when an event with a type that is unknown to matrix-nio is received.
        Currently this is used for reaction events, which are not yet part of a released
        matrix spec (and are thus unknown to nio).

        Args:
            room: The room the reaction was sent in.

            event: The event itself.
        """
        if event.type == "m.reaction":
            # Get the ID of the event this was a reaction to
            relation_dict = event.source.get("content", {}).get("m.relates_to", {})

            reacted_to = relation_dict.get("event_id")
            if reacted_to and relation_dict.get("rel_type") == "m.annotation":
                await self._reaction(room, event, reacted_to)
                return


        logger.debug(
            f"Got unknown event with type to {event.type} from {event.sender} in {room.room_id}."
        )
