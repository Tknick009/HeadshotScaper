import os
import re
import csv
import json
import logging
import time
import gc
from io import StringIO
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try to use rapidfuzz for better fuzzy matching performance
try:
    from rapidfuzz import fuzz as rfuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Path for pre-built roster URL database
ROSTER_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'roster_url_database.json')

# Minimum image height for video board quality output
MIN_OUTPUT_HEIGHT = 800


def load_roster_database():
    """Load roster database if it exists, otherwise return empty dict."""
    logging.info(f"Looking for roster database at: {ROSTER_DB_PATH}")
    if os.path.exists(ROSTER_DB_PATH):
        try:
            with open(ROSTER_DB_PATH, 'r') as f:
                db = json.load(f)
            logging.info(f"Loaded roster database with {len(db)} schools")
            return db
        except Exception as e:
            logging.warning(f"Could not load roster database: {e}")
    else:
        logging.warning(f"Roster database not found at {ROSTER_DB_PATH}")
    return {}


def normalize_school_name(name):
    name = name.strip().lower()
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


# Comprehensive alias map for school name matching
SCHOOL_ALIASES = {
    'army': 'Army West Point',
    'bu': 'Boston University',
    'bc': 'Boston College',
    'uconn': 'Connecticut',
    'umass': 'UMass Amherst',
    'uri': 'Rhode Island',
    'rit': 'RIT',
    'rpi': 'RPI',
    'mit': 'MIT',
    'nyu': 'NYU',
    'usc': 'USC',
    'ucla': 'UCLA',
    'ucsd': 'UC San Diego',
    'uci': 'UC Irvine',
    'unc': 'North Carolina',
    'ole miss': 'Ole Miss',
    'lsu': 'LSU',
    'smu': 'SMU',
    'tcu': 'TCU',
    'byu': 'BYU',
    'unlv': 'UNLV',
    'utep': 'UTEP',
    'utsa': 'UTSA',
    'vcu': 'VCU',
    'wku': 'Western Kentucky',
    'ecu': 'East Carolina',
    'fiu': 'FIU',
    'fau': 'FAU',
    'uab': 'UAB',
    'siue': 'SIU Edwardsville',
    'siuc': 'Southern Illinois',
    'wcsu': 'Western Connecticut State',
    'western conn': 'Western Connecticut',
    'scsu': 'Southern Connecticut',
    'southern conn': 'Southern Connecticut',
    'ecsu': 'Eastern Connecticut',
    'ccsu': 'Central Connecticut',
    'aic': 'American International',
    'snhu': 'SNHU',
    'umass lowell': 'UMass Lowell',
    'umass dartmouth': 'UMass Dartmouth',
    'umass amherst': 'UMass Amherst',
    'umass boston': 'UMass Boston',
    'saint rose': 'Saint Rose',
    'st rose': 'Saint Rose',
    'st. rose': 'Saint Rose',
    'holy cross': 'Holy Cross',
    'stonehill': 'Stonehill',
    'merrimack': 'Merrimack',
    'bentley': 'Bentley',
    'assumption': 'Assumption',
    'smith': 'Smith College',
    'augusta': 'Augusta',
    'ualbany': 'Albany',
    'u of a': 'Arizona',
    'osu': 'Ohio State',
    'psu': 'Penn State',
    'msu': 'Michigan State',
    'isu': 'Iowa State',
    'ksu': 'Kansas State',
    'wsu': 'Washington State',
    'tamu': 'Texas A&M',
    'a&m': 'Texas A&M',
    'ut': 'Texas',
    'ou': 'Oklahoma',
    'uf': 'Florida',
    'uga': 'Georgia',
    'uk': 'Kentucky',
    'ua': 'Alabama',
    'au': 'Auburn',
    'uva': 'Virginia',
    'vt': 'Virginia Tech',
    'gt': 'Georgia Tech',
    'nc state': 'NC State',
    'ncsu': 'NC State',
    # Hy-Tek parenthetical abbreviations
    'loyola md': 'Loyola Maryland',
    'loyola md.': 'Loyola Maryland',
    'loyola (md.)': 'Loyola Maryland',
    'loyola (md)': 'Loyola Maryland',
    'miami fl': 'Miami',
    'miami (fl)': 'Miami',
    'miami (fl.)': 'Miami',
    'miami fl.': 'Miami',
    'miami oh': 'Miami (OH)',
    'miami (oh)': 'Miami (OH)',
    'st johns': "St. John's",
    'st. johns': "St. John's",
    'saint johns': "St. John's",
    'st josephs': "Saint Joseph's",
    'st. josephs': "Saint Joseph's",
    'saint josephs': "Saint Joseph's",
    'st francis pa': 'St. Francis (PA)',
    'st. francis (pa)': 'St. Francis (PA)',
    'mount st marys': "Mount St. Mary's",
    'mt st marys': "Mount St. Mary's",
    'mount st. marys': "Mount St. Mary's",
    'mount st. mary\'s': "Mount St. Mary's",
    'trinity conn': 'Trinity (Conn.)',
    'trinity (conn.)': 'Trinity (Conn.)',
    'app state': 'Appalachian State',
    'appalachian st': 'Appalachian State',
    'penn': 'Penn',
    'u penn': 'Penn',
    'upenn': 'Penn',
}


