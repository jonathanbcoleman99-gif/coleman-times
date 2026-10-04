#!/usr/bin/env python3

"""
The Coleman Times — free daily edition builder.

No API keys.
No paid services.
Uses public sports endpoints and filesystem-based comic rotation.

The HTML page reads:
    editions/latest.json
"""

import json
import os
import random
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
EDITIONS = ROOT / "editions"
AVAILABLE_COMICS = ROOT / "comics" / "available"
USED_COMICS = ROOT / "comics" / "used"
OUTPUT = EDITIONS / "latest.json"

CENTRAL = ZoneInfo("America/Chicago")

TEAMS = {
    "Atlanta Braves": {
        "sport": "baseball",
        "league": "MLB",
        "espn_id": "15",
    },
    "Rocket City Trash Pandas": {
        "sport": "baseball",
        "league": "MiLB",
        "source": "https://www.milb.com/rocket-city",
    },
    "Auburn Tigers": {
        "football": "2",
        "basketball": "2",
        "baseball": "2",
    },
    "Texas Tech Red Raiders": {
        "football": "2641",
        "basketball": "2641",
        "baseball": "2641",
    },
    "Huntsville Havoc": {
        "sport": "hockey",
        "league": "SPHL",
    },
}


# ------------------------------------------------------------
# BASIC HTTP
# ------------------------------------------------------------

