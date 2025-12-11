# Avanti Fellows PostgreSQL MCP Server

Read-only MCP server for querying the Avanti Fellows DB Service (PostgreSQL).

## What is this?

This is an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that lets Claude Code, Cursor, and other AI tools query our PostgreSQL database directly. It's **read-only** - no writes allowed.

## Available Tools

| Tool | Description |
|------|-------------|
| `query` | Run any SELECT query |
| `list_tables` | List all tables in the database |
| `describe_table` | Get column info, primary keys, foreign keys |
| `sample_data` | Get sample rows from a table |
| `count_rows` | Count rows with optional WHERE clause |
| `search_columns` | Find columns by name across all tables |

## Installation

### 1. Install the package

```bash
pip install git+https://github.com/avantifellows/mcp-postgres.git
```

### 2. Set up credentials

Add these to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
export AF_DB_HOST="af-database-host"
export AF_DB_PORT="5432"
export AF_DB_USER="your_username"
export AF_DB_PASSWORD="your_password"
export AF_DB_NAME="database_name"
```

Then reload: `source ~/.zshrc`

### 3. Configure your AI tool

#### Claude Code

```bash
claude mcp add avanti-db -- avanti-mcp-postgres
```

Verify it's working:
```bash
claude mcp list
```

#### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "avanti-db": {
      "command": "avanti-mcp-postgres",
      "env": {
        "AF_DB_HOST": "af-database-host",
        "AF_DB_PORT": "5432",
        "AF_DB_USER": "your_username",
        "AF_DB_PASSWORD": "your_password",
        "AF_DB_NAME": "database_name"
      }
    }
  }
}
```

## Usage Examples

Once configured, just ask Claude/Cursor about the database:

```
"What tables are in the database?"
"Show me the schema for the students table"
"How many users signed up this month?"
"Find all columns with 'email' in the name"
"What does the enrollment data look like?"
```

## Updating

```bash
pip install --upgrade git+https://github.com/avantifellows/mcp-postgres.git
```

## Local Development

```bash
# Clone the repo
git clone https://github.com/avantifellows/mcp-postgres.git
cd mcp-postgres

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install in dev mode
pip install -e .

# Create .env file with credentials
cp .env.example .env
# Edit .env with your credentials

# Test the server
avanti-mcp-postgres
```

## Security Notes

- This server is **read-only** - INSERT, UPDATE, DELETE are blocked
- Uses your personal database credentials
- Queries are logged locally but not sent anywhere
- Don't commit credentials to git

## Troubleshooting

### "Connection refused"
- Check that `AF_DB_HOST` is correct and accessible from your network
- Verify you're on VPN if required

### "Authentication failed"
- Double-check `AF_DB_USER` and `AF_DB_PASSWORD`
- Ensure your user has SELECT permissions

### Server not showing in Claude Code
- Run `claude mcp list` to check status
- Try removing and re-adding: `claude mcp remove avanti-db && claude mcp add avanti-db -- avanti-mcp-postgres`
