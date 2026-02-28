#!/usr/bin/env python3
"""
Build roster URLs for all NCAA schools using TFRRS data and common patterns.
Much faster than scraping NCAA pages individually.
"""
import requests
from bs4 import BeautifulSoup
import csv
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Known athletic domain mappings (add more as discovered)
KNOWN_DOMAINS = {
    'Navy': 'navysports.com',
    'Army West Point': 'goarmywestpoint.com',
    'Princeton': 'goprincetontigers.com',
    'Harvard': 'gocrimson.com',
    'Yale': 'yalebulldogs.com',
    'Columbia': 'gocolumbialions.com',
    'Cornell': 'cornellbigred.com',
    'Dartmouth': 'dartmouthsports.com',
    'Brown': 'brownbears.com',
    'Penn': 'pennathletics.com',
    'MIT': 'mitathletics.com',
    'Boston University': 'goterriers.com',
    'Boston College': 'bceagles.com',
    'Northeastern': 'gonu.com',
    'Holy Cross': 'goholycross.com',
    'Colgate': 'gocolgateraiders.com',
    'Bucknell': 'bucknellbison.com',
    'Lafayette': 'goleopards.com',
    'Lehigh': 'lehighsports.com',
    'American': 'aueagles.com',
    'Georgetown': 'guhoyas.com',
    'Villanova': 'villanova.com',
    'Providence': 'friars.com',
    'Carnegie Mellon': 'athletics.cmu.edu',
    'Suffolk': 'gosuffolkrams.com',
    'RIT': 'ritathletics.com',
    'Rochester': 'uofrathletics.com',
    'Williams': 'ephsports.williams.edu',
    'Amherst': 'athletics.amherst.edu',
    'Middlebury': 'middleburyathletics.com',
    'Bowdoin': 'athletics.bowdoin.edu',
    'Bates': 'bates.edu/athletics',
    'Colby': 'colbymules.com',
    'Tufts': 'gotuftsjumbos.com',
    'Wesleyan': 'athletics.wesleyan.edu',
    'Connecticut College': 'camelathletics.com',
    'Trinity (Conn.)': 'athletics.trincoll.edu',
    'Hamilton': 'athletics.hamilton.edu',
    'Haverford': 'haverfordathletics.com',
    'Swarthmore': 'swarthmoresports.com',
    'Johns Hopkins': 'hopkinssports.com',
    'Emory': 'emoryathletics.com',
    'WashU': 'wustl.edu/athletics',
    'Chicago': 'athletics.uchicago.edu',
    'Case Western': 'cwrusports.com',
    'NYU': 'gonyuathletics.com',
    'Brandeis': 'brandeisjudges.com',
}

# Common URL patterns for roster pages
ROSTER_PATTERNS = [
    '/sports/mens-cross-country/roster',
    '/sports/womens-cross-country/roster',
    '/sports/mens-track-and-field/roster',
    '/sports/womens-track-and-field/roster',
    '/sports/mxc/roster',
    '/sports/wxc/roster',
    '/roster.aspx?path=mxc',
    '/roster.aspx?path=wxc',
]


def get_tfrrs_schools(division='d1'):
    """Get list of schools from TFRRS."""
    division_map = {'d1': 49, 'd2': 50, 'd3': 51}
    url = f"https://www.tfrrs.org/leagues/{division_map.get(division, 49)}.html"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        schools = set()
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/teams/tf/' in href and 'college' in href:
                name = link.get_text(strip=True)
                if name and len(name) > 1:
                    schools.add(name)
        
        return sorted(list(schools))
    except Exception as e:
        print(f"Error fetching {division}: {e}")
        return []


def guess_domain(school_name):
    """Guess the athletic domain for a school."""
    # Check known domains first
    if school_name in KNOWN_DOMAINS:
        return KNOWN_DOMAINS[school_name]
    
    # Generate guesses
    name = school_name.lower()
    name = re.sub(r'[^a-z\s]', '', name)
    words = name.split()
    
    guesses = []
    
    if words:
        # Common patterns
        main = words[0] if len(words) == 1 else ''.join(words[:2])
        guesses.extend([
            f"{main}sports.com",
            f"go{main}.com",
            f"{main}athletics.com",
            f"athletics.{main}.edu",
            f"{words[0]}athletics.com",
            f"go{words[0]}.com",
        ])
        
        # Try abbreviations
        if len(words) >= 2:
            abbrev = ''.join(w[0] for w in words)
            guesses.extend([
                f"go{abbrev}.com",
                f"{abbrev}sports.com",
            ])
    
    return guesses


