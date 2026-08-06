# CGI-Enabled Web Server

A simple Python HTTP server that serves static HTML files and executes Python CGI scripts.

## Project Structure

```
mopa-laser-rasterizer/
├── server.py           # Main server application
├── html/               # Static HTML files directory
│   └── index.html     # Add your HTML files here
├── cgi-bin/           # Python CGI scripts directory
│   └── example.py     # Add your CGI scripts here
└── README.md          # This file
```

## Features

- Serves static HTML files from the `html/` directory
- Executes Python CGI scripts from the `cgi-bin/` directory
- Simple request routing and error handling
- Path traversal protection
- Automatic directory indexing support

## Getting Started

### Prerequisites

- Python 3.6 or higher

### Running the Server

1. Open a terminal in the project directory
2. Run the server:
   ```bash
   python server.py
   ```

3. Open your browser and navigate to: `http://localhost:8000`

## Directory Usage

### HTML Files (`html/`)

Place all your static HTML, CSS, and JavaScript files here:
- `html/index.html` - Main page (serves as default for `/`)
- `html/about.html` - Other static pages
- `html/styles.css` - Stylesheets
- `html/scripts.js` - Client-side scripts
- `html/images/` - Image files

### CGI Scripts (`cgi-bin/`)

Place your Python CGI scripts here:
- Scripts must be executable
- Scripts should output proper HTTP headers
- Access via `/cgi-bin/script_name.py`

Example CGI script:
```python
#!/usr/bin/env python3
print("Content-Type: text/html")
print()
print("<h1>Hello from CGI!</h1>")
```

## Accessing Resources

- Static files: `http://localhost:8000/filename.html`
- CGI scripts: `http://localhost:8000/cgi-bin/script.py`
- Default route: `http://localhost:8000/` → serves `html/index.html`

## Example CGI Script

Create `cgi-bin/hello.py`:

```python
#!/usr/bin/env python3
import cgi

print("Content-Type: text/html")
print()

# Get query parameters
form = cgi.FieldStorage()
name = form.getvalue('name', 'World')

print(f"<h1>Hello, {name}!</h1>")
```

Access it at: `http://localhost:8000/cgi-bin/hello.py?name=YourName`

## Configuration

Edit `server.py` to change:
- `PORT` - Server port (default: 8000)
- `HOST` - Server host (default: localhost)
- `HTML_DIR` - Static files directory
- `CGI_BIN_DIR` - CGI scripts directory

## Notes

- The server runs on `localhost:8000` by default
- Press Ctrl+C to stop the server
- Ensure CGI scripts have proper permissions to execute
- CGI scripts must start with a shebang line: `#!/usr/bin/env python3`
