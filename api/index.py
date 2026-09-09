"""Vercel ASGI entrypoint; retain the existing application and API paths."""
from backend.app.main import app as application


async def app(scope, receive, send):
    # Finish Starlette background work before sending the response to Vercel.
    # No worker process or work after the function response is required.
    if scope["type"] != "http":
        return await application(scope, receive, send)
    messages = []

    async def buffered_send(message):
        messages.append(message)

    await application(scope, receive, buffered_send)
    for message in messages:
        await send(message)
