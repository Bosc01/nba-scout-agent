import asyncio

from tools.search import search


async def main():
    results = await search("Cooper Flagg Duke basketball stats", max_results=5)
    print(f"Got {len(results)} results")
    for r in results:
        print(f"Title: {r.get('title')}")
        print(f"URL: {r.get('url')}")
        print(f"Snippet: {r.get('snippet', '')[:100]}")
        print("---")


asyncio.run(main())
