"""
Optimized Athlete Image Scraper for SideArm Sports Websites
"""
import logging
import os
import re
import time
import concurrent.futures
import json
import threading
from typing import List, Dict, Optional, Tuple, Any
from urllib.parse import urlparse, urljoin, parse_qs, unquote
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from utils import clean_filename, setup_logging

# Configure logging
setup_logging(True)

# Global lock for background removal (rembg uses non-threadsafe Numba)
bg_removal_lock = threading.Lock()

def setup_headless_driver():
    """Configure a more robust headless Chrome WebDriver."""
    options = Options()
    options.add_argument("--headless=new")  # Use the newer headless mode
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # Bypass common bot detection methods
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    
    # Set a realistic user agent with recent Chrome version
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Add additional headers to bypass CDN restrictions
    options.add_argument("--accept=text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7")
    options.add_argument("--accept-language=en-US,en;q=0.9")
    options.add_argument("--sec-ch-ua='Google Chrome';v='120', 'Chromium';v='120', 'Not=A?Brand';v='24'")
    options.add_argument("--sec-ch-ua-mobile=?0")
    options.add_argument("--sec-ch-ua-platform='Windows'")
    options.add_argument("--sec-fetch-dest=document")
    options.add_argument("--sec-fetch-mode=navigate")
    options.add_argument("--sec-fetch-site=same-origin")
    options.add_argument("--upgrade-insecure-requests=1")
    
    # Performance optimizations
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    
    # Enable cookies
    prefs = {
        "profile.managed_default_content_settings.images": 1,  # Load images (needed for CDN detection)
        "profile.default_content_setting_values.notifications": 2,  # Block notifications
        "profile.managed_default_content_settings.javascript": 1,  # Enable JavaScript
        "profile.default_content_settings.cookies": 1,  # Allow cookies
        "profile.cookie_controls_mode": 0,  # Don't block cookies
    }
    options.add_experimental_option("prefs", prefs)
    
    logging.info("Setting up Chrome WebDriver with optimized options...")
    
    try:
        # Try multiple ChromeDriver paths (handle different environments)
        try:
            # Try webdriver-manager for automatic ChromeDriver management
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        except Exception:
            try:
                # Fallback: try system default ChromeDriver
                driver = webdriver.Chrome(options=options)
            except Exception:
                # Last resort: try common paths
                for path in ['/usr/bin/chromedriver', '/usr/local/bin/chromedriver']:
                    if os.path.exists(path):
                        service = Service(executable_path=path)
                        driver = webdriver.Chrome(service=service, options=options)
                        break
                else:
                    raise RuntimeError('Could not find ChromeDriver. Install with: pip install webdriver-manager')
            
        # Configure timeouts more aggressively
        driver.set_page_load_timeout(30)  # 30 second timeout for page load
        driver.set_script_timeout(30)  # Script execution timeout
        
        # Verify the WebDriver is working
        try:
            driver.execute_script("return navigator.userAgent;")
            logging.info("Successfully initialized and verified Chrome WebDriver")
        except Exception as e:
            logging.warning(f"WebDriver initialized but script execution failed: {str(e)}")
            
        return driver
    except Exception as e:
        logging.error(f"Failed to initialize Chrome WebDriver: {str(e)}")
        
        # Instead of raising, return None to allow fallback to HTTP requests
        logging.info("Will use direct HTTP requests instead of Selenium")
        return None

def fast_scroll_page(driver):
    """Perform a very fast scroll sequence to trigger lazy loading."""
    try:
        # Get page height
        page_height = driver.execute_script("return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);")
        logging.info(f"Page height: {page_height}px")
        
        # Quick scroll sequence (just 3 points)
        scroll_points = [
            0,  # Top
            page_height // 2,  # Middle
            page_height,  # Bottom
            0   # Back to top
        ]
        
        for point in scroll_points:
            driver.execute_script(f"window.scrollTo(0, {point});")
            time.sleep(0.2)  # Very short wait
        
        # Extra scroll to handle difficult lazy loading
        driver.execute_script("""
            const height = Math.max(document.body.scrollHeight, 10000);
            let currentPos = 0;
            const step = Math.max(500, height / 10);
            
            // Fast scroll down
            for (let i = 0; i <= height; i += step) {
                window.scrollTo(0, i);
            }
            
            // Back to top
            window.scrollTo(0, 0);
        """)
        
        return True
    except Exception as e:
        logging.error(f"Error during fast scroll: {str(e)}")
        return False

def extract_high_res_image_url(img_url: str, base_url: str) -> str:
    """Extract high-resolution version of image URL with a maximum height of 1000px."""
    if not img_url:
        return ""
    
    try:
        # Fix relative URLs
        if img_url.startswith('/'):
            img_url = urljoin(base_url, img_url)
        elif img_url.startswith('//'):
            img_url = f"https:{img_url}"
        
        # Handle SideArm resize service
        if 'images.sidearmdev.com/resize' in img_url:
            parsed = urlparse(img_url)
            query_params = parse_qs(parsed.query)
            if 'url' in query_params:
                # Extract original URL instead of resized version
                original_url = unquote(query_params['url'][0])
                logging.info(f"Got original URL from resize service: {original_url}")
                # Apply max-height constraint by adding our own parameters
                if '?' in original_url:
                    return f"{original_url}&maxheight=1000"
                else:
                    return f"{original_url}?maxheight=1000"
            
            # If can't extract original, set to high resolution with height constraint
            if 'width' in query_params:
                # Use a 1000px width for standard headshots
                query_params['width'] = ['1000']
                # Add height parameter if supported
                query_params['height'] = ['1000']
                # Add maxheight parameter if supported
                query_params['maxheight'] = ['1000']
                query_string = '&'.join([f"{k}={v[0]}" for k, v in query_params.items()])
                high_res_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query_string}"
                return high_res_url
        
        # Handle direct width parameter
        if 'width=' in img_url:
            img_url = re.sub(r'width=\d+', 'width=1000', img_url)
            
        # Handle direct height parameter if it exists
        if 'height=' in img_url:
            img_url = re.sub(r'height=\d+', 'height=1000', img_url)
        elif '?' in img_url:
            img_url = f"{img_url}&height=1000&maxheight=1000"
        else:
            img_url = f"{img_url}?height=1000&maxheight=1000"
        
        # For CloudFront URLs (common in SideArm sites)
        if 'cloudfront.net' in img_url:
            # Replace width params
            if '&w=' in img_url or '?w=' in img_url:
                img_url = re.sub(r'[?&]w=\d+', '&w=1000', img_url)
            # Add height params
            if '&h=' in img_url or '?h=' in img_url:
                img_url = re.sub(r'[?&]h=\d+', '&h=1000', img_url)
            else:
                sep = '&' if '?' in img_url else '?'
                img_url = f"{img_url}{sep}h=1000"
            
        logging.info(f"Optimized image URL with 1000px max height: {img_url}")
        return img_url
    except Exception as e:
        logging.error(f"Error processing image URL {img_url}: {str(e)}")
        return img_url

def get_columbia_athletes(url: str) -> List[Dict[str, str]]:
    """Special direct HTTP approach for Columbia University."""
    logging.info(f"Using specialized Columbia handler for {url}")
    try:
        # Make direct HTTP request (faster than Selenium)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        athletes = []
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        
        # Find all roster player elements
        players = soup.select('.sidearm-roster-player')
        logging.info(f"Found {len(players)} Columbia roster players")
        
        for player in players:
            try:
                # Extract name (first try first+last name spans)
                first_name_elem = player.select_one('.sidearm-roster-player-first-name')
                last_name_elem = player.select_one('.sidearm-roster-player-last-name')
                
                if first_name_elem and last_name_elem:
                    name = f"{first_name_elem.get_text().strip()} {last_name_elem.get_text().strip()}"
                else:
                    # Try alternative name elements
                    name_elem = player.select_one('.sidearm-roster-player-name')
                    if name_elem:
                        name = name_elem.get_text().strip()
                    else:
                        # Try bio link
                        bio_link = player.select_one('a[title*="Bio"]')
                        if bio_link and bio_link.get('title'):
                            title = str(bio_link.get('title', ''))
                            name = title.split(' - ')[0] if ' - ' in title else title
                        else:
                            continue  # Skip if no name found
                
                # Extract image URL
                img_url = None
                img_container = player.select_one('.sidearm-roster-player-image')
                if img_container:
                    # First try lazyload image
                    img_elem = img_container.select_one('img.lazyload')
                    if img_elem:
                        if img_elem.has_attr('data-src'):
                            img_url = str(img_elem['data-src'])
                        elif img_elem.has_attr('src'):
                            img_url = str(img_elem['src'])
                
                # If no image found with primary method, try alternate methods
                if not img_url:
                    any_img = player.select_one('img[src], img[data-src]')
                    if any_img:
                        img_url = str(any_img.get('data-src') or any_img.get('src') or '')
                
                if img_url:
                    # Get high resolution version
                    img_url = extract_high_res_image_url(img_url, base_url)
                    athletes.append({'name': name, 'image_url': img_url})
                    logging.info(f"Added Columbia athlete: {name}")
            except Exception as e:
                logging.error(f"Error processing Columbia athlete: {str(e)}")
                continue
                
        return athletes
    except Exception as e:
        logging.error(f"Error in Columbia handler: {str(e)}")
        return []

