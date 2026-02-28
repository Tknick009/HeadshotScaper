"""
Modern Athlete Image Scraper - Optimized for Speed and Efficiency
Scrapes athlete images from SideArm Sports websites and saves as SchoolName_FirstName_LastName.png
Uses proven extraction methods from fast_scraper.py with improved file naming
"""

import os
import re
import logging
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Tuple, Optional
from bs4 import BeautifulSoup
import json

# Import the working scraper
from fast_scraper import process_url as fast_scraper_process_url
from sidearm_pattern_extractor import SideArmExtractor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class ModernAthleteScraper:
    """Fast and efficient athlete image scraper"""
    
    def __init__(self, output_dir='athletes'):
        self.output_dir = output_dir
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        os.makedirs(output_dir, exist_ok=True)
    
    def extract_school_name(self, url: str) -> str:
        """Extract clean school name from URL"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www and common suffixes
        domain = domain.replace('www.', '').replace('.com', '').replace('.edu', '').replace('.org', '')
        
        # Common mappings for better names
        mappings = {
            'goarmywestpoint': 'Army',
            'navysports': 'Navy',
            'goairforcefalcons': 'Air Force',
            'goholycross': 'Holy Cross',
            'lehighsports': 'Lehigh',
            'bucknellbison': 'Bucknell',
        }
        
        for key, value in mappings.items():
            if key in domain:
                return value
        
        # Clean up domain for school name
        school = domain.split('.')[0]
        school = re.sub(r'(athletics|sports|go|team)$', '', school, flags=re.IGNORECASE)
        school = school.strip('-_')
        
        # Capitalize properly
        return school.title().replace('-', ' ').replace('_', ' ')
    
    def clean_name(self, name: str) -> Tuple[str, str]:
        """Extract and clean first and last name from full name"""
        if not name:
            return "", ""
        
        # Remove extra whitespace and special characters
        name = re.sub(r'\s+', ' ', name.strip())
        name = re.sub(r'[^\w\s\'-]', '', name)
        
        # Split into parts
        parts = name.split()
        
        if len(parts) == 0:
            return "", ""
        elif len(parts) == 1:
            return parts[0], ""
        else:
            # First name is first part, last name is last part
            first_name = parts[0]
            last_name = parts[-1]
            return first_name, last_name
    
    def create_filename(self, school_name: str, athlete_name: str) -> str:
        """Create filename in format: SchoolName_FirstName_LastName.png"""
        first_name, last_name = self.clean_name(athlete_name)
        
        # Clean school name for filename - keep spaces as-is (don't replace with underscores)
        # This ensures "Navy Men" stays as "Navy Men" so splitting by underscore works correctly
        school = re.sub(r'[^\w\s-]', '', school_name)
        first = re.sub(r'[^\w-]', '', first_name)
        last = re.sub(r'[^\w-]', '', last_name)
        
        if first and last:
            return f"{school}_{first}_{last}.png"
        elif first:
            return f"{school}_{first}.png"
        else:
            return f"{school}_Unknown.png"
    
    
    
    def scrape_url(self, url: str, custom_team_name: Optional[str] = None) -> int:
        """Scrape all athletes from a single URL using fast_scraper and rename files
        
        Args:
            url: The roster page URL to scrape
            custom_team_name: Optional custom team name to use in filenames instead of auto-detected name
        """
        logging.info(f"\n{'='*80}")
        logging.info(f"Processing: {url}")
        logging.info(f"{'='*80}")
        
        # Use custom team name if provided, otherwise auto-detect from URL
        if custom_team_name:
            school_name = custom_team_name
            logging.info(f"Using custom team name: {school_name}")
        else:
            school_name = self.extract_school_name(url)
            logging.info(f"Auto-detected school: {school_name}")
        
        # Create temporary directory for fast_scraper
        temp_dir = os.path.join(self.output_dir, '_temp_download')
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            # Use the proven fast_scraper to download images
            count = fast_scraper_process_url(url, temp_dir)
            
            if count == 0:
                logging.warning(f"No athletes found for {url}")
                return 0
            
            # Rename files to our format: SchoolName_FirstName_LastName.png
            downloaded = 0
            for filename in os.listdir(temp_dir):
                if not filename.endswith(('.png', '.jpg', '.jpeg')):
                    continue
                
                # Extract name from filename (remove extension)
                athlete_name = os.path.splitext(filename)[0]
                
                # Create new filename with school name
                new_filename = self.create_filename(school_name, athlete_name)
                
                # Move and rename file
                old_path = os.path.join(temp_dir, filename)
                new_path = os.path.join(self.output_dir, new_filename)
                
                # Skip if target already exists
                if os.path.exists(new_path):
                    logging.info(f"Already exists: {new_filename}")
                    os.remove(old_path)
                    downloaded += 1
                    continue
                
                # Move file
                os.rename(old_path, new_path)
                downloaded += 1
                logging.info(f"Downloaded and renamed: {new_filename}")
            
            logging.info(f"Completed: {downloaded} images processed")
            return downloaded
            
        finally:
            # Clean up temp directory
            try:
                if os.path.exists(temp_dir):
                    for f in os.listdir(temp_dir):
                        os.remove(os.path.join(temp_dir, f))
                    os.rmdir(temp_dir)
            except:
                pass
    
    def scrape_multiple_urls(self, urls: List[str]) -> Dict[str, int]:
        """Scrape multiple URLs sequentially"""
        results = {}
        
        for url in urls:
            try:
                count = self.scrape_url(url)
                results[url] = count
            except Exception as e:
                logging.error(f"Error processing {url}: {e}")
                results[url] = 0
        
        return results


def scrape_from_csv(csv_path: str, output_dir: str = 'athletes') -> Dict[str, int]:
    """Scrape all URLs from a CSV file"""
    import csv
    
    urls = []
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0].strip().startswith('http'):
                urls.append(row[0].strip())
    
    logging.info(f"Found {len(urls)} URLs in CSV")
    
    scraper = ModernAthleteScraper(output_dir)
    return scraper.scrape_multiple_urls(urls)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python modern_scraper.py <url_or_csv>")
        sys.exit(1)
    
    input_path = sys.argv[1]
    
    if input_path.endswith('.csv'):
        results = scrape_from_csv(input_path)
        print("\n" + "="*80)
        print("SCRAPING COMPLETE")
        print("="*80)
        for url, count in results.items():
            print(f"{url}: {count} athletes")
    else:
        scraper = ModernAthleteScraper()
        count = scraper.scrape_url(input_path)
        print(f"\nTotal: {count} athletes downloaded")
