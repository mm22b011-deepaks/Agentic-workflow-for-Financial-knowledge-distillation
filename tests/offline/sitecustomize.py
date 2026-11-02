"""Optional process-wide network refusal for offline acceptance, including subprocesses."""

import socket


def refuse(*args: object, **kwargs: object) -> None:
    raise RuntimeError('network disabled for offline acceptance')


socket.socket.connect = refuse
socket.socket.connect_ex = refuse
socket.create_connection = refuse
