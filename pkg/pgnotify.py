# Copyright (c) 2023 Shvora Nikita, Livitsky Andrey
# This app, Ratsky Walnut, is licensed under the GNU General Public License version 3.0 (GPL 3.0).
# All source code, design, and other intellectual property rights of Ratsky Walnut, including but not limited to text, graphics, logos, images, and software, are the property of the Ratsky community and are protected by international copyright laws.
# Permission is hereby granted, free of charge, to any person obtaining a copy of this app and associated documentation files (the "App"), to deal in the App without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the App, and to permit persons to whom the App is furnished to do so, subject to the following conditions:
#  1 The above copyright notice and this permission notice shall be included in all copies or substantial portions of the App.
#  2 Any distribution of the App or derivative works must include a copy of the GPL 3.0 license.
#  3 The App is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors or copyright holders be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the App or the use or other dealings in the App.
# For more information on the GPL 3.0 license, please visit https://www.gnu.org/licenses/gpl-3.0.en.html.


#Created by https://pypi.org/user/djrobstep/ however depends on psycopg-binary -______-, so need to change it a bit
from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import fcntl
import os
import select
import signal
import sys

import psycopg2
from logx import log
from six import string_types

log.set_null_handler()

def get_wakeup_fd():
    pipe_r, pipe_w = os.pipe()
    flags = fcntl.fcntl(pipe_w, fcntl.F_GETFL, 0)
    flags = flags | os.O_NONBLOCK
    flags = fcntl.fcntl(pipe_w, fcntl.F_SETFL, flags)

    signal.set_wakeup_fd(pipe_w)
    return pipe_r


def empty_signal_handler(signal, frame):
    pass


try:
    import sqlalchemy
except ImportError:  # pragma: no cover
    sqlalchemy = None

if sqlalchemy:
    from sqlalchemy.engine.base import Engine


def get_dbapi_connection(x):
    if isinstance(x, string_types):
        c = psycopg2.connect(x)
        x = c
    elif sqlalchemy and isinstance(x, Engine):
        sqla_connection = x.connect()
        sqla_connection.execution_options(isolation_level="AUTOCOMMIT")
        sqla_connection.detach()
        x = sqla_connection.connection.connection
    else:
        pass
    x.autocommit = True
    return x


def quote_table_name(name):
    return '"{}"'.format(name)


def start_listening(connection, channels):
    names = (quote_table_name(each) for each in channels)
    listens = "; ".join(["listen {}".format(n) for n in names])

    c = connection.cursor()
    c.execute(listens)
    c.close()


def log_notification(_n):
    log.debug("NOTIFY: {}, {}, {}".format(_n.pid, _n.channel, _n.payload))


def await_pg_notifications(
    dburi_or_sqlaengine_or_dbapiconnection,
    channels=None,
    timeout=5,
    yield_on_timeout=False,
    handle_signals=None,
    notifications_as_list=False,
):
    """Subscribe to PostgreSQL notifications, and handle them
    in infinite-loop style.

    On an actual message, returns the notification (with .pid,
    .channel, and .payload attributes).

    If you've enabled 'yield_on_timeout', yields None on timeout.

    If you've enabled 'handle_keyboardinterrupt', yields False on
    interrupt.
    """
    timeout_is_callable = callable(timeout)
    cc = get_dbapi_connection(dburi_or_sqlaengine_or_dbapiconnection)

    if channels:
        if isinstance(channels, string_types):
            channels = [channels]

        start_listening(cc, channels)

    signals_to_handle = handle_signals or []
    original_handlers = {}

    try:
        if signals_to_handle:
            for s in signals_to_handle:
                original_handlers[s] = signal.signal(s, empty_signal_handler)
            wakeup = get_wakeup_fd()
            listen_on = [cc, wakeup]
        else:
            listen_on = [cc]
            wakeup = None

        while True:
            try:
                if timeout_is_callable:
                    _timeout = timeout()
                    log.debug("dynamic timeout of {_timeout} seconds")
                else:
                    _timeout = timeout
                _timeout = max(0, _timeout)

                r, w, x = select.select(listen_on, [], [], _timeout)
                log.debug("select call awoken, returned: {}".format((r, w, x)))

                if (r, w, x) == ([], [], []):
                    log.debug("idle timeout on select call, carrying on...")
                    if yield_on_timeout:
                        yield None

                if wakeup is not None and wakeup in r:
                    signal_byte = os.read(wakeup, 1)
                    signal_int = int.from_bytes(signal_byte, sys.byteorder)
                    sig = signal.Signals(signal_int)
                    signal_name = signal.Signals(sig).name

                    log.info(f"woken from slumber by signal: {signal_name}")
                    yield signal_int

                if cc in r:
                    cc.poll()

                    nlist = []
                    while cc.notifies:
                        notify = cc.notifies.pop()
                        nlist.append(notify)

                    if notifications_as_list:
                        for n in nlist:
                            log_notification(n)
                        yield nlist
                    else:
                        for n in nlist:
                            log_notification(n)
                            yield n

            except select.error as e:
                e_num, e_message = e
                if e_num == errno.EINTR:
                    log.debug("EINTR happened during select")
                else:
                    raise
    finally:
        if signals_to_handle:
            for s in signals_to_handle:
                if s in original_handlers:
                    signal_name = signal.Signals(s).name
                    log.debug(f"restoring original handler for: {signal_name}")
                    signal.signal(s, original_handlers[s])
