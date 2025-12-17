"""Clear corrupted tracker data from Redis"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main():
    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        print("No REDIS_URL found")
        return

    import redis.asyncio as redis
    r = redis.from_url(redis_url, decode_responses=True)

    # Keys to clear
    keys_to_clear = [
        'exit_tracker_v2',
        'tp_tracker_v2',
        'global_tp_tracker'
    ]

    print("=== CLEARING CORRUPTED TRACKER DATA ===")
    for key in keys_to_clear:
        exists = await r.exists(key)
        if exists:
            await r.delete(key)
            print(f"  Deleted: {key}")
        else:
            print(f"  Not found: {key}")

    print("\nTracker data cleared. Bot will start fresh on next restart.")
    await r.close()

if __name__ == "__main__":
    asyncio.run(main())
