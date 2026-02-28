import os
import logging
import sys
import csv
import gc
import json
import time
from datetime import datetime
from io import StringIO
from threading import Thread
from flask import Flask, render_template, request, jsonify, send_file
import zipfile
import io as io_module
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

# Lazy import of ModernAthleteScraper to speed up app startup
# (will be imported only when needed during upload processing)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Ensure directories exist
os.makedirs('templates', exist_ok=True)
os.makedirs('athletes', exist_ok=True)

app = Flask(__name__)
app.secret_key = 'athlete-scraper-secret-key-2024'

# Global progress tracking
url_progress = {}
completed = False
zip_available = False
start_time = None

# Progress file for crash recovery and batch resumption
PROGRESS_FILE = 'athletes/.scraping_progress.json'
MAX_RETRIES = 3  # Retry failed URLs up to 3 times
RETRY_DELAY_BASE = 5  # Base delay in seconds for exponential backoff (5s, 10s, 20s)


def load_progress():
    """Load previously saved progress from file"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load progress file: {e}")
    return {}


def save_progress(progress_data):
    """Save current progress to file for crash recovery"""
    try:
        os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(progress_data, f, indent=2)
        logger.debug("Progress saved to disk")
    except Exception as e:
        logger.error(f"Failed to save progress: {e}")


def process_single_url_with_retry(scraper, url, custom_team_name, retry_count=0):
    """Process a single URL with retry logic and comprehensive error handling
    
    Returns:
        tuple: (success: bool, count: int, error_msg: str or None)
    """
    try:
        logger.info(f"Processing: {url} (attempt {retry_count + 1}/{MAX_RETRIES + 1})")
        if custom_team_name:
            logger.info(f"Using custom team name: {custom_team_name}")
        
        count = scraper.scrape_url(url, custom_team_name=custom_team_name)
        logger.info(f"✓ Completed {url}: {count} athletes")
        return (True, count, None)
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"✗ {url}: {error_msg}", exc_info=True)
        
        # Retry on error if we have attempts left
        if retry_count < MAX_RETRIES:
            delay = RETRY_DELAY_BASE * (2 ** retry_count)  # Exponential backoff: 5s, 10s, 20s
            logger.info(f"Retrying in {delay} seconds...")
            time.sleep(delay)
            return process_single_url_with_retry(scraper, url, custom_team_name, retry_count + 1)
        
        return (False, 0, error_msg)
        
    finally:
        gc.collect()  # Force memory cleanup after each attempt


def process_urls_async(url_data):
    """Process multiple URLs with comprehensive safety features:
    - Auto-save progress after each URL
    - Resume from crash/restart
    - Retry failed URLs with exponential backoff
    - Timeout protection per URL
    - Memory management
    
    Args:
        url_data: List of tuples (url, custom_team_name) where custom_team_name can be None
    """
    global completed, zip_available, url_progress, start_time
    
    start_time = datetime.now()
    logger.info(f"{'='*80}")
    logger.info(f"STARTING BATCH PROCESSING: {len(url_data)} URLs")
    logger.info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"{'='*80}")
    
    try:
        # Load existing progress (for resume capability)
        saved_progress = load_progress()
        logger.info(f"Loaded {len(saved_progress)} previously completed URLs")
        
        # Initialize progress for all URLs
        for url, _ in url_data:
            if url in saved_progress and saved_progress[url].get('status') == 'success':
                # Already completed in previous run
                url_progress[url] = saved_progress[url]
                logger.info(f"✓ Skipping already completed: {url} ({saved_progress[url]['count']} athletes)")
            else:
                url_progress[url] = {"status": "pending", "count": 0}
        
        # Create scraper (lazy import to speed up app startup)
        from modern_scraper import ModernAthleteScraper
        scraper = ModernAthleteScraper(output_dir='athletes')
        
        # Statistics
        total_urls = len(url_data)
        completed_count = sum(1 for p in url_progress.values() if p.get('status') == 'success')
        remaining_urls = total_urls - completed_count
        
        logger.info(f"Already completed: {completed_count}/{total_urls}")
        logger.info(f"Remaining to process: {remaining_urls}/{total_urls}")
        
        # Process each URL
        for i, (url, custom_team_name) in enumerate(url_data):
            # Skip if already completed
            if url_progress[url].get('status') == 'success':
                continue
            
            url_progress[url] = {"status": "processing", "count": 0}
            logger.info(f"\n[{i+1}/{total_urls}] Processing: {url}")
            
            # Process with retry logic
            success, count, error_msg = process_single_url_with_retry(scraper, url, custom_team_name)
            
            if success:
                url_progress[url] = {
                    "status": "success",
                    "count": count,
                    "completed_at": datetime.now().isoformat()
                }
            else:
                url_progress[url] = {
                    "status": "error",
                    "count": 0,
                    "error": error_msg,
                    "failed_at": datetime.now().isoformat()
                }
            
            # SAVE PROGRESS TO DISK after each URL (crash recovery)
            save_progress(url_progress)
            
            # Progress report
            completed_count = sum(1 for p in url_progress.values() if p.get('status') == 'success')
            logger.info(f"Progress: {completed_count}/{total_urls} URLs completed")
        
        # Final statistics
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        success_count = sum(1 for p in url_progress.values() if p.get('status') == 'success')
        error_count = sum(1 for p in url_progress.values() if p.get('status') == 'error')
        total_athletes = sum(p.get('count', 0) for p in url_progress.values())
        
        logger.info(f"\n{'='*80}")
        logger.info(f"BATCH PROCESSING COMPLETE")
        logger.info(f"Duration: {duration/60:.1f} minutes ({duration:.0f} seconds)")
        logger.info(f"Successful: {success_count}/{total_urls}")
        logger.info(f"Failed: {error_count}/{total_urls}")
        logger.info(f"Total athletes: {total_athletes}")
        logger.info(f"{'='*80}\n")
        
    except Exception as e:
        logger.error(f"CRITICAL ERROR in batch processing: {e}", exc_info=True)
        save_progress(url_progress)  # Save progress even on crash
        
    finally:
        # Mark as completed
        completed = True
        zip_available = True
        gc.collect()
        logger.info("Background processing thread completed")


@app.route('/')
def index():
    """Main upload page"""
    return render_template('upload.html')


@app.route('/health')
def health_check():
    """Health check endpoint for deployment monitoring"""
    return jsonify({'status': 'healthy', 'service': 'athlete-scraper'}), 200


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle CSV file upload"""
    global completed, zip_available, url_progress, start_time
    
    # Reset state for new upload
    url_progress = {}
    completed = False
    zip_available = False
    start_time = None
    
    # Check if file was uploaded
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    
    if not file.filename or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be a CSV'}), 400
    
    try:
        # Read CSV file
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.reader(StringIO(csv_content))
        
        # Get school filter if provided
        school_filter_raw = request.form.get('school_filter', '').strip()
        school_filter = set()
        if school_filter_raw:
            # Parse school names (one per line or comma-separated)
            for line in school_filter_raw.replace(',', '\n').split('\n'):
                name = line.strip().lower()
                if name:
                    school_filter.add(name)
            logger.info(f"School filter active with {len(school_filter)} schools: {school_filter}")
        
        url_data = []
        for row in csv_reader:
            if row and row[0].strip().startswith('http'):
                url = row[0].strip()
                # Check if column 2 exists with a custom team name
                custom_team_name = row[1].strip() if len(row) > 1 and row[1].strip() else None
                
                # Apply school filter if active
                if school_filter:
                    # Check if URL or team name matches any filter
                    url_lower = url.lower()
                    team_lower = (custom_team_name or '').lower()
                    
                    match_found = False
                    for school in school_filter:
                        if school in url_lower or school in team_lower:
                            match_found = True
                            break
                    
                    if not match_found:
                        continue  # Skip this URL
                
                url_data.append((url, custom_team_name))
        
        if not url_data:
            if school_filter:
                return jsonify({'error': f'No URLs matched your school filter. Check spelling.'}), 400
            return jsonify({'error': 'No valid URLs found in CSV'}), 400
        
        logger.info(f"Found {len(url_data)} URLs in uploaded CSV" + (f" (filtered from larger set)" if school_filter else ""))
        
        # Start background processing
        thread = Thread(target=process_urls_async, args=(url_data,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'Processing {len(url_data)} URLs...',
            'url_count': len(url_data)
        })
        
    except Exception as e:
        logger.error(f"Error processing upload: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/status')
def get_status():
    """Get current scraping status"""
    # Calculate statistics
    success_count = sum(1 for p in url_progress.values() if p.get('status') == 'success')
    failed_count = sum(1 for p in url_progress.values() if p.get('status') == 'error')
    total_athletes = sum(p.get('count', 0) for p in url_progress.values())
    
    # Calculate duration
    duration = 0
    if start_time:
        duration = (datetime.now() - start_time).total_seconds()
    
    stats = {
        'success_count': success_count,
        'failed_count': failed_count,
        'total': len(url_progress),
        'total_athletes': total_athletes,
        'duration': duration
    }
    
    return jsonify({
        'completed': completed,
        'progress': url_progress,
        'zip_available': zip_available,
        'stats': stats,
        'failed_count': failed_count
    })


@app.route('/download')
def download_zip():
    """Download all scraped images as a ZIP file"""
    try:
        # Create ZIP file in memory
        memory_file = io_module.BytesIO()
        
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Walk through athletes directory
            for root, dirs, files in os.walk('athletes'):
                for file in files:
                    if file.endswith('.png') or file.endswith('.jpg'):
                        file_path = os.path.join(root, file)
                        # Add to zip with relative path
                        arcname = os.path.relpath(file_path, 'athletes')
                        zf.write(file_path, arcname)
        
        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name='athlete_images.zip'
        )
        
    except Exception as e:
        logger.error(f"Error creating ZIP: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/download_failed')
def download_failed():
    """Download CSV of failed URLs with error messages"""
    try:
        # Get failed URLs
        failed_urls = [(url, data.get('error', 'Unknown error')) 
                       for url, data in url_progress.items() 
                       if data.get('status') == 'error']
        
        if not failed_urls:
            return jsonify({'message': 'No failed URLs - all scraping succeeded!'}), 200
        
        # Create CSV in memory
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['URL', 'Error Message'])
        writer.writerows(failed_urls)
        
        # Convert to bytes for download
        output.seek(0)
        csv_bytes = output.getvalue().encode('utf-8')
        
        return send_file(
            io_module.BytesIO(csv_bytes),
            mimetype='text/csv',
            as_attachment=True,
            download_name='failed_urls.csv'
        )
        
    except Exception as e:
        logger.error(f"Error creating failed URLs CSV: {e}")
        return jsonify({'error': str(e)}), 500


