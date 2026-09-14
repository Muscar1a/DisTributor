"""Public request boundaries for the OpenAI-compatible API.

Keep these defaults in one dependency-free module so validation, middleware,
generated OpenAPI, and configuration defaults cannot silently drift apart.
"""

MAX_BODY_BYTES = 1_000_000
MAX_INPUT_TOKENS = 8_000
MAX_OUTPUT_TOKENS = 8_192
MAX_MESSAGES = 50
