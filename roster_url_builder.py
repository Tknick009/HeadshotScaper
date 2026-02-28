#!/usr/bin/env python3
"""
Build roster URLs for all NCAA schools using TFRRS data and common patterns.
Much faster than scraping NCAA pages individually.
"""
import requests
from bs4 import BeautifulSoup
import csv
import re
import json
import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

logger = logging.getLogger(__name__)

# URL cache file path - persists discovered URLs across runs
URL_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'url_cache.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Known athletic domain mappings - comprehensive coverage for NCAA D1/D2/D3
KNOWN_DOMAINS = {
    # === SEC ===
    'Alabama': 'rolltide.com',
    'Arkansas': 'arkansasrazorbacks.com',
    'Auburn': 'auburntigers.com',
    'Florida': 'floridagators.com',
    'Georgia': 'georgiadogs.com',
    'Kentucky': 'ukathletics.com',
    'LSU': 'lsusports.net',
    'Mississippi State': 'hailstate.com',
    'Missouri': 'mutigers.com',
    'Oklahoma': 'soonersports.com',
    'Ole Miss': 'olemisssports.com',
    'South Carolina': 'gamecocksonline.com',
    'Tennessee': 'utsports.com',
    'Texas': 'texassports.com',
    'Texas A&M': '12thman.com',
    'Vanderbilt': 'vucommodores.com',
    # === Big Ten ===
    'Illinois': 'fightingillini.com',
    'Indiana': 'iuhoosiers.com',
    'Iowa': 'hawkeyesports.com',
    'Maryland': 'umterps.com',
    'Michigan': 'mgoblue.com',
    'Michigan State': 'msuspartans.com',
    'Minnesota': 'gophersports.com',
    'Nebraska': 'huskers.com',
    'Northwestern': 'nusports.com',
    'Ohio State': 'ohiostatebuckeyes.com',
    'Oregon': 'goducks.com',
    'Penn State': 'gopsusports.com',
    'Purdue': 'purduesports.com',
    'Rutgers': 'scarletknights.com',
    'USC': 'usctrojans.com',
    'UCLA': 'uclabruins.com',
    'Washington': 'gohuskies.com',
    'Wisconsin': 'uwbadgers.com',
    # === ACC ===
    'Boston College': 'bceagles.com',
    'California': 'calbears.com',
    'Clemson': 'clemsontigers.com',
    'Duke': 'goduke.com',
    'Florida State': 'seminoles.com',
    'Georgia Tech': 'ramblinwreck.com',
    'Louisville': 'gocards.com',
    'Miami': 'miamihurricanes.com',
    'Miami (FL)': 'miamihurricanes.com',
    'North Carolina': 'goheels.com',
    'NC State': 'gopack.com',
    'Notre Dame': 'und.com',
    'Pittsburgh': 'pittsburghpanthers.com',
    'SMU': 'smumustangs.com',
    'Stanford': 'gostanford.com',
    'Syracuse': 'cuse.com',
    'Virginia': 'virginiasports.com',
    'Virginia Tech': 'hokiesports.com',
    'Wake Forest': 'godeacs.com',
    # === Big 12 ===
    'Arizona': 'arizonawildcats.com',
    'Arizona State': 'thesundevils.com',
    'Baylor': 'baylorbears.com',
    'BYU': 'byucougars.com',
    'Cincinnati': 'gobearcats.com',
    'Colorado': 'cubuffs.com',
    'Houston': 'uhcougars.com',
    'Iowa State': 'cyclones.com',
    'Kansas': 'kuathletics.com',
    'Kansas State': 'kstatesports.com',
    'Oklahoma State': 'okstate.com',
    'TCU': 'gofrogs.com',
    'Texas Tech': 'texastech.com',
    'UCF': 'ucfknights.com',
    'Utah': 'utahutes.com',
    'West Virginia': 'wvusports.com',
    # === American / AAC ===
    'East Carolina': 'ecupirates.com',
    'Memphis': 'gotigersgo.com',
    'Navy': 'navysports.com',
    'North Texas': 'meangreensports.com',
    'Rice': 'riceowls.com',
    'South Florida': 'gousfbulls.com',
    'Temple': 'owlsports.com',
    'Tulane': 'tulanegreenwave.com',
    'Tulsa': 'tulsahurricane.com',
    'UAB': 'uabsports.com',
    'UTSA': 'goutsa.com',
    'Wichita State': 'goshockers.com',
    'Charlotte': 'charlotte49ers.com',
    'FAU': 'fausports.com',
    'FIU': 'fiusports.com',
    # === Mountain West ===
    'Air Force': 'goairforcefalcons.com',
    'Boise State': 'broncosports.com',
    'Colorado State': 'csurams.com',
    'Fresno State': 'gobulldogs.com',
    'Nevada': 'nevadawolfpack.com',
    'New Mexico': 'golobos.com',
    'San Diego State': 'goaztecs.com',
    'San Jose State': 'sjsuspartans.com',
    'UNLV': 'unlvrebels.com',
    'Utah State': 'utahstateaggies.com',
    'Wyoming': 'gowyo.com',
    # === Sun Belt ===
    'App State': 'appstatesports.com',
    'Appalachian State': 'appstatesports.com',
    'Arkansas State': 'astateredwolves.com',
    'Coastal Carolina': 'goccusports.com',
    'Georgia Southern': 'gseagles.com',
    'Georgia State': 'georgiastatesports.com',
    'James Madison': 'jmusports.com',
    'Louisiana': 'ragincajuns.com',
    'Marshall': 'herdzone.com',
    'Old Dominion': 'odusports.com',
    'South Alabama': 'usajaguars.com',
    'Southern Miss': 'southernmiss.com',
    'Texas State': 'txstatebobcats.com',
    'Troy': 'troytrojans.com',
    # === Conference USA ===
    'Liberty': 'libertyflames.com',
    'New Mexico State': 'nmstatesports.com',
    'Sam Houston': 'gobearkats.com',
    'Jacksonville State': 'jsugamecocksports.com',
    'Western Kentucky': 'wkusports.com',
    'UTEP': 'utepminers.com',
    'Middle Tennessee': 'goblueraiders.com',
    'Louisiana Tech': 'latechsports.com',
    # === Ivy League ===
    'Princeton': 'goprincetontigers.com',
    'Harvard': 'gocrimson.com',
    'Yale': 'yalebulldogs.com',
    'Columbia': 'gocolumbialions.com',
    'Cornell': 'cornellbigred.com',
    'Dartmouth': 'dartmouthsports.com',
    'Brown': 'brownbears.com',
    'Penn': 'pennathletics.com',
    # === Patriot League ===
    'Army West Point': 'goarmywestpoint.com',
    'Army': 'goarmywestpoint.com',
    'Colgate': 'gocolgateraiders.com',
    'Bucknell': 'bucknellbison.com',
    'Lafayette': 'goleopards.com',
    'Lehigh': 'lehighsports.com',
    'American': 'aueagles.com',
    'Loyola Maryland': 'loyolagreyhounds.com',
    'Loyola (Md.)': 'loyolagreyhounds.com',
    # === A-10 ===
    'Georgetown': 'guhoyas.com',
    'Villanova': 'villanova.com',
    'Providence': 'friars.com',
    'La Salle': 'goexplorers.com',
    'Saint Joseph\'s': 'sjuhawks.com',
    'Fordham': 'fordhamsports.com',
    'George Mason': 'gomason.com',
    'George Washington': 'gwsports.com',
    'VCU': 'vcuathletics.com',
    'Richmond': 'richmondspiders.com',
    'Dayton': 'daytonflyers.com',
    'Rhode Island': 'gorhody.com',
    'UMass Amherst': 'umassathletics.com',
    'UMass': 'umassathletics.com',
    # === Big East ===
    'Connecticut': 'uconnhuskies.com',
    'UConn': 'uconnhuskies.com',
    'Creighton': 'gocreighton.com',
    'DePaul': 'depaulbluedemons.com',
    'Marquette': 'gomarquette.com',
    'Seton Hall': 'shupirates.com',
    'St. John\'s': 'redstormsports.com',
    'Xavier': 'goxavier.com',
    'Butler': 'butlersports.com',
    # === Northeast / NEC ===
    'Northeastern': 'gonu.com',
    'Holy Cross': 'goholycross.com',
    'Stonehill': 'stonehillskyhawks.com',
    'Merrimack': 'merrimackathletics.com',
    'Central Connecticut': 'ccsuathletics.com',
    'CCSU': 'ccsuathletics.com',
    'Sacred Heart': 'sacredheartpioneers.com',
    'Fairleigh Dickinson': 'fduknights.com',
    'Long Island': 'liuathletics.com',
    'Mount St. Mary\'s': 'mountathletics.com',
    'St. Francis (PA)': 'sfuathletics.com',
    'Wagner': 'wagnerathletics.com',
    # === Northeast / CAA ===
    'Delaware': 'bluehens.com',
    'Drexel': 'drexeldragons.com',
    'Elon': 'elonphoenix.com',
    'Hofstra': 'gohofstra.com',
    'Monmouth': 'monmouthhawks.com',
    'Northeastern': 'gonu.com',
    'Stony Brook': 'stonybrookathletics.com',
    'Towson': 'towsontigers.com',
    'William & Mary': 'tribeathletics.com',
    'College of Charleston': 'cofcsports.com',
    'UNC Wilmington': 'uncwsports.com',
    'Hampton': 'hamptonsports.com',
    'Campbell': 'gocamels.com',
    # === MAAC / NE small ===
    'Iona': 'icgaels.com',
    'Manhattan': 'gojaspers.com',
    'Marist': 'goredfoxes.com',
    'Niagara': 'purpleeagles.com',
    'Quinnipiac': 'gobobcats.com',
    'Rider': 'gobroncs.com',
    'Siena': 'sienasaints.com',
    'Fairfield': 'fairfieldstags.com',
    # === America East ===
    'Albany': 'ualbanysports.com',
    'UAlbany': 'ualbanysports.com',
    'Binghamton': 'bubearcats.com',
    'Hartford': 'hartfordhawks.com',
    'Maine': 'goblackbears.com',
    'New Hampshire': 'unhwildcats.com',
    'UMBC': 'umbcretrievers.com',
    'UMass Lowell': 'goriverhawks.com',
    'Vermont': 'uvmathletics.com',
    # === NE10 / D2 Northeast ===
    'Southern Connecticut': 'southernctowls.com',
    'SCSU': 'southernctowls.com',
    'Assumption': 'assumptiongreyhounds.com',
    'Bentley': 'bentleyfalcons.com',
    'American International': 'aicyellowjackets.com',
    'AIC': 'aicyellowjackets.com',
    'SNHU': 'snhupenmen.com',
    'Saint Rose': 'stroseathletics.com',
    'Saint Michael\'s': 'smcathletics.com',
    'Stonehill': 'stonehillskyhawks.com',
    'Le Moyne': 'lemoynedolphins.com',
    'Adelphi': 'aupanthers.com',
    'Pace': 'paceuathletics.com',
    'Saint Anselm': 'saintanselmhawks.com',
    'Franklin Pierce': 'fpuravens.com',
    # === NESCAC ===
    'Williams': 'ephsports.williams.edu',
    'Amherst': 'athletics.amherst.edu',
    'Middlebury': 'athletics.middlebury.edu',
    'Bowdoin': 'athletics.bowdoin.edu',
    'Bates': 'gobatesbobcats.com',
    'Colby': 'colbyathletics.com',
    'Tufts': 'gotuftsjumbos.com',
    'Wesleyan': 'athletics.wesleyan.edu',
    'Connecticut College': 'camelathletics.com',
    'Trinity (Conn.)': 'bantamsports.com',
    'Hamilton': 'athletics.hamilton.edu',
    # === NEWMAC / UAA / D3 ===
    'MIT': 'mitathletics.com',
    'Carnegie Mellon': 'tartanathletics.com',
    'RIT': 'ritathletics.com',
    'Rochester': 'uofrathletics.com',
    'NYU': 'gonyuathletics.com',
    'Brandeis': 'brandeisjudges.com',
    'Haverford': 'haverfordathletics.com',
    'Swarthmore': 'athletics.swarthmore.edu',
    'Johns Hopkins': 'hopkinssports.com',
    'Emory': 'emoryathletics.com',
    'WashU': 'bearsports.wustl.edu',
    'Washington University': 'bearsports.wustl.edu',
    'Chicago': 'athletics.uchicago.edu',
    'Case Western': 'athletics.case.edu',
    'RPI': 'rpiathletics.com',
    'WPI': 'athletics.wpi.edu',
    'Coast Guard': 'uscga.edu/athletics',
    'Merchant Marine': 'usmmasports.com',
    'Suffolk': 'suffolkrams.com',
    'Smith College': 'smithpioneers.com',
    'Wellesley': 'wellesleyblue.com',
    'Mount Holyoke': 'lyonsathletics.com',
    # === Other notable ===
    'Boston University': 'goterriers.com',
    'Gonzaga': 'gozags.com',
    'Loyola Chicago': 'loyolaramblers.com',
    'Saint Louis': 'slubillikens.com',
    'Valparaiso': 'valpoathletics.com',
    'Drake': 'godrakebulldogs.com',
    'Northern Iowa': 'unipanthers.com',
    'Indiana State': 'gosycamores.com',
    'Southern Illinois': 'siusalukis.com',
    'Youngstown State': 'ysusports.com',
    'North Carolina A&T': 'ncataggies.com',
    'Howard': 'hubison.com',
    'Morgan State': 'morganstatebears.com',
    'Norfolk State': 'nsuspartans.com',
    'Coppin State': 'coppinstatesports.com',
    'Delaware State': 'dsuhornets.com',
    'Kennesaw State': 'ksuowls.com',
    'Lipscomb': 'lipscombsports.com',
    'Bellarmine': 'athletics.bellarmine.edu',
    'North Florida': 'unfospreys.com',
    'Stetson': 'gohatters.com',
    'Eastern Kentucky': 'ekusports.com',
    'Morehead State': 'msueagles.com',
    'Southeast Missouri': 'gosoutheast.com',
    'Eastern Illinois': 'eiupanthers.com',
    'Murray State': 'goracers.com',
    'Austin Peay': 'letsgopeay.com',
    'Tennessee Tech': 'tntech.com',
    'Chattanooga': 'gomocs.com',
    'Furman': 'furmanpaladins.com',
    'Samford': 'samfordsports.com',
    'The Citadel': 'citadelsports.com',
    'Wofford': 'woffordterriers.com',
    'Western Carolina': 'catamountsports.com',
    'High Point': 'highpointpanthers.com',
    'Radford': 'radfordathletics.com',
    'UNC Asheville': 'uncabulldogs.com',
    'Winthrop': 'winthropeagles.com',
    'Presbyterian': 'gobluehose.com',
    'Gardner-Webb': 'gwusports.com',
    'Charleston Southern': 'csusports.com',
}