def extract_athletes(html: str, base_url: str, is_sidearm_api: bool = False) -> List[Dict[str, str]]:
    """Extract athlete information from HTML content."""
    if is_sidearm_api:
        # Handle API response format
        try:
            data = json.loads(html)
            athletes = []
            found_names = set()
            
            for item in data:
                try:
                    name = item.get('name', '').strip()
                    # Clean up name
                    name = re.sub(r'\s+', ' ', name)  # Normalize whitespace
                    name = re.sub(r'\([^)]*\)', '', name)  # Remove parentheses content
                    name = name.strip()
                    
                    if not name or name in found_names:
                        continue
                        
                    img_url = item.get('image_url') or item.get('photo') or ''
                    if img_url:
                        img_url = extract_high_res_image_url(img_url, base_url)
                        athletes.append({'name': name, 'image_url': img_url})
                        found_names.add(name)
                except Exception as e:
                    logging.error(f"Error processing API athlete: {str(e)}")
            
            return athletes
            
        except json.JSONDecodeError:
            logging.error("Failed to parse API response as JSON")
            is_sidearm_api = False  # Fall back to HTML parsing
    
    # Handle HTML content
    soup = BeautifulSoup(html, 'html.parser')
    athletes = []
    found_names = set()
    
    # Try to detect template type - expanded with more selector patterns
    # 1. Modern SideArm templates (most common)
    modern_items = soup.select('.s-person-card, .sidearm-roster-player, .roster_player, .sidearm-roster-player-container')
    
    # 2. Classic SideArm templates
    classic_items = soup.select('.roster_item, .roster-card, .roster-player, .rosterListRow, .player-card')
    
    # 3. Table-based rosters
    table_rows = []
    roster_tables = soup.select('table.roster, table.sidearm-roster-table, table.rosterTable, table.roster-table')
    if roster_tables:
        for table in roster_tables:
            rows = table.select('tr:not(:first-child), tr[class*="player"], tr[class*="roster"]')  # Skip header row
            table_rows.extend(rows)
            logging.info(f"Found table-based roster with {len(rows)} rows")
    
    # 4. New/modern grid layouts
    grid_items = soup.select('.player-card, .athlete-item, .roster-card, .bio-card, .roster-grid-item, .grid-item')
    
    # 5. Universal roster item fallback
    universal_items = soup.select('[class*="roster-player"], [class*="player-card"], [class*="athlete"]')
    
    # 6. Special case for combined rosters with separate sections
    section_items = []
    men_section = soup.select_one('#mens-roster, #roster-men, .mens-roster, [id*="mens"]')
    women_section = soup.select_one('#womens-roster, #roster-women, .womens-roster, [id*="womens"]')
    
    if men_section or women_section:
        logging.info("Detected separate men's/women's sections")
        if men_section:
            section_items.extend(men_section.select('[class*="player"], [class*="roster"], [class*="athlete"]'))
        if women_section:
            section_items.extend(women_section.select('[class*="player"], [class*="roster"], [class*="athlete"]'))
    
    # Select the appropriate items based on detected template
    items = []
    if modern_items:
        items.extend(modern_items)
        logging.info(f"Using modern SideArm template ({len(modern_items)} items)")
    if classic_items:
        items.extend(classic_items)
        logging.info(f"Using classic SideArm template ({len(classic_items)} items)")
    if table_rows:
        items.extend(table_rows)
        logging.info(f"Using table-based roster ({len(table_rows)} rows)")
    if grid_items:
        items.extend(grid_items)
        logging.info(f"Using grid layout ({len(grid_items)} items)")
    if section_items:
        items.extend(section_items)
        logging.info(f"Using section-specific items ({len(section_items)} items)")
    
    # If still no items, try universal fallbacks
    if not items and universal_items:
        items.extend(universal_items)
        logging.info(f"Using universal fallback selectors ({len(universal_items)} items)")
        
    # Last resort: try to find any div that might contain an athlete
    if not items:
        potential_divs = soup.select('div[id*="player"], div[class*="player"], div[id*="athlete"], div[class*="athlete"]')
        if potential_divs:
            items.extend(potential_divs)
            logging.info(f"Using last-resort div selectors ({len(potential_divs)} items)")
    
    logging.info(f"Found {len(items)} potential athlete items")
    
    for item in items:
        try:
            # Find name using expanded selectors covering more template formats
            name_elem = item.select_one(
                # Common modern templates
                '.s-person-details h3, .s-person-details h4, .player-name, .player_name, '
                '.sidearm-roster-player-name, .name, div.name, span.name, .fullname, '
                '.full-name, .rosterName, .roster-name, .athlete-name, .athlete_name, '
                # Table-based formats
                'td.name, td.player, th.name, td:first-child, td:nth-child(2), '
                # Bio links and headers
                'a.roster-player-name, h3.name, h4.name, .card-title, .card-header, '
                # General classes
                '.player-info h3, .player-info h4, .player-bio h3, '
                # Special cases
                '[data-name], [data-player-name], [data-athlete-name]'
            )
            
            name = None
            
            if name_elem:
                name = name_elem.get_text().strip()
            else:
                # Try multiple alternate methods for name
                
                # Method 1: First/last name separately
                first_name = item.select_one('.sidearm-roster-player-first-name, .first_name, .firstName, .first-name, [data-first-name]')
                last_name = item.select_one('.sidearm-roster-player-last-name, .last_name, .lastName, .last-name, [data-last-name]')
                
                if first_name and last_name:
                    first = first_name.get_text().strip()
                    last = last_name.get_text().strip()
                    if first and last:
                        name = f"{first} {last}"
                
                # Method 2: Bio link title or text content
                if not name:
                    bio_link = item.select_one('a[title*="Bio"], a[title*="Profile"], a[href*="player"], a[href*="athletes"]')
                    if bio_link:
                        # Try title attribute
                        if bio_link.get('title'):
                            title = str(bio_link.get('title', ''))
                            name_parts = title.split(' - ') if ' - ' in title else [title]
                            name = name_parts[0].strip()
                        # Try text content
                        elif bio_link.get_text():
                            link_text = bio_link.get_text().strip()
                            # Only use if it looks like a name (2-3 words)
                            if 1 <= len(link_text.split()) <= 3:
                                name = link_text
                
                # Method 3: Data attributes
                if not name:
                    data_attrs = ['data-name', 'data-player-name', 'data-athlete-name', 'data-player', 'data-athlete']
                    for attr in data_attrs:
                        if item.has_attr(attr) and item[attr]:
                            name = str(item[attr]).strip()
                            break
                
                # Method 4: Table cells in roster tables
                if not name and item.name == 'tr':
                    # Try first and second cell (often name is in one of these)
                    for idx in [0, 1]:
                        cells = item.find_all('td')
                        if len(cells) > idx:
                            cell_text = cells[idx].get_text().strip()
                            # Check if text looks like a name (no numbers, reasonable length)
                            if cell_text and len(cell_text) > 3 and not any(c.isdigit() for c in cell_text):
                                name = cell_text
                                break
                
                # Method 5: Look for structured patterns in text content
                if not name:
                    for text in item.stripped_strings:
                        text = text.strip()
                        # Look for patterns that resemble names (2-3 words, mixed case)
                        if text and 1 <= len(text.split()) <= 3 and any(c.isupper() for c in text):
                            # Skip text that's likely not a name (all caps headers, positions)
                            if not text.isupper() and not text.islower() and len(text) > 3:
                                name = text
                                break
                
                if not name:
                    # If we still can't find a name, skip this item
                    continue
            
            # Clean up and validate name
            # Remove non-name elements
            name = re.sub(r'\s+', ' ', name)  # Normalize whitespace
            name = re.sub(r'\([^)]*\)', '', name)  # Remove parentheses content
            name = re.sub(r'\d{1,2}$', '', name)  # Remove trailing jersey numbers
            name = re.sub(r'^\d{1,2}\s+', '', name)  # Remove leading jersey numbers
            name = re.sub(r'\s*\d{1,2}\s+', ' ', name)  # Remove embedded numbers
            
            # Remove common suffixes and prefixes
            name = re.sub(r'(?i)(fr\.|so\.|jr\.|sr\.|freshman|sophomore|junior|senior)$', '', name)
            
            # Remove trailing dashes (e.g., "Hayden Green -" -> "Hayden Green")
            name = re.sub(r'\s*-\s*$', '', name)
            
            # Final trim
            name = name.strip()
            
            # Verify we have a valid name
            if not name or len(name) < 3 or name in found_names:
                continue
            
            # Find image - greatly expanded methods
            img_url = None
            
            # Method 1: Check for background-image style (common in modern templates)
            style_elements = item.select('[style*="background-image"]')
            for elem in style_elements:
                style = str(elem.get('style', ''))
                bg_match = re.search(r'background-image\s*:\s*url\([\'"]?([^\'"]+)[\'"]?\)', style)
                if bg_match:
                    img_url = bg_match.group(1)
                    logging.info(f"Found image from background-image: {img_url}")
                    break
            
            # Method 2: Look for img elements with comprehensive selector list
            if not img_url:
                img_selectors = [
                    # Lazy loading images
                    'img.lazyload[data-src]',
                    'img[data-src]',
                    'img[data-lazy]',
                    'img[data-lazy-src]',
                    'img[data-image]',
                    'img[data-original]',
                    'img.lazy',
                    # Common roster image classes
                    '.sidearm-roster-player-image img',
                    '.player-photo img',
                    '.image img',
                    '.headshot img',
                    '.s-person-image img',
                    '.athlete-photo img',
                    '.roster-player-image img',
                    '.roster-photo img',
                    '.rosterImg img',
                    # Image inside links
                    'a[href*="player"] img',
                    'a[href*="roster"] img',
                    'a[href*="bio"] img',
                    'a[href*="athlete"] img',
                    # Direct image with relevant filenames
                    'img[src*="roster"]',
                    'img[src*="player"]',
                    'img[src*="head"]',
                    'img[src*="photo"]',
                    'img[src*="athlete"]',
                    'img[src*="portrait"]',
                    # Table cells with images
                    'td img',
                    # Fallback - any image
                    'img'
                ]
                
                for selector in img_selectors:
                    img_elem = item.select_one(selector)
                    if img_elem:
                        # Try multiple attributes in priority order
                        for attr in ['data-src', 'data-lazy-src', 'data-lazy', 'data-original', 'src']:
                            if img_elem.has_attr(attr) and img_elem[attr]:
                                img_url = str(img_elem[attr]).strip()
                                if img_url:
                                    logging.info(f"Found image from {attr}: {img_url}")
                                    break
                        if img_url:
                            break
                            
            # Method 3: Look in parent or wrapper elements for images
            if not img_url:
                # Try parent element
                parent = item.parent
                if parent:
                    img_elem = parent.select_one('img')
                    if img_elem:
                        img_url = img_elem.get('data-src') or img_elem.get('src')
                        if img_url:
                            logging.info(f"Found image from parent element: {img_url}")
                
                # Try searching up multiple levels
                if not img_url:
                    current = item
                    for _ in range(3):  # Check up to 3 levels up
                        if current.parent:
                            current = current.parent
                            img_elem = current.select_one('img')
                            if img_elem:
                                img_url = img_elem.get('data-src') or img_elem.get('src')
                                if img_url:
                                    logging.info(f"Found image from ancestor element: {img_url}")
                                    break
            
            # Method 4: Check meta data attributes directly on the element
            if not img_url:
                for attr in ['data-image', 'data-photo', 'data-img', 'data-portrait', 'data-headshot']:
                    if item.has_attr(attr) and item[attr]:
                        img_url = str(item[attr])
                        logging.info(f"Found image from data attribute {attr}: {img_url}")
                        break
                        
            # Method 5: Extract from URL - some sites have predictable image paths
            if not img_url:
                # Look for player IDs in links or attributes
                player_id = None
                id_attrs = ['data-player-id', 'data-id', 'id']
                
                # Try to get player ID from attributes
                for attr in id_attrs:
                    if item.has_attr(attr) and item[attr]:
                        id_val = str(item[attr])
                        # Verify it's numeric
                        if id_val.isdigit():
                            player_id = id_val
                            break
                
                # Try to get player ID from links
                if not player_id:
                    player_link = item.select_one('a[href*="player"], a[href*="roster"], a[href*="bio"], a[href*="athlete"]')
                    if player_link and player_link.has_attr('href'):
                        href = player_link['href']
                        # Common patterns: player-id=123, player_id=123, id=123, etc.
                        id_match = re.search(r'(?:player[-_]?id|id|p_id)=(\d+)', href)
                        if id_match:
                            player_id = id_match.group(1)
                
                # If we found a player ID, try common image URL patterns
                if player_id:
                    logging.info(f"Found player ID: {player_id}")
                    # Common patterns for player image URLs
                    patterns = [
                        f"{base_url}/images/players/{player_id}.jpg",
                        f"{base_url}/images/players/{player_id}.png",
                        f"{base_url}/images/roster/{player_id}.jpg",
                        f"{base_url}/images/roster/{player_id}.png",
                        f"{base_url}/images/headshots/{player_id}.jpg",
                        f"{base_url}/images/headshots/{player_id}.png",
                        f"{base_url}/images/{player_id}.jpg",
                        f"{base_url}/images/{player_id}.png"
                    ]
                    img_url = patterns[0]  # Use first pattern (will check URL later)
            
            if img_url:
                # Process to high-resolution version
                img_url = extract_high_res_image_url(img_url, base_url)
                athletes.append({'name': name, 'image_url': img_url})
                found_names.add(name)
                logging.info(f"Found athlete: {name} with image: {img_url}")
        
        except Exception as e:
            logging.error(f"Error processing athlete item: {str(e)}")
            continue
    
    return athletes