def check_url_exists(url, timeout=5):
    """Check if a URL exists and returns content."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        return response.status_code == 200 and len(response.text) > 1000
    except:
        return False


def find_roster_url(school_name, sport='mxc'):
    """Find roster URL for a school and sport."""
    sport_patterns = {
        'mxc': ['/sports/mens-cross-country/roster', '/sports/mxc/roster', '/roster.aspx?path=mxc'],
        'wxc': ['/sports/womens-cross-country/roster', '/sports/wxc/roster', '/roster.aspx?path=wxc'],
        'mtf': ['/sports/mens-track-and-field/roster', '/sports/mtf/roster', '/roster.aspx?path=mtrack'],
        'wtf': ['/sports/womens-track-and-field/roster', '/sports/wtf/roster', '/roster.aspx?path=wtrack'],
    }
    
    patterns = sport_patterns.get(sport, sport_patterns['mxc'])
    
    # Get domain guesses
    domain = guess_domain(school_name)
    domains = [domain] if isinstance(domain, str) else domain
    
    for dom in domains[:5]:  # Limit to first 5 guesses
        base = f"https://{dom}" if not dom.startswith('http') else dom
        for pattern in patterns:
            url = f"{base.rstrip('/')}{pattern}"
            if check_url_exists(url):
                return url
    
    return None


def build_roster_csv(divisions=['d1', 'd2', 'd3'], sports=['mxc', 'wxc'], output_file='all_rosters.csv', max_workers=20):
    """Build CSV of all roster URLs."""
    print(f"Building roster URLs for divisions: {divisions}")
    print(f"Sports: {sports}")
    
    # Get all schools
    all_schools = {}
    for div in divisions:
        print(f"\nFetching {div.upper()} schools from TFRRS...")
        schools = get_tfrrs_schools(div)
        for school in schools:
            if school not in all_schools:
                all_schools[school] = div
        print(f"  Found {len(schools)} schools in {div.upper()}")
    
    print(f"\nTotal unique schools: {len(all_schools)}")
    print(f"Searching for roster URLs with {max_workers} workers...")
    
    results = []
    processed = 0
    
    def process_school(school, div):
        found = []
        for sport in sports:
            url = find_roster_url(school, sport)
            if url:
                found.append((school, sport, url))
        return found
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_school, school, div): school 
                   for school, div in all_schools.items()}
        
        for future in as_completed(futures):
            processed += 1
            school = futures[future]
            try:
                found = future.result()
                if found:
                    results.extend(found)
                    print(f"[{processed}/{len(all_schools)}] {school}: Found {len(found)} roster(s)")
                elif processed % 50 == 0:
                    print(f"[{processed}/{len(all_schools)}] Progress...")
            except Exception as e:
                pass
    
    # Save to CSV
    print(f"\nSaving {len(results)} roster URLs to {output_file}...")
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for school, sport, url in results:
            writer.writerow([url, school])
    
    print(f"\nDone! Found {len(results)} roster URLs for {len(set(r[0] for r in results))} schools")
    return results


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Build NCAA roster URLs')
    parser.add_argument('--divisions', nargs='+', default=['d1', 'd2', 'd3'],
                       help='Divisions to include (d1, d2, d3)')
    parser.add_argument('--sports', nargs='+', default=['mxc', 'wxc'],
                       help='Sports to find (mxc, wxc, mtf, wtf)')
    parser.add_argument('--output', default='all_rosters.csv',
                       help='Output CSV file')
    parser.add_argument('--workers', type=int, default=20,
                       help='Number of parallel workers')
    
    args = parser.parse_args()
    
    build_roster_csv(
        divisions=args.divisions,
        sports=args.sports,
        output_file=args.output,
        max_workers=args.workers
    )
