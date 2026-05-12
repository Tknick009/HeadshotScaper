# Testing HeadshotScraper

## Overview
HeadshotScraper is a Flask web app that scrapes college athlete headshots from roster pages. The primary workflow is: upload a Hy-Tek Meet Manager CSV -> app finds roster URLs -> fuzzy-matches athlete names -> downloads headshots -> removes backgrounds.

## Devin Secrets Needed
- `GITHUB_PAT` - GitHub personal access token for pushing to the repo

## Local Setup
1. Install dependencies: `pip install flask requests beautifulsoup4 selenium webdriver-manager Pillow numpy tqdm rapidfuzz`
2. Start the app: `PORT=8080 python app.py` (port 5000 may be unavailable on some systems)
3. Open browser to `http://localhost:8080`
4. The app uses headless Selenium + ChromeDriver for scraping. webdriver-manager handles ChromeDriver installation automatically.

## Testing the Targeted CSV Flow

### Creating a Small Test CSV
The full meet CSV (469 athletes, 10 schools) takes too long for quick testing. Create a subset with 2-3 schools:
```python
import csv, io, sys
sys.path.insert(0, '/path/to/HeadshotScaper')
from targeted_scraper import parse_meet_csv

# Filter the full CSV to keep only rows for specific schools
# In Hy-Tek format, school name is in column 14 (0-indexed)
```
Good test schools: American (31 athletes, 100% match), Colgate (28 athletes, 96% match) - both are small and have well-structured SideArm roster pages.

### Test Steps
1. Clean output directory: `rm -rf athletes/targeted && mkdir -p athletes/targeted`
2. Start Flask app in background
3. Open `http://localhost:8080` in browser
4. Default tab is "Targeted (CSV Meet File)" - click the drop zone to upload CSV
5. Leave sport as "Track & Field", click "Start Targeted Scrape"
6. Watch progress: stats grid shows Schools/Athletes/Found/Not Found counts
7. Per-school status list shows each school transitioning: pending -> scraping... -> done
8. On completion: title shows "Complete - X/Y athletes found"
9. Action buttons appear: Download All Images (ZIP), Download Unmatched CSV, Start New Scrape
10. Click Download ZIP to verify download works

### Verifying Image Quality
```python
from PIL import Image
import os
d = 'athletes/targeted/'
for f in sorted(os.listdir(d))[:5]:
    img = Image.open(os.path.join(d, f))
    print(f'{f}: {img.size[0]}x{img.size[1]}')
```
Expect images around 800x1000 pixels for schools with standard SideArm roster pages.

## Known Issues
- **Selenium opens extra browser tabs**: The headless ChromeDriver may open visible browser windows/tabs if Chrome flags aren't perfectly configured. These are harmless but clutter the browser. Close them manually.
- **rembg not installed**: Background removal requires `rembg` and `onnxruntime` (~500MB). If not installed, images save without background removal - this is expected behavior, not a failure.
- **Schools with outdated rosters**: Some schools (e.g., Lafayette) have roster pages with completely different athletes than the current meet CSV. This produces 0% match rate and is a data issue, not a code bug.
- **Old SideArm formats**: Some schools (e.g., Loyola Md.) use `roster.aspx?path=` URLs that the HTML parser can't extract athletes from. Selenium fallback also struggles with these.
- **Port conflicts**: Port 5000 may be taken. Always use `PORT=8080` or another available port.

## Expected Test Results
For well-structured schools (American, Colgate, Holy Cross, Navy, Army, Lehigh):
- 95-100% match rate
- Images at 800x1000 resolution
- ZIP download ~150KB per athlete

For schools with issues (Bucknell, Lafayette, Loyola Md.):
- 0-25% match rate due to placeholder images or outdated rosters
