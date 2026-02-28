import requests
from bs4 import BeautifulSoup
import os
import re
from urllib.parse import urljoin
import cairosvg
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NCAALogoScraper:
    def __init__(self, output_dir='ncaa_logos'):
        self.base_url = 'https://www.ncaa.com/schools-index'
        self.output_dir = output_dir
        self.schools_data = []
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
    
    def sanitize_filename(self, name):
        """Convert school name to valid filename"""
        # Remove invalid characters for filenames
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        # Clean up multiple spaces
        name = re.sub(r'\s+', ' ', name)
        return name.strip()
    
    def scrape_page(self, page_num):
        """Scrape a single page and extract school data"""
        if page_num == 0:
            url = self.base_url
        else:
            url = f"{self.base_url}/{page_num}"
        
        logging.info(f"Scraping page {page_num}: {url}")
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all table rows
            rows = soup.find_all('tr')
            
            schools_on_page = 0
            for row in rows:
                # Find image and name in the row
                img = row.find('img')
                name_cell = row.find_all('td')
                
                if img and len(name_cell) >= 2:
                    logo_url = img.get('src')
                    # The second column contains the team name
                    school_name = name_cell[1].get_text(strip=True)
                    
                    if logo_url and school_name:
                        # Make sure logo URL is absolute
                        if logo_url.startswith('//'):
                            logo_url = 'https:' + logo_url
                        elif logo_url.startswith('/'):
                            logo_url = urljoin('https://www.ncaa.com', logo_url)
                        
                        self.schools_data.append({
                            'name': school_name,
                            'logo_url': logo_url
                        })
                        schools_on_page += 1
            
            logging.info(f"Found {schools_on_page} schools on page {page_num}")
            return schools_on_page > 0
            
        except Exception as e:
            logging.error(f"Error scraping page {page_num}: {e}")
            return False
    
    def download_and_convert_logo(self, school_data):
        """Download SVG logo and convert to transparent PNG"""
        school_name = school_data['name']
        logo_url = school_data['logo_url']
        
        # Create filename from school name
        filename = self.sanitize_filename(school_name) + '.png'
        output_path = os.path.join(self.output_dir, filename)
        
        # Skip if already exists
        if os.path.exists(output_path):
            logging.info(f"Already exists: {filename}")
            return True
        
        try:
            # Download SVG
            response = requests.get(logo_url, timeout=30)
            response.raise_for_status()
            
            svg_data = response.content
            
            # Convert SVG to PNG with transparency
            cairosvg.svg2png(
                bytestring=svg_data,
                write_to=output_path,
                background_color='transparent'
            )
            
            logging.info(f"Downloaded and converted: {filename}")
            return True
            
        except Exception as e:
            logging.error(f"Error downloading logo for {school_name}: {e}")
            return False
    
    def scrape_all_pages(self):
        """Scrape all 24 pages (0-23)"""
        logging.info("Starting to scrape all pages...")
        
        # Scrape pages 0 through 23 (24 total pages)
        for page_num in range(24):
            success = self.scrape_page(page_num)
            if not success and page_num > 0:
                # If a page fails and it's not the first page, we might have reached the end
                logging.warning(f"No data found on page {page_num}, stopping pagination")
                break
        
        logging.info(f"Total schools found: {len(self.schools_data)}")
        return len(self.schools_data)
    
    def download_all_logos(self):
        """Download and convert all logos"""
        logging.info(f"Starting to download {len(self.schools_data)} logos...")
        
        successful = 0
        failed = 0
        
        for school_data in tqdm(self.schools_data, desc="Downloading logos"):
            if self.download_and_convert_logo(school_data):
                successful += 1
            else:
                failed += 1
        
        logging.info(f"Download complete: {successful} successful, {failed} failed")
        return successful, failed
    
    def run(self):
        """Run the complete scraping process"""
        print("=" * 60)
        print("NCAA Logo Scraper")
        print("=" * 60)
        
        # Step 1: Scrape all pages
        total_schools = self.scrape_all_pages()
        
        if total_schools == 0:
            print("No schools found. Exiting.")
            return
        
        print(f"\nFound {total_schools} schools across all pages")
        
        # Step 2: Download and convert logos
        successful, failed = self.download_all_logos()
        
        print("\n" + "=" * 60)
        print("SCRAPING COMPLETE")
        print("=" * 60)
        print(f"Total schools: {total_schools}")
        print(f"Successfully downloaded: {successful}")
        print(f"Failed: {failed}")
        print(f"Output directory: {os.path.abspath(self.output_dir)}")
        print("=" * 60)

if __name__ == '__main__':
    scraper = NCAALogoScraper()
    scraper.run()