def get_direct_cdn_url(img_url: str) -> str:
    """Get a direct CloudFront CDN URL bypassing SideArm Sports redirects."""
    domain_cdn_map = {
        # Using known patterns from SideArm Sports sites to map to their CloudFront CDNs
        'gobuffsgo.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/wtamu.internetconsult.com',
        'gousm.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/southernmiss.sidearmsports.com',
        'gocrimson.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gocrimson.sidearmsports.com',
        'gofoldsgo.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gofoldsgo.com',
        'gorangerathletics.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gorangerathletics.com',
        'goransnathletics.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/goransnathletics.com',
        'uttylerpatriots.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/uttylerpatriots.com',
        'wildcats.athletics.wilmu.edu': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/wildcats.athletics.wilmu.edu',
        'svsucardinals.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/svsucardinals.com',
        'ohiodominicanpanthers.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/ohiodominicanpanthers.com',
        'tusculumpioneers.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/tusculumpioneers.com',
        'wwuvikings.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/wwuvikings.com',
        'chadroneagles.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/chadroneagles.com',
        'minesathletics.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/minesathletics.com',
        'dupanthers.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/dupanthers.com',
        'gonorthwood.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gonorthwood.com',
    }
    
    try:
        # Parse the URL to get the domain and path
        parsed_url = urlparse(img_url)
        domain = parsed_url.netloc.lower()
        
        # Remove 'www.' if present
        if domain.startswith('www.'):
            domain = domain[4:]
            
        # Check if domain is in our mapping
        if any(known_domain in domain for known_domain in domain_cdn_map.keys()):
            # Find the matching domain
            matching_domain = next((d for d in domain_cdn_map.keys() if d in domain), None)
            
            if matching_domain:
                # Get the CDN domain for this site
                cdn_domain = domain_cdn_map[matching_domain]
                
                # Create a direct CDN URL
                path = parsed_url.path
                query = parsed_url.query
                
                # Remove any resizing parameters which might cause issues
                if query:
                    # Keep only essential params (removing size, width, height, etc.)
                    query_parts = parse_qs(query)
                    clean_query_parts = {}
                    
                    # Only maintain format/type params if needed
                    for key in query_parts:
                        if key.lower() not in ['width', 'height', 'maxwidth', 'maxheight', 'size', 'quality']:
                            clean_query_parts[key] = query_parts[key]
                            
                    # Rebuild query string
                    if clean_query_parts:
                        query_str = '&'.join([f"{k}={v[0]}" for k, v in clean_query_parts.items()])
                        cdn_url = f"https://{cdn_domain}{path}?{query_str}"
                    else:
                        cdn_url = f"https://{cdn_domain}{path}"
                else:
                    cdn_url = f"https://{cdn_domain}{path}"
                    
                # Add height parameter explicitly to get high-res version  
                if '?' in cdn_url:
                    cdn_url += '&height=1000'
                else:
                    cdn_url += '?height=1000'
                    
                logging.info(f"Generated direct CDN URL: {cdn_url}")
                return cdn_url
                
    except Exception as e:
        logging.error(f"Error generating direct CDN URL: {str(e)}")
        
    # Return original URL if no mapping was found or an error occurred
    return img_url

