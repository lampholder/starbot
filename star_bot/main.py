#!/usr/bin/env python3
import asyncio
import logging
import sys
from time import sleep

from aiohttp import ClientConnectionError, ServerDisconnectedError
from nio import (
    AsyncClient,
    AsyncClientConfig,
    InviteMemberEvent,
    LocalProtocolError,
    LoginError,
    MegolmEvent,
    RoomMessageText,
    RedactionEvent,
    JoinError,
    UnknownEvent,
)

from star_bot.chat_functions import send_text_to_room
from star_bot.callbacks import Callbacks
from star_bot.config import Config
from star_bot.storage import Storage

logger = logging.getLogger(__name__)


async def main():
    """The first function that is run when starting the bot"""

    # Read user-configured options from a config file.
    # A different config file path can be specified as the first command line argument
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = "config.yaml"

    # Read the parsed config file and create a Config object
    config = Config(config_path)

    # Configure the database
    store = Storage(config.database)

    # Configuration options for the AsyncClient
    client_config = AsyncClientConfig(
        max_limit_exceeded=0,
        max_timeouts=0,
        store_sync_tokens=True,
        encryption_enabled=True,
    )

    # Initialize the matrix client
    client = AsyncClient(
        config.homeserver_url,
        config.user_id,
        device_id=config.device_id,
        store_path=config.store_path,
        config=client_config,
    )

    if config.user_token:
        client.access_token = config.user_token
        client.user_id = config.user_id

    # Set up event callbacks
    callbacks = Callbacks(client, store, config)
    client.add_event_callback(callbacks.unknown, (UnknownEvent,))

    # Keep trying to reconnect on failure (with some time in-between)
    while True:
        try:
            if config.user_token:
                # Use token to log in
                client.load_store()

                # Sync encryption keys with the server
                if client.should_upload_keys:
                    await client.keys_upload()
            else:
                # Try to login with the configured username/password
                try:
                    login_response = await client.login(
                        password=config.user_password,
                        device_name=config.device_name,
                    )

                    # Check if login failed
                    if type(login_response) == LoginError:
                        logger.error("Failed to login: %s", login_response.message)
                        return False
                except LocalProtocolError as e:
                    # There's an edge case here where the user hasn't installed the correct C
                    # dependencies. In that case, a LocalProtocolError is raised on login.
                    logger.fatal(
                        "Failed to login. Have you installed the correct dependencies? "
                        "https://github.com/poljar/matrix-nio#installation "
                        "Error: %s",
                        e,
                    )
                    return False

                # Login succeeded!

            logger.info(f"Logged in as {config.user_id}")

            # Try and get the full state so we knoow what rooms we're in
            # EDIT: This doesn't seem to help
            # await client.sync(full_state=True)

            logger.info("Joining star room")
            if config.star_room_id not in client.rooms:
                for attempt in range(3):
                    logger.info(f"attempt {attempt}")
                    result = await client.join(config.star_room_id)
                    if type(result) == JoinError:
                        logger.error(
                            f"Error joining room {room.room_id} (attempt %d): %s",
                            attempt,
                            result.message,
                        )
                    else:
                        logger.info(result)
                        logger.info("We're in the room (aside: we're not)")
            else:
                logger.info("We're already joined")

            # await send_text_to_room(
            #     client,
            #     config.star_room_id,
            #     'STARBOT ONLINE',
            #     notice=True
            # )

            await client.sync_forever(timeout=9000000, full_state=True)

        except (ClientConnectionError, ServerDisconnectedError):
            logger.warning("Unable to connect to homeserver, retrying in 15s...")

            # Sleep so we don't bombard the server with login requests
            sleep(15)
        finally:
            # Make sure to close the client connection on disconnect
            await client.close()


# Run the main function in an asyncio event loop
asyncio.get_event_loop().run_until_complete(main())
