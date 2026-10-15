# Amazon Orders MCP

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets
Claude read your own Amazon.com order history: order totals, items, sellers,
and whether a product is marked "FSA or HSA eligible." It only reads pages. It
never buys, adds to a cart, or changes an order.

## First-time setup (sign-in is required first)

The server uses your normal Amazon session, saved as cookies on your computer.
It does not store your password. You sign in once in a browser window, and the
server reuses that session.

1. Install the requirements (Python 3.11 or 3.12, then `pip install -e .` in
   this folder). The first run also needs Playwright's browser:
   `python -m playwright install chromium`.
2. Start a sign-in: ask Claude to run `refresh_session`, or run
   `python cookie_capture.py` in this folder.
3. A Chromium window opens on Amazon's sign-in page. Sign in as usual,
   including any 2FA code. The window closes when the session is saved to
   `~/.amazon-orders-mcp/cookies.json`.

Amazon ends sessions on its own schedule. When that happens, the read tools open
the sign-in window once and retry the request. If you don't finish signing in
within about three minutes, the request fails and you can try again.

## Tools

| Tool | Opens a browser? | Needs sign-in? | What it does |
| --- | --- | --- | --- |
| `refresh_session` | Yes, a visible sign-in window | — | Signs in and saves the session |
| `check_auth_status` | No | No | Checks whether a session file exists |
| `setup_authentication` | No | No | Shows the setup steps |
| `get_order_history(year)` | Yes, invisible | Yes | Lists one year's orders, about 2–3 seconds per page |
| `get_order(order_id)` | Yes, invisible | Yes | Totals, items, sellers, and ASINs for one order |
| `match_transactions_by_amount` | Yes, invisible | Yes | Matches amounts to orders by date |
| `check_asin_eligibility(asin)` | Yes, invisible | No | Reads the public product page for "FSA or HSA eligible" |

"Invisible" means a headless browser loads the page in the background, and you
won't see a window.

## What to expect

- If Amazon changes a page's layout, the tool returns an error with the page
  address and a short text snippet. It does not guess at the data. Fixing it
  means updating the parser and its test fixtures. Ask a coding assistant to
  do this with the error text and the saved page text.
- An eligibility result of "not marked" means the label is absent from the
  product page. It does not prove the item is ineligible.
- The server is for US Amazon.com accounts only.

## Register with Claude Code

Add the server to your Claude Code MCP settings (`~/.claude.json` or the
project's `.mcp.json`):

```json
{
  "mcpServers": {
    "amazon-orders": {
      "command": "python",
      "args": ["-m", "amazon_orders_mcp.server"],
      "cwd": "/absolute/path/to/amazon-orders-mcp"
    }
  }
}
```

Restart Claude Code, then run `/mcp` to confirm `amazon-orders` is connected.

## Privacy

- Cookies stay on your computer in `~/.amazon-orders-mcp/cookies.json`. Don't
  share that file.
- Tool results, including order details, appear in your Claude conversation.
  Decide what you save or share from there.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests use fake browsers and synthetic page text. They don't contact Amazon.
`scripts/live_smoke_test.py` makes real Amazon requests. Run it only by hand,
when you choose to.

## License

MIT. See [LICENSE](LICENSE).

## Credits

- Started from [amazon-orders-mcp](https://github.com/seanoliver/amazon-orders-mcp)
  by Sean Oliver (MIT). The server design has changed substantially since.
- Earlier versions used [amazon-orders](https://github.com/alexdlaird/amazon-orders)
  by Alex Laird. This version no longer depends on it.
