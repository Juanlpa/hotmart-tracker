import asyncio
import logging
from src.scrapers.hotmart import scrape_all_categories
from src.core.config import settings

# Setup logging to output nicely to a file
logger = logging.getLogger("src.scrapers.hotmart")
logger.setLevel(logging.INFO)
fh = logging.FileHandler("test_scraper.log", encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logger.addHandler(fh)

async def main():
    print("Starting fast auth test... Email:", settings.hotmart_email)
    products = await scrape_all_categories()
    print(f"Extraction complete. Found {len(products)} products.")

    import json

    # Now dump the inner html of the very first product
    print("\n--- FIRST PRODUCT TRACE ---")
    raw_html = "NO_DEBUG"
    dump_url = ""
    for p in products:
        if hasattr(p, '_debug_html'):
            raw_html = p._debug_html
            dump_url = p.url_venta
            break
            
    with open("debug_trace.json", "w", encoding="utf-8") as f:
        json.dump({"html": raw_html, "url": dump_url}, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
