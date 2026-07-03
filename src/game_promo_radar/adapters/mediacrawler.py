from __future__ import annotations


class MediaCrawlerAdapter:
    """Optional adapter boundary for MediaCrawler public data analysis."""

    def analyze_keyword(self, keyword: str) -> dict:
        return {
            "keyword": keyword,
            "works_7d": None,
            "works_30d": None,
            "median_views": None,
            "interaction_rate": None,
            "creator_count": None,
            "heat_growth": None,
            "top_titles": [],
            "top_topics": [],
            "top_works": [],
            "status": "not_configured",
        }