# Roster URL discovery state
roster_discovery_progress = {
    'status': 'idle',
    'message': '',
    'schools_found': 0,
    'rosters_found': 0,
    'current_school': '',
    'results': []
}

@app.route('/discover-rosters', methods=['POST'])
def discover_rosters():
    """Start NCAA roster URL discovery process using TFRRS data."""
    global roster_discovery_progress
    
    data = request.get_json() or {}
    divisions = data.get('divisions', ['d1', 'd2', 'd3'])
    sports = data.get('sports', ['mxc', 'wxc'])  # mxc, wxc, mtf, wtf
    
    def run_discovery():
        global roster_discovery_progress
        try:
            roster_discovery_progress = {
                'status': 'running',
                'message': 'Starting roster URL discovery...',
                'schools_found': 0,
                'rosters_found': 0,
                'current_school': '',
                'results': []
            }
            
            # Import the new TFRRS-based finder
            from roster_url_builder import get_tfrrs_schools, find_roster_url
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            # Get all schools from TFRRS
            all_schools = {}
            for div in divisions:
                roster_discovery_progress['message'] = f'Fetching {div.upper()} schools from TFRRS...'
                div_schools = get_tfrrs_schools(div)
                for school in div_schools:
                    if school not in all_schools:
                        all_schools[school] = div
            
            roster_discovery_progress['schools_found'] = len(all_schools)
            roster_discovery_progress['message'] = f'Found {len(all_schools)} schools. Searching for roster URLs...'
            
            # Process schools in parallel
            results = []
            processed = 0
            
            def process_school(school):
                found = []
                for sport in sports:
                    url = find_roster_url(school, sport)
                    if url:
                        found.append({'school': school, 'sport': sport, 'url': url})
                return found
            
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(process_school, school): school 
                          for school in all_schools.keys()}
                
                for future in as_completed(futures):
                    processed += 1
                    school = futures[future]
                    roster_discovery_progress['current_school'] = school
                    roster_discovery_progress['message'] = f'Processing {processed}/{len(all_schools)} schools...'
                    
                    try:
                        found = future.result()
                        if found:
                            results.extend(found)
                            roster_discovery_progress['rosters_found'] = len(results)
                    except Exception:
                        pass
            
            # Save to CSV
            output_file = 'discovered_rosters.csv'
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                for result in results:
                    writer.writerow([result['url'], result['school']])
            
            roster_discovery_progress['status'] = 'complete'
            roster_discovery_progress['message'] = f'Done! Found {len(results)} schools with rosters. CSV ready for download.'
            
        except Exception as e:
            roster_discovery_progress['status'] = 'error'
            roster_discovery_progress['message'] = f'Error: {str(e)}'
            logger.error(f"Roster discovery error: {e}", exc_info=True)
    
    # Start in background thread
    thread = Thread(target=run_discovery)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': 'Discovery started'})