def find_school_in_database(school_name, db):
    """Find school in database with fuzzy matching."""
    if not db:
        return None

    normalized = normalize_school_name(school_name)

    # Exact match
    for db_school in db:
        if normalize_school_name(db_school) == normalized:
            return db_school

    # Alias match
    if normalized in SCHOOL_ALIASES:
        alias_target = SCHOOL_ALIASES[normalized]
        for db_school in db:
            if normalize_school_name(db_school) == normalize_school_name(alias_target):
                return db_school

    # Substring match (if query is long enough)
    if len(normalized) >= 5:
        for db_school in db:
            db_norm = normalize_school_name(db_school)
            shorter = min(len(normalized), len(db_norm))
            longer = max(len(normalized), len(db_norm))
            if shorter >= 5 and longer <= shorter * 2 and (normalized in db_norm or db_norm in normalized):
                return db_school

    # Fuzzy match
    best_match = None
    best_score = 0

    if HAS_RAPIDFUZZ:
        for db_school in db:
            db_norm = normalize_school_name(db_school)
            score = rfuzz.ratio(normalized, db_norm)
            if score > best_score:
                best_score = score
                best_match = db_school
        if best_score >= 85:
            return best_match
    else:
        for db_school in db:
            db_norm = normalize_school_name(db_school)
            ratio = SequenceMatcher(None, normalized, db_norm).ratio()
            if ratio > best_score:
                best_score = ratio
                best_match = db_school
        if best_score >= 0.85:
            return best_match

    return None


def get_roster_urls_for_school(school_name, db, sport='tf'):
    """Get roster URLs for a school. Tries database first, then dynamic discovery."""
    # Try the pre-built database first
    if db:
        db_school = find_school_in_database(school_name, db)
        if db_school:
            school_data = db[db_school]
            urls = []

            sport_data = school_data.get(sport, {})
            if not sport_data:
                other_sport = 'xc' if sport == 'tf' else 'tf'
                sport_data = school_data.get(other_sport, {})

            invalid_patterns = ['college closed', 'no roster', 'discontinued', 'n/a', 'none']

            for key in ['combined', 'men', 'women']:
                url = sport_data.get(key, '')
                if url and url.startswith('http'):
                    url_lower = url.lower()
                    if not any(inv in url_lower for inv in invalid_patterns):
                        urls.append(url)

            if urls:
                return urls, db_school

    # Dynamic URL discovery using roster_url_builder
    logging.info(f"No database entry for '{school_name}', trying dynamic URL discovery...")
    try:
        from roster_url_builder import find_roster_url

        # Map sport codes to roster_url_builder sport codes
        sport_map = {
            'tf': ['mtf', 'wtf'],
            'xc': ['mxc', 'wxc'],
        }
        sport_codes = sport_map.get(sport, ['mtf', 'wtf'])

        urls = []
        for code in sport_codes:
            url = find_roster_url(school_name, code)
            if url:
                urls.append(url)
                logging.info(f"Dynamic discovery found URL for {school_name} ({code}): {url}")

        if urls:
            return urls, school_name

    except Exception as e:
        logging.warning(f"Dynamic URL discovery failed for '{school_name}': {e}")

    return None, None


def _detect_hytek_format(rows):
    for row in rows[:5]:
        row_str = ','.join(row).lower()
        if 'hy-tek' in row_str or 'meet manager' in row_str:
            return True
    return False


def _parse_hytek_csv(rows):
    athletes_by_school = {}
    all_athletes = []
    seen = set()
    
    skip_schools = {
        'unattached', 'unat', 'guest', 'exhibition',
    }
    
    for row in rows:
        if len(row) < 15:
            continue
        
        name = row[12].strip() if len(row) > 12 else ''
        school = row[14].strip() if len(row) > 14 else ''
        
        if not name or not school:
            continue
        
        if re.match(r'^\d+\.$', name):
            continue
        
        if school.lower() in skip_schools:
            continue
        
        name = re.sub(r'\s+', ' ', name).strip()
        name = name.title()
        
        key = (school.lower(), name.lower())
        if key in seen:
            continue
        seen.add(key)
        
        if school not in athletes_by_school:
            athletes_by_school[school] = []
        
        athletes_by_school[school].append(name)
        all_athletes.append({'school': school, 'name': name})
    
    return athletes_by_school, all_athletes


