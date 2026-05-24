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
    Scrape Friends TV show transcripts from transcripts.foreverdreaming.org.
    Selects random unused episodes and extracts transcript text.

    Args:
        base_url: The forum index page URL for Friends transcripts.
        used_episodes: List of already-used episode URLs to avoid.

    Returns:
        List of dicts with keys: source, raw_text, url
    """
    results = []
    new_episode_urls = []

    try:
        response = _fetch_with_retry(base_url)
        if not response:
            logger.warning("Failed to fetch Friends transcript index page")
            return results

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find episode thread links
        episode_links = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if 'viewtopic' in href:
                full_url = href if href.startswith('http') else f"https://transcripts.foreverdreaming.org{href}"
                # Normalize URL for comparison
                if full_url not in used_episodes:
                    episode_links.append({
                        'url': full_url,
                        'title': a_tag.get_text(strip=True)
                    })

        if not episode_links:
            logger.warning("No new Friends episodes found to scrape")
            return results

        # Randomly select 3-5 episodes
        num_to_select = min(random.randint(3, 5), len(episode_links))
        selected_episodes = random.sample(episode_links, num_to_select)

        for episode in selected_episodes:
            try:
                logger.info(f"Scraping Friends episode: {episode['title']}")
                ep_response = _fetch_with_retry(episode['url'])
                if not ep_response:
                    continue

                ep_soup = BeautifulSoup(ep_response.text, 'html.parser')

                # Extract transcript text
                transcript_text = ''
                for selector in ['div.postbody', 'div.content']:
                    content_div = ep_soup.select_one(selector)
                    if content_div:
                        transcript_text = content_div.get_text(separator='\n', strip=True)
                        break

                if transcript_text:
                    results.append({
                        'source': 'Friends',
                        'raw_text': transcript_text,
                        'url': episode['url']
                    })
                    new_episode_urls.append(episode['url'])
                    logger.info(f"Successfully scraped transcript from: {episode['title']}")

                # Polite delay
                time.sleep(random.uniform(1.0, 2.0))

            except Exception as e:
                logger.warning(f"Failed to scrape episode {episode['url']}: {e}")
                continue

    except Exception as e:
        logger.warning(f"Failed to scrape Friends transcripts: {e}")

    return results


def scrape_all_sources(sources_config: dict, used_episodes: list) -> tuple[list[dict], list[str]]:
    """
    Main entry point for scraping all configured sources.
    Orchestrates RSS fetching, article scraping, and transcript scraping.

    Args:
        sources_config: Dict of source configurations. Each source has:
            - name: str
            - type: 'news', 'business', or 'transcript'
            - rss_urls: list[str] (for news/business)
            - base_url: str (for transcript)
        used_episodes: List of already-used episode URLs.

    Returns:
        Tuple of (text_chunks, new_used_episode_urls)
        - text_chunks: List of {"source": str, "raw_text": str, "url": str}
        - new_used_episode_urls: List of newly scraped episode URLs
    """
    text_chunks = []
    new_used_episode_urls = []

    for source_key, source_cfg in sources_config.items():
        source_name = source_cfg.get('name', source_key)
        source_type = source_cfg.get('type', '')

        logger.info(f"Processing source: {source_name} (type: {source_type})")

        try:
            if source_type in ('news', 'business'):
                rss_urls = source_cfg.get('rss_urls', [])
                if not rss_urls:
                    logger.warning(f"No RSS URLs configured for source: {source_name}")
                    continue

                articles = _fetch_rss_articles(rss_urls)
                logger.info(f"Fetched {len(articles)} articles from {source_name}")

                for article in articles:
                    # Try to scrape full article content
                    full_text = ''
                    if article.get('url'):
                        full_text = _scrape_article_content(article['url'])

                    # Fallback to RSS description if full scrape fails
                    raw_text = full_text if full_text else article.get('description', '')

                    if raw_text:
                        text_chunks.append({
                            'source': source_name,
                            'raw_text': raw_text,
                            'url': article.get('url', '')
                        })

            elif source_type == 'transcript':
                base_url = source_cfg.get('base_url', '')
                if not base_url:
                    logger.warning(f"No base URL configured for transcript source: {source_name}")
                    continue

                transcript_chunks = _scrape_friends_transcript(base_url, used_episodes)
                text_chunks.extend(transcript_chunks)

                # Collect new episode URLs
                for chunk in transcript_chunks:
                    if chunk.get('url'):
                        new_used_episode_urls.append(chunk['url'])

            else:
                logger.warning(f"Unknown source type '{source_type}' for source: {source_name}")

        except Exception as e:
            logger.warning(f"Source '{source_name}' completely failed: {e}. Continuing with other sources.")
            continue

    logger.info(f"Scraping complete. Total text chunks: {len(text_chunks)}, New episodes: {len(new_used_episode_urls)}")
    return text_chunks, new_used_episode_urls