# Common URL patterns for roster pages (ordered by likelihood)
ROSTER_PATTERNS = [
    '/sports/mens-cross-country/roster',
    '/sports/womens-cross-country/roster',
    '/sports/mens-track-and-field/roster',
    '/sports/womens-track-and-field/roster',
    '/sports/track-and-field/roster',
    '/sports/cross-country/roster',
    '/sports/mxc/roster',
    '/sports/wxc/roster',
    '/sports/mtf/roster',
    '/sports/wtf/roster',
    '/roster.aspx?path=mxc',
    '/roster.aspx?path=wxc',
    '/roster.aspx?path=mtrack',
    '/roster.aspx?path=wtrack',
]

# School-specific URL overrides for sites that use non-standard patterns
# These were discovered through live testing and don't follow SideArm conventions
SCHOOL_ROSTER_OVERRIDES = {
    'Arkansas': {
        'mtf': 'https://arkansasrazorbacks.com/sport/m-track/roster/',
        'wtf': 'https://arkansasrazorbacks.com/sport/w-track/roster/',
        'mxc': 'https://arkansasrazorbacks.com/sport/m-xc/roster/',
        'wxc': 'https://arkansasrazorbacks.com/sport/w-xc/roster/',
    },
    'Auburn': {
        'mtf': 'https://auburntigers.com/sports/xctrack/roster',
        'wtf': 'https://auburntigers.com/sports/xctrack/roster',
        'mxc': 'https://auburntigers.com/sports/xctrack/roster',
        'wxc': 'https://auburntigers.com/sports/xctrack/roster',
    },
    'Clemson': {
        'mtf': 'https://clemsontigers.com/team/mens-track-and-field/roster',
        'wtf': 'https://clemsontigers.com/team/womens-track-and-field/roster',
        'mxc': 'https://clemsontigers.com/team/mens-cross-country/roster',
        'wxc': 'https://clemsontigers.com/team/womens-cross-country/roster',
    },
    'Penn State': {
        'mxc': 'https://gopsusports.com/sports/cross-country/roster',
        'wxc': 'https://gopsusports.com/sports/cross-country/roster',
    },
    'Iowa': {
        'mtf': 'https://hawkeyesports.com/roster.aspx?rp_id=4818',
        'wtf': 'https://hawkeyesports.com/roster.aspx?rp_id=4819',
    },
    'Old Dominion': {
        'mtf': 'https://odusports.com/roster.aspx?rp_id=14',
        'wtf': 'https://odusports.com/roster.aspx?rp_id=13',
    },
    'Chattanooga': {
        'mtf': 'https://gomocs.com/sports/track-and-field/roster',
        'wtf': 'https://gomocs.com/sports/track-and-field/roster',
        'mxc': 'https://gomocs.com/sports/track-and-field/roster',
        'wxc': 'https://gomocs.com/sports/track-and-field/roster',
    },
}