def download_image(name: str, img_url: str, output_dir: str) -> bool:
    """Download a single athlete image."""
    from urllib.parse import parse_qs, urlparse
    
    try:
        if not img_url:
            logging.warning(f"No image URL for {name}")
            return False
            
        # Create safe filename with spaces instead of underscores
        safe_name = clean_filename(name)
        safe_name = safe_name.replace('_', ' ')  # Replace underscores with spaces
        if not safe_name:
            logging.warning(f"Invalid name: {name}")
            return False
        
        # Check if this is a SideArm Sports URL and get direct CDN URL if possible
        if any(domain in img_url for domain in [
            'gobuffsgo.com', 'gousm.com', 'gocrimson.com', 'uttylerpatriots.com',
            'wildcats.athletics.wilmu.edu', 'ohiodominicanpanthers.com',
            'tusculumpioneers.com', 'wwuvikings.com', 'gonorthwood.com', 'dupanthers.com'
        ]):
            # Try to get a direct CDN URL
            direct_url = get_direct_cdn_url(img_url)
            if direct_url != img_url:
                logging.info(f"Using direct CDN URL for {name}")
                img_url = direct_url
        
        # Create a session to handle redirects properly    
        session = requests.Session()
        
        # More robust headers for CDN interactions
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': img_url,  # Important for some CDNs
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Cache-Control': 'no-cache',
        }
        
        # Now do the actual download
        logging.info(f"Downloading image for {name} from URL: {img_url}")
        response = session.get(img_url, stream=True, timeout=20, headers=headers, allow_redirects=True)
        
        # Handle redirect to SideArm CDN
        if response.status_code == 200 and 'images.sidearmdev.com' in response.url:
            logging.info(f"Got redirected to SideArm CDN: {response.url}")
            
            # Extract the actual image URL from the redirect parameters
            parsed = urlparse(response.url)
            params = parse_qs(parsed.query)
            
            if 'url' in params:
                # Use the actual CDN URL instead
                real_url = params['url'][0]
                logging.info(f"Extracted real CDN URL from redirect: {real_url}")
                
                # Try downloading from the real URL
                response = session.get(real_url, stream=True, timeout=20, headers=headers, allow_redirects=True)
                
        if response.status_code != 200:
            logging.error(f"Failed to download image for {name}: HTTP {response.status_code} from {img_url}")
            
            # Try one last time with a direct CloudFront URL pattern
            try:
                # Extract path from URL
                url_path = urlparse(img_url).path
                # Try a generic CloudFront URL pattern as last resort
                cf_url = f"https://dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites{url_path}?height=1000"
                logging.info(f"Last resort - trying generic CloudFront URL: {cf_url}")
                
                cf_response = session.get(cf_url, stream=True, timeout=20, headers=headers)
                if cf_response.status_code == 200:
                    response = cf_response
                    logging.info("Successfully retrieved image from generic CloudFront URL")
                else:
                    return False
            except Exception as e:
                logging.error(f"Failed last resort attempt: {str(e)}")
                return False
        
        # Determine file extension from content type
        content_type = response.headers.get('Content-Type', '').lower()
        logging.info(f"Content type received: {content_type}")
        
        if 'jpeg' in content_type or 'jpg' in content_type:
            ext = '.jpg'
        elif 'png' in content_type:
            ext = '.png'
        elif 'webp' in content_type:
            ext = '.webp'
        else:
            # Try to get extension from the URL
            url_ext = os.path.splitext(img_url.split('?')[0].lower())[1]
            if url_ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                ext = url_ext
            else:
                # Default to jpg for unrecognized content types
                ext = '.jpg'
            
        # Save to temporary file first
        temp_path = os.path.join(output_dir, f"{safe_name}_temp{ext}")
        
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Remove background and save as PNG with transparency
        try:
            import gc
            from rembg import remove, new_session
            from PIL import Image, ImageFilter
            import numpy as np
            
            logging.info(f"Removing background for {name} with high-quality settings...")
            
            # Open image
            input_img = Image.open(temp_path)
            
            # Use lock to prevent concurrent Numba access
            with bg_removal_lock:
                # Use u2net_human_seg model ONLY - it's specifically trained for full human bodies
                # and preserves arms/legs/torso better than general models
                try:
                    session = new_session("u2net_human_seg")
                    logging.debug("Using u2net_human_seg model (optimized for human body preservation)")
                except:
                    session = new_session("u2net")
                    logging.debug("Fallback to default u2net model")
                
                # Remove background with settings optimized to preserve body parts
                output_img = remove(
                    input_img,
                    session=session,
                    alpha_matting=False,  # Disabled to avoid Numba TypingError
                    post_process_mask=False,  # Disable cleanup that might remove body parts
                    only_mask=False,  # Return full RGBA image
                    bgcolor=None  # Keep transparent background
                )
            
            # Use the AI model's output directly without modification for speed and quality
            # Skipping quality checks for faster processing - u2net_human_seg is reliable
            
            # Resize image to max 400px height while maintaining aspect ratio for efficiency
            width, height = output_img.size
            if height > 400:
                ratio = 400 / height
                new_width = int(width * ratio)
                output_img = output_img.resize((new_width, 400), Image.Resampling.LANCZOS)
                logging.info(f"Resized from {width}x{height} to {new_width}x400 for efficiency")
            
            # Save as PNG with transparency
            final_path = os.path.join(output_dir, f"{safe_name}.png")
            output_img.save(final_path, 'PNG', optimize=True)
            
            # Clean up image objects immediately
            del input_img
            del output_img
            del session
            
            # Remove temp file
            os.remove(temp_path)
            
            # Force garbage collection to free memory from AI model
            gc.collect()
            
            logging.info(f"Successfully saved high-quality transparent PNG for {name} to {final_path}")
            return True
            
        except Exception as bg_error:
            logging.warning(f"Background removal failed for {name}: {str(bg_error)}")
            # Fallback: just rename the temp file to final name
            final_path = os.path.join(output_dir, f"{safe_name}{ext}")
            os.rename(temp_path, final_path)
            logging.info(f"Saved original image (without background removal) to {final_path}")
            return True
        
    except Exception as e:
        logging.error(f"Error downloading image for {name}: {str(e)}")
        return False

