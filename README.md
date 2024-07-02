# Messenger-Bot [![Built with matrix-nio](https://img.shields.io/badge/built%20with-matrix--nio-brightgreen)](https://github.com/poljar/matrix-nio) <a href="https://matrix.to/#/#nio-template:matrix.org"><img src="https://img.shields.io/matrix/nio-template:matrix.org?color=blue&label=Join%20the%20Matrix%20Room&server_fqdn=matrix-client.matrix.org" /></a>

Notification API for Matrix Synapse Element implemented through a matrix bot. Supports text and media messages.

API commands:

* Send a text message to a specific recipient:
```
curl -k -X POST -H "Content-Type: text/plain" -H 'Send-To: @recipient:example.com' -H "Api-Key-Here: Supersecretkey123" --data "Test message" https://127.0.0.1
```

* Send a file to a specific recipient:
```
curl -k -X POST -H "Content-Type: image/png" -H 'Send-To: @recipient:example.com' "Api-Key-Here: Supersecretkey123" -H "File-Name: yourFile.png" --data-binary @./yourFile.png https://127.0.0.1
```

* Send a message to the management channel - omit the `Send-To` header.

## Getting started

See [SETUP.md](SETUP.md) for how to setup and run the project.

## License

Apache2