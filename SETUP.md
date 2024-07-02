# Setup

Below is a quick setup guide to running the messenger-bot.

## Install the dependencies

There are two paths to installing the dependencies for development.

### Using `docker-compose`

It is **recommended** to use Docker Compose to run the bot while
developing, as all necessary dependencies are handled for you. After
installation and ensuring the `docker-compose` command works, you need to:

1. Create a data directory and config file by following the
   [docker setup instructions](docker#setup).

2. Create a docker volume pointing to that directory:

   ```
   docker volume create \
     --opt type=none \
     --opt o=bind \
     --opt device="/path/to/data/dir" messenger_bot_data_volume
   ```

Run `docker/start-dev.sh` to start the bot.

Additionally, you can directly link the data using the following:

```bash
cp sample.config.yaml config.yaml
# Edit config.yaml, see the file for details
mkdir data
docker run -v ${PWD}/config.docker.yaml:/config/config.yaml:ro \
    -v ${PWD}/data:/data -p 50051:50051 --name messenger_bot murlock1000/messenger_bot
```

**Note:** If you are trying to connect to a Synapse instance running on the
host, you need to allow the IP address of the docker container to connect. This
is controlled by `bind_addresses` in the `listeners` section of Synapse's
config. If present, either add the docker internal IP address to the list, or
remove the option altogether to allow all addresses.

### Running natively

If you would rather not or are unable to run docker, the following will
instruct you on how to install the dependencies natively:

#### Install libolm

You can install [libolm](https://gitlab.matrix.org/matrix-org/olm) from source,
or alternatively, check your system's package manager. Version `3.0.0` or
greater is required and can be installed using:

```
sudo apt install libolm-dev
```

#### Python dev dependencies

```
sudo apt install python3-dev build-essential
```

**Postgres development headers**

By default, the bot uses Postgres as its storage backend. you'll need to install postgres development headers:

Debian/Ubuntu:
```
sudo apt install libpq-dev libpq5
```

Arch:
```
sudo pacman -S postgresql-libs
```

#### Install Python dependencies

We will be using [Poetry](https://python-poetry.org/) to manage our project dependencies.

- Create a Python 3 virtual environment:
    ```
    pip install virtualenv
    virtualenv -p python3 env
    source ./env/bin/activate
    ```
- Install poetry and dependencies:
   ```
   pip install poetry
   poetry install
   ```

## Configuration

Copy the sample configuration file to a new `config.yaml` file.

```
cp sample.config.yaml config.yaml
```

Edit the config file. The `matrix` section must be modified at least.

## Setup SSL authentication files for API endpoint

Create locally signed certificate:
openssl req -newkey rsa:2048 -new -nodes -x509 -days 3650 -keyout ./data/server.key -out ./data/server.crt

cat server.crt server.key > ./data/server.pem

#### (Optional) Set up a Postgres database

Create a postgres user and database for messenger-bot:

```
sudo -u postgresql psql createuser messenger-bot -W  # prompts for a password
sudo -u postgresql psql createdb -O messenger-bot messenger-bot
```

Edit the `storage.database` config option, replacing the `sqlite://...` string with `postgres://...`. The syntax is:

```
database: "postgres://username:password@localhost/dbname?sslmode=disable"
```

See also the comments in `sample.config.yaml`.

## Running

### Docker

Refer to the docker [run instructions](docker/README.md#running).

### Native installation

Make sure to source your python environment if you haven't already:

```
source env/bin/activate
```

Then simply run the bot with:

```
poetry run python3 main.py
```

By default, the bot will run with the config file at `./config.yaml`. However, an
alternative relative or absolute filepath can be specified after the command:

```
poetry run python3 main.py other-config.yaml
```

## Testing the bot works

Invite the bot to the management room and it should accept the invite and join.

API commands:

* Send a text message to a specific recipient:
```
curl -k -X POST -H "Content-Type: text/plain" -H 'Send-To: @recipient:example.com' -H "Api-Key-Here: Supersecretkey123" --data "Test message" https://127.0.0.1
```

* Send a file to a specific recipient:
```
curl -k -X POST -H "Content-Type: image/png" -H 'Send-To: @recipient:example.com' "Api-Key-Here: Supersecretkey123" -H "File-Name: yourFile.png" --data-binary @./yourFile.png https://127.0.0.1
```

* Send a text message to the management channel - omit the `Send-To` header.

## Changing bot user Message throttling settings
In order to allow the bot to write messages quickly without the synapse server throttling the messages,
we must overwrite the user message throttling settings.
We will be using the synapse Admin API to make a POST request to the server - 
[Documentation of synapse admin api](https://matrix-org.github.io/synapse/latest/usage/administration/admin_api/).

### Fetching the admin api key 
* Create a matrix user with admin privileges
* Log in with the user
* Go to 'All settings' -> 'Help & About' -> 'Advanced' -> 'Access Token' (at the bottom)
* Copy the Access Token.
This token is only valid for the duration you are logged in with the user!
 
### Make the API call 
The call for overwriting the @test:synapse.local user throttle settings is:

```
curl --header "Authorization: Bearer ENTERADMINAPIKEYHERE" -H "Content-Type: application/json" --request POST -k http://localhost:8008/_synapse/admin/v1/users/@test:synapse.local/override_ratelimit
```

It should return result of `{"messages_per_second":0, "burst_count":0}`

## Going forwards

Congratulations! Your bot is up and running. Now you can modify the code,
re-run the bot and see how it behaves. Have fun!

## Troubleshooting

If you had any difficulties with this setup process, please [file an
issue](https://github.com/murlock1000/MatrixNotificationBot/issues).
