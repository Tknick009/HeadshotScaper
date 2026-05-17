"""
HeadshotScraper - Setup for editable install

Install in development/editable mode:
    pip install -e .

This lets you edit the code and see changes immediately without reinstalling.
After installing, you can run the app with:
    headshot-scraper
"""
from setuptools import setup, find_packages

setup(
    name='headshot-scraper',
    version='1.0.0',
    description='Scrape college athlete headshots from roster pages, match by CSV, remove backgrounds',
    author='tknick009',
    url='https://github.com/Tknick009/HeadshotScaper',
    py_modules=[
        'app',
        'launch',
        'targeted_scraper',
        'roster_url_builder',
        'fast_scraper',
        'sidearm_pattern_extractor',
        'modern_scraper',
        'utils',
    ],
    install_requires=[
        'flask>=2.3.0',
        'requests>=2.31.0',
        'beautifulsoup4>=4.12.0',
        'selenium>=4.15.0',
        'webdriver-manager>=4.0.0',
        'Pillow>=10.0.0',
        'rembg>=2.0.50',
        'onnxruntime>=1.16.0',
        'numpy>=1.24.0',
        'tqdm>=4.65.0',
        'rapidfuzz>=3.5.0',
    ],
    entry_points={
        'console_scripts': [
            'headshot-scraper=launch:main',
        ],
    },
    python_requires='>=3.9',
    include_package_data=True,
    package_data={
        '': ['templates/*.html', 'roster_url_database.json'],
    },
)
