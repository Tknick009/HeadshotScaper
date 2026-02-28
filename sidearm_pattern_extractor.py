"""
SideArm Sports Pattern Extractor

This module contains specialized pattern extraction logic for SideArm sports websites,
using direct HTML parsing to find athlete images even when JavaScript-based loading is used.
"""

import logging
import os
import re
import threading
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

# Global lock for background removal (rembg uses non-threadsafe Numba)
bg_removal_lock = threading.Lock()

class SideArmExtractor:
    def __init__(self, url, output_dir, selective_filter=None, html_content=None):
        self.url = url
        self.output_dir = output_dir
        self.selective_filter = selective_filter  # Dict with school -> [athlete names]
        self.html_content = html_content  # Pre-fetched HTML (e.g., from Selenium)
        
        # Parse URL components
        parsed = urlparse(url)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.domain = parsed.netloc.lower()
        if self.domain.startswith('www.'):
            self.domain = self.domain[4:]
        self.path = parsed.path
        
        # Setup common headers
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': self.base_url,
        }
    
    def is_valid_athlete_name(self, name):
        """Check if a name looks like a valid athlete name (not a filename code or invalid term)."""
        if not name:
            return False
        
        name_lower = name.lower()
        
        # Filter out common non-athlete terms
        invalid_terms = ['full bio', 'bio', 'profile', 'roster', 'anchor', 'generic', 'missing', 'placeholder']
        if any(term in name_lower for term in invalid_terms):
            return False
        
        # Filter out names with random codes (e.g., "Blake pW7bv", "Sophie26", "0H2My")
        # A valid name shouldn't have sequences of random letters/numbers mixed together
        # Pattern: look for strings with mix of uppercase/lowercase/numbers in a way that suggests codes
        if re.search(r'[a-z][A-Z0-9]{2,}|[A-Z]{2,}[0-9]|[0-9][a-zA-Z]{2,}[0-9]', name):
            return False
        
        # Filter out names that are too short or don't have at least 2 words (first + last)
        words = name.split()
        if len(words) < 2:
            return False
        
        # Each word should start with a capital letter (proper names)
        for word in words:
            if word and not word[0].isupper():
                return False
        
        return True
    
    def fetch_html(self):
        """Fetch HTML content from the URL, or use pre-fetched content if available."""
        # Use pre-fetched HTML if provided (e.g., from Selenium for PrestoSports sites)
        if self.html_content:
            logging.info(f"Using pre-fetched HTML ({len(self.html_content)} bytes)")
            return self.html_content
            
        logging.info(f"Fetching HTML from {self.url}")
        try:
            response = requests.get(self.url, headers=self.headers, timeout=15)  # Reduced timeout for speed
            if response.status_code == 200:
                logging.info(f"Success - received {len(response.text)} bytes")
                return response.text
            else:
                logging.error(f"Failed to fetch HTML: HTTP {response.status_code}")
                return None
        except Exception as e:
            logging.error(f"Error fetching HTML: {str(e)}")
            return None
            
    def extract_athlete_info_from_markup(self, html):
        """Extract athlete information directly from HTML markup patterns."""
        athletes = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Pattern 1: Look for sidearm-roster-player links
        player_links = soup.select("a.sidearm-roster-player-name, a[href*='/roster/']")
        for link in player_links:
            name = link.text.strip()
            if not name:
                # If no text, try to find name components
                first_name = link.select_one(".sidearm-roster-player-first-name")
                last_name = link.select_one(".sidearm-roster-player-last-name")
                if first_name and last_name:
                    name = f"{first_name.text.strip()} {last_name.text.strip()}"
            
            # If still no name, try to extract from the URL slug
            if not name:
                player_url = link.get('href', '')
                # URL format: /roster/first-last/12345
                url_match = re.search(r'/roster/([a-z\-]+)/\d+', player_url, re.IGNORECASE)
                if url_match:
                    name_slug = url_match.group(1)
                    # Convert "julia-blake" to "Julia Blake"
                    name = ' '.join(word.capitalize() for word in name_slug.split('-'))
            
            # Validate the extracted name
            if not self.is_valid_athlete_name(name):
                continue
                
            # Get the player detail URL
            player_url = link.get('href')
            if player_url and not player_url.startswith(('http://', 'https://')):
                player_url = urljoin(self.base_url, player_url)
                
            # Look for an associated image
            image_url = None
            
            # Check for parent with image container
            parent_li = link.find_parent("li", class_="sidearm-roster-player")
            if parent_li:
                # Try multiple patterns for images
                image_div = parent_li.select_one("div.sidearm-roster-player-image-container div[style*='background-image']")
                if image_div:
                    style = image_div.get('style', '')
                    match = re.search(r"background-image:url\(['\"]?(.*?)['\"]?\)", style)
                    if match:
                        image_url = match.group(1)
                        
                # If no image found, try img tag
                if not image_url:
                    img = parent_li.select_one("img.sidearm-roster-player-image, img[data-src]")
                    if img:
                        image_url = img.get('src') or img.get('data-src')
                        
            if name and image_url:
                athletes.append({
                    'name': name,
                    'url': player_url,
                    'image': image_url
                })
                
        return athletes
        
    def extract_js_image_urls(self, html):
        """Extract image URLs from JavaScript data in the HTML."""
        # Pattern 1: Look for URLs in background-image style attributes
        bg_image_matches = re.finditer(r"background-image:url\(['\"]?(.*?)['\"]?\)", html)
        
        image_urls = []
        for match in bg_image_matches:
            url = match.group(1)
            # Only count .jpg, .png, etc. files that look like player images
            if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']) and not any(exclude in url.lower() for exclude in ['logo', 'banner', 'icon', 'background']):
                # Check for name context around the image
                context_before = html[max(0, match.start() - 200):match.start()]
                context_after = html[match.end():min(len(html), match.end() + 200)]
                
                # Look for player name pattern nearby
                name = None
                name_matches = re.search(r'["\']?name["\']?\s*[:=]\s*["\']([^"\']+)["\']', context_before + context_after)
                if name_matches:
                    name = name_matches.group(1)
                    
                if not name:
                    # Try first/last name pattern
                    first_name_match = re.search(r'["\']?firstName["\']?\s*[:=]\s*["\']([^"\']+)["\']', context_before + context_after)
                    last_name_match = re.search(r'["\']?lastName["\']?\s*[:=]\s*["\']([^"\']+)["\']', context_before + context_after)
                    
                    if first_name_match and last_name_match:
                        name = f"{first_name_match.group(1)} {last_name_match.group(1)}"
                
                if not name:
                    # Try to get name from filename
                    file_match = re.search(r'/([^/]+)\.(jpg|jpeg|png)', url, re.IGNORECASE)
                    if file_match:
                        name_from_file = file_match.group(1)
                        
                        # Handle CMU format: lastname_firstname_hs
                        if name_from_file.endswith('_hs'):
                            # Strip the _hs suffix
                            name_from_file = name_from_file[:-3]
                            # Reverse order (lastname_firstname -> firstname lastname)
                            parts = name_from_file.split('_')
                            if len(parts) >= 2:
                                # Last part is first name, first parts are last name
                                first_name = parts[-1]
                                last_name = '_'.join(parts[:-1])
                                name_from_file = f"{first_name}_{last_name}"
                        
                        name_from_file = name_from_file.replace('_', ' ')
                        # Properly capitalize each word
                        name = ' '.join(word.capitalize() for word in name_from_file.split())
                
                # Validate the name before adding
                if name and self.is_valid_athlete_name(name):
                    image_urls.append({
                        'name': name,
                        'image': url
                    })
        
        return image_urls
        
    def extract_from_komodel_data(self, html):
        """Extract data from knockout.js data models commonly used by SideArm."""
        athletes = []
        
        # Pattern for knockout.js data objects
        ko_patterns = [
            r'koObject\(\s*(\{.*?\})\s*\)',
            r'ko\.mapping\.fromJS\(\s*(\{.*?\})\s*\)',
            r'ko\.computed\(\s*function\s*\(\)\s*\{\s*return\s*(\{.*?\})\s*\}\s*\)',
        ]
        
        for pattern in ko_patterns:
            matches = re.finditer(pattern, html, re.DOTALL)
            for match in matches:
                ko_data = match.group(1)
                
                # Look for player name in the ko data
                name_match = re.search(r'["\']?name["\']?\s*[:=]\s*["\']([^"\']+)["\']', ko_data)
                first_match = re.search(r'["\']?firstName["\']?\s*[:=]\s*["\']([^"\']+)["\']', ko_data)
                last_match = re.search(r'["\']?lastName["\']?\s*[:=]\s*["\']([^"\']+)["\']', ko_data)
                
                name = None
                if name_match:
                    name = name_match.group(1)
                elif first_match and last_match:
                    name = f"{first_match.group(1)} {last_match.group(1)}"
                    
                if not name:
                    continue
                    
                # Look for image URL
                img_match = re.search(r'["\']?(image|photo|photoUrl|playerPhoto|headshot)["\']?\s*[:=]\s*["\']([^"\']+)["\']', ko_data)
                if img_match:
                    image_url = img_match.group(2)
                    
                    athletes.append({
                        'name': name,
                        'image': image_url
                    })
        
        return athletes
        
    def extract_from_html_data_attributes(self, html):
        """Extract athlete info from data attributes."""
        athletes = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for elements with data-* attributes that might contain player info
        data_elements = soup.select('[data-player-id], [data-athlete-id], [data-player-name], [data-player-info]')
        
        for elem in data_elements:
            # Try to extract name
            name = elem.get('data-player-name')
            if not name:
                # Look for name inside
                name_elem = elem.select_one('.name, .player-name, h3, h4')
                if name_elem:
                    name = name_elem.text.strip()
            
            # If still no name, skip
            if not name:
                continue
                
            # Look for image
            image_url = None
            
            # Check for image element inside
            img = elem.select_one('img')
            if img:
                image_url = img.get('src') or img.get('data-src')
                
            # Check for style with background-image
            if not image_url:
                div_with_style = elem.select_one('[style*="background-image"]')
                if div_with_style:
                    style = div_with_style.get('style', '')
                    match = re.search(r'background-image:url\(["\']?(.*?)["\']?\)', style)
                    if match:
                        image_url = match.group(1)
            
            if image_url:
                athletes.append({
                    'name': name,
                    'image': image_url
                })
        
        return athletes

    def extract_from_person_cards(self, html):
        athletes = []
        soup = BeautifulSoup(html, 'html.parser')
        seen_names = set()

        roster_section = soup.select_one('.c-rosterpage__players, [class*=rosterpage__players]')
        if not roster_section:
            roster_section = soup

        cards = roster_section.select('a[href*="/roster/"]')
        for card in cards:
            all_imgs = card.select('img[alt]')
            if not all_imgs:
                continue

            img = all_imgs[0]
            image_url = img.get('src') or img.get('data-src', '')
            if len(all_imgs) > 1:
                for candidate in all_imgs:
                    csrc = candidate.get('src') or candidate.get('data-src', '') or ''
                    ccls = ' '.join(candidate.get('class', [])).lower()
                    if 'headshot' in ccls or 'crop?' in csrc:
                        img = candidate
                        image_url = csrc
                        break

            name = img.get('alt', '').strip()
            if not image_url:
                image_url = img.get('src') or img.get('data-src', '')

            if not name:
                heading = card.select_one('h3, h4, h2')
                if heading:
                    name = heading.get_text(strip=True)

            if not name or not image_url:
                continue

            if not self.is_valid_athlete_name(name):
                continue

            name_key = name.lower()
            if name_key in seen_names:
                continue
            seen_names.add(name_key)

            if not image_url.startswith(('http://', 'https://')):
                image_url = urljoin(self.base_url, image_url)

            player_url = card.get('href', '')
            if player_url and not player_url.startswith(('http://', 'https://')):
                player_url = urljoin(self.base_url, player_url)

            athletes.append({
                'name': name,
                'image_url': image_url,
                'image': image_url,
                'url': player_url
            })

        return athletes

    def download_athlete_image(self, athlete, headers=None):
        """Download an athlete's image."""
        name = athlete.get('name', 'Unknown Athlete')
        image_url = athlete.get('image', '')
        
        if not image_url:
            logging.error(f"No image URL for {name}")
            return False
            
        logging.info(f"Downloading image for {name}")
        
        # Make absolute URL if needed
        if image_url.startswith("//"):
            image_url = "https:" + image_url
        elif not image_url.startswith(("http://", "https://")):
            image_url = urljoin(self.base_url, image_url)
            
        original_url = image_url
        
        from urllib.parse import urlparse, parse_qs, urlencode, unquote
        parsed = urlparse(image_url)
        query_params = parse_qs(parsed.query)
        
        if 'url' in query_params:
            inner_url = unquote(query_params['url'][0])
            if '?' in inner_url:
                image_url = f"{inner_url}&height=1000&quality=90"
            else:
                image_url = f"{inner_url}?height=1000&quality=90"
        elif "?" in image_url:
            base_url = image_url.split("?")[0]
            image_url = f"{base_url}?height=1000&quality=90"
        else:
            image_url = f"{image_url}?height=1000&quality=90"
            
        logging.info(f"Original URL: {original_url}")
        logging.info(f"High-res URL: {image_url}")
        
        try:
            # Use provided headers or default headers
            request_headers = headers or self.headers
            
            response = requests.get(image_url, headers=request_headers, timeout=8)  # Optimized timeout for speed
            
            if response.status_code == 200:
                # Create safe filename - replace underscores with spaces, keep other safe chars
                safe_name = re.sub(r'[^\w\-\.\s]', '', name)  # Remove unsafe chars but keep spaces
                safe_name = safe_name.replace('_', ' ')  # Replace underscores with spaces
                safe_name = re.sub(r'\s+', ' ', safe_name).strip()  # Clean up multiple spaces
                if not safe_name:
                    safe_name = "athlete image"
                    
                # Create output directory if it doesn't exist
                os.makedirs(self.output_dir, exist_ok=True)
                
                # Save to temporary file first
                temp_path = os.path.join(self.output_dir, f"{safe_name}_temp.jpg")
                with open(temp_path, "wb") as f:
                    f.write(response.content)
                
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
                    file_path = os.path.join(self.output_dir, f"{safe_name}.png")
                    output_img.save(file_path, 'PNG', optimize=True)
                    
                    # Clean up image objects immediately
                    del input_img
                    del output_img
                    del session
                    
                    # Remove temp file
                    os.remove(temp_path)
                    
                    # Force garbage collection to free memory from AI model
                    gc.collect()
                    
                    logging.info(f"Successfully saved high-quality transparent PNG to {file_path}")
                    return True
                    
                except Exception as bg_error:
                    logging.warning(f"Background removal failed for {name}: {str(bg_error)}")
                    # Fallback: just rename the temp file
                    file_path = os.path.join(self.output_dir, f"{safe_name}.jpg")
                    os.rename(temp_path, file_path)
                    logging.info(f"Saved original image (without background removal) to {file_path}")
                    return True
            else:
                logging.error(f"Failed to download image: HTTP {response.status_code}")
                return False
        except Exception as e:
            logging.error(f"Error downloading image: {str(e)}")
            return False
            
    def extract_and_download_all(self):
        """Extract and download all athlete images."""
        html = self.fetch_html()
        if not html:
            return []
            
        # Extract athletes using all methods
        all_athletes = []
        
        # Method 1: HTML markup extraction
        markup_athletes = self.extract_athlete_info_from_markup(html)
        logging.info(f"Found {len(markup_athletes)} athletes via HTML markup")
        all_athletes.extend(markup_athletes)
        
        # Method 2: JS image URL extraction
        js_athletes = self.extract_js_image_urls(html)
        logging.info(f"Found {len(js_athletes)} athletes via JS image patterns")
        all_athletes.extend(js_athletes)
        
        # Method 3: Knockout.js model extraction
        ko_athletes = self.extract_from_komodel_data(html)
        logging.info(f"Found {len(ko_athletes)} athletes via KO models")
        all_athletes.extend(ko_athletes)
        
        # Method 4: Data attributes extraction
        data_athletes = self.extract_from_html_data_attributes(html)
        logging.info(f"Found {len(data_athletes)} athletes via data attributes")
        all_athletes.extend(data_athletes)
        
        # Method 5: Person card extraction (newer SideArm layout)
        card_athletes = self.extract_from_person_cards(html)
        logging.info(f"Found {len(card_athletes)} athletes via person cards")
        all_athletes.extend(card_athletes)
        
        if not all_athletes:
            logging.error("Failed to find any athletes")
            return []
            
        # Create a unique list of athletes (by name)
        unique_athletes = {}
        for athlete in all_athletes:
            name = athlete.get('name')
            if name and name not in unique_athletes:
                unique_athletes[name] = athlete
                
        athletes_list = list(unique_athletes.values())
        
        # Apply selective filtering if provided
        if self.selective_filter:
            filtered_athletes = self.apply_selective_filter(athletes_list)
            logging.info(f"Applied selective filter: {len(filtered_athletes)} of {len(athletes_list)} athletes match the filter")
            return filtered_athletes
            
        return athletes_list
    
    def apply_selective_filter(self, athletes_list):
        """Filter athletes based on the selective CSV criteria."""
        if not self.selective_filter:
            return athletes_list
            
        filtered_athletes = []
        
        # Extract school name from URL for matching
        school_keywords = self.extract_school_keywords_from_url()
        
        for athlete in athletes_list:
            athlete_name = athlete.get('name', '').lower().strip()
            
            # Check if this athlete matches any filter criteria
            should_include = False
            
            for school_key, athlete_names in self.selective_filter.items():
                # Check if current URL matches this school
                if self.school_matches(school_key, school_keywords):
                    # Check if athlete name matches
                    for filter_name in athlete_names:
                        if self.name_matches(athlete_name, filter_name):
                            should_include = True
                            logging.info(f"Matched athlete: {athlete_name} for school: {school_key}")
                            break
                    
                    if should_include:
                        break
            
            if should_include:
                filtered_athletes.append(athlete)
        
        return filtered_athletes
    
    def extract_school_keywords_from_url(self):
        """Extract potential school name keywords from the URL."""
        # Extract from domain and path
        domain_parts = self.domain.replace('.', ' ').split()
        path_parts = self.path.replace('/', ' ').replace('-', ' ').split()
        
        # Common keywords to extract
        keywords = []
        for part in domain_parts + path_parts:
            if len(part) > 2 and part.lower() not in ['com', 'edu', 'org', 'www', 'athletics', 'sports', 'roster', 'track', 'field']:
                keywords.append(part.lower())
        
        return keywords
    
    def school_matches(self, school_key, school_keywords):
        """Check if the school filter matches the current URL."""
        school_words = school_key.split()
        
        # Check if any significant words from the school name appear in URL
        matches = 0
        for word in school_words:
            if len(word) > 2:  # Only check meaningful words
                for keyword in school_keywords:
                    if word in keyword or keyword in word:
                        matches += 1
                        break
        
        # Consider it a match if at least one significant word matches
        return matches > 0
    
    def name_matches(self, athlete_name, filter_name):
        """Check if athlete name matches the filter."""
        # Simple fuzzy matching - check if filter name is contained in athlete name or vice versa
        athlete_words = athlete_name.split()
        filter_words = filter_name.split()
        
        # Check if all filter words appear in athlete name
        matches = 0
        for filter_word in filter_words:
            if len(filter_word) > 1:  # Skip single characters
                for athlete_word in athlete_words:
                    if filter_word in athlete_word or athlete_word in filter_word:
                        matches += 1
                        break
        
        # Consider it a match if most words match
        return matches >= len(filter_words) * 0.6  # 60% match threshold
    
    def download_all_images(self):
        """Download all athlete images found on the page using high-speed concurrent processing."""
        athletes = self.extract_and_download_all()
        
        if not athletes:
            return 0
            
        # Download images concurrently for maximum speed
        logging.info(f"Starting high-speed download of {len(athletes)} athlete images")
        
        import concurrent.futures
        
        success_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:  # Increased to 5 for faster processing while maintaining stability
            # Submit all download tasks
            future_to_athlete = {
                executor.submit(self.download_athlete_image, athlete): athlete 
                for athlete in athletes
            }
            
            # Process completed downloads
            for future in concurrent.futures.as_completed(future_to_athlete):
                try:
                    if future.result():
                        success_count += 1
                except Exception as e:
                    athlete = future_to_athlete[future]
                    logging.error(f"Download failed for {athlete.get('name', 'unknown')}: {str(e)}")
                
        logging.info(f"High-speed download completed: {success_count} of {len(athletes)} images")
        return success_count