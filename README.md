# News Aggregator

A minimal web-based news aggregator that pulls content from:
- Hacker News (top stories by score)
- LessWrong (top posts by karma)
- EA Forum (top posts by karma)
- Marginal Revolution (latest posts)
- Gwern.net (latest content)
- Substack subscriptions

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python app.py
```

3. Open your browser to: http://localhost:5000

## Features

- Minimal, clean interface with just article titles as links
- Grouped by source
- Native "best" sorting for each platform
- Auto-refresh every 5 minutes
- Manual refresh button
- Opens links in new tabs

## Usage

The aggregator will automatically fetch and display the top/latest articles from each source. Articles are sorted by each platform's native ranking system (score, karma, or recency).
