import asyncio
import nio
import logging

logger = logging.getLogger(__name__)

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
            if isinstance(response, nio.ErrorResponse):
                if response.status_code == "M_LIMIT_EXCEEDED":
                    await sleep_ms(response.retry_after_ms)
                else:
                    return response
            else:
                return response

    return wrapper