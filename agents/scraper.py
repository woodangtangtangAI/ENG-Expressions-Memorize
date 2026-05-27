"""
Agent 1: Data Scraper
Scrapes text from multiple sources (news RSS, business articles, TV transcripts)
to find English expressions for the expression database.
"""

import requests
import feedparser
import random
import time
import re
from bs4 import BeautifulSoup
from utils.logger import setup_logger

logger = setup_logger('scraper')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

MAX_RETRIES = 3
BASE_BACKOFF = 2  # seconds


def _fetch_with_retry(url: str, timeout: int = 15) -> requests.Response | None:
    """Fetch a URL with exponential backoff retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            if response.status_code == 429:
                wait_time = BASE_BACKOFF ** (attempt + 1)
                logger.warning(f"Rate limited (429) on {url}. Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            response.raise_for_status()
            return response
        except requests.exceptions.ConnectionError as e:
            wait_time = BASE_BACKOFF ** (attempt + 1)
            logger.warning(f"Connection error on {url} (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Waiting {wait_time}s...")
            time.sleep(wait_time)
        except requests.exceptions.Timeout as e:
            wait_time = BASE_BACKOFF ** (attempt + 1)
            logger.warning(f"Timeout on {url} (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Waiting {wait_time}s...")
            time.sleep(wait_time)
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request error on {url} (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(BASE_BACKOFF ** (attempt + 1))
    logger.error(f"All {MAX_RETRIES} retries failed for {url}")
    return None


def _fetch_rss_articles(rss_urls: list) -> list[dict]:
    """
    Try each RSS URL in the list until one works.
    Extract title, description, and link from each feed entry.

    Args:
        rss_urls: List of RSS feed URLs to try.

    Returns:
        List of dicts with keys: title, description, url
    """
    articles = []

    for rss_url in rss_urls:
        try:
            logger.info(f"Trying RSS feed: {rss_url}")
            feed = feedparser.parse(rss_url)

            if feed.bozo and not feed.entries:
                logger.warning(f"RSS feed error for {rss_url}: {feed.bozo_exception}")
                continue

            if not feed.entries:
                logger.warning(f"No entries found in RSS feed: {rss_url}")
                continue

            for entry in feed.entries:
                title = entry.get('title', '')
                description = entry.get('description', entry.get('summary', ''))
                link = entry.get('link', '')

                # Clean HTML from description
                if description:
                    soup = BeautifulSoup(description, 'html.parser')
                    description = soup.get_text(strip=True)

                articles.append({
                    'title': title,
                    'description': description,
                    'url': link
                })

            logger.info(f"Successfully fetched {len(articles)} articles from {rss_url}")
            break  # Stop trying other URLs once one works

        except Exception as e:
            logger.warning(f"Failed to parse RSS feed {rss_url}: {e}")
            continue

    return articles


def _scrape_article_content(url: str) -> str:
    """
    Fetch and extract article body text from a news/business article URL.
    Uses site-specific selectors with generic fallbacks.

    Args:
        url: The article URL to scrape.

    Returns:
        Extracted article text, or empty string on failure.
    """
    try:
        response = _fetch_with_retry(url)
        if not response:
            return ''

        soup = BeautifulSoup(response.text, 'html.parser')
        text = ''

        # Site-specific selectors
        if 'cnbc.com' in url:
            selectors = ['div.ArticleBody-articleBody', 'div.RenderKeyPoints-list']
            for selector in selectors:
                element = soup.select_one(selector)
                if element:
                    text += element.get_text(separator=' ', strip=True) + ' '

        elif 'bbc.com' in url or 'bbc.co.uk' in url:
            selectors = ['article[role=main]', 'div.ssrcss-11r1m41-RichTextComponentWrapper']
            for selector in selectors:
                elements = soup.select(selector)
                for element in elements:
                    text += element.get_text(separator=' ', strip=True) + ' '

        elif 'hbr.org' in url:
            selectors = ['div.article-body', 'div.article-content']
            for selector in selectors:
                element = soup.select_one(selector)
                if element:
                    text += element.get_text(separator=' ', strip=True) + ' '

        # Generic fallback
        if not text.strip():
            article_tag = soup.find('article')
            if article_tag:
                text = article_tag.get_text(separator=' ', strip=True)
            else:
                paragraphs = soup.find_all('p')
                text = ' '.join(p.get_text(strip=True) for p in paragraphs)

        # Polite delay (1-2 seconds)
        time.sleep(random.uniform(1.0, 2.0))

        return text.strip()

    except Exception as e:
        logger.warning(f"Failed to scrape article content from {url}: {e}")
        return ''


def _scrape_friends_transcript(base_url: str, used_episodes: list) -> list[dict]:
    """
    Selects a random Friends episode directly from fangj.github.io,
    downloads it, extracts transcript, and slices it to a lightweight size.
    """
    results = []
    
    seasons = {
        1: 24, 2: 24, 3: 25, 4: 24, 5: 24,
        6: 25, 7: 24, 8: 24, 9: 24, 10: 18
    }

    # Attempt to find an unused random episode
    selected_url = None
    selected_title = None
    
    for _ in range(20):  # Try 20 times to find an unused episode
        season = random.choice(list(seasons.keys()))
        episode = random.randint(1, seasons[season])
        filename = f"{season:02d}{episode:02d}.html"
        url = f"https://fangj.github.io/friends/season/{filename}"
        
        if url not in used_episodes:
            selected_url = url
            selected_title = f"Friends Season {season} Episode {episode}"
            break
            
    if not selected_url:
        logger.warning("Could not find an unused Friends episode in random selection")
        return results

    try:
        logger.info(f"Fetching Friends transcript directly: {selected_title}")
        response = _fetch_with_retry(selected_url)
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract plain text from all paragraphs and table elements, or directly body text
            paragraphs = soup.find_all('p')
            lines = []
            for p in paragraphs:
                txt = p.get_text(separator=' ', strip=True)
                if txt:
                    lines.append(txt)
                    
            if not lines:
                # Fallback to direct text splitting if no <p> tags
                text_content = soup.get_text(separator='\n')
                lines = [line.strip() for line in text_content.split('\n') if line.strip()]

            if lines:
                # Slice the transcript to make it lightweight
                # Take a chunk of 70 lines (approx. 2000-3000 chars)
                if len(lines) > 80:
                    start_idx = random.randint(0, len(lines) - 70)
                    sliced_lines = lines[start_idx : start_idx + 70]
                    sliced_text = "\n".join(sliced_lines)
                else:
                    sliced_text = "\n".join(lines)

                results.append({
                    'source': 'Friends',
                    'raw_text': sliced_text,
                    'url': selected_url
                })
                logger.info(f"Successfully fetched Friends transcript snippet ({len(sliced_text)} chars) from {selected_url}")
            else:
                logger.warning(f"No transcript lines found in page: {selected_url}")

    except Exception as e:
        logger.warning(f"Failed to fetch transcript from {selected_url}: {e}")

    return results


def scrape_all_sources(sources_config: dict, used_episodes: list) -> tuple[list[dict], list[str]]:
    """
    Main entry point for scraping all configured sources.
    Lightweight version: uses only RSS title/description and sliced transcripts.
    """
    text_chunks = []
    new_used_episode_urls = []

    for source_key, source_cfg in sources_config.items():
        source_name = source_cfg.get('name', source_key)
        source_type = source_cfg.get('type', '')

        logger.info(f"Processing source (lightweight mode): {source_name} (type: {source_type})")

        try:
            if source_type in ('news', 'business'):
                rss_urls = source_cfg.get('rss_urls', [])
                if not rss_urls:
                    logger.warning(f"No RSS URLs configured for source: {source_name}")
                    continue

                articles = _fetch_rss_articles(rss_urls)
                
                # Combine titles and summaries of the top 10 articles into a single text block
                combined_rss_text = ""
                limit_articles = articles[:10]  # Get top 10 articles
                
                for article in limit_articles:
                    title = article.get('title', '').strip()
                    desc = article.get('description', '').strip()
                    if title or desc:
                        combined_rss_text += f"- Title: {title}\nSummary: {desc}\n\n"
                
                if combined_rss_text:
                    text_chunks.append({
                        'source': source_name,
                        'raw_text': combined_rss_text,
                        'url': rss_urls[0]
                    })
                    logger.info(f"Combined {len(limit_articles)} RSS summaries for {source_name} ({len(combined_rss_text)} chars)")

            elif source_type == 'transcript':
                base_url = source_cfg.get('base_url', '')
                if not base_url:
                    logger.warning(f"No base URL configured for transcript source: {source_name}")
                    continue

                transcript_chunks = _scrape_friends_transcript(base_url, used_episodes)
                text_chunks.extend(transcript_chunks)

                for chunk in transcript_chunks:
                    if chunk.get('url'):
                        new_used_episode_urls.append(chunk['url'])

            else:
                logger.warning(f"Unknown source type '{source_type}' for source: {source_name}")

        except Exception as e:
            logger.warning(f"Source '{source_name}' completely failed: {e}. Continuing with other sources.")
            continue

    logger.info(f"Lightweight scraping complete. Total text chunks: {len(text_chunks)}, New episodes: {len(new_used_episode_urls)}")
    return text_chunks, new_used_episode_urls

