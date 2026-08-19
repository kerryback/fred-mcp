# fred-mcp

FRED MCP server for Rice Business Executive Education.

Publishes a catalog of tracked economic series and serves observations, metadata,
search, and past vintages over the Model Context Protocol (streamable HTTP).

Tools: `fred_list_catalog`, `fred_search_series`, `fred_series_info`,
`fred_get_observations`, `fred_get_vintage`.

Endpoint: https://fred.kerryback.com/mcp

Requires `FRED_API_KEY` in the environment. The key stays on the server.

`/mcp` requires a bearer token: set `MCP_AUTH_TOKEN` on the server and send
`Authorization: Bearer <token>` from the client. The root page stays open so the
platform health check works. With `MCP_AUTH_TOKEN` unset the server runs open,
which is fine on localhost and wrong anywhere else.
