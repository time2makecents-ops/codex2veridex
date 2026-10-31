"""Bounded, read-only sports score retrieval for the Betting room."""

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

LEAGUES = {
    "nfl": "football/nfl", "nba": "basketball/nba", "mlb": "baseball/mlb",
    "nhl": "hockey/nhl", "atp": "tennis/atp", "wta": "tennis/wta",
}


def scores(league: str) -> dict:
    if league not in LEAGUES:
        raise ValueError("Unsupported league")
    url = f"https://site.api.espn.com/apis/site/v2/sports/{LEAGUES[league]}/scoreboard"
    request = Request(url, headers={"User-Agent": "Veridex/1.0", "Accept": "application/json", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read(2_000_001))
    events = []
    for event in payload.get("events", [])[:100]:
        competition = (event.get("competitions") or [{}])[0]
        status = competition.get("status") or event.get("status") or {}
        competitors = []
        for item in competition.get("competitors", [])[:2]:
            identity = item.get("team") or item.get("athlete") or {}
            score = item.get("score")
            competitors.append({"name": identity.get("displayName") or identity.get("shortDisplayName") or "Unknown", "score": "" if score is None else str(score)})
        events.append({"id": str(event.get("id") or ""), "name": str(event.get("name") or ""), "date": str(event.get("date") or ""), "status": str((status.get("type") or {}).get("shortDetail") or (status.get("type") or {}).get("description") or "Unknown"), "competitors": competitors})
    return {"league": league, "source": "ESPN public scoreboard (unofficial)", "source_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(), "events": events}
