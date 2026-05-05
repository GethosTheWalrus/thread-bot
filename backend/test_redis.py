import asyncio
import redis.asyncio as aioredis

async def main():
    r = aioredis.from_url("redis://redis:6379")
    await r.delete("test")
    await r.rpush("test", "A", "B", "C")
    print(await r.lrange("test", 3, -1))
    await r.close()

asyncio.run(main())