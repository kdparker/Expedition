from hikari import Permissions

SQLITE_DB="expedition.sqlite"

READ_PERMISSIONS = (
    Permissions.READ_MESSAGE_HISTORY
    | Permissions.VIEW_CHANNEL 
)

READ_DENIES = (
    Permissions.MANAGE_CHANNELS
    | Permissions.MANAGE_ROLES
    | Permissions.MANAGE_GUILD
    | Permissions.MANAGE_WEBHOOKS
    | Permissions.MANAGE_THREADS
    | Permissions.CREATE_INSTANT_INVITE
    | Permissions.CREATE_PRIVATE_THREADS
    | Permissions.CREATE_PUBLIC_THREADS
    | Permissions.SEND_MESSAGES
    | Permissions.SEND_MESSAGES_IN_THREADS
    | Permissions.EMBED_LINKS
    | Permissions.ATTACH_FILES
    | Permissions.ADD_REACTIONS
    | Permissions.USE_EXTERNAL_EMOJIS
    | Permissions.USE_EXTERNAL_STICKERS
    | Permissions.MENTION_ROLES
    | Permissions.MANAGE_MESSAGES
    | Permissions.SEND_TTS_MESSAGES
    | Permissions.USE_APPLICATION_COMMANDS
)

WRITE_PERMISSIONS = (
    Permissions.READ_MESSAGE_HISTORY
    | Permissions.VIEW_CHANNEL 
    | Permissions.ATTACH_FILES
    | Permissions.EMBED_LINKS
    | Permissions.SEND_MESSAGES
    | Permissions.USE_APPLICATION_COMMANDS
    | Permissions.USE_EXTERNAL_EMOJIS
    | Permissions.USE_EXTERNAL_STICKERS
)

WRITE_DENIES = (
    Permissions.MANAGE_CHANNELS
    | Permissions.MANAGE_ROLES
    | Permissions.MANAGE_GUILD
    | Permissions.MANAGE_WEBHOOKS
    | Permissions.MANAGE_THREADS
    | Permissions.ADD_REACTIONS
    | Permissions.CREATE_INSTANT_INVITE
    | Permissions.CREATE_PRIVATE_THREADS
    | Permissions.CREATE_PUBLIC_THREADS
    | Permissions.SEND_MESSAGES_IN_THREADS
    | Permissions.MENTION_ROLES
    | Permissions.MANAGE_MESSAGES
    | Permissions.SEND_TTS_MESSAGES
)