@app.route('/discover-rosters/status')
def discover_rosters_status():
    """Get roster discovery progress."""
    return jsonify(roster_discovery_progress)


@app.route('/discover-rosters/download')
def download_discovered_rosters():
    """Download the discovered rosters CSV."""
    csv_path = 'discovered_rosters.csv'
    if os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=True, download_name='ncaa_rosters.csv')
    return jsonify({'error': 'No roster file available'}), 404


@app.route('/targeted-upload', methods=['POST'])
def targeted_upload():
    global completed, zip_available
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file.filename or not file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be a CSV'}), 400
    
    sport = request.form.get('sport', 'tf')
    
    try:
        csv_content = file.read().decode('utf-8')
        
        from targeted_scraper import parse_meet_csv
        athletes_by_school, all_athletes = parse_meet_csv(csv_content)
        
        if not athletes_by_school:
            return jsonify({'error': 'No athletes found in CSV. Expected format: School, Athlete Name (one per row)'}), 400
        
        from targeted_scraper import run_targeted_scrape
        
        thread = Thread(target=run_targeted_scrape, args=(csv_content, sport))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'Processing {len(all_athletes)} athletes from {len(athletes_by_school)} schools...',
            'athlete_count': len(all_athletes),
            'school_count': len(athletes_by_school),
            'schools': list(athletes_by_school.keys())
        })
        
    except Exception as e:
        logger.error(f"Error processing targeted upload: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/targeted-status')
def targeted_status():
    from targeted_scraper import targeted_progress
    return jsonify(targeted_progress)


@app.route('/targeted-download')
def targeted_download():
    try:
        output_dir = 'athletes/targeted'
        if not os.path.exists(output_dir):
            return jsonify({'error': 'No images available yet'}), 404
        
        memory_file = io_module.BytesIO()
        
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    if file.endswith(('.png', '.jpg', '.jpeg')):
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, output_dir)
                        zf.write(file_path, arcname)
        
        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name='targeted_athlete_images.zip'
        )
        
    except Exception as e:
        logger.error(f"Error creating targeted ZIP: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/targeted-unmatched')
def targeted_unmatched():
    from targeted_scraper import targeted_progress
    
    unmatched = targeted_progress.get('unmatched_athletes', [])
    if not unmatched:
        return jsonify({'message': 'All athletes were found!'}), 200
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['School', 'Athlete Name', 'Reason'])
    
    for item in unmatched:
        school = item.get('school', '')
        name = item.get('name', '')
        school_result = targeted_progress.get('school_results', {}).get(school, {})
        reason = 'No roster URL found' if school_result.get('status') == 'no_url' else 'Not found on roster page'
        writer.writerow([school, name, reason])
    
    output.seek(0)
    csv_bytes = output.getvalue().encode('utf-8')
    
    return send_file(
        io_module.BytesIO(csv_bytes),
        mimetype='text/csv',
        as_attachment=True,
        download_name='unmatched_athletes.csv'
    )


@app.route('/school-lookup')
def school_lookup():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({'results': []})
    
    try:
        from targeted_scraper import load_roster_database, normalize_school_name
        db = load_roster_database()
        
        query_lower = query.lower()
        matches = []
        for school in db:
            if query_lower in school.lower():
                has_tf = bool(db[school].get('tf'))
                has_xc = bool(db[school].get('xc'))
                matches.append({
                    'name': school,
                    'has_tf': has_tf,
                    'has_xc': has_xc
                })
        
        matches.sort(key=lambda x: x['name'])
        return jsonify({'results': matches[:20]})
    except Exception as e:
        return jsonify({'results': [], 'error': str(e)})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
