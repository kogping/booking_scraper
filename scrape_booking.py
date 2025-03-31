import csv
import time
import random
import re
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementClickInterceptedException
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback
from urllib.parse import urlencode

# Search constants
BASE_URL = "https://www.booking.com/searchresults.en-gb.html"
CHECKIN_DATE = "2026-02-01"
CHECKOUT_DATE = "2026-02-02"
ADULTS = 2
ROOMS = 1
CHILDREN = 0

# It seems that booking.com has a limit of 1000 per query -
# even after pressing load more. What I've done here is break up
# the search into different parts to try cover more ground.
# - Josh

# Defining some prices ranges
PRICE_RANGES = [
    {'min': None, 'max': 175},
    {'min': 176,  'max': 225},
    {'min': 226,  'max': 325},
    {'min': 326,  'max': None}
]

# Defining some regions
AUSTRALIAN_REGIONS = [
    "New South Wales, Australia",
    "Queensland, Australia",
    "Victoria, Australia",
    "South Australia, Australia",
    "Western Australia, Australia",
    "Northern Territory, Australia",
    "Australian Capital Territory, Australia",
    "Tasmania, Australia"
]

CSV_FILENAME = "booking_listings.csv"
MAX_LOAD_MORE_ATTEMPTS = 40
WAIT_TIMEOUT = 20
MAX_WORKERS = 30

# Amongst the selenium emulation, I've inserted random intervals of downtime
# to mimic human interaction, and reduce the chance of rate limiting.
def human_sleep(a=1, b=3):
    time.sleep(random.uniform(a, b))

# These are some initialisation options for the selenium driver.
def initialise_driver():
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = webdriver.Chrome(options=chrome_options)
    return driver

# This function extracts the data from a single card - which is an element describing a single property.
def process_card(card):
    title, address, headline_room_type, cost, review_score, num_reviews = "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"
    extracted_data = {} 
    try:
        try: title = card.find_element(By.CSS_SELECTOR, "[data-testid='title']").text
        except NoSuchElementException: pass

        try: address = card.find_element(By.CSS_SELECTOR, "[data-testid='address']").text
        except NoSuchElementException: pass
        try: headline_room_type = card.find_element(By.CSS_SELECTOR, "div[data-testid='recommended-units'] h4").text
        except NoSuchElementException:
             try:
                 room_elements = card.find_elements(By.CSS_SELECTOR, "div[data-testid='availability-cta'] .room__title")
                 if room_elements: headline_room_type = room_elements[0].text.strip()
             except NoSuchElementException: pass

        try:
            cost_element = card.find_element(By.CSS_SELECTOR, "[data-testid='price-and-discounted-price']")
            cost_text = cost_element.text
            cost_match = re.search(r'[\sA-Z]*([\d,]+(?:\.\d+)?)', cost_text)
            if cost_match:
                cost = cost_match.group(1).replace(",", "")
            else:
                 cost_match_simple = re.search(r'([\d,]+)', cost_text)
                 if cost_match_simple:
                     cost = cost_match_simple.group(1).replace(",", "")
        except NoSuchElementException: pass

        try:
            review_score_container = card.find_element(By.CSS_SELECTOR, "[data-testid='review-score']")
            try:
                review_score_text = review_score_container.find_element(By.XPATH, "./div[1]").text.strip()
                review_score_match = re.search(r'(\d+\.\d+)', review_score_text)
                if review_score_match:
                    review_score = review_score_match.group(1)
                else:
                     review_score_match_int = re.search(r'(\d+)', review_score_text)
                     if review_score_match_int:
                         review_score = review_score_match_int.group(1)
            except NoSuchElementException: pass

            try:
                num_reviews_text = review_score_container.find_element(By.XPATH, "./div[2]/div[2]").text.strip()
                num_reviews_match = re.search(r'([\d,]+)', num_reviews_text)
                if num_reviews_match:
                    num_reviews = num_reviews_match.group(1).replace(",", "")
            except NoSuchElementException: pass
        except NoSuchElementException: pass
        except Exception as e:
             print(f"Error parsing review section for card potentially titled '{title}': {e}")

        extracted_data = {
            "Title": title,
            "Address": address,
            "Headline Room Type": headline_room_type,
            "Cost (AUD)": cost,
            "Review Score": review_score,
            "# of Reviews": num_reviews
        }
    except Exception as e:
        print(f"General error processing a card. Title might be '{title}'. Error: {e}")
        extracted_data = {
            "Title": "N/A", "Address": "N/A", "Headline Room Type": "N/A",
            "Cost (AUD)": "N/A", "Review Score": "N/A", "# of Reviews": "N/A"
        }

    return extracted_data

