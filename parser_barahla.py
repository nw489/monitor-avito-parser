# parser_barahla.py

import time
import re
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=3)

BASE_URL = "https://www.barahla.ru"


async def parse_barahla(search_query: str, max_price: int = None, limit: int = 30, city: str = 'Все регионы'):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        _sync_parse_barahla,
        search_query,
        max_price,
        limit,
        city
    )
    return result


def _clean_title(raw_title: str) -> str:
    if not raw_title:
        return ""
    return re.sub(r'\s+', ' ', raw_title).strip()


def _sync_parse_barahla(search_query: str, max_price: int = None, limit: int = 30, city: str = 'Все регионы'):
    query = search_query.replace(' ', '+')
    url = f"{BASE_URL}/search?q={query}"
    if max_price:
        url += f"&price_max={max_price}"

    items = []
    driver = None

    try:
        print(f"🚀 Барахла: запуск браузера для: {search_query}")

        options = uc.ChromeOptions()
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-web-security')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        driver = uc.Chrome(options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        print(f"🌐 Барахла: открываем {url}")
        driver.get(url)
        time.sleep(5)

        # Скролл
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        with open('debug_barahla.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("💾 debug_barahla.html сохранён")

        # Поиск карточек
        ad_elements = soup.select('.ad-item, .item, .product, .listing-item, .ad')
        if not ad_elements:
            ad_elements = soup.select('div[data-item-id], div[data-id]')
        if not ad_elements:
            ad_elements = soup.select('div[class*="item"], div[class*="ad"], div[class*="product"]')

        print(f"📦 Барахла: найдено {len(ad_elements)} элементов")

        for element in ad_elements[:limit]:
            try:
                # ID
                ad_id = element.get('data-item-id') or element.get('data-id')
                if not ad_id:
                    ad_id = element.get('id', '').replace('item-', '')

                # Заголовок
                title_elem = element.find('a', class_=re.compile(r'title|link|name')) or element.find('h2') or element.find('h3')
                title = _clean_title(title_elem.text) if title_elem else "Без названия"

                # Цена
                price = None
                price_elem = element.find('span', class_=re.compile(r'price|cost'))
                if price_elem:
                    price_text = price_elem.text
                    digits = re.sub(r'[^0-9]', '', price_text)
                    if digits:
                        price = int(digits)

                if price is None:
                    continue
                if max_price and price > max_price:
                    continue

                # Ссылка
                url_elem = element.find('a', href=re.compile(r'/item/|/ad/|/product/'))
                ad_url = None
                if url_elem:
                    ad_url = url_elem.get('href')
                    if ad_url and not ad_url.startswith('http'):
                        ad_url = f"{BASE_URL}{ad_url}"

                if not ad_url:
                    continue

                # Локация
                location = ""
                loc_elem = element.find('span', class_=re.compile(r'location|address|city|town'))
                if loc_elem:
                    location = _clean_title(loc_elem.text)

                # Картинка
                image_url = ""
                img_elem = element.find('img')
                if img_elem:
                    image_url = img_elem.get('src') or img_elem.get('data-src') or ""
                    if image_url and image_url.startswith('//'):
                        image_url = 'https:' + image_url

                items.append({
                    'id': ad_id or f"barahla_{int(time.time())}_{len(items)}",
                    'title': title,
                    'price': price,
                    'url': ad_url,
                    'location': location,
                    'description': '',
                    'image_url': image_url,
                    'source': 'barahla',
                    'found_at': datetime.utcnow().isoformat()
                })
                print(f"✅ Барахла: {title[:40]} — {price} ₽")

            except Exception as e:
                print(f"⚠️ Ошибка элемента Барахла: {e}")
                continue

    except Exception as e:
        print(f"❌ Ошибка Барахла: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
            print("🔚 Барахла: браузер закрыт")

    print(f"📊 Барахла: найдено {len(items)} объявлений")
    return items