def _load_url_cache():
    """Load the URL cache from disk."""
    try:
        if os.path.exists(URL_CACHE_FILE):
            with open(URL_CACHE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load URL cache: {e}")
    return {}


def _save_url_cache(cache):
    """Save the URL cache to disk."""
    try:
        with open(URL_CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save URL cache: {e}")


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
    # Check known domains first (case-insensitive)
    if school_name in KNOWN_DOMAINS:
        return KNOWN_DOMAINS[school_name]
    
    # Try case-insensitive lookup
    lower_name = school_name.lower()
    for known, domain in KNOWN_DOMAINS.items():
        if known.lower() == lower_name:
            return domain
    
    # Generate guesses
    name = re.sub(r'[^a-z\s]', '', lower_name)
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
            f"{words[0]}sports.com",
        ])
        
        # Try abbreviations
        if len(words) >= 2:
            abbrev = ''.join(w[0] for w in words)
            guesses.extend([
                f"go{abbrev}.com",
                f"{abbrev}sports.com",
                f"{abbrev}athletics.com",
            ])
    
    return guesses


def check_url_exists(url, timeout=8):
    """Check if a URL exists and returns roster-like content."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if response.status_code != 200:
            return False
        text = response.text.lower()
        # Check for roster signals to avoid false positives
        roster_signals = ['roster', 'player', 'athlete', 'name', 'hometown', 'height', 'class']
        signal_count = sum(1 for s in roster_signals if s in text)
        return signal_count >= 2 and len(text) > 2000
    except Exception:
        return False


def find_roster_url(school_name, sport='mxc'):
    """Find roster URL for a school and sport.
    
    Uses a multi-tier approach:
    1. Check URL cache for previously discovered URLs
    2. Check school-specific overrides for non-standard sites
    3. Try standard SideArm URL patterns against known/guessed domains
    4. Cache any discovered URLs for future runs
    """
    # 1. Check URL cache first
    cache = _load_url_cache()
    cache_key = f"{school_name}|{sport}"
    if cache_key in cache:
        cached_url = cache[cache_key]
        logger.info(f"Using cached URL for {school_name} ({sport}): {cached_url}")
        return cached_url
    
    # 2. Check school-specific overrides
    if school_name in SCHOOL_ROSTER_OVERRIDES:
        overrides = SCHOOL_ROSTER_OVERRIDES[school_name]
        if sport in overrides:
            url = overrides[sport]
            logger.info(f"Using override URL for {school_name} ({sport}): {url}")
            # Cache it
            cache[cache_key] = url
            _save_url_cache(cache)
            return url
    
    # Also check overrides with case-insensitive matching
    for override_school, overrides in SCHOOL_ROSTER_OVERRIDES.items():
        if override_school.lower() == school_name.lower() and sport in overrides:
            url = overrides[sport]
            cache[cache_key] = url
            _save_url_cache(cache)
            return url
    
    # 3. Build sport-specific URL patterns (comprehensive list)
    sport_patterns = {
        'mxc': [
            '/sports/mens-cross-country/roster',
            '/sports/cross-country/roster',
            '/sports/mxc/roster',
            '/sport/m-xc/roster/',
            '/roster.aspx?path=mxc',
        ],
        'wxc': [
            '/sports/womens-cross-country/roster',
            '/sports/cross-country/roster',
            '/sports/wxc/roster',
            '/sport/w-xc/roster/',
            '/roster.aspx?path=wxc',
        ],
        'mtf': [
            '/sports/mens-track-and-field/roster',
            '/sports/track-and-field/roster',
            '/sports/mens-track-field/roster',
            '/sports/mens-indoor-track-and-field/roster',
            '/sports/mens-outdoor-track-and-field/roster',
            '/sports/mtf/roster',
            '/sport/m-track/roster/',
            '/team/mens-track-and-field/roster',
            '/roster.aspx?path=mtrack',
            '/roster.aspx?rp_id=4818',
            '/sports/xctrack/roster',
        ],
        'wtf': [
            '/sports/womens-track-and-field/roster',
            '/sports/track-and-field/roster',
            '/sports/womens-track-field/roster',
            '/sports/womens-indoor-track-and-field/roster',
            '/sports/womens-outdoor-track-and-field/roster',
            '/sports/wtf/roster',
            '/sport/w-track/roster/',
            '/team/womens-track-and-field/roster',
            '/roster.aspx?path=wtrack',
            '/roster.aspx?rp_id=4819',
            '/sports/xctrack/roster',
        ],
    }
    
    patterns = sport_patterns.get(sport, sport_patterns['mxc'])
    
    # Get domain guesses
    domain = guess_domain(school_name)
    domains = [domain] if isinstance(domain, str) else domain
    
    for dom in domains[:6]:  # Limit to first 6 guesses
        base = f"https://{dom}" if not dom.startswith('http') else dom
        for pattern in patterns:
            url = f"{base.rstrip('/')}{pattern}"
            if check_url_exists(url):
                logger.info(f"Discovered roster URL for {school_name} ({sport}): {url}")
                # Cache the discovered URL
                cache[cache_key] = url
                _save_url_cache(cache)
                return url
    
    logger.warning(f"No roster URL found for {school_name} ({sport})")
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
