<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

## CGI-Enabled Web Server Project

This is a Python HTTP server project with support for:
- Serving static HTML files from the `static/` directory
- Executing Python CGI scripts from the `templates/` directory
- Security features like path traversal protection

### Project Structure
- `app.py` - Main server application
- `sattic/` - Place static HTML, CSS, JS files here
- `templates/` - Place Python CGI scripts here
- `README.md` - Full project documentation

### Key Guidelines
- Keep server logic in `server.py` only
- Add static content to `static/` directory
- Add CGI scripts to `templates/` directory with `#!/usr/bin/env python3` shebang
- CGI scripts must output proper HTTP headers before content