def extract_tampa_style_roster(url: str, output_dir: str) -> int:
    """Extract athletes from Tampa-style table rosters where images are on bio pages.
    
    Tampa and similar sites show a table roster with links to individual bio pages.
    This function uses Selenium to bypass bot protection and extracts bio page links.
    """
    logging.info("Attempting Tampa-style table roster extraction (bio page method)")
    downloaded_count = 0
    driver = None
    
    try:
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # Use Selenium to bypass bot protection (403 errors)
        driver = setup_headless_driver()
        if not driver:
            logging.error("Failed to setup headless driver for Tampa extraction")
            return 0
        
        # Load the main roster page
        logging.info(f"Loading roster page with Selenium: {url}")
        driver.get(url)
        time.sleep(2)
        
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract bio page links from the roster
        # Works for both table-based (Tampa) and div-based (Saginaw) layouts
        bio_links = []
        
        # Find all bio page links
        all_bio_links = soup.find_all('a', href=lambda x: x and '/bios/' in x)
        
        for link in all_bio_links:
            bio_url = urljoin(base_url, link.get('href'))
            # Get athlete name from link text
            name_text = link.get_text().strip()
            
            # Clean up name (remove " - Jr.", " - So.", etc.)
            name_text = name_text.split(' - ')[0].strip()
            
            # Filter out non-athlete links (Full Bio, View Bio, etc.)
            if name_text.lower() in ['full bio', 'view bio', 'bio', 'profile', 'more']:
                continue
            
            if name_text and len(name_text.split()) >= 2:  # Has first and last name
                bio_links.append((bio_url, name_text))
        
        logging.info(f"Found {len(bio_links)} bio page links")
        
        if not bio_links:
            if driver:
                driver.quit()
            return 0
        
        # Scrape each bio page for headshot using Selenium
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 5  # Stop after 5 consecutive timeouts
        
        for bio_url, name_text in bio_links[:30]:  # Limit to 30 to avoid excessive time
            try:
                logging.debug(f"Fetching bio page: {bio_url}")
                driver.set_page_load_timeout(30)  # 30-second timeout per bio page
                driver.get(bio_url)
                time.sleep(0.5)
                
                bio_html = driver.page_source
                bio_soup = BeautifulSoup(bio_html, 'html.parser')
                
                # Find headshot image (usually the largest or first in main content)
                # First try specific bio/roster image selectors
                headshot_img = bio_soup.select_one('.sidearm-roster-player-bio-image img, .roster-bio-image img, .player-bio-image img, .athlete-bio-image img, .bio-photo img')
                
                if not headshot_img:
                    # Fallback: find all images and filter aggressively
                    images = bio_soup.find_all('img', src=lambda x: x and any(ext in x.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']))
                    
                    # Filter out logos, nav, headers, and other non-athlete images
                    exclude_keywords = ['logo', 'nav', 'footer', 'header', 'setup', 'primary', 'banner', 'icon', 'button', 'background', 'design', 'tartan', 'bear']
                    content_images = [img for img in images if 
                                    not any(keyword in img.get('src', '').lower() for keyword in exclude_keywords) and
                                    not any(keyword in img.get('class', []) for keyword in ['logo', 'nav-logo', 'site-logo', 'header-logo']) and
                                    int(img.get('width', 0) or 0) > 50 and  # Exclude tiny images
                                    int(img.get('height', 0) or 0) > 50]
                    
                    if content_images:
                        # Use the first content image (usually the headshot)
                        headshot_img = content_images[0]
                
                if headshot_img:
                    img_url = urljoin(base_url, headshot_img.get('src'))
                    
                    # Clean name for filename
                    name_parts = name_text.strip().split()
                    if len(name_parts) >= 2:
                        clean_name = f"{name_parts[0]}_{name_parts[-1]}"
                        if download_image(clean_name, img_url, output_dir):
                            downloaded_count += 1
                            consecutive_failures = 0  # Reset on success
                            logging.info(f"Downloaded headshot for {name_text}")
                else:
                    consecutive_failures += 1
                
            except Exception as e:
                consecutive_failures += 1
                logging.warning(f"Error fetching bio page {bio_url}: {str(e)}")
                
                # Stop if too many consecutive failures
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logging.error(f"Stopping bio-page extraction after {MAX_CONSECUTIVE_FAILURES} consecutive failures")
                    break
                continue
        
        # Clean up
        if driver:
            driver.quit()
        
        return downloaded_count
        
    except Exception as e:
        logging.error(f"Error in Tampa-style extraction: {str(e)}")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return 0

def process_url(url: str, output_dir: str) -> int:
    """Process a single team URL and return the number of images downloaded.
    Uses specialized pattern extraction with multiple fallback methods."""
    logging.info(f"Processing URL: {url}")
    athletes = []
    downloaded_count = 0
    
    try:
        # Special handling for year-based roster URLs
        if re.search(r'/2\d{3}-\d{2}/roster', url) or '/roster/2' in url:
            logging.info("Detected year-based roster URL format")
            
        # Special handling for combined roster URLs
        is_combined = False
        for pattern in ['combined-roster', 'mwroster', '/track-and-field/roster', 'track/roster']:
            if pattern in url.lower():
                is_combined = True
                break
                
        if is_combined:
            logging.info("Detected a combined roster URL - special handling may be applied")
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Normalize URL with proper handling of protocols and domains
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        
        # Extract base URL for resolving relative URLs
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        logging.info(f"Base URL: {base_url}")
        
        # Handle special domain-specific issues
        domain = parsed_url.netloc.lower()
        
        # Some domains need specific handling - add known problematic domains here
        domain_specific_issues = {
            'uttylerpatriots.com': "This domain requires special session cookies",
            'gobuffsgo.com': "This domain uses CDN redirects that need special handling",
            'gousm.com': "This domain uses CDN redirects that need special handling",
            'gocrimson.com': "This domain uses CDN redirects that need special handling",
            'wildcats.athletics.wilmu.edu': "This domain uses a complex multi-level subdomain structure"
        }
        
        # Enhanced mapping of domains to their CDN configurations
        SIDEARM_CDN_MAPPINGS = {
            # Known SideArm domains mapped to their cloudfront CDN patterns
            'gobuffsgo.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/wtamu.internetconsult.com',
            'gousm.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/southernmiss.sidearmsports.com',
            'gocrimson.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gocrimson.sidearmsports.com',
            'gofoldsgo.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gofoldsgo.com',
            'gorangerathletics.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gorangerathletics.com',
            'goransnathletics.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/goransnathletics.com',
            'uttylerpatriots.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/uttylerpatriots.com',
            'wildcats.athletics.wilmu.edu': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/wildcats.athletics.wilmu.edu',
            'svsucardinals.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/svsucardinals.com',
            'ohiodominicanpanthers.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/ohiodominicanpanthers.com',
            'tusculumpioneers.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/tusculumpioneers.com',
            'wwuvikings.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/wwuvikings.com',
            'chadroneagles.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/chadroneagles.com',
            'minesathletics.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/minesathletics.com',
            'dupanthers.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/dupanthers.com',
            'gonorthwood.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gonorthwood.com',
            # Adding the newly identified problematic sites from debug
            'cokercobras.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/cokercobras.com',
            'cmumavericks.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/cmumavericks.com',
            'cspbears.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/cspbears.com',
            'govalkyries.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/govalkyries.com',
            'gofightingscots.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gofightingscots.com',
            'gowasps.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/gowasps.com',
            'ferrisstatebulldogs.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/ferrisstatebulldogs.com',
            'marshilllions.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/marshilllions.com',
            'rockathletics.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/rockathletics.com',
            'stacathletics.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/stacathletics.com',
            'tampaspartans.com': 'dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/tampaspartans.com',
        }
        
        # List of domains known to use SideArm's CDN redirect system
        cdn_redirect_domains = list(SIDEARM_CDN_MAPPINGS.keys())
        
        # Domains that MUST use bio-page extraction (roster thumbnails are placeholders/logos)
        bio_page_extraction_domains = ['onusports.com', 'bsubears.com', 'athletics.cmu.edu']
        
        # PrestoSports domains that block direct HTTP requests (CloudFront 403)
        # These MUST use Selenium from the start
        prestosports_domains = [
            'goregispride.com', 'gosuffolkrams.com', 'wentworthathletics.com',
            'westfieldstateowls.com', 'aicyellowjackets.com', 'laserpride.lasell.edu',
            'ecgulls.com', 'leeuflames.com'
        ]
        
        # Check if this is a PrestoSports domain that needs Selenium
        if any(presto_domain in domain for presto_domain in prestosports_domains):
            logging.info(f"PrestoSports domain detected ({domain}) - using Selenium to bypass CloudFront protection")
            try:
                driver = setup_headless_driver()
                if driver:
                    logging.info(f"Loading PrestoSports page with Selenium: {url}")
                    driver.get(url)
                    time.sleep(4)  # Wait for JavaScript to render
                    fast_scroll_page(driver)
                    html = driver.page_source
                    driver.quit()
                    
                    logging.info(f"Got {len(html)} bytes from PrestoSports via Selenium")
                    
                    # Now use pattern extractor on the Selenium-rendered HTML
                    from sidearm_pattern_extractor import SideArmExtractor
                    extractor = SideArmExtractor(url, output_dir, html_content=html)
                    presto_count = extractor.download_all_images()
                    
                    if presto_count >= 5:
                        logging.info(f"Successfully extracted {presto_count} athletes from PrestoSports site")
                        return presto_count
                    elif presto_count > 0:
                        logging.warning(f"PrestoSports extraction found only {presto_count} athletes")
                        # Try Tampa-style as fallback
                        tampa_count = extract_tampa_style_roster(url, output_dir)
                        if tampa_count > presto_count:
                            return tampa_count
                        return presto_count
                    else:
                        logging.warning("PrestoSports pattern extraction found 0 athletes, trying Tampa-style")
                        tampa_count = extract_tampa_style_roster(url, output_dir)
                        if tampa_count > 0:
                            return tampa_count
            except Exception as e:
                logging.error(f"PrestoSports Selenium extraction failed: {str(e)}")
        
        if domain in domain_specific_issues:
            logging.warning(f"Known issue with domain {domain}: {domain_specific_issues[domain]}")
        
        # Force bio-page extraction for known problematic domains
        if any(bio_domain in domain for bio_domain in bio_page_extraction_domains):
            logging.info(f"Domain {domain} requires bio-page extraction (roster thumbnails are placeholders)")
            tampa_count = extract_tampa_style_roster(url, output_dir)
            if tampa_count > 0:
                logging.info(f"Successfully extracted {tampa_count} athletes from bio pages")
                return tampa_count
            else:
                logging.warning(f"Bio-page extraction found 0 athletes, trying other methods")
            
        # Use our specialized pattern extractor first (works for all SideArm sites)
        pattern_extracted_count = 0
        try:
            from sidearm_pattern_extractor import SideArmExtractor
            
            logging.info("Using SideArm Pattern Extractor for direct HTML pattern extraction")
            extractor = SideArmExtractor(url, output_dir)
            pattern_extracted_count = extractor.download_all_images()
            
            # If we found a reasonable number of athletes, we're done
            if pattern_extracted_count >= 5:
                logging.info(f"Successfully extracted and downloaded {pattern_extracted_count} images using SideArm Pattern Extractor")
                return pattern_extracted_count
            elif pattern_extracted_count > 0:
                logging.warning(f"SideArm Pattern Extractor found only {pattern_extracted_count} images (might be non-athlete graphics), trying Selenium for more")
            else:
                logging.warning("SideArm Pattern Extractor did not find any images, trying fallback methods")
        except Exception as e:
            logging.error(f"Error using SideArm Pattern Extractor: {str(e)}")
            logging.warning("Using fallback methods")
        
        # If pattern extractor found few or no athletes, try Tampa-style roster (table with bio links)
        if pattern_extracted_count < 5:
            logging.info(f"Pattern extractor found {pattern_extracted_count} athletes - trying Tampa-style table roster extraction")
            tampa_count = extract_tampa_style_roster(url, output_dir)
            if tampa_count > 0:
                logging.info(f"Successfully extracted {tampa_count} athletes from Tampa-style roster")
                return tampa_count
        
        # If pattern extractor found few or no athletes, try Selenium for JavaScript-heavy sites
        if pattern_extracted_count < 5:
            logging.info(f"Pattern extractor found {pattern_extracted_count} athletes (threshold: 5) - trying Selenium for JavaScript-rendered sites")
            try:
                driver = setup_headless_driver()
                if driver:
                    logging.info(f"Loading page with Selenium: {url}")
                    driver.get(url)
                    
                    # Wait for page to load
                    time.sleep(3)
                    
                    # Fast scroll to trigger lazy loading
                    fast_scroll_page(driver)
                    
                    # Get the rendered HTML
                    html = driver.page_source
                    driver.quit()
                    
                    logging.info(f"Got {len(html)} bytes of HTML from Selenium")
                    
                    # Extract athletes from rendered HTML
                    extracted = extract_athletes(html, base_url, False)
                    if extracted and len(extracted) > 0:
                        athletes = extracted
                        logging.info(f"Selenium found {len(athletes)} athletes")
                        
                        # Download the images
                        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:  # Increased to 5 for faster processing while maintaining stability
                            futures = {}
                            for athlete in athletes:
                                name = athlete['name']
                                img_url = athlete['image_url']
                                if img_url and isinstance(img_url, str):
                                    future = executor.submit(download_image, name, img_url, output_dir)
                                    futures[future] = name
                            
                            # Process results
                            selenium_downloaded = 0
                            for future in concurrent.futures.as_completed(futures):
                                athlete_name = futures[future]
                                try:
                                    if future.result():
                                        selenium_downloaded += 1
                                except Exception as e:
                                    logging.error(f"Error downloading image for {athlete_name}: {str(e)}")
                        
                        if selenium_downloaded > 0:
                            logging.info(f"Selenium successfully downloaded {selenium_downloaded} images")
                            return selenium_downloaded
                else:
                    logging.warning("Selenium WebDriver not available")
            except Exception as e:
                logging.warning(f"Selenium processing failed: {str(e)}")
            
        # Fall back to special case handling for known sites
        if 'gocolumbialions.com' in base_url:
            # Columbia University uses a unique layout with LazyLoad
            logging.info("Using Columbia-specific handler")
            athletes = get_columbia_athletes(url)
        elif any(cdn_domain in domain for cdn_domain in cdn_redirect_domains):
            # Use our specialized SideArm CDN parser for these domains
            logging.info(f"Using specialized SideArm CDN parser for {domain}")
            
            try:
                import sidearm_specialized_parser
                success = sidearm_specialized_parser.parse_sidearm_roster_page(url, output_dir)
                
                if success:
                    # Count the images that were downloaded
                    count = len([f for f in os.listdir(output_dir) 
                                if os.path.isfile(os.path.join(output_dir, f)) 
                                and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))])
                                
                    logging.info(f"Successfully downloaded {count} images using specialized CDN parser")
                    return count
                else:
                    logging.warning("Specialized CDN parser failed, falling back to standard methods")
            except Exception as e:
                logging.error(f"Error using specialized CDN parser: {str(e)}")
                logging.warning("Falling back to standard methods")
            
        # Try multiple methods for other sites, in order of preference
            
            # Method 1: Direct HTTP Request (fastest)
            if not athletes:
                try:
                    logging.info(f"Trying direct HTTP request to {url}")
                    # More robust headers to bypass protections
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Cache-Control': 'max-age=0',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Pragma': 'no-cache',
                        'sec-ch-ua': '"Google Chrome";v="121", "Chromium";v="121", "Not=A?Brand";v="24"',
                        'sec-ch-ua-mobile': '?0',
                        'sec-ch-ua-platform': '"Windows"',
                        'sec-fetch-dest': 'document',
                        'sec-fetch-mode': 'navigate',
                        'sec-fetch-site': 'none',
                        'sec-fetch-user': '?1',
                    }
                    
                    # Some sites need cookies to bypass security
                    cookies = {
                        'visited': 'true',
                        'cf_clearance': 'bypass_cloudflare',  # Helps with some Cloudflare sites
                        'sessionid': 'authenticated_session',  # Generic session cookie
                        'has_js': '1',  # Common in Drupal sites
                    }
                    
                    # Create a session for maintaining cookies
                    session = requests.Session()
                    
                    # First try the original URL
                    try:
                        response = session.get(url, headers=headers, cookies=cookies, timeout=30, allow_redirects=True)
                        success = response.status_code == 200
                    except Exception as e:
                        logging.error(f"Error accessing URL directly: {str(e)}")
                        success = False
                    
                    # If direct access failed but we have a CDN mapping, try that instead
                    if (not success or len(response.content) < 1000) and domain in SIDEARM_CDN_MAPPINGS:
                        cdn_url = f"https://{SIDEARM_CDN_MAPPINGS[domain]}{parsed_url.path}"
                        logging.info(f"Direct access failed or returned minimal content. Trying CDN URL: {cdn_url}")
                        
                        try:
                            # Add referer header for CDN access
                            cdn_headers = headers.copy()
                            cdn_headers['Referer'] = url
                            
                            response = session.get(cdn_url, headers=cdn_headers, cookies=cookies, timeout=30, allow_redirects=True)
                            logging.info(f"CDN URL status: {response.status_code}, content length: {len(response.content)}")
                        except Exception as e:
                            logging.error(f"Error accessing CDN URL: {str(e)}")
                            # Continue with the original response if it exists
                    
                    if response.status_code == 200:
                        html = response.text
                        logging.info(f"Got {len(html)} bytes of HTML from direct request")
                        
                        # Save HTML for debugging if needed
                        if len(html) < 1000:
                            logging.warning(f"Suspiciously small HTML response. Content: {html[:200]}...")
                        
                        # Check for common redirect/security patterns
                        if 'access denied' in html.lower() or 'security check' in html.lower():
                            logging.warning("Security check or access denied detected in response")
                        
                        # Check for robot detection
                        if 'robot' in html.lower() and 'detection' in html.lower():
                            logging.warning("Possible bot protection detected")
                            
                        # Try to detect if this is an API response
                        is_api = False
                        if response.headers.get('Content-Type', '').startswith('application/json'):
                            is_api = True
                            logging.info("Detected JSON API response")
                        
                        # Handle combined rosters with gender filtering
                        if is_combined:
                            logging.info("Processing as combined roster with gender filtering")
                            # Extract all athletes first
                            all_athletes = extract_athletes(html, base_url, is_api)
                            
                            if all_athletes:
                                # Determine which folder we're working with
                                gender_dir = os.path.basename(output_dir).lower()
                                is_men = gender_dir == 'men'
                                
                                logging.info(f"Found {len(all_athletes)} total athletes, filtering for {gender_dir}")
                                
                                # Filter HTML sections for this gender
                                soup = BeautifulSoup(html, 'html.parser')
                                gender_section = None
                                
                                if is_men:
                                    gender_section = soup.select_one('div[id*="men"], div[class*="men"], section[id*="men"], #mens-roster')
                                else:
                                    gender_section = soup.select_one('div[id*="women"], div[class*="women"], section[id*="women"], #womens-roster')
                                
                                if gender_section:
                                    logging.info(f"Found specific {gender_dir} section in HTML")
                                    gender_html = str(gender_section)
                                    gender_athletes = extract_athletes(gender_html, base_url, is_api)
                                    
                                    if gender_athletes:
                                        athletes = gender_athletes
                                        logging.info(f"Filtered to {len(athletes)} {gender_dir} athletes")
                                    else:
                                        # Fall back to name-based filtering
                                        athletes = all_athletes
                                else:
                                    athletes = all_athletes
                            
                            # If we couldn't filter by HTML section, set all athletes
                            if not athletes:
                                athletes = all_athletes
                        else:
                            # Standard extraction for non-combined rosters
                            extracted = extract_athletes(html, base_url, is_api)
                            if extracted:
                                athletes = extracted
                                logging.info(f"Direct HTTP request found {len(athletes)} athletes")
                    else:
                        logging.warning(f"HTTP request returned status code {response.status_code}")
                except Exception as e:
                    logging.warning(f"Direct HTTP request failed: {str(e)}")
            
            # Method 2: Selenium WebDriver (if available and needed)
            if not athletes:
                try:
                    driver = setup_headless_driver()
                    if driver is not None:
                        try:
                            logging.info(f"Using Selenium WebDriver to load {url}")
                            
                            # Navigate with timeout
                            driver.get(url)
                            
                            # Wait for initial load
                            logging.info("Waiting for initial page load...")
                            time.sleep(3)
                            
                            # Scroll to trigger lazy loading
                            logging.info("Scrolling page to load lazy content...")
                            fast_scroll_page(driver)
                            
                            # Get final HTML after scrolling
                            html = driver.page_source
                            logging.info(f"Got {len(html)} bytes of HTML from Selenium")
                        finally:
                            # Always clean up the driver
                            try:
                                driver.quit()
                            except:
                                pass
                        
                        # Extract athletes
                        extracted = extract_athletes(html, base_url)
                        if extracted:
                            athletes = extracted
                            logging.info(f"Selenium found {len(athletes)} athletes")
                    else:
                        logging.warning("Selenium WebDriver not available")
                except Exception as e:
                    logging.warning(f"Selenium processing failed: {str(e)}")
            
            # Method 3: Try to fetch roster data from SideArm's API directly
            if not athletes:
                try:
                    logging.info("Attempting to access SideArm API directly")
                    # Extract the team ID from the URL
                    if 'team=' in url:
                        team_id = re.search(r'team=(\d+)', url)
                        if team_id:
                            team_id = team_id.group(1)
                            api_url = f"{base_url}/services/roster_feed.ashx?team={team_id}"
                            logging.info(f"Trying API URL: {api_url}")
                            
                            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
                            response = requests.get(api_url, headers=headers, timeout=20)
                            
                            if response.status_code == 200:
                                try:
                                    # Try to parse as JSON
                                    api_data = response.json()
                                    if isinstance(api_data, list) and len(api_data) > 0:
                                        # Convert API data to our athlete format
                                        for player in api_data:
                                            name = player.get('name', '')
                                            img_url = player.get('player_image', '') or player.get('player_image_url', '')
                                            
                                            if name and img_url:
                                                # Fix up the image URL
                                                if img_url.startswith('//'):
                                                    img_url = f"https:{img_url}"
                                                elif img_url.startswith('/'):
                                                    img_url = urljoin(base_url, img_url)
                                                
                                                img_url = extract_high_res_image_url(img_url, base_url)
                                                athletes.append({'name': name, 'image_url': img_url})
                                        
                                        logging.info(f"SideArm API found {len(athletes)} athletes")
                                except:
                                    logging.warning("Failed to parse API response as JSON")
                except Exception as e:
                    logging.warning(f"SideArm API approach failed: {str(e)}")
        
        # If we still have no athletes, give up
        if not athletes:
            logging.error(f"All methods failed to find athletes on {url}")
            return 0
        
        logging.info(f"Successfully found {len(athletes)} athletes on {url}")
        
        # Filter out athletes without valid image URLs
        valid_athletes = [a for a in athletes if a.get('image_url')]
        if len(valid_athletes) < len(athletes):
            logging.info(f"Filtered out {len(athletes) - len(valid_athletes)} athletes without image URLs")
            athletes = valid_athletes
        
        if not athletes:
            logging.warning("No athletes with valid image URLs")
            return 0
        
        # Download images in parallel with better error handling
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:  # Increased to 5 for faster processing while maintaining stability
            futures = {}
            for athlete in athletes:
                name = athlete['name']
                img_url = athlete['image_url']
                if img_url and isinstance(img_url, str):  # Extra validation
                    future = executor.submit(download_image, name, img_url, output_dir)
                    futures[future] = name
            
            # Process results as they complete
            for future in concurrent.futures.as_completed(futures):
                athlete_name = futures[future]
                try:
                    if future.result():
                        downloaded_count += 1
                        if downloaded_count % 5 == 0 or downloaded_count == len(athletes):
                            logging.info(f"Downloaded {downloaded_count}/{len(athletes)} images")
                except Exception as e:
                    logging.error(f"Error downloading image for {athlete_name}: {str(e)}")
        
        if downloaded_count > 0:
            logging.info(f"Successfully downloaded {downloaded_count} images from {url}")
        else:
            logging.error(f"Failed to download any images from {url}")
            
        return downloaded_count
        
    except Exception as e:
        logging.error(f"Critical error processing {url}: {str(e)}")
        return downloaded_count

