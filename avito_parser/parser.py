import asyncio
import json
import re
import requests
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

# ============================================
# 1. НАСТРОЙКИ
# ============================================

ADS_POWER_API_URL = "http://local.adspower.net:50325"
PROFILE_ID = "k1cbp123"
TARGET_URL = "https://www.avito.ru/sankt_peterburg_i_lo/telefony/mobile-ASgBAgICAUSwwQ2I_Dc"

# Фразы, которые не являются названиями товаров
SKIP_PHRASES = [
    "показать телефон", "показать номер", "показать",
    "доставка", "авито доставка", "перейти", "подробнее",
    "написать", "позвонить", "купить", "в корзину",
    "сообщение", "пожаловаться", "избранное"
]


def is_valid_title(title: str) -> bool:
    """Проверяет, является ли строка реальным названием товара"""
    title_lower = title.lower().strip()

    # Проверяем на служебные фразы
    for phrase in SKIP_PHRASES:
        if phrase in title_lower:
            return False

    # Проверяем длину и содержание
    if len(title) < 3:
        return False

    # Должна содержать хотя бы одну букву
    if not re.search(r'[а-яА-Яa-zA-Z]', title):
        return False

    return True


def clean_title(title: str) -> str:
    """Очищает название от лишних символов"""
    # Убираем восклицательные знаки в начале
    title = re.sub(r'^!+', '', title)
    # Убираем повторяющиеся части в кавычках
    title = re.sub(r'"[^"]*"', '', title)
    # Убираем множественные пробелы
    title = re.sub(r'\s+', ' ', title).strip()
    return title


# ============================================
# 2. ФУНКЦИИ ДЛЯ РАБОТЫ С ADSPOWER
# ============================================

def start_profile(profile_id: str) -> str:
    url = f"{ADS_POWER_API_URL}/api/v1/browser/start"
    params = {"user_id": profile_id, "headless": 0, "open_tabs": 0}
    response = requests.get(url, params=params, timeout=30)
    data = response.json()

    if data.get("code") == 0:
        ws_data = data.get("data", {}).get("ws", {})
        cdp_url = ws_data.get("puppeteer") or ws_data.get("selenium")
        if cdp_url:
            print(f"   ✅ Профиль {profile_id} запущен")
            return cdp_url
    raise Exception(f"Ошибка: {data}")


def stop_profile(profile_id: str):
    url = f"{ADS_POWER_API_URL}/api/v1/browser/stop"
    params = {"user_id": profile_id}
    requests.get(url, params=params, timeout=10)


# ============================================
# 3. ИЗВЛЕЧЕНИЕ ТОВАРОВ (ОЧИЩЕННАЯ ВЕРСИЯ)
# ============================================

def extract_products_from_text(page_text: str):
    print("   🔍 Ищу товары в тексте...")

    lines = page_text[:100000].split('\n')
    products = []

    for i, line in enumerate(lines):
        if '₽' in line:
            price_match = re.search(r'(\d{1,3}(?:[\s]?\d{3})*)\s?₽', line)
            if price_match:
                price_str = price_match.group(1).replace(' ', '')
                try:
                    price = int(price_str)
                    title = ""

                    # Ищем название в предыдущих 5 строках
                    for offset in range(1, 6):
                        if i - offset >= 0:
                            candidate = lines[i - offset].strip()
                            # Очищаем от Markdown
                            candidate = re.sub(r'[#\*\[\]\(\)]', '', candidate)
                            candidate = re.sub(r'http\S+', '', candidate)
                            candidate = re.sub(r'!\[.*?\]\(.*?\)', '', candidate)
                            candidate = candidate.strip()

                            if candidate and 3 < len(candidate) < 100:
                                if is_valid_title(candidate):
                                    title = clean_title(candidate)
                                    break

                    if title and price > 0:
                        products.append({
                            "title": title,
                            "price_rub": price,
                            "url": None
                        })
                except:
                    pass

    # Убираем дубликаты
    seen = set()
    unique = []
    for p in products:
        key = f"{p['title']}_{p['price_rub']}"
        if key not in seen:
            seen.add(key)
            unique.append(p)

    print(f"   ✅ Найдено {len(unique)} уникальных товаров")

    if unique:
        print("\n   📦 Первые 10 товаров:")
        for i, p in enumerate(unique[:10], 1):
            print(f"      {i}. {p['title'][:50]} — {p['price_rub']} ₽")

    return {"products": unique[:30]}


# ============================================
# 4. ОСНОВНАЯ ЛОГИКА
# ============================================

async def main():
    print("=" * 60)
    print("🚀 ЗАПУСК ПАРСЕРА AVITO (итоговая версия)")
    print("=" * 60)

    print(f"\n1️⃣ Запускаю профиль AdsPower: {PROFILE_ID}...")
    try:
        cdp_url = start_profile(PROFILE_ID)
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return

    await asyncio.sleep(3)

    try:
        print("\n2️⃣ Настраиваю браузер...")
        browser_config = BrowserConfig(
            browser_mode="custom",
            cdp_url=cdp_url,
            headless=False,
            verbose=False,
            viewport_width=1920,
            viewport_height=1080,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        crawl_config = CrawlerRunConfig(
            wait_until="domcontentloaded",
            page_timeout=60000,
            scan_full_page=True,
            scroll_delay=0.5,
            verbose=False
        )

        print(f"\n3️⃣ Загружаю страницу...")
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=TARGET_URL, config=crawl_config)

            if not result.success:
                print(f"   ❌ Ошибка: {result.error_message}")
                return

            print(f"   ✅ Загружено {len(result.markdown):,} символов")

            print("\n4️⃣ Извлекаю товары из текста...")
            extracted = extract_products_from_text(result.markdown)

            print("\n" + "=" * 60)
            print("🎯 РЕЗУЛЬТАТ ПАРСИНГА:")
            print("=" * 60)

            products = extracted.get("products", [])
            if products:
                print(f"\n✅ Найдено {len(products)} товаров:")
                for i, p in enumerate(products, 1):
                    print(f"   {i:2}. {p['title'][:55]} — {p['price_rub']} ₽")

                with open("avito_products.json", "w", encoding="utf-8") as f:
                    json.dump(extracted, f, indent=2, ensure_ascii=False)
                print(f"\n💾 Результат сохранён в avito_products.json")
            else:
                print("\n⚠️ Товары не найдены")

    finally:
        print("\n5️⃣ Закрываю профиль...")
        stop_profile(PROFILE_ID)

    print("\n✅ ГОТОВО")


if __name__ == "__main__":
    asyncio.run(main())
