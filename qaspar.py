#!/usr/bin/env python3

# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# ***** END GPL LICENCE BLOCK *****
#
# (c) 2016 Bastien Montagne

# <pep8 compliant>


"""
Qaspar stands for Qaspar Audio Stream Player And Recorder.

Usage
=====

This is a tool for playing and archiving an audio stream, using ffmpeg as backend currently.

Example
=======

   ./qaspar.py -u http://radioevasion.fr:8020/

You can use e.g. daemon tool [1] to daemonize it and automatically re-run it in case it terminates or crashes:

   daemon -n qaspar -r -A 1 -L 10 -M 100 -O "daemon.info" -- \
          /path/to/qaspar.py -u http://radioevasion.fr:8020/ -o /path/to/archived/files

[1] https://github.com/jwa/daemon
"""

from collections import namedtuple


# Sleep n seconds between every 'check' of background processes.
MAIN_LOOP_SLEEP = 1

# Seconds in a day
SECONDS_IN_DAY = 86400


# Simple storage for our processes...
ProcessHandler = namedtuple("ProcessHandler", (
    "proc", "name", "max_empty_loops",
))


def cleanup_storage(args):
    import time
    import os

    # Note that we add st_split_time to be absolutely sure we never ever delete currently recorded audio file...
    mtime_limit = time.time() - (SECONDS_IN_DAY * args.st_keep) + args.st_split_time

    for entry in os.scandir(args.st_path):
        if entry.is_file():
            if entry.stat().st_mtime < mtime_limit:
                try:
                    os.remove(entry.path)
                except Exception as e:
                    print(e)


def processes_manage(args, processes):
    from concurrent.futures import ThreadPoolExecutor
    import queue
    import time

    # Using threaded readers for subprocess pipes, simplest solution for now
    # (could also use something like asyncio, but that's much more complex).
    pipe_queues = [(queue.Queue(), queue.Queue()) for _ph in processes]
    pipe_reader_flags = [True]
    def queued_pipe_reader(fd, queue, flags):
        for line in iter(fd.readline, ''):
            queue.put(line)
            if not flags[0]:
                break

    empty_loops = [[0] for _ph in processes]

    with ThreadPoolExecutor(max_workers=len(processes) * 2) as pipe_reader_pool:
        for ph, pq in zip(processes, pipe_queues):
            pipe_reader_pool.submit(queued_pipe_reader, ph.proc.stdout, pq[0], pipe_reader_flags)
            pipe_reader_pool.submit(queued_pipe_reader, ph.proc.stderr, pq[1], pipe_reader_flags)

        # We roughly check archived files for deletion once for every two archived files written
        # (i.e. if we store 1h files, we check for their deletion ~ every 2h).
        st_cleanup_skiploop = (args.st_split_time / MAIN_LOOP_SLEEP) * 2
        st_cleanup_counter = st_cleanup_skiploop
        do_it = True
        while do_it:
            time.sleep(MAIN_LOOP_SLEEP)

            for ph, pq, ph_empty_loops in zip(processes, pipe_queues, empty_loops):
                lines = []
                lines.append("*** stdout ***\n")
                while not pq[0].empty():
                    lines.append(pq[0].get())
                lines.append("*** stderr ***\n")
                while not pq[1].empty():
                    lines.append(pq[1].get())

                if args.do_verbose:
                    print("%s:\n\t" % ph.name, "\t".join(lines), sep="")

                if len(lines) <= 2:
                    ph_empty_loops[0] += 1
                    if ph_empty_loops[0] > ph.max_empty_loops:
                        print("Process %s seems to be stalled, aborting..." % ph.name)
                        do_it = False
                else:
                    ph_empty_loops[0] = 0

                if ph.proc.poll() is not None:
                    print("Process %s seems to have failed (exit code %d), aborting..." % (ph.name, ph.proc.returncode))
                    do_it = False

            if st_cleanup_counter <= 0:
                if args.do_cleanup:
                    cleanup_storage(args)
                st_cleanup_counter = st_cleanup_skiploop
            else :
                st_cleanup_counter -= 1

        # Finalize (most of cleanup is done by with context managers).
        pipe_reader_flags[0] = False
        for ph in processes:
            ph.proc.kill()


##### Main #####

