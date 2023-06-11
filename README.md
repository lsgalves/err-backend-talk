# err-backend-talk

This is a backend for [Nexcloud Talk](https://nextcloud.com/talk/) for [Errbot](https://errbot.io/).

## Installation

```sh
# Clone the repository in the errbot backend directory (BOT_EXTRA_BACKEND_DIR)
git clone https://github.com/lsgalves/err-backend-talk.git
cd err-backend-talk
pip install -r requirements.txt
```

Add to Errbot `config.py`:

```py
BACKEND = 'Talk'
```

## Authentication

### Add OAuth 2.0 Client

Access Nextcloud at `/settings/admin/security` and create an OAuth 2.0 Client with the following data:

- **Name:** Errbot
- **Redirect URL:** http://localhost:8081/

The redirect URL must point to the host running Errbot (_localhost_ in this example).
Save the Client ID and Secret Key.

### OAuth Authentication

1. Run the `oauth.py` script:

    ```sh
    python oauth.py
    ```

2. Provide the following data:
    - Nextcloud installation base URL
    - OAUTH KEY (Client ID)
    - OAUTH SECERT (Secret Key)

3. It will open a page in your browser to authorize the OAuth client with the logged in user.

4. After granting access to the OAuth client, you will be redirected to a screen with the data you must add in your **BOT_IDENTITY** section of your `config.py`:

    ```py
    BOT_IDENTITY = {
        'domain': 'http://localhost:8080',
        'oauth_token': 'YOUR-TOKEN',
        'oauth_key': 'YOUR-KEY',
        'oauth_secret': 'YOUR-SECRET',
    }
    ```

## Contributing

1. Fork it!
2. Create your feature branch: `git checkout -b my-new-feature`
3. Commit your changes: `git commit -am 'Add some feature'`
4. Push to the branch: `git push origin my-new-feature`
5. Submit a pull request :D
