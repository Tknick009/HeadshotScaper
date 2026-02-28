import argparse
import logging
import os
import sys
import re
import csv
import json
import concurrent.futures
import time
import random
from typing import Tuple, List, Optional, Union, Any
from bs4 import BeautifulSoup
import requests
from tqdm import tqdm
from utils import setup_logging, clean_filename, remove_resize_params
from urllib.parse import urlparse, urljoin, unquote, parse_qs
from PIL import Image
import io
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager, ChromeType
import stat


def verify_scroll_position(driver,
                           expected_position: int,
                           tolerance: int = 50) -> bool:
    """Verify that the actual scroll position matches the expected position within tolerance."""
    try:
        actual_position = driver.execute_script(
            "return Math.round(window.pageYOffset);")
        is_valid = abs(actual_position - expected_position) <= tolerance
        if not is_valid:
            logging.warning(
                f"Scroll position mismatch - Expected: {expected_position}, Actual: {actual_position}"
            )
        else:
            logging.info(
                f"Scroll position verified - Expected: {expected_position}, Actual: {actual_position}"
            )
        return is_valid
    except Exception as e:
        logging.error(f"Error verifying scroll position: {str(e)}")
        return False


def scroll_page_sequence(driver) -> bool:
    """Execute the predefined scroll sequence to ensure content is loaded."""
    try:
        logging.info("Starting scroll sequence...")
        scroll_positions = list(range(500, 15500,
                                      500))  # 500px intervals up to 15000
        scroll_data = []
        start_time = time.time()
        retry_count = 0
        max_retries = 3

        # Wait for initial page load
        logging.info("Waiting for page to be fully loaded...")
        time.sleep(2)  # Initial wait increased to ensure page is ready
        
        # Check if the page is Columbia University's roster which needs special handling
        current_url = driver.current_url
        if 'gocolumbialions.com' in current_url:
            logging.info("Columbia University site detected - using special handling")
            # Wait much longer for initial load
            time.sleep(5)
            
            # Check for loading indicator and wait for it to disappear
            try:
                loading_elements = driver.find_elements("css selector", '.loading')
                if loading_elements:
                    logging.info("Found loading indicator, waiting for it to disappear")
                    for i in range(30):  # Wait up to 30 seconds
                        time.sleep(1)
                        try:
                            is_visible = driver.execute_script(
                                "return document.querySelector('.loading') && document.querySelector('.loading').offsetParent !== null;"
                            )
                            if not is_visible:
                                logging.info("Loading indicator no longer visible")
                                break
                        except:
                            break
                    
                    # Force page to completely load by scrolling up and down several times
                    logging.info("Forcing Columbia page load with multiple scroll operations")
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)
                    driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(2)
                    driver.execute_script("window.scrollTo(0, Math.floor(document.body.scrollHeight/2));")
                    time.sleep(2)
                    driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(2)
                    
                    # Wait for any AJAX requests to complete
                    driver.execute_script("return new Promise(resolve => setTimeout(resolve, 3000));")
            except Exception as e:
                logging.warning(f"Error waiting for Columbia loading indicator: {str(e)}")
                
            # Directly try to access the roster elements to verify loading is complete
            try:
                roster_players = driver.find_elements("css selector", '.sidearm-roster-player')
                if roster_players:
                    logging.info(f"Found {len(roster_players)} roster players in Columbia page")
                else:
                    logging.warning("No roster players found, Columbia page may not have fully loaded")
                    # Force more wait time
                    time.sleep(5)
            except Exception as e:
                logging.warning(f"Error checking for Columbia roster players: {str(e)}")

        for position in scroll_positions:
            scroll_success = False
            retry_count = 0

            while not scroll_success and retry_count < max_retries:
                try:
                    # Log attempt
                    logging.info(
                        f"Attempt {retry_count + 1} to scroll to position {position}px"
                    )

                    # Execute scroll with smooth behavior
                    driver.execute_script(f"""
                        window.scrollTo({{
                            top: {position},
                            behavior: 'smooth'
                        }});
                    """)

                    # Wait exactly 2 seconds between scrolls for consistent timing
                    logging.info(f"Waiting 2ms at position {position}px")
                    time.sleep(1)

                    # Verify position
                    scroll_success = verify_scroll_position(driver, position)

                    if scroll_success:
                        # Record successful scroll
                        current_time = time.time() - start_time
                        scroll_data.append({
                            'position': position,
                            'timestamp': current_time,
                            'success': True
                        })
                        logging.info(
                            f"Successfully scrolled to {position}px at time {current_time:.2f}s"
                        )
                    else:
                        retry_count += 1
                        logging.warning(
                            f"Scroll verification failed, attempt {retry_count} of {max_retries}"
                        )
                        time.sleep(1)  # Short wait before retry

                except Exception as e:
                    retry_count += 1
                    logging.error(
                        f"Error during scroll to {position}px: {str(e)}")
                    if retry_count >= max_retries:
                        logging.error(
                            "Max retries reached, continuing to next position")
                    time.sleep(1)

            if not scroll_success and retry_count >= max_retries:
                logging.error(
                    f"Failed to scroll to position {position}px after {max_retries} attempts"
                )
                # Record failed scroll attempt
                scroll_data.append({
                    'position': position,
                    'timestamp': time.time() - start_time,
                    'success': False
                })

        # Save detailed scroll data
        try:
            with open('scroll_positions.json', 'w') as f:
                json.dump(
                    {
                        'url':
                        driver.current_url,
                        'scroll_data':
                        scroll_data,
                        'total_duration':
                        time.time() - start_time,
                        'scroll_count':
                        len(scroll_data),
                        'successful_scrolls':
                        len([
                            x for x in scroll_data if x.get('success', False)
                        ]),
                        'recorded_at':
                        time.strftime('%Y-%m-%d %H:%M:%S')
                    },
                    f,
                    indent=2)
            logging.info(
                f"Saved scroll data: {len(scroll_data)} positions recorded")
            successful_scrolls = len(
                [x for x in scroll_data if x.get('success', False)])
            logging.info(
                f"Successful scrolls: {successful_scrolls}/{len(scroll_data)}")
            return successful_scrolls > 0
        except Exception as e:
            logging.error(f"Error saving scroll data: {str(e)}")
            return False

    except Exception as e:
        logging.error(f"Critical error in scroll sequence: {str(e)}")
        return False
    finally:
        try:
            # Return to top and wait for any final loading
            logging.info("Returning to top of page...")
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            logging.info("Scroll sequence complete")
        except Exception as e:
            logging.error(f"Error returning to top of page: {str(e)}")


