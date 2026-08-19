# fred-mcp

FRED MCP server for Rice Business Executive Education.

Publishes a catalog of tracked economic series and serves observations, metadata,
search, and past vintages over the Model Context Protocol (streamable HTTP).

Tools: `fred_list_catalog`, `fred_search_series`, `fred_series_info`,
`fred_get_observations`, `fred_get_vintage`.

Endpoint: https://fred.kerryback.com/mcp

Requires `FRED_API_KEY` in the environment. The key stays on the server.

`/mcp` requires an API key: set `MCP_API_KEYS` (comma separated, so keys can be added
and revoked one at a time) on the server, and send either `Authorization: Bearer <key>`
or `X-API-Key: <key>` from the client. The root page stays open so the platform health
check works. With `MCP_API_KEYS` unset the server runs open, which is fine on localhost
and wrong anywhere else.