def parse_meet_csv(csv_content):
    reader = csv.reader(StringIO(csv_content))
    rows = list(reader)
    
    if _detect_hytek_format(rows):
        logging.info("Detected Hy-Tek Meet Manager CSV format")
        return _parse_hytek_csv(rows)
    
    athletes_by_school = {}
    all_athletes = []
    
    header = None
    school_col = None
    name_col = None
    first_col = None
    last_col = None
    
    for i, row in enumerate(rows):
        if not row or all(not cell.strip() for cell in row):
            continue
            
        if i == 0:
            header_lower = [c.strip().lower() for c in row]
            
            for j, h in enumerate(header_lower):
                if h in ('school', 'team', 'college', 'university', 'affiliation', 'school name', 'team name'):
                    school_col = j
                elif h in ('name', 'athlete', 'athlete name', 'full name', 'runner'):
                    name_col = j
                elif h in ('first', 'first name', 'firstname', 'first_name'):
                    first_col = j
                elif h in ('last', 'last name', 'lastname', 'last_name', 'surname'):
                    last_col = j
            
            if school_col is not None and (name_col is not None or first_col is not None):
                continue
            
            school_col = None
            name_col = None
            first_col = None
            last_col = None
        
        if school_col is None:
            if len(row) >= 2:
                school_raw = row[0].strip()
                name_raw = row[1].strip() if len(row) > 1 else ''
                
                if not school_raw or school_raw.lower().startswith('http'):
                    continue
                
                if name_raw:
                    school = school_raw
                    athlete_name = name_raw
                else:
                    parts = school_raw.split('_')
                    if len(parts) >= 3:
                        school = parts[0].replace('_', ' ')
                        athlete_name = ' '.join(parts[1:])
                    else:
                        continue
            else:
                continue
        else:
            school = row[school_col].strip() if school_col < len(row) else ''
            if not school:
                continue
            
            if name_col is not None and name_col < len(row):
                athlete_name = row[name_col].strip()
            elif first_col is not None:
                first = row[first_col].strip() if first_col < len(row) else ''
                last = row[last_col].strip() if last_col is not None and last_col < len(row) else ''
                athlete_name = f"{first} {last}".strip()
            else:
                continue
        
        if not athlete_name or not school:
            continue
        
        athlete_name = re.sub(r'\s+', ' ', athlete_name).strip()
        athlete_name = athlete_name.title()
        
        if school not in athletes_by_school:
            athletes_by_school[school] = []
        
        athletes_by_school[school].append(athlete_name)
        all_athletes.append({'school': school, 'name': athlete_name})
    
    return athletes_by_school, all_athletes


SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v'}

NICKNAME_MAP = {
    'mike': 'michael', 'michael': 'mike',
    'bill': 'william', 'william': 'bill',
    'will': 'william',
    'bob': 'robert', 'robert': 'bob',
    'rob': 'robert',
    'jim': 'james', 'james': 'jim',
    'jimmy': 'james',
    'joe': 'joseph', 'joseph': 'joe',
    'dan': 'daniel', 'daniel': 'dan',
    'danny': 'daniel',
    'dave': 'david', 'david': 'dave',
    'tom': 'thomas', 'thomas': 'tom',
    'tommy': 'thomas',
    'chris': 'christopher', 'christopher': 'chris',
    'matt': 'matthew', 'matthew': 'matt',
    'nick': 'nicholas', 'nicholas': 'nick',
    'pat': 'patrick', 'patrick': 'pat',
    'ed': 'edward', 'edward': 'ed',
    'eddie': 'edward',
    'ted': 'theodore', 'theodore': 'ted',
    'sam': 'samuel', 'samuel': 'sam',
    'ben': 'benjamin', 'benjamin': 'ben',
    'alex': 'alexander', 'alexander': 'alex',
    'tony': 'anthony', 'anthony': 'tony',
    'steve': 'steven', 'steven': 'steve',
    'stephen': 'steve',
    'rick': 'richard', 'richard': 'rick',
    'dick': 'richard',
    'rich': 'richard',
    'andy': 'andrew', 'andrew': 'andy',
    'drew': 'andrew',
    'charlie': 'charles', 'charles': 'charlie',
    'chuck': 'charles',
    'jack': 'john', 'john': 'jack',
    'johnny': 'john',
    'jon': 'jonathan', 'jonathan': 'jon',
    'larry': 'lawrence', 'lawrence': 'larry',
    'greg': 'gregory', 'gregory': 'greg',
    'jeff': 'jeffrey', 'jeffrey': 'jeff',
    'josh': 'joshua', 'joshua': 'josh',
    'tim': 'timothy', 'timothy': 'tim',
    'zach': 'zachary', 'zachary': 'zach',
    'zack': 'zachary',
    'nate': 'nathan', 'nathan': 'nate',
    'nathaniel': 'nate',
    'pete': 'peter', 'peter': 'pete',
    'phil': 'philip', 'philip': 'phil',
    'liz': 'elizabeth', 'elizabeth': 'liz',
    'beth': 'elizabeth',
    'kate': 'katherine', 'katherine': 'kate',
    'kathy': 'katherine',
    'katie': 'katherine',
    'jenny': 'jennifer', 'jennifer': 'jenny',
    'jenn': 'jennifer',
    'meg': 'margaret', 'margaret': 'meg',
    'maggie': 'margaret',
    'maddie': 'madeline', 'madeline': 'maddie',
    'abby': 'abigail', 'abigail': 'abby',
    'sam': 'samantha', 'samantha': 'sam',
    'chris': 'christina', 'christina': 'chris',
    'ali': 'allison', 'allison': 'ali',
    'allie': 'allison',
    'becky': 'rebecca', 'rebecca': 'becky',
    'vicky': 'victoria', 'victoria': 'vicky',
    'mel': 'melanie', 'melanie': 'mel',
    'sue': 'susan', 'susan': 'sue',
    'mandy': 'amanda', 'amanda': 'mandy',
    'em': 'emily', 'emily': 'em',
    'gabby': 'gabriella', 'gabriella': 'gabby',
    'gabi': 'gabriella',
    'liv': 'olivia', 'olivia': 'liv',
}


