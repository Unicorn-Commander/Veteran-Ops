# Valor-Ops MCP server over SSE — so Brigade's MCP registry can connect to it.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir "mcp>=1.2" "httpx>=0.27,<0.28"
COPY valor_mcp.py .
ENV MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8766
EXPOSE 8766
CMD ["python", "valor_mcp.py"]