# Handles the scraping logic for a particular subsection of the search
def scrape_region(driver, region, price_filter_dict=None):
    min_p = price_filter_dict.get('min') if price_filter_dict else None
    max_p = price_filter_dict.get('max') if price_filter_dict else None
    filter_desc = ""
    if min_p is not None and max_p is not None:
        filter_desc = f" with price filter {min_p}-{max_p} AUD"
    elif min_p is not None:
        filter_desc = f" with price filter {min_p}+ AUD"
    elif max_p is not None:
        filter_desc = f" with price filter up to {max_p} AUD"
    else:
         filter_desc = " (no price filter)"

    print(f"\n--- Scraping region: {region}{filter_desc} ---")

    base_params = {
        "ss": region,
        "lang": "en-gb",
        "sb": "1",
        "src_elem": "sb",
        "dest_id": "",
        "dest_type": "",
        "checkin": CHECKIN_DATE,
        "checkout": CHECKOUT_DATE,
        "group_adults": ADULTS,
        "no_rooms": ROOMS,
        "group_children": CHILDREN,
        "order": "price"
    }
    
    # Here we build the price filter for the particular search
    nflt_value_parts = []
    if price_filter_dict:
        min_price = price_filter_dict.get('min')
        max_price = price_filter_dict.get('max')
        if max_price is None:
            nflt_value_parts.append(f"price=AUD-{min_price}-max-1")
        elif min_price is None:
            nflt_value_parts.append(f"price=AUD-min-{max_price}-1")
        else:
            nflt_value_parts.append(f"price=AUD-{min_price}-{max_price}-1")

    nflt_final_value = ";".join(nflt_value_parts)

    final_params = base_params.copy()
    if nflt_final_value:
        final_params['nflt'] = nflt_final_value
   
    query_string = urlencode(final_params)
    url = f"{BASE_URL}?{query_string}"

    print(f"Navigating to URL: {url}")
    driver.get(url)
    human_sleep(1, 3)

    print("Attempting to load all results for this price range...")
    # Here is the page logic for loading property cards - we keep scrolling down until either
    # we hit the 1000 cap or there are no more results left to load.
    attempts = 0
    while attempts < MAX_LOAD_MORE_ATTEMPTS:
        try:
            elem = driver.find_element(By.TAG_NAME, "html")
            elem.send_keys(Keys.END)
            human_sleep(0.5, 1)
            load_more_button = WebDriverWait(driver, WAIT_TIMEOUT).until(
                 EC.element_to_be_clickable((By.XPATH, "//button[.//span[contains(text(),'Load more results')]]"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
            human_sleep(0.5, 1)
            load_more_button.click()
            print(f"Clicked 'Load more results' (Attempt {attempts + 1})")
            human_sleep(2, 3)
            attempts += 1
        except (TimeoutException, NoSuchElementException):
            print("Load more results button not found or timed out.")
            break
        except ElementClickInterceptedException:
            print("Load more results button was intercepted. Trying to scroll/wait.")
            driver.execute_script("window.scrollBy(0, 300);")
            human_sleep(1.5, 2.5)
        except Exception as e:
            print(f"An unexpected error occurred while clicking 'Load more': {e}")
            break
    if attempts == MAX_LOAD_MORE_ATTEMPTS: print("Reached maximum load more attempts.")
    human_sleep(1, 2)

    # Here we parse the listings using multithreading (its faster)
    listings_in_region_price = []
    cards = driver.find_elements(By.CSS_SELECTOR, "[data-testid='property-card']")
    print(f"Found {len(cards)} property cards for {region}{filter_desc}.")
    start_time = time.time()
    if cards:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = executor.map(process_card, cards)
            listings_in_region_price = list(results)
    else:
        print("No cards found to process.")
    end_time = time.time()
    print(f"Processed {len(listings_in_region_price)} listings in {end_time - start_time:.2f} seconds.")

    print(f"Scraped {len(listings_in_region_price)} listings for {region}{filter_desc}.")
    return listings_in_region_price

# This handles the logic for saving to a csv
def save_to_csv(listings, filename):
    if not listings:
        print("No listings data to save.")
        return
    if not all(isinstance(item, dict) for item in listings):
        print("Error: Found non-dictionary items in the listings data.")
        return
    first_dict = next((item for item in listings if isinstance(item, dict)), None)
    if first_dict is None:
        print("Error: No valid dictionary found in listings data.")
        return
    keys = first_dict.keys()
    try:
        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=keys)
            writer.writeheader()
            valid_rows = [row for row in listings if isinstance(row, dict)]
            writer.writerows(valid_rows)
        print(f"\nData successfully saved to {filename} with {len(valid_rows)} total listings.")
    except IOError as e: print(f"Error writing to CSV file {filename}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during CSV writing: {e}")
        print(traceback.format_exc())

if __name__ == '__main__':
    driver = None
    all_listings_raw = []
    start_time = time.time()

    try:
        driver = initialise_driver()
        total_regions = len(AUSTRALIAN_REGIONS)
        total_price_ranges = len(PRICE_RANGES)
        search_count = 0

        # Loop through regions and then through price ranges
        for i, region in enumerate(AUSTRALIAN_REGIONS):
            for j, price_range_dict in enumerate(PRICE_RANGES): # Iterate through the list of dictionaries
                search_count += 1
                print(f"\n>>> Starting Search {search_count}/{total_regions * total_price_ranges} "
                      f"(Region {i+1}/{total_regions}, Price Range {j+1}/{total_price_ranges})")

                # Pass the dictionary to scrape_region
                region_listings = scrape_region(driver, region, price_filter_dict=price_range_dict)
                if region_listings:
                     all_listings_raw.extend(region_listings)

                human_sleep(0.5, 1)

            print(f"--- Finished all price ranges for region: {region} ---")
            human_sleep(0.5, 1)
    except Exception as e:
        print(f"\nAn critical error occurred during scraping: {e}")
        print(traceback.format_exc())
    finally:
        if driver:
            print("Closing the browser...")
            driver.quit()

    end_time = time.time()
    print(f"\nScraping finished. Total time: {end_time - start_time:.2f} seconds.")
    print(f"Collected {len(all_listings_raw)} raw listings (including duplicates).")

    # Sometimes, booking.com will show the same property multiple times, thus its pretty helpful
    # to have a deduplication step.
    if all_listings_raw:
        print("\nDeduplicating results...")
        try:
            df = pd.DataFrame(all_listings_raw)
            initial_count = len(df)
            # We deduplicate based on Title and Address
            df_deduplicated = df.drop_duplicates(subset=['Title', 'Address'], keep='first')
            final_count = len(df_deduplicated)
            print(f"Removed {initial_count - final_count} duplicate listings based on Title and Address.")
            final_listings = df_deduplicated.to_dict(orient="records")
            save_to_csv(final_listings, CSV_FILENAME)
        except Exception as e:
             print(f"Error during deduplication or saving: {e}")
             print(traceback.format_exc())
             print("Saving raw (non-deduplicated) data as fallback...")
             save_to_csv(all_listings_raw, CSV_FILENAME.replace(".csv", "_raw.csv"))
    else:
        print("No listings were collected.")