def determine_roster_type(url):
    """Determine if the URL is for a combined roster, men's team, or women's team."""
    url_lower = url.lower()
    
    # Check for combined roster indicators
    if any(pattern in url_lower for pattern in [
            'combined-roster', 'mwroster', 'combined', '/m-w-', 
            '/track/roster', '/track-and-field/roster']):
        return 'combined'
    elif any(pattern in url_lower for pattern in [
            'women', '/w-', 'wtrack', '/w/']):
        return 'women'
    else:
        return 'men'  # Default to men's roster

def multi_process_urls(urls: List[str], base_output_dir: str = 'athletes', selective_filter=None) -> Dict[str, Dict[str, Any]]:
    """Process multiple URLs with improved school and gender organization."""
    results = {}
    
    for url in urls:
        try:
            # Extract domain to use as folder name
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace('www.', '')  # Remove www prefix
            school_folder = re.sub(r'[^a-zA-Z0-9]', '_', domain)
            
            # Determine roster type
            roster_type = determine_roster_type(url)
            
            # Handle based on roster type
            if roster_type == 'combined':
                # Process combined roster - first as men
                logging.info(f"Processing combined roster {url} as men first")
                men_output_dir = os.path.join(base_output_dir, school_folder, 'men')
                
                # Special case handling for known problematic CDN domains
                domain = parsed_url.netloc.lower()
                cdn_domains = ['gobuffsgo.com', 'gousm.com', 'gocrimson.com', 'gofoldsgo.com', 
                              'gorangerathletics.com', 'goransnathletics.com',
                              'uttylerpatriots.com', 'wildcats.athletics.wilmu.edu',
                              'svsucardinals.com', 'ohiodominicanpanthers.com',
                              'tusculumpioneers.com', 'wwuvikings.com']
                
                if any(cdn_domain in domain for cdn_domain in cdn_domains):
                    # Use specialized parser for these domains for men's team
                    logging.info(f"Using specialized SideArm CDN parser for {domain} (men's team)")
                    
                    try:
                        # Ensure output directory exists
                        os.makedirs(men_output_dir, exist_ok=True)
                        logging.info(f"Men's team output directory confirmed: {men_output_dir}")
                        
                        # Import in a more robust way
                        import importlib.util
                        spec = importlib.util.find_spec('sidearm_specialized_parser')
                        if spec is None:
                            logging.error("sidearm_specialized_parser module not found")
                            raise ImportError("sidearm_specialized_parser module not found")
                        
                        import sidearm_specialized_parser
                        
                        # Print detailed information for logging
                        logging.info(f"Calling specialized parser for men's team with URL: {url}")
                        logging.info(f"Men's team output directory: {men_output_dir}")
                        
                        # Call the specialized parser
                        success = sidearm_specialized_parser.parse_sidearm_roster_page(url, men_output_dir)
                        
                        if success:
                            # Create a detailed list of all files
                            file_list = [f for f in os.listdir(men_output_dir) 
                                       if os.path.isfile(os.path.join(men_output_dir, f))]
                            logging.info(f"All files in men's team output directory: {file_list}")
                            
                            # Count the downloaded images
                            men_count = len([f for f in file_list 
                                          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))])
                            
                            logging.info(f"Successfully downloaded {men_count} images using specialized CDN parser")
                        else:
                            # Fall back to standard processing
                            logging.warning("Specialized CDN parser failed for men's team (returned False), falling back to standard methods")
                            # Force direct download and skip Selenium
                            logging.info("Forcing direct download mode for men's team fallback")
                            men_count = process_url(url, men_output_dir)
                    except Exception as e:
                        import traceback
                        logging.error(f"Error using specialized CDN parser for men's team: {str(e)}")
                        logging.error(f"Men's team traceback: {traceback.format_exc()}")
                        # Fall back to standard processing
                        logging.info("Using standard process_url as fallback after exception for men's team")
                        men_count = process_url(url, men_output_dir)
                else:
                    # Standard processing for all other domains
                    men_count = process_url(url, men_output_dir)
                
                # Then as women
                logging.info(f"Processing combined roster {url} as women next")
                women_output_dir = os.path.join(base_output_dir, school_folder, 'women')
                
                if any(cdn_domain in domain for cdn_domain in cdn_domains):
                    # Use specialized parser for these domains for women's team
                    logging.info(f"Using specialized SideArm CDN parser for {domain} (women's team)")
                    
                    try:
                        # Ensure output directory exists
                        os.makedirs(women_output_dir, exist_ok=True)
                        logging.info(f"Women's team output directory confirmed: {women_output_dir}")
                        
                        # Import in a more robust way
                        import importlib.util
                        spec = importlib.util.find_spec('sidearm_specialized_parser')
                        if spec is None:
                            logging.error("sidearm_specialized_parser module not found")
                            raise ImportError("sidearm_specialized_parser module not found")
                        
                        import sidearm_specialized_parser
                        
                        # Print detailed information for logging
                        logging.info(f"Calling specialized parser for women's team with URL: {url}")
                        logging.info(f"Women's team output directory: {women_output_dir}")
                        
                        # Call the specialized parser
                        success = sidearm_specialized_parser.parse_sidearm_roster_page(url, women_output_dir)
                        
                        if success:
                            # Create a detailed list of all files
                            file_list = [f for f in os.listdir(women_output_dir) 
                                       if os.path.isfile(os.path.join(women_output_dir, f))]
                            logging.info(f"All files in women's team output directory: {file_list}")
                            
                            # Count the downloaded images
                            women_count = len([f for f in file_list 
                                           if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))])
                            
                            logging.info(f"Successfully downloaded {women_count} images using specialized CDN parser")
                        else:
                            # Fall back to standard processing
                            logging.warning("Specialized CDN parser failed for women's team (returned False), falling back to standard methods")
                            # Force direct download and skip Selenium
                            logging.info("Forcing direct download mode for women's team fallback")
                            women_count = process_url(url, women_output_dir)
                    except Exception as e:
                        import traceback
                        logging.error(f"Error using specialized CDN parser for women's team: {str(e)}")
                        logging.error(f"Women's team traceback: {traceback.format_exc()}")
                        # Fall back to standard processing
                        logging.info("Using standard process_url as fallback after exception for women's team")
                        women_count = process_url(url, women_output_dir)
                else:
                    # Standard processing for all other domains
                    women_count = process_url(url, women_output_dir)
                
                # Total combined count
                image_count = men_count + women_count
                gender = 'combined'
                
                # Individual results for debugging
                results[f"{url}#men"] = {
                    "status": "success" if men_count > 0 else "error",
                    "count": men_count,
                    "school": domain,
                    "gender": "men (from combined)"
                }
                
                results[f"{url}#women"] = {
                    "status": "success" if women_count > 0 else "error",
                    "count": women_count,
                    "school": domain,
                    "gender": "women (from combined)"
                }
            else:
                # Standard single-gender roster
                gender = roster_type
                output_dir = os.path.join(base_output_dir, school_folder, gender)
                
                # Process URL
                logging.info(f"Processing {url} -> {output_dir}")
                
                # Special case handling for known problematic CDN domains
                domain = parsed_url.netloc.lower()
                cdn_domains = ['gobuffsgo.com', 'gousm.com', 'gocrimson.com', 'gofoldsgo.com', 
                              'gorangerathletics.com', 'goransnathletics.com',
                              'uttylerpatriots.com', 'wildcats.athletics.wilmu.edu',
                              'svsucardinals.com', 'ohiodominicanpanthers.com',
                              'tusculumpioneers.com', 'wwuvikings.com']
                
                if any(cdn_domain in domain for cdn_domain in cdn_domains):
                    # Use specialized parser for these domains
                    logging.info(f"Using specialized SideArm CDN parser for {domain}")
                    
                    try:
                        # Ensure output directory exists
                        os.makedirs(output_dir, exist_ok=True)
                        logging.info(f"Output directory confirmed: {output_dir}")
                        
                        # Import in a more robust way
                        import importlib.util
                        spec = importlib.util.find_spec('sidearm_specialized_parser')
                        if spec is None:
                            logging.error("sidearm_specialized_parser module not found")
                            raise ImportError("sidearm_specialized_parser module not found")
                        
                        import sidearm_specialized_parser
                        
                        # Print detailed information for logging
                        logging.info(f"Calling specialized parser with URL: {url}")
                        logging.info(f"Output directory: {output_dir}")
                        
                        # Call the specialized parser
                        success = sidearm_specialized_parser.parse_sidearm_roster_page(url, output_dir)
                        
                        if success:
                            # Create a detailed list of all files
                            file_list = [f for f in os.listdir(output_dir) 
                                       if os.path.isfile(os.path.join(output_dir, f))]
                            logging.info(f"All files in output directory: {file_list}")
                            
                            # Count the downloaded images
                            image_count = len([f for f in file_list 
                                             if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))])
                            
                            logging.info(f"Successfully downloaded {image_count} images using specialized CDN parser")
                        else:
                            # Fall back to standard processing
                            logging.warning("Specialized CDN parser failed (returned False), falling back to standard methods")
                            # Force direct download and skip Selenium
                            logging.info("Forcing direct download mode for fallback")
                            image_count = process_url(url, output_dir)
                    except Exception as e:
                        import traceback
                        logging.error(f"Error using specialized CDN parser: {str(e)}")
                        logging.error(f"Traceback: {traceback.format_exc()}")
                        # Fall back to standard processing
                        logging.info("Using standard process_url as fallback after exception")
                        image_count = process_url(url, output_dir)
                else:
                    # Standard processing for all other domains
                    image_count = process_url(url, output_dir)
            
            # Main result record
            results[url] = {
                "status": "success" if image_count > 0 else "error",
                "count": image_count,
                "school": domain,
                "gender": gender
            }
            
        except Exception as e:
            logging.error(f"Error processing URL {url}: {str(e)}")
            results[url] = {
                "status": "error",
                "count": 0,
                "error": str(e)
            }
    
    return results

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python fast_scraper.py <url> [output_dir]")
        sys.exit(1)
        
    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else 'athletes'
    
    count = process_url(url, output_dir)
    print(f"Downloaded {count} athlete images to {output_dir}")
