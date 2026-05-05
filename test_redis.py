import asyncio
import redis.asyncio as aioredis

async def main():
    r = aioredis.from_url("redis://localhost:6379")
    await r.delete("test_events")
    await r.rpush("test_events", "A", "B", "C")
    print(await r.lrange("test_events", 0, -1))
    print(await r.lrange("test_events", 3, -1))
    await r.close()

asyncio.run(main())
