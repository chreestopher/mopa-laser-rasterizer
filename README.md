# CGI-Enabled Web Server

Simple web form for processing image files to prepare for color engraving on stainless steel

## To use this app:
### add your laser settings for each color to a lightburn material settings file 
Make sure the MaterilName contains "stainless steel"

Make sure the Material Settings Description matches one of the following descriptions:

| Description | hex color code for layer |
| --- | --- |
| Light-Gray  | #B4B4B4 |
| Black | #000000 |
| Blue | #0000FF |
| Red | #FF0000 | 
| Green | #00E000 |
| Yellow | #D0D000 |
| Orange | #FF8000 |
| Cyan | #00E0E0 |
| Magenta | #FF00FF |
| Dark-Blue | #0000A0 |
| Dark-Red | #A00000 |
| Dark-Green | #00A000 |
| Dark-Yellow | #A0A000 |
| Dark-Orange | #C08000 |
| Light-Blue | #00A0FF |
| Dark-Magenta | #A000A0 |
| Medium-Gray | #808080 |
| Slate-Blue | #7D87B9 |
| Rose | #BB7784 |
| Periwinkle-Blue | #4A6FE3 |
| Raspberry | #D33F6A |
| Sage-Green | #8CD78C |
| Peach | #F0B98D |
| Light-Pink | #F6C4E1 |
| Orchid-Pink | #FA9ED4 |
| Deep-Purple | #500A78 |
| Rust-Brown | #B45A00 |
| Teal | #004754 |
| Bright-Mint-Green | #86FA88 |
| Light-Gold | #FFDB66 |

## Project Structure

```
mopa-laser-rasterizer/
├── server.py               # Main server application
├── html/                   # Static HTML files directory
│   └── index.html          # Add your HTML files here
├── cgi-bin/                # Python CGI scripts directory
│   └── example.py          # Add your CGI scripts here
├── lib/                    # Core library and utility modules
│   ├── lightburn.py        # library for interacting with lightburn project and material files
│   └── Material_Library.py # process sent file with sent material settings file
└── README.md               # This file
```

## Getting Started

### Prerequisites

- Python 3.6 or higher
- pip install -r requirements.txt

### Running the Server 

1. Open a terminal in the project directory
2. Run the server:
   ```bash
   python server.py
   ```
3. Open your browser and navigate to: `http://localhost:8000`

## Directory Usage

### HTML Files (`html/`)

Place any static HTML, CSS, and JavaScript files here if you want to customize the upload form or add additional pages


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