def verify_driver_setup():
    """Verify ChromeDriver setup and permissions."""
    try:
        # Use the latest Chromium from Nix store
        chrome_path = "/nix/store/khk7xpgsm5insk81azy9d560yq4npf77-chromium-131.0.6778.204/bin/chromium"

        if not os.path.exists(chrome_path):
            logging.error(f"Latest Chrome binary not found at {chrome_path}")
            logging.info("Available Chrome binaries:")
            os.system("ls -l /nix/store/*chromium*/bin/chromium 2>/dev/null")
            return None

        logging.info(f"Using Chrome binary at: {chrome_path}")

        # Set library path
        os.environ[
            "LD_LIBRARY_PATH"] = "/nix/store/khk7xpgsm5insk81azy9d560yq4npf77-chromium-131.0.6778.204/lib"
        logging.info(
            f"Set LD_LIBRARY_PATH to: {os.environ.get('LD_LIBRARY_PATH')}")

        # Use system chromedriver
        driver_path = "/nix/store/qlk9w1rvm6y5341v934wk05njppjlvad-chromedriver-unwrapped-131.0.6778.204/bin/chromedriver"
        if not os.path.exists(driver_path):
            logging.error(f"ChromeDriver not found at {driver_path}")
            return None

        # Ensure both binaries are executable
        for path in [chrome_path, driver_path]:
            st = os.stat(path)
            if not (st.st_mode & stat.S_IEXEC):
                logging.info(f"Making {path} executable")
                os.chmod(path, st.st_mode | stat.S_IEXEC)

        logging.info(f"ChromeDriver installed at: {driver_path}")
        return chrome_path

    except Exception as e:
        logging.error(f"Error verifying driver setup: {str(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        return None


def get_page_content(url: str) -> Tuple[str, dict]:
    """Fetch roster data from SideArm sports sites with proper scroll sequence."""
    driver = None
    try:
        logging.info("Initializing Chrome options...")
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-infobars')
        chrome_options.add_argument('--disable-notifications')
        chrome_options.add_argument('--enable-automation')
        chrome_options.add_argument('--disable-browser-side-navigation')
        chrome_options.add_argument('--disable-web-security')
        chrome_options.add_argument('--dns-prefetch-disable')

        # Verify driver setup before proceeding
        chrome_path = verify_driver_setup()
        if not chrome_path:
            logging.error("Failed to verify driver setup")
            return "", {}

        chrome_options.binary_location = chrome_path
        logging.info(f"Using Chrome binary at: {chrome_path}")

        logging.info(f"Processing URL: {url}")
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        logging.info("Creating Chrome WebDriver instance...")
        service = Service(
            "/nix/store/qlk9w1rvm6y5341v934wk05njppjlvad-chromedriver-unwrapped-131.0.6778.204/bin/chromedriver"
        )

        try:
            driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception as e:
            logging.error(f"Error creating Chrome WebDriver: {str(e)}")
            logging.error(f"ChromeDriver path: {service.path}")
            logging.error(f"Chrome binary: {chrome_options.binary_location}")
            logging.error(
                f"LD_LIBRARY_PATH: {os.environ.get('LD_LIBRARY_PATH')}")
            raise

        wait = WebDriverWait(driver, 20)

        try:
            logging.info(f"Loading page: {url}")
            driver.get(url)
            time.sleep(1)  # Initial page load wait

            # Execute scroll sequence before extracting content
            logging.info("Starting scroll sequence...")
            if not scroll_page_sequence(driver):
                logging.error("Scroll sequence failed")
                return "", {}

            # Get the fully loaded page content
            html_content = driver.page_source
            logging.info("Retrieved page content after scroll sequence")

            return html_content, {
                "base_url": base_url,
                "is_api_response": False
            }

        finally:
            if driver:
                try:
                    logging.info("Closing Chrome WebDriver...")
                    driver.quit()
                except Exception as e:
                    logging.error(f"Error closing driver: {str(e)}")

    except Exception as e:
        logging.error(f"Error fetching {url}: {str(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return "", {}


def clean_athlete_name(name: str) -> str:
    """Clean up athlete name from various formats."""
    name = re.sub(r'^Full Bio\s+for\s+', '', name)
    name = re.sub(r'\s*\([^)]*\)', '', name)  # Remove anything in parentheses
    return name.strip()


def extract_original_image_url(resize_url: str) -> str:
    """Extract original image URL from SideArm resize service URL."""
    if not resize_url:
        return ""
        
    try:
        parsed = urlparse(resize_url)
        
        # Columbia University's images - update to high-resolution versions
        if "gocolumbialions.com" in parsed.netloc:
            query_params = parse_qs(parsed.query)
            
            # Update to high resolution
            if 'width' in query_params:
                query_params['width'] = ['1200']
                logging.info("Updated Columbia width parameter to 1200px")
                
            # Rebuild URL with high-res params
            query_string = '&'.join([f"{k}={v[0]}" for k, v in query_params.items()])
            high_res_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if query_string:
                high_res_url += f"?{query_string}"
                
            logging.info(f"Created Columbia high-res URL: {high_res_url}")
            return high_res_url
            
        # Handle SideArm resize service - extract original URL
        if 'images.sidearmdev.com' in parsed.netloc:
            query_params = parse_qs(parsed.query)
            if 'url' in query_params:
                original_url = unquote(query_params['url'][0])
                logging.info(f"Extracted original URL from SideArm service: {original_url}")
                return original_url
                
        # If no transformations were applied but the URL has width parameter
        if 'width=' in resize_url:
            # Set to high resolution
            high_res_url = re.sub(r'width=\d+', 'width=1200', resize_url)
            if high_res_url != resize_url:
                logging.info(f"Updated width to high-res: {high_res_url}")
                return high_res_url
                
        # Return original URL if no transformations could be applied
        return resize_url
    except Exception as e:
        logging.error(
            f"Error extracting original URL from {resize_url}: {str(e)}")
        return resize_url


def fix_image_url(img_url: str, base_url: str) -> str:
    """Fix and normalize image URLs."""
    if not img_url:
        return ""  # Return empty string instead of None for type safety

    try:
        # Check if it's a Columbia University image that needs special handling
        is_columbia = "gocolumbialions.com" in base_url
        
        # Special handling for Columbia URLs with image parameters
        if is_columbia and ("width=" in img_url or "quality=" in img_url):
            logging.info(f"Special handling for Columbia image: {img_url}")
            # Update to high resolution version
            if "width=" in img_url:
                img_url = re.sub(r'width=\d+', 'width=1200', img_url)
                logging.info(f"Updated Columbia image width to 1200: {img_url}")
            
            parsed = urlparse(img_url)
            if parsed.netloc == '':
                # It's a relative URL, join with base_url
                img_url = urljoin(base_url, img_url)
            logging.info(f"Processed Columbia high-res image URL: {img_url}")
            return img_url
            
        # Standard processing for other sites
        img_url = extract_original_image_url(img_url)

        if img_url.startswith('//'):
            img_url = f"https:{img_url}"
        elif not img_url.startswith(('http:', 'https:')):
            img_url = urljoin(base_url, img_url)

        parsed = urlparse(img_url)
        query_params = parse_qs(parsed.query)

        filtered_params = {}
        if 'quality' in query_params:
            filtered_params['quality'] = query_params['quality'][0]
            
        # For Columbia, keep width and height if present
        if is_columbia:
            if 'width' in query_params:
                filtered_params['width'] = query_params['width'][0]
            if 'height' in query_params:
                filtered_params['height'] = query_params['height'][0]
            if 'mode' in query_params:
                filtered_params['mode'] = query_params['mode'][0]
            if 'anchor' in query_params:
                filtered_params['anchor'] = query_params['anchor'][0]

        if filtered_params:
            img_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            img_url += f"?{'&'.join(f'{k}={v}' for k, v in filtered_params.items())}"
        else:
            img_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        logging.info(f"Processed high-res image URL: {img_url}")
        return img_url
    except Exception as e:
        logging.error(f"Error processing image URL {img_url}: {str(e)}")
        return ""  # Return empty string instead of None for type safety


def extract_athletes_from_html(html: str, base_url: str,
                               is_api_response: bool) -> List[dict]:
    """Extract athlete information with proper wait times for lazy loading."""
    if is_api_response:
        try:
            data = json.loads(html)
            athletes = []
            found_names = set()
            for item in data:
                try:
                    name = clean_athlete_name(item.get('name', ''))
                    if not name or name in found_names:
                        continue
                    img_url = fix_image_url(
                        item.get('image_url', item.get('photo', '')), base_url)
                    if img_url:
                        athletes.append({'name': name, 'image_url': img_url})
                        found_names.add(name)
                        logging.info(
                            f"Found athlete (API): {name} with high-res image: {img_url}"
                        )
                        # Add wait time between processing each athlete
                        time.sleep(1)
                except Exception as e:
                    logging.error(
                        f"Error processing athlete from API response: {str(e)}"
                    )
                    continue
            return athletes
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON: {str(e)}")
            return []
    else:
        # Special case for Columbia University which needs direct HTML approach
        is_columbia = "gocolumbialions.com" in base_url
        if is_columbia:
            logging.info("Detected Columbia University site - using special direct HTML extraction")
            # For Columbia, we'll use a direct HTTP request approach rather than Selenium's HTML
            # This is more reliable for their site structure
            try:
                # Make a direct request to the Columbia URL
                url = base_url + "/sports/track-and-field/roster?view=3"
                if "/sports/track-and-field/roster" in html:
                    # If we already have an URL with roster in it, use that instead
                    url_match = re.search(r'(https?://[^/]+/sports/[^/]+/roster[^"\']*)', html)
                    if url_match:
                        url = url_match.group(1)
                        logging.info(f"Extracted Columbia roster URL from HTML: {url}")
                
                logging.info(f"Making direct HTTP request to Columbia: {url}")
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                }
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                
                columbia_html = response.text
                logging.info(f"Received {len(columbia_html)} bytes from direct Columbia request")
                
                # Parse the HTML with BeautifulSoup
                soup = BeautifulSoup(columbia_html, 'html.parser')
                athletes = []
                found_names = set()
                
                # Find all roster player elements
                columbia_items = soup.select('.sidearm-roster-player')
                logging.info(f"Found {len(columbia_items)} Columbia roster players via direct request")
                
                for item in columbia_items:
                    try:
                        # Extract name - Columbia has first/last name in separate spans
                        first_name_elem = item.select_one('.sidearm-roster-player-first-name')
                        last_name_elem = item.select_one('.sidearm-roster-player-last-name')
                        
                        if first_name_elem and last_name_elem:
                            first_name = first_name_elem.get_text().strip()
                            last_name = last_name_elem.get_text().strip()
                            name = f"{first_name} {last_name}"
                            logging.info(f"Found Columbia player: {name}")
                        else:
                            # Fallback to any available name
                            name_elem = item.select_one('.sidearm-roster-player-name')
                            if name_elem:
                                name = name_elem.get_text().strip()
                            else:
                                # Try to find by title
                                a_elem = item.select_one('a[title*="View Full Bio"]')
                                if a_elem:
                                    title = a_elem.get('title', '')
                                    name = title.split(' - ')[0] if ' - ' in title else title
                                else:
                                    continue
                        
                        # Skip if no name or duplicate
                        if not name or name in found_names:
                            continue
                        
                        # Find image - Columbia uses lazyload images with data-src
                        img_url = None
                        img_container = item.select_one('.sidearm-roster-player-image')
                        if img_container:
                            img_elem = img_container.select_one('img.lazyload')
                            if img_elem and img_elem.has_attr('data-src'):
                                img_url = img_elem['data-src']
                                logging.info(f"Found Columbia lazyload image: {img_url}")
                        
                        if img_url:
                            # Fix the image URL to get high resolution version
                            # Remove any width parameter to get full size
                            if '&width=' in img_url:
                                img_url = re.sub(r'&width=\d+', '', img_url)
                            if 'width=' in img_url:
                                img_url = re.sub(r'width=\d+', 'width=1200', img_url)
                                
                            # For SideArm resize service URLs, adjust to high resolution
                            if 'images.sidearmdev.com/resize' in img_url:
                                img_url = re.sub(r'width=\d+', 'width=1200', img_url)
                            
                            # Fix relative URLs
                            if img_url.startswith('/'):
                                img_url = urljoin(base_url, img_url)
                                
                            # For images in the resize service, extract the original URL
                            if 'resize?url=' in img_url:
                                try:
                                    # Extract the original URL from the resize parameter
                                    from urllib.parse import parse_qs, urlparse
                                    parsed_url = urlparse(img_url)
                                    params = parse_qs(parsed_url.query)
                                    if 'url' in params:
                                        original_url = params['url'][0]
                                        logging.info(f"Extracted original URL from resize service: {original_url}")
                                        img_url = original_url
                                except Exception as e:
                                    logging.error(f"Failed to extract original URL: {str(e)}")
                            
                            logging.info(f"Using high-res image URL: {img_url}")
                            
                            athletes.append({
                                'name': name,
                                'image_url': img_url
                            })
                            found_names.add(name)
                            logging.info(f"Added Columbia athlete: {name} with image URL: {img_url}")
                    
                    except Exception as e:
                        logging.error(f"Error processing Columbia athlete: {str(e)}")
                        continue
                
                return athletes
            
            except Exception as e:
                logging.error(f"Error in Columbia special handling: {str(e)}")
                # Fall back to standard approach
        
        # Standard approach for non-Columbia sites or if Columbia special handling failed
        soup = BeautifulSoup(html, 'html.parser')
        athletes = []
        found_names = set()

        try:
            # Determine if we're dealing with a Columbia site
            is_columbia = "gocolumbialions.com" in base_url
            
            # For all other sites, use standard approach
            if soup.select('.sidearm-roster-players .sidearm-roster-player'):
                logging.info("Detected Columbia University or similar SideArm template")
                # Get the roster players directly
                columbia_items = soup.select('.sidearm-roster-player')
                if columbia_items:
                    logging.info(f"Found {len(columbia_items)} Columbia-style roster players")
                    # Continue with these items
                    modern_items = columbia_items
                else:
                    # Fall back to standard approach
                    modern_items = soup.find_all(['div', 'li'],
                                              class_=[
                                                  's-person-card',
                                                  'sidearm-roster-player',
                                                  'roster_player'
                                              ])
            else:
                # Standard approach for non-Columbia sites
                modern_items = soup.find_all(['div', 'li'],
                                          class_=[
                                              's-person-card',
                                              'sidearm-roster-player',
                                              'roster_player'
                                          ])
            if modern_items:
                logging.info(
                    f"Found {len(modern_items)} modern template player items")
                for item in modern_items:
                    try:
                        # Look for name element, including sidearm-roster-player-name
                        name_elem = (
                            item.find('div', class_='s-text-regular-bold')
                            or item.find(['span', 'h3', 'h4', 'div', 'a', 'p'],
                                         class_=re.compile(
                                             r'(player-name|name)', re.I))
                            or item.find(['div', 'span', 'a'],
                                         class_=re.compile(r'name', re.I)))
                        
                        # Special case for loyolagreyhounds.com and Columbia which has title attribute with athlete name
                        if not name_elem and item.find('a', title=re.compile(r'.*View Full Bio')):
                            name_elem = item.find('a', title=re.compile(r'.*View Full Bio'))
                            # Extract name from the title attribute which is in format "Name - View Full Bio"
                            name = name_elem.get('title', '').split(' - ')[0] if name_elem else ''
                        # Special case for Columbia University's format with first name and last name in separate spans
                        elif not name_elem and item.find('span', class_='sidearm-roster-player-first-name') and item.find('span', class_='sidearm-roster-player-last-name'):
                            first_name = item.find('span', class_='sidearm-roster-player-first-name').get_text().strip()
                            last_name = item.find('span', class_='sidearm-roster-player-last-name').get_text().strip()
                            name = f"{first_name} {last_name}"
                            logging.info(f"Found Columbia-style name: {name}")
                        else:
                            if not name_elem:
                                continue
                            name = clean_athlete_name(name_elem.get_text())
                        if not name or name in found_names:
                            continue

                        img_url = None
                        img_containers = [
                            item.find('div', class_='s-person-thumbnail'),
                            item.find('div',
                                      class_=re.compile(
                                          r'(image|photo|headshot)', re.I)),
                            item.find('div',
                                      class_=re.compile(
                                          r'(player-photo|player-image)',
                                          re.I)),
                            # Add specific class for loyolagreyhounds.com
                            item.find('div', class_='sidearm-roster-player-image'),
                            item
                        ]

                        for container in img_containers:
                            if not container:
                                continue
                                
                            # First check for background-image style attribute (for sites like loyolagreyhounds.com)
                            if container.has_attr('style') and 'background-image' in container['style']:
                                style = container['style']
                                bg_url_match = re.search(r'background-image:url\([\'"]?([^\'"]+)[\'"]?\)', style)
                                if bg_url_match:
                                    img_url = bg_url_match.group(1)
                                    logging.info(f"Found image URL in background-image style: {img_url}")
                                    break
                                    
                            # Also look inside child elements with background-image style
                            bg_img_divs = container.find_all('div', style=re.compile(r'background-image'))
                            if bg_img_divs:
                                for bg_div in bg_img_divs:
                                    style = bg_div['style']
                                    bg_url_match = re.search(r'background-image:url\([\'"]?([^\'"]+)[\'"]?\)', style)
                                    if bg_url_match:
                                        img_url = bg_url_match.group(1)
                                        logging.info(f"Found image URL in background-image style: {img_url}")
                                        break
                                if img_url:
                                    break

                            # Standard img tag search as before
                            img_tags = (
                                container.find_all('img',
                                                   {'data-player-image': True})
                                or container.find_all(
                                    'img', {'data-player-photo': True})
                                # Columbia uses lazyload class extensively - prioritize this for Columbia site
                                or container.find_all(
                                    'img',
                                    class_=['lazyload', 'lazy', 'roster-img'])
                                or container.find_all(
                                    'img', {
                                        'data-test-id': [
                                            's-image-resized__img',
                                            'roster-image'
                                        ]
                                    }) or container.find_all('img'))

                            for img in img_tags:
                                # Wait 10ms before processing each image to allow lazy loading
                                time.sleep(1)

                                # Try direct high-res attributes first
                                for attr in [
                                        'data-player-image',
                                        'data-player-photo', 'data-hi-res',
                                        'data-zoom-src', 'data-fullsize',
                                        'data-large', 'data-src',
                                        'data-original', 'data-lazy',
                                        'data-full', 'src'
                                ]:
                                    potential_url = img.get(attr)
                                    if potential_url:
                                        img_url = potential_url
                                        logging.info(
                                            f"Found image URL via {attr}: {img_url}"
                                        )
                                        break

                                if not img_url:
                                    for srcset_attr in [
                                            'srcset', 'data-srcset'
                                    ]:
                                        srcset = img.get(srcset_attr)
                                        if srcset:
                                            try:
                                                sources = srcset.split(',')
                                                max_width = 0
                                                for source in sources:
                                                    parts = source.strip(
                                                    ).split()
                                                    if len(parts) >= 2:
                                                        url = parts[0]
                                                        width = int(''.join(
                                                            filter(
                                                                str.isdigit,
                                                                parts[1])))
                                                        if width > max_width:
                                                            max_width = width
                                                            img_url = url
                                            except Exception as e:
                                                logging.error(
                                                    f"Error parsing srcset: {str(e)}"
                                                )
                                                continue

                                if img_url:
                                    break

                            if img_url:
                                break

                        if img_url:
                            img_url = fix_image_url(img_url, base_url)
                            if img_url:
                                athletes.append({
                                    'name': name,
                                    'image_url': img_url
                                })
                                found_names.add(name)
                                logging.info(
                                    f"Found athlete: {name} with high-res image: {img_url}"
                                )

                    except Exception as e:
                        logging.error(f"Error processing athlete: {str(e)}")
                        continue

            if not athletes:
                logging.error("No athletes found in HTML parsing")
                logging.debug("Sample HTML structure:")
                for elem in soup.find_all(['div', 'article'])[:5]:
                    logging.debug(
                        f"Element: {elem.name}, class: {elem.get('class', [])}"
                    )

        except Exception as e:
            logging.error(f"Error processing athletes: {str(e)}")

        return athletes


def download_single_image(args: Tuple[str, str, str]) -> Optional[str]:
    """Download a single athlete image."""
    name, url, output_dir = args
    try:
        headers = {
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/webp,image/jpeg,image/png,*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Referer': url
        }

        logging.info(f"Starting download for athlete: {name} from URL: {url}")
        # Removed delay entirely for faster processing

        response = requests.get(url, headers=headers, timeout=10, stream=True)
        response.raise_for_status()

        content_type = response.headers.get('content-type', '').lower()
        logging.info(f"Content type received: {content_type}")

        ext = '.jpg'
        if 'png' in content_type:
            ext = '.png'
        elif 'webp' in content_type:
            ext = '.webp'

        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '', name.replace(' ', '_'))
        filename = f"{safe_name}{ext}"
        filepath = os.path.join(output_dir, filename)

        img_data = response.content
        img = Image.open(io.BytesIO(img_data))

        logging.info(f"Original image size for {name}: {img.size}")
        if img.size[1] > 800:  # Reduced max height for faster processing
            aspect_ratio = img.size[0] / img.size[1]
            new_height = 800
            new_width = int(aspect_ratio * new_height)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            logging.info(
                f"Resized image for {name} to {new_width}x{new_height}")

        img.save(
            filepath, quality=80,
            optimize=True)  # Further reduced quality for faster processing

        if os.path.getsize(filepath) > 0:
            logging.info(f"Successfully saved image for {name} to {filepath}")
            return filename
        else:
            os.remove(filepath)
            logging.error(f"Downloaded file for {name} was empty")
            return None

    except Exception as e:
        logging.error(f"Failed to download image for {name}: {str(e)}")
        return None


