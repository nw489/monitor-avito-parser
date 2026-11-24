# parser_avito.py

import time
import re
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=3)

CITY_CODES = {
    'Все регионы': 'rossiya',
    'Москва': 'moskva',
    'СПб': 'sankt-peterburg',
    'Новосибирск': 'novosibirsk',
    'Екатеринбург': 'ekaterinburg',
    'Казань': 'kazan',
    'Нижний Новгород': 'nizhniy_novgorod',
    'Челябинск': 'chelyabinsk',
    'Самара': 'samara',
    'Омск': 'omsk',
    'Ростов-на-Дону': 'rostov-na-donu',
    'Уфа': 'ufa',
    'Красноярск': 'krasnoyarsk',
    'Пермь': 'perm',
    'Воронеж': 'voronezh',
    'Волгоград': 'volgograd',
}


async def parse_avito(search_query: str, max_price: int = None, limit: int = 30, city: str = 'Все регионы'):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        _sync_parse_avito,
        search_query,
        max_price,
        limit,
        city
    )
    return result


def _sync_parse_avito(search_query: str, max_price: int = None, limit: int = 30, city: str = 'Все регионы'):
    city_code = CITY_CODES.get(city, 'rossiya')
    
    # Правильный URL для Avito
    query = search_query.replace(' ', '+')
    url = f"https://www.avito.ru/{city_code}?q={query}"
    if max_price:
        url += f"&pmax={max_price}"
    url += "&s=104"  # Сортировка по цене
    
    items = []
    driver = None

    try:
        print(f"🚀 Avito: запуск браузера")
        print(f"🌐 Avito URL: {url}")

        options = uc.ChromeOptions()
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-web-security')
        options.add_argument('--disable-features=IsolateOrigins,site-per-process')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        driver = uc.Chrome(options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        driver.get(url)
        time.sleep(5)

        # Прокрутка для загрузки
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        with open('debug_avito.html', 'w', encoding='utf-8') as f:
            f.write(html)

        # Пробуем разные селекторы
        ad_elements = []
        
        # Основной селектор
        elements = soup.select('[data-marker="item"]')
        if elements:
            ad_elements = elements
            print(f"📦 Найдено по data-marker='item': {len(elements)}")
        
        if not ad_elements:
            elements = soup.select('.iva-item-root')
            if elements:
                ad_elements = elements
                print(f"📦 Найдено по .iva-item-root: {len(elements)}")
        
        if not ad_elements:
            elements = soup.select('div[data-item-id]')
            if elements:
                ad_elements = elements
                print(f"📦 Найдено по div[data-item-id]: {len(elements)}")
        
        if not ad_elements:
            # Ищем любые карточки с ценой
            elements = soup.select('[class*="item"]')
            if elements:
                ad_elements = elements[:30]
                print(f"📦 Найдено по [class*='item']: {len(elements)}")

        print(f"📦 Всего элементов: {len(ad_elements)}")

        for element in ad_elements[:limit]:
            try:
                # ID
                ad_id = element.get('data-item-id')
                if not ad_id:
                    ad_id = element.get('id')
                if not ad_id:
                    continue

                # Заголовок
                title = "Без названия"
                title_elem = element.find('a', {'data-marker': 'item-title'})
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if not title:
                        title = title_elem.get('title', 'Без названия')
                
                if not title or title == "Без названия":
                    title_elem = element.find('h3')
                    if title_elem:
                        title = title_elem.get_text(strip=True)

                # Цена
                price = None
                price_elem = element.find('span', {'data-marker': 'item-price'})
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    digits = re.sub(r'[^0-9]', '', price_text)
                    if digits:
                        price = int(digits)
                
                if price is None:
                    # Ищем другие элементы с ценой
                    price_elem = element.find('span', class_=re.compile(r'price|Price'))
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        digits = re.sub(r'[^0-9]', '', price_text)
                        if digits:
                            price = int(digits)

                if price is None:
                    continue
                
                if max_price and price > max_price:
                    continue

                # URL
                ad_url = None
                url_elem = element.find('a', {'data-marker': 'item-title'})
                if url_elem:
                    ad_url = url_elem.get('href')
                if not ad_url:
                    url_elem = element.find('a', href=re.compile(r'/item_\d+'))
                    if url_elem:
                        ad_url = url_elem.get('href')
                
                if ad_url:
                    if not ad_url.startswith('http'):
                        ad_url = f"https://www.avito.ru{ad_url}"
                    ad_url = ad_url.split('?')[0]
                else:
                    continue

                # Локация
                location = ""
                loc_elem = element.find('span', {'data-marker': 'item-address'})
                if loc_elem:
                    location = loc_elem.get_text(strip=True)
                else:
                    loc_elem = element.find('div', class_=re.compile(r'address|location'))
                    if loc_elem:
                        location = loc_elem.get_text(strip=True)

                # Картинка
                image_url = ""
                img_elem = element.find('img')
                if img_elem:
                    image_url = img_elem.get('src') or img_elem.get('data-src') or ""
                    if image_url and image_url.startswith('//'):
                        image_url = 'https:' + image_url

                items.append({
                    'id': ad_id,
                    'title': title[:200],
                    'price': price,
                    'url': ad_url,
                    'location': location,
                    'description': '',
                    'image_url': image_url,
                    'source': 'avito',
                    'found_at': datetime.utcnow().isoformat()
                })
                print(f"✅ Avito: {title[:40]} — {price} ₽")

            except Exception as e:
                print(f"⚠️ Ошибка элемента Avito: {e}")
                continue

    except Exception as e:
        print(f"❌ Ошибка Avito: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

    print(f"📊 Avito: найдено {len(items)} объявлений")
    return items