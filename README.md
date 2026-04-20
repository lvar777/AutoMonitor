A Discord bot that monitors both auto(gidas/plius) listings

You give the bot a search URL (with all your filters already set in the browser).

## Setup

1. Setup `config.py`
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python main.py`

Or with Docker: `docker compose up -d`

## Commands

`/autogidas <url>` | Start monitoring an autogidas.lt search |
`/autoplius <url>` | Start monitoring an autoplius.lt search |
`/list` | Show active searches |
`/stop <id>` | Stop a search |

## Notes

- On first run, existing listings are loaded silently.
- Active hours are configurable (defaults to 06:00–23:00 Lithuanian time).
- Proxy support
- Uses Xpaths for more accurate results