def process_team_page(url: str, output_dir: str) -> bool:
    """Process a single team page."""
    try:
        # Special case for Columbia University which needs direct approach
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        is_columbia = "gocolumbialions.com" in base_url
        
        if is_columbia:
            logging.info(f"Columbia University site detected: {url}")
            logging.info("Using direct request approach for Columbia")
            
            # For Columbia, we'll skip Selenium and go straight to extraction
            athletes = extract_athletes_from_html("", base_url, False)
            if not athletes:
                logging.error(f"No athletes found on Columbia URL {url}")
                return False
        else:
            # Standard approach for non-Columbia sites
            logging.info(f"Starting to process team page: {url}")
            html, page_data = get_page_content(url)
            is_api_response = page_data.get('is_api_response', False)
            base_url = page_data.get('base_url', url)

            if not html or not base_url:
                logging.error(f"Failed to get content from {url}")
                return False

            athletes = extract_athletes_from_html(html, base_url, is_api_response)
            if not athletes:
                logging.error(f"No athletes found on {url}")
                return False

        logging.info(f"Found {len(athletes)} athletes")

        os.makedirs(output_dir, exist_ok=True)
        logging.info(f"Ensuring output directory exists: {output_dir}")

        download_args = [(athlete['name'], athlete['image_url'], output_dir)
                         for athlete in athletes if athlete.get('image_url')]

        logging.info(f"Preparing to download {len(download_args)} images")
        if not download_args:
            logging.error("No valid image URLs found to download")
            return False

        # Increased max_workers to 8 for faster parallel downloads
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for args in download_args:
                futures.append(executor.submit(download_single_image, args))

            completed = 0
            for future in concurrent.futures.as_completed(futures):
                try:
                    if future.result():
                        completed += 1
                        logging.info(
                            f"Successfully downloaded {completed}/{len(download_args)} images"
                        )
                except Exception as e:
                    logging.error(f"Error in download thread: {str(e)}")

        downloaded = [
            f for f in os.listdir(output_dir)
            if f.endswith(('.jpg', '.png', '.webp'))
        ]
        logging.info(
            f"Successfully downloaded {len(downloaded)} out of {len(athletes)} images"
        )

        return len(downloaded) > 0
    except Exception as e:
        logging.error(f"Error processing {url}: {str(e)}")
        return False


def main():
    args = parse_arguments()
    setup_logging(args.debug)

    if args.csv:
        with open(args.csv, 'r') as f:
            reader = csv.reader(f)
            urls = [row[0].strip() for row in reader if row and row[0].strip()]

        success_count = 0
        for url in tqdm(urls, desc="Processing teams"):
            if process_team_page(url, args.output):
                success_count += 1

        logging.info(
            f"Successfully processed {success_count} out of {len(urls)} teams")
    else:
        process_team_page(args.url, args.output)
        logging.info("Download complete!")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Scrape athlete images from Sidearm sports team rosters')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--url',
                       help='URL of the Sidearm sports team roster page')
    group.add_argument('--csv',
                       help='CSV file containing team URLs (one per line)')
    parser.add_argument(
        '-o',
        '--output',
        default='athletes',
        help='Output directory for downloaded images (default: athletes)')
    parser.add_argument('--debug',
                        action='store_true',
                        help='Enable debug logging')
    return parser.parse_args()


if __name__ == '__main__':
    main()
