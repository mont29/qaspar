Qaspar stands for Qaspar Audio Stream Player And Recorder.

Usage
=====

This is a tool for playing and archiving an audio stream, using ffmpeg as backend currently.

This script is typically daemonized to run on a client, e.g. to broadcast a web radio on waves, and/or archive its content for a given lap of time...

Example
=======

```
./qaspar.py -u http://radioevasion.fr:8020/
```

You can use e.g. daemon tool [1] to daemonize it and automatically re-run it in case it terminates or crashes:

```
daemon -n qaspar -r -A 1 -L 10 -M 500 -O "daemon.info" -- /path/to/qaspar.py -u http://radioevasion.fr:8020/ -o /path/to/archived/files
```

[1] https://github.com/jwa/daemon