def normalize_name_part(name):
    name = re.sub(r'[^\w\s]', '', name.lower().strip())
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def split_name_parts(name):
    normalized = normalize_name_part(name)
    if ',' in name:
        parts = [p.strip() for p in name.split(',', 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            normalized = normalize_name_part(f"{parts[1]} {parts[0]}")
    
    parts = normalized.split()
    parts = [p for p in parts if p.lower() not in SUFFIXES]
    
    if len(parts) >= 2:
        return parts[0], parts[-1], parts[1:-1]
    elif len(parts) == 1:
        return parts[0], '', []
    return '', '', []


def first_names_match(name1, name2):
    """Check if two first names match, accounting for nicknames and initials."""
    if name1 == name2:
        return True

    # Prefix match (3+ chars) - catches "Dan" matching "Daniel", etc.
    if len(name1) >= 3 and len(name2) >= 3 and name1[:3] == name2[:3]:
        return True

    # Nickname lookup
    canonical1 = NICKNAME_MAP.get(name1, name1)
    canonical2 = NICKNAME_MAP.get(name2, name2)
    if canonical1 == canonical2:
        return True
    if canonical1 == name2 or canonical2 == name1:
        return True

    # Initial match (e.g., "J" matches "James")
    if len(name1) == 1 and name2.startswith(name1):
        return True
    if len(name2) == 1 and name1.startswith(name2):
        return True

    # Rapidfuzz partial match for longer names
    if HAS_RAPIDFUZZ and len(name1) >= 4 and len(name2) >= 4:
        if rfuzz.ratio(name1, name2) >= 80:
            return True

    return False


def last_names_match(name1, name2):
    """Check if two last names match, handling hyphens, apostrophes, and typos."""
    if name1 == name2:
        return True

    # Normalize special characters
    n1 = name1.replace('-', '').replace("'", '').replace(' ', '')
    n2 = name2.replace('-', '').replace("'", '').replace(' ', '')
    if n1 == n2:
        return True

    # One name is a prefix of the other (e.g., hyphenated vs single)
    if len(n1) >= 3 and len(n2) >= 3:
        if n1.startswith(n2) or n2.startswith(n1):
            return True

    # Fuzzy match
    if HAS_RAPIDFUZZ:
        if rfuzz.ratio(name1, name2) >= 85:
            return True
    else:
        ratio = SequenceMatcher(None, name1, name2).ratio()
        if ratio >= 0.85:
            return True

    return False


def name_matches(roster_name, target_name):
    """Check if a roster name matches a target name with comprehensive fuzzy matching."""
    r_first, r_last, r_mid = split_name_parts(roster_name)
    t_first, t_last, t_mid = split_name_parts(target_name)

    if not r_first or not t_first:
        return False

    # Direct match
    if r_first == t_first and r_last == t_last:
        return True

    # Fuzzy component match
    if first_names_match(r_first, t_first) and last_names_match(r_last, t_last):
        return True

    # Swapped first/last (some systems list "Last First")
    if first_names_match(r_first, t_last) and last_names_match(r_last, t_first):
        return True

    # Try matching with middle names included
    if r_mid and last_names_match(r_last, t_last):
        # Check if first or middle name matches target first
        for mid in r_mid:
            if first_names_match(mid, t_first):
                return True

    if t_mid and last_names_match(r_last, t_last):
        for mid in t_mid:
            if first_names_match(r_first, mid):
                return True

    # Full name fuzzy match as last resort
    r_full = normalize_name_part(roster_name)
    t_full = normalize_name_part(target_name)

    if HAS_RAPIDFUZZ:
        score = rfuzz.ratio(r_full, t_full)
        if score >= 80:
            return True
        # Token sort ratio handles word order differences
        token_score = rfuzz.token_sort_ratio(r_full, t_full)
        if token_score >= 85:
            return True
    else:
        ratio = SequenceMatcher(None, r_full, t_full).ratio()
        if ratio >= 0.80:
            return True

    return False


def try_bio_page_extraction(url, target_names, output_dir, school_name, html_content=None):
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, urljoin, parse_qs, unquote
    import requests
    
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    if not html_content:
        try:
            r = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            html_content = r.text
        except Exception as e:
            logging.error(f"Failed to fetch roster page: {e}")
            return [], list(target_names)
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    roster_links = soup.find_all('a', href=lambda x: x and '/roster/' in x)
    
    athlete_links = {}
    for a in roster_links:
        href = a['href']
        text = a.get_text(strip=True)
        if not text or len(text.split()) < 2:
            continue
        if text.lower() in ['full bio', 'view bio', 'bio', 'profile', 'more']:
            continue
        if 'Full Bio' in text or 'View Bio' in text:
            continue
        if href not in athlete_links:
            athlete_links[href] = text
    
    if not athlete_links:
        logging.info("No athlete bio links found on roster page")
        return [], list(target_names)
    
    logging.info(f"Found {len(athlete_links)} athlete bio links, matching against {len(target_names)} targets")
    
    matched_bio_links = []
    matched_targets = set()
    for href, roster_name in athlete_links.items():
        for target in target_names:
            if target.lower() in matched_targets:
                continue
            if name_matches(roster_name, target):
                full_url = urljoin(base_url, href)
                matched_bio_links.append((full_url, roster_name, target))
                matched_targets.add(target.lower())
                logging.info(f"BIO MATCH: roster '{roster_name}' matches target '{target}'")
                break
    
    if not matched_bio_links:
        logging.info("No target athletes matched roster bio links")
        return [], list(target_names)
    
    logging.info(f"Matched {len(matched_bio_links)} athletes, visiting bio pages for headshots")
    
    matched = []
    seen_image_urls = set()  # Track unique image URLs to detect default/placeholder images
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    for bio_url, roster_name, target_name in matched_bio_links:
        try:
            logging.info(f"Fetching bio page for {roster_name}: {bio_url}")
            bio_resp = session.get(bio_url, timeout=15)
            if bio_resp.status_code != 200:
                logging.warning(f"Bio page returned {bio_resp.status_code} for {roster_name}")
                continue
            
            bio_soup = BeautifulSoup(bio_resp.text, 'html.parser')
            
            headshot_img = None
            for img in bio_soup.find_all('img'):
                alt = (img.get('alt') or '').strip()
                src = img.get('src') or ''
                if not src:
                    continue
                if alt and name_matches(alt, roster_name):
                    headshot_img = img
                    break
            
            if not headshot_img:
                imgs = bio_soup.find_all('img', src=lambda x: x and any(
                    ext in x.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']
                ))
                exclude = ['logo', 'nav', 'footer', 'header', 'icon', 'button', 'background', 'sponsor', 'banner']
                for img in imgs:
                    src = (img.get('src') or '').lower()
                    if any(kw in src for kw in exclude):
                        continue
                    cls_str = ' '.join(img.get('class', [])).lower()
                    if any(kw in cls_str for kw in ['logo', 'nav-logo', 'site-logo']):
                        continue
                    headshot_img = img
                    break
            
            if not headshot_img:
                logging.warning(f"No headshot found on bio page for {roster_name}")
                continue
            
            img_url = headshot_img.get('src', '')
            if not img_url:
                continue
            
            if img_url.startswith('//'):
                img_url = 'https:' + img_url
            elif not img_url.startswith('http'):
                img_url = urljoin(base_url, img_url)
            
            img_parsed = urlparse(img_url)
            img_params = parse_qs(img_parsed.query)
            if 'url' in img_params:
                inner_url = unquote(img_params['url'][0])
                if '?' in inner_url:
                    img_url = f"{inner_url}&height=1000&quality=90"
                else:
                    img_url = f"{inner_url}?height=1000&quality=90"
            elif '?' in img_url:
                img_base = img_url.split('?')[0]
                img_url = f"{img_base}?height=1000&quality=90"
            else:
                img_url = f"{img_url}?height=1000&quality=90"
            
            # Check for duplicate/default images (same URL used for multiple athletes)
            img_base_url = img_url.split('?')[0]  # Compare without query params
            if img_base_url in seen_image_urls:
                logging.warning(f"Skipping duplicate/default image for {roster_name}: {img_base_url[:80]}")
                continue
            seen_image_urls.add(img_base_url)
            
            logging.info(f"Downloading headshot for {roster_name}: {img_url[:120]}")
            img_resp = session.get(img_url, timeout=10)
            if img_resp.status_code != 200:
                logging.warning(f"Image download failed ({img_resp.status_code}) for {roster_name}")
                continue
            
            from PIL import Image
            from io import BytesIO
            
            img_data = img_resp.content
            try:
                pil_img = Image.open(BytesIO(img_data))
            except Exception:
                logging.warning(f"Invalid image data for {roster_name}")
                continue
            
            try:
                from rembg import remove
                import threading
                lock = threading.Lock()
                with lock:
                    logging.info(f"Removing background for {roster_name} with high-quality settings...")
                    result = remove(img_data, post_process_mask=False, alpha_matting=False)
                    pil_img = Image.open(BytesIO(result)).convert('RGBA')
            except Exception as e:
                logging.warning(f"Background removal failed for {roster_name}: {e}")
                pil_img = pil_img.convert('RGBA')
            
            # Keep images at high resolution for video board quality
            # Only resize if extremely large (> 2000px) to avoid memory issues
            max_height = 2000
            if pil_img.height > max_height:
                ratio = max_height / pil_img.height
                new_width = int(pil_img.width * ratio)
                logging.info(f"Resized from {pil_img.width}x{pil_img.height} to {new_width}x{max_height} (capping extremely large image)")
                pil_img = pil_img.resize((new_width, max_height), Image.LANCZOS)
            
            os.makedirs(output_dir, exist_ok=True)
            
            clean_school = re.sub(r'[^\w\s]', '', school_name).strip()
            clean_school = re.sub(r'\s+', '_', clean_school)
            parts = roster_name.split()
            first_name = parts[0] if parts else ''
            last_name = ' '.join(parts[1:]) if len(parts) >= 2 else ''
            clean_first = re.sub(r'[^\w]', '', first_name)
            clean_last = re.sub(r'[^\w]', '', last_name)
            
            filename = f"{clean_school}_{clean_first}_{clean_last}.png"
            filepath = os.path.join(output_dir, filename)
            
            pil_img.save(filepath, 'PNG', optimize=True)
            logging.info(f"Saved bio-page headshot: {filepath}")
            matched.append(roster_name)
            
            gc.collect()
            
        except Exception as e:
            logging.error(f"Error processing bio page for {roster_name}: {e}")
            continue
    
    unmatched = []
    for target in target_names:
        found = False
        for m in matched:
            if name_matches(m, target):
                found = True
                break
        if not found:
            unmatched.append(target)
    
    logging.info(f"Bio-page extraction results for {school_name}: {len(matched)} downloaded, {len(unmatched)} not found")
    return matched, unmatched


def scrape_roster_for_athletes(url, target_names, output_dir, school_name):
    from sidearm_pattern_extractor import SideArmExtractor
    from urllib.parse import urlparse
    
    logging.info(f"Scraping roster for {school_name}: {url}")
    logging.info(f"Looking for {len(target_names)} athletes: {target_names}")
    
    domain = urlparse(url).netloc.lower()
    
    prestosports_domains = [
        'goregispride.com', 'gosuffolkrams.com', 'wentworthathletics.com',
        'westfieldstateowls.com', 'aicyellowjackets.com', 'laserpride.lasell.edu',
        'ecgulls.com', 'leeuflames.com'
    ]
    
    html_content = None
    is_presto = any(pd in domain for pd in prestosports_domains)
    
    if is_presto:
        logging.info(f"PrestoSports domain detected - using Selenium")
        try:
            from fast_scraper import setup_headless_driver, fast_scroll_page
            driver = setup_headless_driver()
            if driver:
                driver.get(url)
                time.sleep(4)
                fast_scroll_page(driver)
                html_content = driver.page_source
                driver.quit()
        except Exception as e:
            logging.error(f"Selenium failed for {url}: {e}")
    
    extractor = SideArmExtractor(url, output_dir, html_content=html_content)
    all_athletes = extractor.extract_and_download_all()
    
    real_count = len([a for a in (all_athletes or []) if a.get('name') and a.get('image_url') and 'dummy' not in a.get('image_url', '').lower()])
    if real_count < 5:
        logging.info(f"Only {real_count} real athletes found, trying Selenium fallback...")
        if not is_presto and not html_content:
            try:
                from fast_scraper import setup_headless_driver, fast_scroll_page
                driver = setup_headless_driver()
                if driver:
                    driver.get(url)
                    time.sleep(4)
                    fast_scroll_page(driver)
                    html_content = driver.page_source
                    driver.quit()
                    
                    extractor2 = SideArmExtractor(url, output_dir, html_content=html_content)
                    all_athletes = extractor2.extract_and_download_all()
            except Exception as e:
                logging.error(f"Selenium fallback failed: {e}")
    
    if not all_athletes:
        logging.info(f"No athletes with images found, trying bio-page extraction for {school_name}")
        matched, unmatched = try_bio_page_extraction(url, target_names, output_dir, school_name, html_content)
        if matched:
            return matched, unmatched
        logging.warning(f"No athletes found on roster page for {school_name}")
        return [], list(target_names)
    
    logging.info(f"Found {len(all_athletes)} total athletes on roster, filtering for {len(target_names)} targets")
    
    athletes = []
    matched_targets = set()
    for athlete in all_athletes:
        roster_name = athlete.get('name', '')
        for target in target_names:
            if target.lower() in matched_targets:
                continue
            if name_matches(roster_name, target):
                athletes.append(athlete)
                matched_targets.add(target.lower())
                logging.info(f"MATCH: roster '{roster_name}' matches target '{target}'")
                break
    
    logging.info(f"Filtered to {len(athletes)} matching athletes")
    
    # If no athletes matched via roster extraction, fall back to bio-page extraction
    if len(athletes) == 0:
        logging.info(f"No athletes matched from roster extraction, trying bio-page extraction for {school_name}")
        matched, unmatched = try_bio_page_extraction(url, target_names, output_dir, school_name, html_content)
        if matched:
            return matched, unmatched
        logging.warning(f"Bio-page extraction also found no matches for {school_name}")
        return [], list(target_names)
    
    matched = []
    downloaded = 0
    
    import concurrent.futures
    
    def download_one(athlete):
        name = athlete.get('name', '')
        result = extractor.download_athlete_image(athlete)
        if result:
            src_filename = re.sub(r'[^\w\-\.\s]', '', name)
            src_filename = src_filename.replace('_', ' ')
            src_filename = re.sub(r'\s+', ' ', src_filename).strip()
            
            src_path_png = os.path.join(output_dir, f"{src_filename}.png")
            src_path_jpg = os.path.join(output_dir, f"{src_filename}.jpg")
            
            clean_school = re.sub(r'[^\w\s]', '', school_name).strip()
            clean_school = re.sub(r'\s+', '_', clean_school)
            
            first_name, last_name = '', ''
            parts = name.split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = ' '.join(parts[1:])
            elif parts:
                first_name = parts[0]
            
            clean_first = re.sub(r'[^\w]', '', first_name)
            clean_last = re.sub(r'[^\w]', '', last_name)
            
            new_filename = f"{clean_school}_{clean_first}_{clean_last}.png"
            new_path = os.path.join(output_dir, new_filename)
            
            for src_path in [src_path_png, src_path_jpg]:
                if os.path.exists(src_path) and src_path != new_path:
                    try:
                        os.rename(src_path, new_path)
                        logging.info(f"Renamed: {src_path} -> {new_path}")
                    except Exception as e:
                        logging.warning(f"Rename failed: {e}")
                    break
            
            return name
        return None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(download_one, a): a for a in athletes}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                matched.append(result)
                downloaded += 1
    
    gc.collect()
    
    unmatched = []
    for target in target_names:
        found = False
        for m in matched:
            if name_matches(m, target):
                found = True
                break
        if not found:
            unmatched.append(target)
    
    # If downloads failed for all matched athletes, try bio-page extraction
    if downloaded == 0 and len(athletes) > 0:
        logging.info(f"All {len(athletes)} image downloads failed, trying bio-page extraction for {school_name}")
        bio_matched, bio_unmatched = try_bio_page_extraction(url, target_names, output_dir, school_name, html_content)
        if bio_matched:
            return bio_matched, bio_unmatched
    
    logging.info(f"Results for {school_name}: {downloaded} downloaded, {len(unmatched)} not found")
    
    return matched, unmatched


targeted_progress = {
    'status': 'idle',
    'total_athletes': 0,
    'total_schools': 0,
    'processed_schools': 0,
    'matched_athletes': 0,
    'unmatched_athletes': [],
    'school_results': {},
    'current_school': '',
    'completed': False,
    'zip_ready': False,
    'errors': [],
    'sport': 'tf'
}


def reset_targeted_progress():
    global targeted_progress
    targeted_progress = {
        'status': 'idle',
        'total_athletes': 0,
        'total_schools': 0,
        'processed_schools': 0,
        'matched_athletes': 0,
        'unmatched_athletes': [],
        'school_results': {},
        'current_school': '',
        'completed': False,
        'zip_ready': False,
        'errors': [],
        'sport': 'tf'
    }


def run_targeted_scrape(csv_content, sport='tf', output_dir='athletes/targeted'):
    global targeted_progress
    
    reset_targeted_progress()
    targeted_progress['status'] = 'parsing'
    targeted_progress['sport'] = sport
    
    os.makedirs(output_dir, exist_ok=True)
    
    existing_files = set()
    if os.path.exists(output_dir):
        for f in os.listdir(output_dir):
            if f.endswith('.png'):
                existing_files.add(f)
    logging.info(f"Found {len(existing_files)} existing images in {output_dir} - will skip already-downloaded athletes")
    
    try:
        athletes_by_school, all_athletes = parse_meet_csv(csv_content)
        
        if not athletes_by_school:
            targeted_progress['status'] = 'error'
            targeted_progress['errors'].append('No athletes found in CSV. Check format: School, Name')
            targeted_progress['completed'] = True
            return
        
        targeted_progress['total_athletes'] = len(all_athletes)
        targeted_progress['total_schools'] = len(athletes_by_school)
        
        logging.info(f"Parsed {len(all_athletes)} athletes from {len(athletes_by_school)} schools")
        
        db = load_roster_database()
        targeted_progress['status'] = 'discovering'
        
        # Initialize all school results as pending
        for school, athletes in athletes_by_school.items():
            targeted_progress['school_results'][school] = {
                'status': 'discovering',
                'matched': 0,
                'total': len(athletes),
                'unmatched': [],
                'db_school': None
            }
        
        # Parallel URL discovery - much faster than sequential
        school_db_map = {}
        school_list = list(athletes_by_school.keys())
        logging.info(f"Starting parallel URL discovery for {len(school_list)} schools...")
        
        def _discover_urls(school_name):
            return school_name, get_roster_urls_for_school(school_name, db, sport)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(_discover_urls, school): school for school in school_list}
            discovered = 0
            for future in as_completed(futures):
                school_name, (urls, db_school) = future.result()
                school_db_map[school_name] = (urls, db_school)
                discovered += 1
                targeted_progress['school_results'][school_name]['db_school'] = db_school if db_school and db_school != school_name else None
                targeted_progress['school_results'][school_name]['status'] = 'pending' if urls else 'no_url'
                if discovered % 10 == 0:
                    logging.info(f"URL discovery progress: {discovered}/{len(school_list)} schools")
        
        logging.info(f"URL discovery complete: {sum(1 for v in school_db_map.values() if v[0])}/{len(school_list)} schools have roster URLs")
        targeted_progress['status'] = 'scraping'
        
        for school, athletes in athletes_by_school.items():
            targeted_progress['current_school'] = school
            targeted_progress['school_results'][school]['status'] = 'processing'
            
            urls, db_school = school_db_map[school]
            
            if not urls:
                msg = f"No roster URL found for '{school}'"
                logging.warning(msg)
                targeted_progress['errors'].append(msg)
                targeted_progress['unmatched_athletes'].extend(
                    [{'school': school, 'name': a} for a in athletes]
                )
                targeted_progress['school_results'][school] = {
                    'status': 'no_url',
                    'matched': 0,
                    'total': len(athletes),
                    'unmatched': athletes
                }
                targeted_progress['processed_schools'] += 1
                continue
            
            logging.info(f"Found roster URL(s) for {school} (matched: {db_school}): {urls}")
            
            all_matched = []
            all_unmatched = []
            school_label = (db_school or school).replace(' ', '_').replace("'", "").replace(".", "")
            for athlete_name in athletes:
                name_part = athlete_name.replace(' ', '_').replace("'", "").replace("-", "")
                expected_file = f"{school_label}_{name_part}.png"
                if any(f.replace("-","").replace("'","") == expected_file.replace("-","").replace("'","") for f in existing_files):
                    all_matched.append(athlete_name)
                    logging.info(f"SKIP (already downloaded): {school_label} {athlete_name}")
                else:
                    all_unmatched.append(athlete_name)
            
            if all_matched and not all_unmatched:
                logging.info(f"All {len(all_matched)} athletes already downloaded for {school}")
                targeted_progress['matched_athletes'] += len(all_matched)
                targeted_progress['school_results'][school] = {
                    'status': 'done',
                    'db_school': db_school,
                    'matched': len(all_matched),
                    'total': len(athletes),
                    'matched_names': all_matched,
                    'unmatched': [],
                    'reason': None
                }
                targeted_progress['processed_schools'] += 1
                continue
            
            if all_matched:
                logging.info(f"Skipping {len(all_matched)} already-downloaded athletes for {school}, scraping {len(all_unmatched)} remaining")
            
            scrape_errors = []
            for roster_url in urls:
                if not all_unmatched:
                    break
                    
                try:
                    matched, unmatched = scrape_roster_for_athletes(
                        roster_url, all_unmatched, output_dir, db_school or school
                    )
                    all_matched.extend(matched)
                    all_unmatched = unmatched
                except Exception as e:
                    logging.error(f"Error scraping {roster_url}: {e}")
                    targeted_progress['errors'].append(f"Error scraping {school} ({roster_url}): {str(e)}")
                    scrape_errors.append(str(e)[:80])
            
            targeted_progress['matched_athletes'] += len(all_matched)
            targeted_progress['unmatched_athletes'].extend(
                [{'school': school, 'name': a} for a in all_unmatched]
            )
            
            reason = None
            if all_unmatched:
                reasons = []
                if scrape_errors:
                    reasons.append(f"Roster page error: {scrape_errors[0]}")
                elif len(all_matched) == 0 and len(athletes) > 0:
                    reasons.append("Could not extract any athlete data from roster page")
                else:
                    reasons.append(f"{len(all_unmatched)} athlete(s) not found on roster or image download failed")
                reason = "; ".join(reasons)
            
            targeted_progress['school_results'][school] = {
                'status': 'done',
                'db_school': db_school,
                'matched': len(all_matched),
                'total': len(athletes),
                'matched_names': all_matched,
                'unmatched': all_unmatched,
                'reason': reason
            }
            targeted_progress['processed_schools'] += 1
            
            gc.collect()
        
        targeted_progress['status'] = 'complete'
        targeted_progress['completed'] = True
        targeted_progress['zip_ready'] = True
        
        total = targeted_progress['total_athletes']
        matched = targeted_progress['matched_athletes']
        logging.info(f"Targeted scrape complete: {matched}/{total} athletes found across {len(athletes_by_school)} schools")
        
    except Exception as e:
        logging.error(f"Targeted scrape error: {e}", exc_info=True)
        targeted_progress['status'] = 'error'
        targeted_progress['errors'].append(str(e))
        targeted_progress['completed'] = True