def argparse_create():
    import argparse
    global __doc__

    def positive_number(arg):
        value = float(arg)
        if value <= 0.0:
            raise argparse.ArgumentTypeError("%r is not a strictly positive number" % arg)
        return value

    # When --help or no args are given, print this help
    usage_text = __doc__

    epilog = ("This script is typically daemonized to run on a client, e.g. to broadcast a web radio on waves, and/or "
              "archive its content for a given lap of time...")

    parser = argparse.ArgumentParser(description=usage_text, epilog=epilog,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument(
        "-u", "--url", dest="url", metavar='STREAM_URL',
        help="Url of audio stream to play and store")
    parser.add_argument(
        "-e", "--executable", dest="executable", default="ffmpeg", metavar='FFMPEG_EXECUTABLE',
        help="Path to the ffmpeg executable (on *nix you can usually leave it to default)")

    parser.add_argument(
        "--no-play", dest="do_play", default=True, action='store_false', required=False,
        help=("Do not play audio stream"))
    parser.add_argument(
        "--play-sink", dest="pl_sink", default="pulse", metavar='FFMPEG_SINK',
        help=("Which device/audio system to use to play audio "
              "(default pulse one should be OK for any modern linux, must be valid ffmpeg 'format' audio output)"))

    parser.add_argument(
        "--no-store", dest="do_store", default=True, action='store_false', required=False,
        help=("Do not store audio stream"))
    parser.add_argument(
        "--store-split-time", dest="st_split_time", default=3600, metavar='SPLIT_TIME', type=positive_number,
        help=("Time (in seconds) each chunk of stored audio file (default is 1h)"))
    parser.add_argument(
        "-o", "--store-path", dest="st_path", default="./archived_files", metavar='PATH',
        help=("Directory where to store audio files "
              "(WARNING: should point to a directory containing ONLY audio files, unless you disable auto-deletion)"))
    parser.add_argument(
        "--store-filename", dest="st_filename", metavar='FILENAME', default="archive-%Y_%m_%d-%H_%M_%S.mp3",
        help=("Filename template used for archived audio files (must contain at least one strftime formating sequence -"
              " you shall also change it if your web streaming is not using mp3 codec...)"))
    parser.add_argument(
        "--no-auto-delete", dest="do_cleanup", default=True, action='store_false', required=False,
        help=("Do not delete archived audio files after '--store-keep' number of days"))
    parser.add_argument(
        "--store-keep", dest="st_keep", default=30, metavar='KEEP', type=positive_number,
        help=("Amount of days to keep archived audio files, when auto-deletion is enabled (default is 30 days)"))

    parser.add_argument(
        "-v", "--verbose", dest="do_verbose", default=False, action='store_true', required=False,
        help=("Print everything from ffmpeg processes"))

    return parser


def main():
    from contextlib import ExitStack
    import os
    import subprocess

    # Parse Args
    args = argparse_create().parse_args()

    if not (args.do_play or args.do_store):
        print("Called without anything to do!")
        return

    if args.do_store and not os.path.exists(args.st_path):
        print("Creating missing archive directory '%s'..." % args.st_path)
        os.makedirs(args.st_path)

    # Single process:
    # ffmpeg -i http://radioevasion.fr:8020/ -f pulse ffmpeg_audio_player_stream -c:a copy \
    # -f tee -map 0:a "[onfail=ignore:f=segment:segment_time=3600:segment_atclocktime=1:strftime=1]\
    # archive-%Y_%m_%d-%H_%M_%S.mp3"

    # Two separate processes (chosen solution for now):
    # ffmpeg -i http://radioevasion.fr:8020/ -f pulse ffmpeg_audio_player_stream
    #
    # ffmpeg -i http://radioevasion.fr:8020/ -f segment -segment_time 3600 -segment_atclocktime 1 -strftime 1 \
    # archive-%Y_%m_%d-%H_%M_%S.mp3"

    proc_params = {"stdin":None, "stdout":subprocess.PIPE, "stderr":subprocess.PIPE, "universal_newlines":True}
    pl_command = (args.executable, "-i", args.url, "-f", args.pl_sink, "qaspar_ffmpeg_player")
    st_command = (args.executable, "-i", args.url, "-c:a", "copy", "-f", "segment",
                  "-segment_time", str(int(args.st_split_time)), "-segment_atclocktime", "1", "-strftime", "1",
                  os.path.join(args.st_path, args.st_filename))

    commands = []
    if args.do_play:
        commands.append(ProcessHandler(pl_command, "Player", 2))
    if args.do_store:
        # About large 'delay' before declaring Store process as stalled:
        # Seems like shoutcast generates 'erratic' streaming sometimes (e.g. when relaying stream from another source?),
        # which leads store (which downloads and saves whole available data immediately) to sometimes waits several
        # seconds before getting next data, so we need not to abort immediately in case this process remains silent
        # for a few seconds...
        commands.append(ProcessHandler(st_command, "Store", 20))

    processes = []
    with ExitStack() as stack:
        for cmmd, name, max_empty_loops in commands:
            proc = stack.enter_context(subprocess.Popen(cmmd, **proc_params))
            processes.append(ProcessHandler(proc, name, max_empty_loops))
        processes_manage(args, processes)

    print("Finished!")


if __name__ == "__main__":
    main()
