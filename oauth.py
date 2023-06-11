#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, urlencode
from getpass import getpass
import threading
import webbrowser
import os
import signal

import requests


BASE_URL = None
CLIENT_ID = None
CLIENT_SECRET = None


class CallbackServer(BaseHTTPRequestHandler):
    def do_GET(self):
        global BASE_URL, CLIENT_ID, CLIENT_SECRET
        query = parse_qs(urlparse(self.path).query)
        print(f'Receive code {query["code"][0]} from NextCloud')
        payload = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'code': query['code'],
            'redirect_uri':'http://localhost:8081/',
            'grant_type': 'authorization_code',
        }

        response = requests.post(f'{BASE_URL}/apps/oauth2/api/v1/token', data=payload)
        content = response.json()
        token = content['refresh_token']
        print(f'''
You need to put this in your BOT_IDENTITY section of your config.py:

"domain": "{BASE_URL}",
"oauth_token": "{token}",
"oauth_key": "{CLIENT_ID}",
"oauth_secret": "{CLIENT_SECRET}",
        ''')

        threading.Timer(2.0, lambda:os.kill(os.getpid(), signal.SIGTERM)).start()

        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        response_bytes = bytes(f'<html><body>You need to put this in your BOT_IDENTITY section of your config.py:<br/><br/>DOMAIN={BASE_URL}<br/>OAUTH_TOKEN={token}<br/>OAUTH_KEY={CLIENT_ID}<br/>OAUTH_SECRET={CLIENT_SECRET}</body></html>', 'utf-8')
        self.wfile.write(response_bytes)


def run_server(bind_address: str, port: int):
    webserver = HTTPServer((bind_address, port), CallbackServer)

    try:
        webserver.serve_forever()
    except KeyboardInterrupt:
        pass

    webserver.server_close()


if __name__ == '__main__':
    # Put http://localhost:8080 when using with docker
    BASE_URL = input('Enter URL to Nextcloud:').strip()

    print(f'''
Welcome to the NextCloud OAuth 2 authenticator for err.

Go to {BASE_URL}/settings/admin/security.
For `Name` any name, example: errbot
For `Redirect URL` copy paste: http://localhost:8081/
The site will give you back the necessary information.
    ''')

    CLIENT_ID = input('Enter the OAUTH KEY:').strip()
    CLIENT_SECRET = getpass('Enter the OAUTH SECRET:').strip()

    init_payload = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': 'http://localhost:8081/'
    }

    url = f'{BASE_URL}/apps/oauth2/authorize?{urlencode(init_payload)}'
    print(f'Now point your browser to:\n{url}\nto authorize Errbot to use NextCloud. I\'ll try to spawn your browser locally if possible.')
    webbrowser.open_new_tab(url)

    run_server('localhost', 8081)