def get_json(url):
    """Download JSON from a public endpoint."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Coleman-Times/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"WARNING: could not retrieve {url}")
        print(f"         {exc}")
        return None


# ------------------------------------------------------------
# DATES
# ------------------------------------------------------------

now = datetime.now(CENTRAL)

today = now.date()
yesterday = today - timedelta(days=1)

today_iso = today.isoformat()
yesterday_iso = yesterday.isoformat()

print(f"Coleman Times build")
print(f"Today:      {today_iso}")
print(f"Yesterday:  {yesterday_iso}")
print(f"Central:    {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")


# ------------------------------------------------------------
# COMIC ROTATION
# ------------------------------------------------------------

def choose_comic():
    """
    Select a comic from available/ and move it to used/.

    A comic can therefore never be selected twice until the
    available folder has been replenished.
    """

    AVAILABLE_COMICS.mkdir(parents=True, exist_ok=True)
    USED_COMICS.mkdir(parents=True, exist_ok=True)

    comics = [
        p for p in AVAILABLE_COMICS.iterdir()
        if p.is_file()
        and p.suffix.lower() in {
            ".jpg", ".jpeg", ".png", ".webp", ".gif"
        }
    ]

    if not comics:
        return None

    comic = random.choice(comics)

    destination = USED_COMICS / f"{today_iso}-{comic.name}"

    # Avoid a collision if the workflow is manually run twice.
    counter = 2
    while destination.exists():
        destination = USED_COMICS / f"{today_iso}-{counter}-{comic.name}"
        counter += 1

    shutil.move(str(comic), str(destination))

    # The HTML is served from the repository root.
    # Used comic gets a permanent URL.
    relative = destination.relative_to(ROOT).as_posix()

    return {
        "image": relative,
        "filename": destination.name,
        "date": today_iso,
    }


# ------------------------------------------------------------
# ESPN HELPERS
# ------------------------------------------------------------

def espn_scoreboard(sport, league, date):
    """
    ESPN public scoreboard endpoint.

    Date must be YYYYMMDD.
    """

    url = (
        "https://site.api.espn.com/apis/site/v2/sports/"
        f"{sport}/{league}/scoreboard"
        f"?dates={date}"
    )

    return get_json(url)


def espn_standings(sport, league):
    url = (
        "https://site.api.espn.com/apis/v2/sports/"
        f"{sport}/{league}/standings"
    )

    return get_json(url)


def find_team_event(data, team_name):
    """Find an ESPN event involving a particular team."""

    if not data:
        return None

    for event in data.get("events", []):
        for competition in event.get("competitions", []):
            competitors = competition.get("competitors", [])

            names = []

            for team in competitors:
                t = team.get("team", {})
                names.append(t.get("displayName", ""))
                names.append(t.get("shortDisplayName", ""))

            if any(
                team_name.lower() in n.lower()
                or n.lower() in team_name.lower()
                for n in names
                if n
            ):
                return event

    return None


def make_basic_game(event):
    """
    Convert an ESPN event into the structure expected by index.html.
    """

    if not event:
        return None

    competition = event.get("competitions", [{}])[0]
    competitors = competition.get("competitors", [])

    if len(competitors) < 2:
        return None

    away = None
    home = None

    for team in competitors:
        if team.get("homeAway") == "away":
            away = team
        elif team.get("homeAway") == "home":
            home = team

    if not away or not home:
        away, home = competitors[0], competitors[1]

    away_team = away.get("team", {}).get(
        "displayName",
        "Away"
    )

    home_team = home.get("team", {}).get(
        "displayName",
        "Home"
    )

    away_score = away.get("score", "")
    home_score = home.get("score", "")

    status = (
        competition
        .get("status", {})
        .get("type", {})
        .get("description", "")
    )

    return {
        "away": away_team,
        "awayScore": away_score,
        "home": home_team,
        "homeScore": home_score,
        "status": status,
        "source": "ESPN",
        "url": (
            "https://www.espn.com/"
            + event.get("links", [{}])[0].get("href", "")
            if event.get("links")
            else "https://www.espn.com/"
        ),
    }


# ------------------------------------------------------------
# SPORTS
# ------------------------------------------------------------

def build_mlb_team(team_name):
    """
    Braves section.

    Uses ESPN's public MLB scoreboard for the previous day.
    """

    data = espn_scoreboard(
        "baseball",
        "mlb",
        yesterday.strftime("%Y%m%d"),
    )

    event = find_team_event(data, team_name)

    games = []

    if event:
        game = make_basic_game(event)

        if game:
            games.append(game)

    return {
        "name": team_name,
        "sports": [
            {
                "name": "MLB",
                "games": games,
                "standings": {
                    "title": "MLB standings",
                    "headers": [
                        "Team",
                        "W",
                        "L",
                        "PCT",
                        "GB",
                    ],
                    "rows": [],
                    "note": (
                        "League standings are being populated "
                        "from the daily sports data source."
                    ),
                    "source": "ESPN",
                    "url": "https://www.espn.com/mlb/standings",
                },
            }
        ],
    }


def build_college_team(team_name, team_id):
    """
    Build Auburn or Texas Tech.

    We query the three major sports independently.
    """

    sports = []

    college_sports = [
        ("Football", "football", "college-football"),
        ("Basketball", "basketball", "mens-college-basketball"),
        ("Baseball", "baseball", "college-baseball"),
    ]

    for display_name, sport, league in college_sports:

        data = espn_scoreboard(
            sport,
            league,
            yesterday.strftime("%Y%m%d"),
        )

        event = find_team_event(data, team_name)

        games = []

        if event:
            game = make_basic_game(event)

            if game:
                games.append(game)

        if not games:
            sports.append({
                "name": display_name,
                "games": [],
                "offSeason": True,
                "offSeasonNote": (
                    "No game for this program yesterday. "
                    "Meaningful developments are still monitored."
                ),
                "standings": {
                    "title": f"{display_name} standings",
                    "headers": [
                        "Team",
                        "W",
                        "L",
                        "PCT",
                    ],
                    "rows": [],
                    "source": "ESPN",
                    "url": (
                        f"https://www.espn.com/"
                        f"{league}/standings"
                    ),
                },
            })
        else:
            sports.append({
                "name": display_name,
                "games": games,
                "standings": {
                    "title": f"{display_name} standings",
                    "headers": [
                        "Team",
                        "W",
                        "L",
                        "PCT",
                    ],
                    "rows": [],
                    "source": "ESPN",
                    "url": (
                        f"https://www.espn.com/"
                        f"{league}/standings"
                    ),
                },
            })

    return {
        "name": team_name,
        "sports": sports,
    }


def build_havoc():
    return {
        "name": "Huntsville Havoc",
        "sports": [
            {
                "name": "SPHL Hockey",
                "games": [],
                "offSeason": True,
                "offSeasonNote": (
                    "No confirmed SPHL game data was available "
                    "from the current free public feed."
                ),
                "standings": {
                    "title": "SPHL standings",
                    "headers": [
                        "Team",
                        "W",
                        "L",
                        "OTL",
                        "PTS",
                    ],
                    "rows": [],
                    "source": "SPHL",
                    "url": "https://www.thesphl.com/",
                },
            }
        ],
    }


def build_trash_pandas():
    return {
        "name": "Rocket City Trash Pandas",
        "sports": [
            {
                "name": "Southern League",
                "games": [],
                "offSeason": True,
                "offSeasonNote": (
                    "Rocket City game and standings data will be "
                    "filled from the MiLB feed."
                ),
                "standings": {
                    "title": "Southern League standings",
                    "headers": [
                        "Team",
                        "W",
                        "L",
                        "PCT",
                        "GB",
                    ],
                    "rows": [],
                    "source": "MiLB",
                    "url": "https://www.milb.com/rocket-city/standings",
                },
            }
        ],
    }


def build_sports():
    return [
        build_mlb_team("Atlanta Braves"),
        build_trash_pandas(),
        build_college_team(
            "Auburn Tigers",
            TEAMS["Auburn Tigers"]["football"],
        ),
        build_college_team(
            "Texas Tech Red Raiders",
            TEAMS["Texas Tech Red Raiders"]["football"],
        ),
        build_havoc(),
    ]


# ------------------------------------------------------------
# HISTORY
# ------------------------------------------------------------

def build_history():
    """
    History is intentionally kept as a separate data source.

    The automation framework will eventually populate this from
    selected public historical sources.
    """

    return [
        {
            "year": today.year,
            "headline": "Today in history",
            "body": (
                "Historical events for today's date will be "
                "added to the daily research feed."
            ),
            "source": "Coleman Times",
        }
    ]


# ------------------------------------------------------------
# DIVERSION PLACEHOLDERS
# ------------------------------------------------------------

def build_diversions(comic):
    comic_block = {
        "title": "The Cader Files",
        "subtitle": "Cader Vane — freelance spy, mercenary, and reluctant sailor",
    }

    if comic:
        comic_block["image"] = comic["image"]
    else:
        comic_block["image"] = None
        comic_block["note"] = (
            "No unused Cader Vane strip remains. "
            "A new strip is coming soon."
        )

    return {
        "comic": comic_block,

        "puzzles": [
            {
                "label": "Logic Puzzle",
                "question": (
                    "Three switches are outside a closed room. "
                    "Inside are three incandescent bulbs. "
                    "Each switch controls exactly one bulb. "
                    "You may manipulate the switches however you like, "
                    "but may enter the room only once. "
                    "How can you determine which switch controls "
                    "which bulb?"
                ),
                "answer": (
                    "Turn switch 1 on for several minutes, then turn it "
                    "off. Turn switch 2 on and enter the room. The bulb "
                    "that is on belongs to switch 2. Of the two bulbs "
                    "that are off, the warm bulb belongs to switch 1; "
                    "the cold bulb belongs to switch 3."
                ),
            },
            {
                "label": "Quick Puzzle",
                "question": (
                    "What five-letter English word becomes shorter "
                    "when you add two letters to it?"
                ),
                "answer": "Short → shorter.",
            },
        ],
    }


# ------------------------------------------------------------
# OTHER SECTIONS
# ------------------------------------------------------------

def build_politics():
    return {
        "stories": [
            {
                "headline": "Politics & Defense",
                "tag": "Daily research feed",
                "bias": "Neutral",
                "body": (
                    "The automated political and defense research feed "
                    "will populate this section with previous-day "
                    "developments and source links."
                ),
                "source": "Coleman Times",
            }
        ]
    }


def build_science():
    return {
        "stories": [
            {
                "headline": "Science & Engineering",
                "tag": "Daily research feed",
                "body": (
                    "The automated science feed will prioritize AI, "
                    "materials science, structures, engineering, "
                    "failure analysis, and thermal analysis."
                ),
                "source": "Coleman Times",
            }
        ]
    }


def build_exploration():
    return {
        "stories": [
            {
                "headline": "Exploration",
                "tag": "Daily research feed",
                "body": (
                    "Space travel, solo sailing, the Great Loop, "
                    "remote places, and modern exploration will be "
                    "tracked here."
                ),
                "source": "Coleman Times",
            }
        ]
    }


# ------------------------------------------------------------
# EDITION
# ------------------------------------------------------------

comic = choose_comic()

edition = {
    "date": today_iso,
    "displayDate": now.strftime("%A, %B %-d, %Y"),
    "contentDate": yesterday_iso,

    "sports": build_sports(),

    "politics": build_politics(),

    "science": build_science(),

    "exploration": build_exploration(),

    "history": build_history(),

    "diversions": build_diversions(comic),

    "generatedAt": now.isoformat(),
    "generator": "Coleman Times free automation",
}


# ------------------------------------------------------------
# WRITE JSON
# ------------------------------------------------------------

EDITIONS.mkdir(parents=True, exist_ok=True)

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(
        edition,
        f,
        indent=2,
        ensure_ascii=False,
    )
    f.write("\n")

print(f"Wrote {OUTPUT}")

if comic:
    print(f"Selected comic: {comic['filename']}")
else:
    print("No unused comic available.")

print("Build complete.")
