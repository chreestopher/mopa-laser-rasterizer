#!/usr/bin/env python3
"""
Simple CGI-enabled HTTP server for serving static files and executing Python CGI scripts.
"""

from email import policy
from email.parser import BytesParser
from email import message_from_bytes
import http.client
import http.server
import os
import socketserver
import sys
from pathlib import Path
import subprocess

# Configuration
PORT = 8000
HOST = '0.0.0.0'
BASE_DIR = Path(__file__).parent
HTML_DIR = BASE_DIR / 'html'
CGI_BIN_DIR = BASE_DIR / 'cgi-bin'
UPLOADS_DIR = BASE_DIR / 'uploads'

# Ensure directories exist
HTML_DIR.mkdir(exist_ok=True)
CGI_BIN_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)


class CGIHTTPRequestHandler(http.server.CGIHTTPRequestHandler):
    """HTTP request handler with CGI support."""
    protocol_version = "HTTP/1.1"
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path.startswith('/cgi-bin/'):
            # Set CGI directories
            self.cgi_directories = ['/cgi-bin']
            http.server.CGIHTTPRequestHandler.do_GET(self)
        else:
            # Serve static files from html directory
            self.serve_static()
    
    def do_POST(self):
        """Handle POST requests."""
        if self.path == '/upload':
            self.handle_upload()
        elif self.path.startswith('/cgi-bin/'):
            self.cgi_directories = ['/cgi-bin']
            http.server.CGIHTTPRequestHandler.do_POST(self)
        else:
            self.send_error(http.client.METHOD_NOT_ALLOWED)

    def handle_upload(self):
        """Handle file upload and save the uploaded file to disk."""
        try:
            # Log incoming request info for debugging headers from the browser
            print('\n=== Incoming /upload request ===')
            print('Client:', self.client_address)
            for k, v in self.headers.items():
                print(f'{k}: {v}')
            sys.stdout.flush()

            content_type = self.headers.get('Content-Type')
            if not content_type or 'multipart/form-data' not in content_type:
                self.send_response(400)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"Expected multipart/form-data payload.")
                return

            # If the client used Expect: 100-continue, acknowledge so it sends the body
            expect_hdr = self.headers.get('Expect', '')
            if expect_hdr and '100-continue' in expect_hdr.lower():
                try:
                    self.send_response_only(100)
                    self.end_headers()
                except Exception:
                    pass

            content_length = self.headers.get('Content-Length')
            if content_length is not None:
                # Read exactly Content-Length bytes in a loop to avoid partial reads
                to_read = int(content_length)
                buf = bytearray()
                while len(buf) < to_read:
                    chunk = self.rfile.read(min(65536, to_read - len(buf)))
                    if not chunk:
                        # client closed connection early
                        break
                    buf.extend(chunk)
                raw_body = bytes(buf)
            else:
                # Read until the client closes the connection for chunked or unknown length
                parts = []
                while True:
                    chunk = self.rfile.read(8192)
                    if not chunk:
                        break
                    parts.append(chunk)
                raw_body = b''.join(parts)

            if raw_body is None or len(raw_body) == 0:
                self.send_response(400)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"Empty request body.")
                return

            # Manual multipart parsing to robustly extract binary file content
            # Extract boundary from Content-Type header
            boundary = None
            for part in content_type.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part.split('=', 1)[1]
                    if boundary.startswith('"') and boundary.endswith('"'):
                        boundary = boundary[1:-1]
                    break

            if not boundary:
                self.send_response(400)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"Missing boundary in Content-Type header.")
                return

            bboundary = ('--' + boundary).encode('utf-8')
            parts = raw_body.split(bboundary)
            file_saved = False
            form_fields = {}
            processed_log = {}
            for p in parts:
                if not p or p == b'--' or p == b'--\r\n':
                    continue
                # strip leading CRLF if present
                if p.startswith(b'\r\n'):
                    p = p[2:]

                # find header/body separator
                hdr_end = p.find(b"\r\n\r\n")
                if hdr_end == -1:
                    continue
                hdr_block = p[:hdr_end].decode('utf-8', errors='replace')
                body = p[hdr_end+4:]

                # remove trailing CRLF or ending marker
                if body.endswith(b"\r\n"):
                    body = body[:-2]
                if body.endswith(b"--"):
                    body = body[:-2]

                field_name = None
                filename = None
                for line in hdr_block.split('\r\n'):
                    if line.lower().startswith('content-disposition:'):
                        import re
                        m_name = re.search(r'name="([^\"]+)"', line)
                        if m_name:
                            field_name = m_name.group(1)
                        m_file = re.search(r'filename="([^\"]+)"', line)
                        if m_file:
                            filename = m_file.group(1)
                        break

                if filename:
                    msg_bytes = f"Content-Type: {content_type}\r\n\r\n".encode('utf-8') + raw_body
                    msg = message_from_bytes(msg_bytes)
                    for the_part in msg.get_payload():
                        the_filename = the_part.get_filename()
                        file_payload = the_part.get_payload(decode=True)

                    # 1. Isolate the extension (e.g., '.jpg', '.pdf') in lowercase
                    _, ext = os.path.splitext(filename.lower())

                    # 2. Route files dynamically by their extensions
                    if ext in ['.jpg', '.jpeg', '.png', '.bmp']:
                        processed_log["image"]= UPLOADS_DIR / filename 
                        
                    elif ext in ['.clb']:
                        processed_log["material_settings"]= UPLOADS_DIR / filename 
                    else:
                        print("I dont know what to do with files of type {ext}")
                        print(f"valid extensions for image files are {['.jpg', '.jpeg', '.png', '.bmp']}")
                        print(f"valid extensions for Lightburn Material Settings files is .clb")

                    filename = os.path.basename(filename)
                    dest_path = UPLOADS_DIR / filename
                    with open(dest_path, 'wb') as out_file:
                        out_file.write(body)
                        out_file.flush()
                        try:
                            os.fsync(out_file.fileno())
                        except Exception:
                            pass

                    file_size = dest_path.stat().st_size if dest_path.exists() else 0
                    print(f"[File] Field: '{field_name or 'file'}' | Filename: '{filename}' | Size: {file_size} bytes")
                    file_saved = True
                elif field_name:
                    try:
                        value = body.decode('utf-8')
                    except UnicodeDecodeError:
                        value = body.decode('latin-1', errors='replace')
                    existing = form_fields.get(field_name)
                    if existing is None:
                        form_fields[field_name] = value
                    elif isinstance(existing, list):
                        existing.append(value)
                    else:
                        form_fields[field_name] = [existing, value]
                    print(f"[Field] {field_name} = {form_fields[field_name]}")
            
            if not file_saved:
                self.send_response(400)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"No file field named 'file' found in multipart upload.")
                return

            #PROCESS THE UPLOADED FILE 
            print(processed_log["image"])
            input_file=processed_log["image"] #dest_path
            output_file=f"{processed_log['image']}.svg"
            square_mm=form_fields['pixel_square_mm']
            new_width=form_fields['new_width']
            new_height=form_fields['new_height']
            material_settings=processed_log["material_settings"]
            try:
                result_of_script = subprocess.run(
                    ["python", "lib/Material_Library.py", input_file, output_file, f"{square_mm}", f"{new_width}",f"{new_height}", material_settings],
                    capture_output=True, 
                    text=True
                )
                print(result_of_script.stdout)
                print(result_of_script.stderr)
            except Exception as ex:
                print(ex)


            # Only send response after the file is fully written to disk
            field_lines = []
            for key, value in form_fields.items():
                field_lines.append(f"{key}={value}")
            field_info = '\n'.join(field_lines)
            resp_text = f"File '{filename}' uploaded successfully. Size: {file_size} bytes."
            if field_info:
                resp_text += f"\nParsed form fields:\n{field_info}"
                resp_text += result_of_script.stdout
                resp_text += result_of_script.stderr
            resp = resp_text.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(resp)))
            self.end_headers()
            try:
                self.wfile.write(resp)
                self.wfile.flush()
            except Exception:
                pass
            # Ensure the connection is closed to signal end-of-response to the client
            try:
                self.close_connection = True
            except Exception:
                pass
            return
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            error_message = f"Upload processing error: {e}".encode('utf-8')
            self.wfile.write(error_message)
            sys.stderr.write(f"Upload error: {e}\n")
            return

    
    def serve_static(self):
        """Serve static files from html directory."""
        if self.path == '/':
            self.path = '/index.html'
        
        # Prevent path traversal
        file_path = HTML_DIR / self.path.lstrip('/')
        
        try:
            # Resolve to check if it's within html directory
            file_path = file_path.resolve()
            html_dir_resolved = HTML_DIR.resolve()
            
            if not str(file_path).startswith(str(html_dir_resolved)):
                self.send_error(http.client.FORBIDDEN)
                return
            
            if file_path.is_file():
                self.send_file(file_path)
            elif file_path.is_dir() and (file_path / 'index.html').exists():
                self.send_file(file_path / 'index.html')
            else:
                self.send_error(http.client.NOT_FOUND)
        except Exception as e:
            self.send_error(http.client.INTERNAL_SERVER_ERROR)
            sys.stderr.write(f"Error: {e}\n")
    
    def send_file(self, file_path):
        """Send a file to the client."""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Determine content type
            content_type = self.guess_type(str(file_path))
            
            self.send_response(http.client.OK)
            self.send_header('Content-type', content_type)
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(http.client.INTERNAL_SERVER_ERROR)
            sys.stderr.write(f"Error sending file: {e}\n")
    
    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax."""
        if path.startswith('/cgi-bin/'):
            # For CGI scripts, map to cgi-bin directory
            cgi_path = path[9:]  # Remove '/cgi-bin/'
            return str(CGI_BIN_DIR / cgi_path)
        else:
            # For static files, map to html directory
            static_path = path.lstrip('/')
            return str(HTML_DIR / static_path)
    
    def log_message(self, format, *args):
        """Log HTTP requests."""
        print(f"[{self.client_address[0]}] {format % args}")


def run_server():
    """Start the HTTP server."""
    handler = CGIHTTPRequestHandler

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True
    
    try:
        with ReusableTCPServer((HOST, PORT), handler) as httpd:
            print(f"\n{'='*60}")
            print(f"CGI-enabled HTTP Server")
            print(f"{'='*60}")
            print(f"Server listening on: http://{HOST}:{PORT}")
            print(f"Static files:         {HTML_DIR}")
            print(f"CGI scripts:          {CGI_BIN_DIR}")
            print(f"{'-'*60}")
            print("Note: this Python server binds to all local interfaces for")
            print("      compatibility outside Kubernetes.")
            print("      When running inside k3s/cluster, Kubernetes still")
            print("      requires NodePort/public IP or port forwarding.")
            print(f"{'='*60}")
            print("Press Ctrl+C to stop the server\n")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nServer stopped.")
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"Error starting server: {e}\n")
        sys.exit(1)


if __name__ == '__main__':
    run_server()
