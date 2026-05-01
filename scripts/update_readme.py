
import os
import re
import requests
from datetime import datetime, timezone

USERNAME = os.environ["GITHUB_USERNAME"]
TOKEN    = os.environ["GITHUB_TOKEN"]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL    = "https://api.github.com"


# ── helpers ────────────────────────────────────────────────────────────────────

def gql(query: str, variables: dict = None) -> dict:
    r = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables or {}},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["data"]


def rest(path: str) -> dict | list:
    r = requests.get(f"{REST_URL}{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


# ── fetch data ─────────────────────────────────────────────────────────────────

def fetch_profile() -> dict:
    """
    Pull everything we need in a single GraphQL call:
    - basic stats (followers, following, starred repos count)
    - contribution totals for current year
    - top 6 repos by star count (non-forked, non-archived)
    - language breakdown across all repos
    """
    query = """
    query($login: String!) {
      user(login: $login) {
        name
        followers { totalCount }
        following  { totalCount }
        starredRepositories { totalCount }

        contributionsCollection {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          totalRepositoryContributions
          contributionCalendar {
            totalContributions
          }
        }

        repositories(
          first: 100
          ownerAffiliations: OWNER
          isFork: false
          privacy: PUBLIC
          orderBy: { field: STARGAZERS, direction: DESC }
        ) {
          totalCount
          nodes {
            name
            description
            url
            stargazerCount
            forkCount
            isArchived
            primaryLanguage { name }
            updatedAt
            defaultBranchRef {
              target {
                ... on Commit {
                  history { totalCount }
                }
              }
            }
          }
        }
      }
    }
    """
    return gql(query, {"login": USERNAME})["user"]


def language_breakdown(repos: list) -> list[tuple[str, float]]:
    """Return top languages sorted by repo count."""
    counts: dict[str, int] = {}
    total = 0
    for r in repos:
        lang = (r.get("primaryLanguage") or {}).get("name")
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
            total += 1
    if not total:
        return []
    sorted_langs = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [(lang, round(count / total * 100, 1)) for lang, count in sorted_langs[:5]]


# ── format sections ────────────────────────────────────────────────────────────

def fmt_projects(repos: list) -> str:
    active = [r for r in repos if not r["isArchived"]][:6]
    rows = []
    for r in active:
        lang  = (r.get("primaryLanguage") or {}).get("name", "—")
        stars = r["stargazerCount"]
        forks = r["forkCount"]
        desc  = (r.get("description") or "").strip() or "—"
        name  = r["name"]
        url   = r["url"]
        rows.append(
            f"| [{name}]({url}) | {desc} | {lang} "
            f"| {'★ ' + str(stars) if stars else '—'} "
            f"| {'⑂ ' + str(forks) if forks else '—'} |"
        )
    header = (
        "| project | description | lang | stars | forks |\n"
        "|---|---|---|---|---|"
    )
    return header + "\n" + "\n".join(rows)


def fmt_stats(user: dict, repos: list) -> str:
    cc   = user["contributionsCollection"]
    commits = cc["totalCommitContributions"]
    prs     = cc["totalPullRequestContributions"]
    issues  = cc["totalIssueContributions"]
    contribs= cc["contributionCalendar"]["totalContributions"]
    total_stars = sum(r["stargazerCount"] for r in repos)
    total_repos = user["repositories"]["totalCount"]
    followers   = user["followers"]["totalCount"]
    following   = user["following"]["totalCount"]

    return (
        f"| metric | value |\n"
        f"|---|---|\n"
        f"| public repos | {total_repos} |\n"
        f"| total stars | {total_stars} |\n"
        f"| commits this year | {commits} |\n"
        f"| pull requests | {prs} |\n"
        f"| issues opened | {issues} |\n"
        f"| total contributions | {contribs} |\n"
        f"| followers | {followers} |\n"
        f"| following | {following} |"
    )


def fmt_languages(repos: list) -> str:
    breakdown = language_breakdown(repos)
    if not breakdown:
        return "_no language data_"
    bars = []
    for lang, pct in breakdown:
        filled = round(pct / 5)   # 20 chars = 100 %
        bar    = "█" * filled + "░" * (20 - filled)
        bars.append(f"`{lang:<16}` {bar} {pct:>5}%")
    return "\n".join(bars)


def fmt_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%d %b %Y, %H:%M UTC")


# ── patch README ───────────────────────────────────────────────────────────────

MARKER = re.compile(
    r"(<!-- (\w+):start -->).*?(<!-- \2:end -->)",
    re.DOTALL,
)

def patch(readme: str, key: str, content: str) -> str:
    replacement = f"<!-- {key}:start -->\n{content}\n<!-- {key}:end -->"
    new, count = MARKER.subn(
        lambda m: replacement if m.group(2) == key else m.group(0),
        readme,
    )
    if count == 0:
        raise ValueError(f"Marker '<!-- {key}:start -->' not found in README.md")
    return new


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"[{fmt_timestamp()}] Fetching GitHub data for @{USERNAME}...")
    user  = fetch_profile()
    repos = user["repositories"]["nodes"]

    sections = {
        "projects":  fmt_projects(repos),
        "stats":     fmt_stats(user, repos),
        "languages": fmt_languages(repos),
        "updated":   f"_Last updated: {fmt_timestamp()}_",
    }

    readme_path = "README.md"
    with open(readme_path, "r", encoding="utf-8") as f:
        readme = f.read()

    for key, content in sections.items():
        readme = patch(readme, key, content)
        print(f"  ✓ patched [{key}]")

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)

    print("Done.")


if __name__ == "__main__":
    main()
