from flask import Flask, render_template, jsonify, request
import asyncio
import aiohttp
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import threading
import time
import os

app = Flask(__name__)

class NewsAggregator:
    def __init__(self):
        # Using OrderedDict to maintain specific order
        from collections import OrderedDict
        self.sources = OrderedDict([
            ('LessWrong', self.get_lesswrong),
            ('EA Forum', self.get_ea_forum),
            ('Substack (Last 24h)', self.get_substack_feeds),
            ('Business', self.get_business_feeds),
            ('Hacker News', self.get_hackernews),
            ('Marginal Revolution', self.get_marginal_revolution),
            ('Bloomberg', self.get_bloomberg),
            ('Nature Neuroscience', self.get_nature_neuro),
            ('Gwern.net', self.get_gwern)
        ])
        
        # Cache for news data
        self.news_cache = {}
        self.last_refresh = None
        self.cache_duration = 24 * 60 * 60  # 24 hours in seconds
        
        # Start background refresh thread
        self.start_background_refresh()
        
        # Bookmarks storage
        self.bookmarks_file = 'bookmarks.json'
        self.bookmarks = self.load_bookmarks()
        
    async def get_hackernews(self):
        """Get top stories from Hacker News API"""
        try:
            response = requests.get('https://hacker-news.firebaseio.com/v0/topstories.json')
            story_ids = response.json()[:20]  # Top 20 stories
            
            stories = []
            for story_id in story_ids:
                story_response = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{story_id}.json')
                story = story_response.json()
                if story and 'title' in story and 'url' in story:
                    stories.append({
                        'title': story['title'],
                        'url': story['url'],
                        'score': story.get('score', 0)
                    })
            
            return sorted(stories, key=lambda x: x['score'], reverse=True)
        except Exception as e:
            print(f"Error fetching Hacker News: {e}")
            return []
    
    async def get_lesswrong(self):
        """Get top posts from LessWrong GraphQL API"""
        try:
            query = """
            {
              posts(input: {terms: {view: "frontpage", limit: 20}}) {
                results {
                  title
                  slug
                  baseScore
                }
              }
            }
            """
            
            response = requests.post(
                'https://www.lesswrong.com/graphql',
                json={'query': query},
                headers={'Content-Type': 'application/json'}
            )
            
            data = response.json()
            posts = []
            
            if 'data' in data and 'posts' in data['data']:
                for post in data['data']['posts']['results']:
                    posts.append({
                        'title': post['title'],
                        'url': f"https://www.lesswrong.com/posts/{post['slug']}",
                        'score': post.get('baseScore', 0)
                    })
            
            return sorted(posts, key=lambda x: x['score'], reverse=True)
        except Exception as e:
            print(f"Error fetching LessWrong: {e}")
            return []
    
    async def get_ea_forum(self):
        """Get top posts from EA Forum GraphQL API"""
        try:
            query = """
            {
              posts(input: {terms: {view: "new", limit: 20}}) {
                results {
                  title
                  slug
                  _id
                  baseScore
                  postedAt
                }
              }
            }
            """
            
            response = requests.post(
                'https://forum.effectivealtruism.org/graphql',
                json={'query': query},
                headers={'Content-Type': 'application/json'}
            )
            
            data = response.json()
            posts = []
            
            if 'data' in data and 'posts' in data['data']:
                for post in data['data']['posts']['results']:
                    # Use _id instead of slug for more reliable links
                    post_id = post.get('_id', '')
                    slug = post.get('slug', '')
                    
                    # EA Forum URL format is /posts/{id}/{slug}
                    url = f"https://forum.effectivealtruism.org/posts/{post_id}/{slug}" if post_id else f"https://forum.effectivealtruism.org/posts/{slug}"
                    
                    posts.append({
                        'title': post['title'],
                        'url': url,
                        'score': post.get('baseScore', 0)
                    })
            
            # Sort by score since these are recent posts
            return sorted(posts, key=lambda x: x['score'], reverse=True)
        except Exception as e:
            print(f"Error fetching EA Forum: {e}")
            return []
    
    async def get_marginal_revolution(self):
        """Scrape latest posts from Marginal Revolution"""
        try:
            response = requests.get('https://marginalrevolution.com')
            soup = BeautifulSoup(response.content, 'html.parser')
            
            posts = []
            article_links = soup.find_all('h2', class_='entry-title')[:10]
            
            for article in article_links:
                link = article.find('a')
                if link:
                    posts.append({
                        'title': link.text.strip(),
                        'url': link.get('href')
                    })
            
            return posts
        except Exception as e:
            print(f"Error fetching Marginal Revolution: {e}")
            return []
    
    async def get_gwern(self):
        """Scrape latest from Gwern.net"""
        try:
            response = requests.get('https://gwern.net')
            soup = BeautifulSoup(response.content, 'html.parser')
            
            posts = []
            # Look for main content links
            links = soup.find_all('a', href=True)[:15]
            
            for link in links:
                href = link.get('href')
                title = link.text.strip()
                
                if href and title and len(title) > 10 and not href.startswith('#'):
                    if href.startswith('/'):
                        href = 'https://gwern.net' + href
                    posts.append({
                        'title': title,
                        'url': href
                    })
            
            return posts[:10]
        except Exception as e:
            print(f"Error fetching Gwern: {e}")
            return []
    
    async def get_substack_feeds(self):
        """Get posts from Substack newsletters from the last day"""
        substack_feeds = [
            'https://benthams.substack.com/feed',
            'https://humaninvariant.substack.com/feed',
            'https://a16zgrowth.substack.com/feed',
            'https://adelesscience.substack.com/feed',
            'https://antonhowes.substack.com/feed',
            'https://press.asimov.com/feed',
            'https://astralcodexten.substack.com/feed',
            'https://bossbeautysaas.substack.com/feed',
            'https://constructionphysics.substack.com/feed',
            'https://corememory.substack.com/feed',
            'https://danielgreco.substack.com/feed',
            'https://dwarkeshpatel.substack.com/feed',
            'https://blog.eladgil.com/feed',
            'https://extropicthoughts.substack.com/feed',
            'https://fabricatedknowledge.substack.com/feed',
            'https://generalist.substack.com/feed',
            'https://glasshalftrue.substack.com/feed',
            'https://interconnects.substack.com/feed',
            'https://jackhanlon.substack.com/feed',
            'https://jacobrobinson.substack.com/feed',
            'https://katechon99.substack.com/feed',
            'https://newsletter.lennyrachitsky.com/feed',
            'https://loganthrashercollins.substack.com/feed',
            'https://mrsmithsbookshelf.substack.com/feed',
            'https://neurobiology.substack.com/feed',
            'https://neurotechfutures.substack.com/feed',
            'https://newcomer.substack.com/feed',
            'https://noetik.substack.com/feed',
            'https://notboring.substack.com/feed',
            'https://on.substack.com/feed',
            'https://owlposting.substack.com/feed',
            'https://planetocracy.substack.com/feed',
            'https://davidgamejournal.substack.com/feed',
            'https://richardhanania.substack.com/feed',
            'https://robkhenderson.substack.com/feed',
            'https://roon.substack.com/feed',
            'https://roughdiamonds.substack.com/feed',
            'https://secondperson.substack.com/feed',
            'https://semianalysis.substack.com/feed',
            'https://socraticpsychiatrist.substack.com/feed',
            'https://splittinginfinity.substack.com/feed',
            'https://statecraft.substack.com/feed',
            'https://tbpn.substack.com/feed',
            'https://technotheoria.substack.com/feed',
            'https://rashmee.substack.com/feed'
        ]
        
        all_posts = []
        one_day_ago = datetime.now() - timedelta(days=1)
        
        for feed_url in substack_feeds:
            try:
                feed = feedparser.parse(feed_url)
                
                for entry in feed.entries:
                    # Parse the published date
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6])
                        
                        # Only include posts from the last day
                        if pub_date >= one_day_ago:
                            all_posts.append({
                                'title': entry.title,
                                'url': entry.link,
                                'published': pub_date,
                                'source': feed.feed.get('title', 'Unknown Substack')
                            })
                            
            except Exception as e:
                print(f"Error fetching feed {feed_url}: {e}")
                continue
        
        # Sort by publication time (most recent first)
        all_posts.sort(key=lambda x: x['published'], reverse=True)
        
        # Return only the essential info
        return [{'title': post['title'], 'url': post['url']} for post in all_posts[:20]]
    
    async def get_bloomberg(self):
        """Get latest Bloomberg news via RSS"""
        try:
            feed_url = 'https://feeds.bloomberg.com/markets/news.rss'
            feed = feedparser.parse(feed_url)
            
            posts = []
            for entry in feed.entries[:15]:
                posts.append({
                    'title': entry.title,
                    'url': entry.link
                })
            
            return posts
        except Exception as e:
            print(f"Error fetching Bloomberg: {e}")
            return []
    
    async def get_nature_neuro(self):
        """Get latest Nature Neuroscience articles via RSS"""
        try:
            feed_url = 'http://feeds.nature.com/neuro/rss/current'
            feed = feedparser.parse(feed_url)
            
            posts = []
            for entry in feed.entries[:10]:
                posts.append({
                    'title': entry.title,
                    'url': entry.link
                })
            
            return posts
        except Exception as e:
            print(f"Error fetching Nature Neuroscience: {e}")
            return []
    
    async def get_business_feeds(self):
        """Get posts from business and investing sources"""
        business_feeds = [
            ('https://diff.substack.com/feed', 'The Diff'),
            ('https://stratechery.com/feed/', 'Stratechery'),
            ('https://semianalysis.substack.com/feed', 'SemiAnalysis')
        ]
        
        all_posts = []
        one_day_ago = datetime.now() - timedelta(days=3)  # Slightly longer for business content
        
        for feed_url, source_name in business_feeds:
            try:
                feed = feedparser.parse(feed_url)
                
                for entry in feed.entries:
                    # Parse the published date
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6])
                        
                        # Only include posts from recent days
                        if pub_date >= one_day_ago:
                            all_posts.append({
                                'title': f"[{source_name}] {entry.title}",
                                'url': entry.link,
                                'published': pub_date,
                                'source': source_name
                            })
                    else:
                        # Include recent entries without date parsing (fallback)
                        all_posts.append({
                            'title': f"[{source_name}] {entry.title}",
                            'url': entry.link,
                            'published': datetime.now(),
                            'source': source_name
                        })
                            
            except Exception as e:
                print(f"Error fetching business feed {feed_url}: {e}")
                continue
        
        # Sort by publication time (most recent first)
        all_posts.sort(key=lambda x: x['published'], reverse=True)
        
        # Return only the essential info
        return [{'title': post['title'], 'url': post['url']} for post in all_posts[:20]]
    
    def start_background_refresh(self):
        """Start background thread for daily news refresh"""
        def refresh_worker():
            while True:
                try:
                    print("Starting daily news refresh...")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    fresh_news = loop.run_until_complete(self.fetch_all_news())
                    loop.close()
                    
                    self.news_cache = fresh_news
                    self.last_refresh = datetime.now()
                    print(f"News refreshed successfully at {self.last_refresh}")
                    
                except Exception as e:
                    print(f"Error in background refresh: {e}")
                
                # Sleep for 24 hours
                time.sleep(self.cache_duration)
        
        # Start the worker thread
        refresh_thread = threading.Thread(target=refresh_worker, daemon=True)
        refresh_thread.start()
        
        # Do initial refresh
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.news_cache = loop.run_until_complete(self.fetch_all_news())
            loop.close()
            self.last_refresh = datetime.now()
            print(f"Initial news cache loaded at {self.last_refresh}")
        except Exception as e:
            print(f"Error in initial refresh: {e}")
            self.news_cache = {}
    
    async def fetch_all_news(self):
        """Fetch fresh news from all sources"""
        all_news = {}
        
        for source_name, fetch_func in self.sources.items():
            try:
                news_items = await fetch_func()
                all_news[source_name] = news_items
            except Exception as e:
                print(f"Error fetching {source_name}: {e}")
                all_news[source_name] = []
        
        return all_news
    
    def get_cached_news(self):
        """Get news from cache"""
        if not self.news_cache:
            # If cache is empty, do a fresh fetch
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self.news_cache = loop.run_until_complete(self.fetch_all_news())
                loop.close()
                self.last_refresh = datetime.now()
            except Exception as e:
                print(f"Error fetching fresh news: {e}")
                return {}
        
        return self.news_cache
    
    def force_refresh(self):
        """Force a manual refresh of the news cache"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.news_cache = loop.run_until_complete(self.fetch_all_news())
            loop.close()
            self.last_refresh = datetime.now()
            print(f"Manual refresh completed at {self.last_refresh}")
            return True
        except Exception as e:
            print(f"Error in manual refresh: {e}")
            return False
    
    def load_bookmarks(self):
        """Load bookmarks from file"""
        try:
            if os.path.exists(self.bookmarks_file):
                with open(self.bookmarks_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading bookmarks: {e}")
        return []
    
    def save_bookmarks(self):
        """Save bookmarks to file"""
        try:
            with open(self.bookmarks_file, 'w', encoding='utf-8') as f:
                json.dump(self.bookmarks, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Error saving bookmarks: {e}")
            return False
    
    def add_bookmark(self, title, url, source):
        """Add a bookmark"""
        bookmark = {
            'title': title,
            'url': url,
            'source': source,
            'timestamp': datetime.now().isoformat()
        }
        
        # Check if bookmark already exists
        for existing in self.bookmarks:
            if existing['url'] == url:
                return False  # Already bookmarked
        
        self.bookmarks.insert(0, bookmark)  # Add to beginning
        return self.save_bookmarks()
    
    def remove_bookmark(self, url):
        """Remove a bookmark"""
        self.bookmarks = [b for b in self.bookmarks if b['url'] != url]
        return self.save_bookmarks()
    
    def get_bookmarks(self):
        """Get all bookmarks"""
        return self.bookmarks

aggregator = NewsAggregator()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/news')
def get_news():
    news = aggregator.get_cached_news()
    return jsonify(news)

@app.route('/api/refresh')
def refresh_news():
    success = aggregator.force_refresh()
    if success:
        return jsonify({
            'status': 'success', 
            'message': 'News refreshed successfully',
            'last_refresh': aggregator.last_refresh.isoformat() if aggregator.last_refresh else None
        })
    else:
        return jsonify({'status': 'error', 'message': 'Failed to refresh news'}), 500

@app.route('/api/bookmark', methods=['POST'])
def add_bookmark():
    data = request.json
    title = data.get('title')
    url = data.get('url')
    source = data.get('source', 'Unknown')
    
    if not title or not url:
        return jsonify({'status': 'error', 'message': 'Title and URL required'}), 400
    
    success = aggregator.add_bookmark(title, url, source)
    if success:
        return jsonify({'status': 'success', 'message': 'Bookmark added'})
    else:
        return jsonify({'status': 'error', 'message': 'Already bookmarked'}), 400

@app.route('/api/bookmark', methods=['DELETE'])
def remove_bookmark():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL required'}), 400
    
    success = aggregator.remove_bookmark(url)
    return jsonify({'status': 'success', 'message': 'Bookmark removed'})

@app.route('/api/bookmarks')
def get_bookmarks():
    bookmarks = aggregator.get_bookmarks()
    return jsonify(bookmarks)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)