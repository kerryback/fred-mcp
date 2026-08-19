# fred-mcp

FRED MCP server for Rice Business Executive Education.

Publishes a catalog of tracked economic series and serves observations, metadata,
search, and past vintages over the Model Context Protocol (streamable HTTP).

Tools: `fred_list_catalog`, `fred_search_series`, `fred_series_info`,
`fred_get_observations`, `fred_get_vintage`.

Endpoint: https://fred.rice-business.org/mcp

Requires `FRED_API_KEY` in the environment. The key stays on the server.
