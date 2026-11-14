"""CPU Slurm startup preflight: bind both installed communication mechanisms."""
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from isolate_runtime import ipc_path_lengths


def main():
    from multiprocessing.connection import Listener
    import zmq
    job = os.environ['SLURM_JOB_ID']
    tmp = Path(os.environ['TMPDIR']) / f'{job}_0'
    rpc = Path(os.environ['VLLM_RPC_BASE_PATH'])
    expected = ipc_path_lengths(tmp.parent, rpc, job)
    tmp.mkdir(parents=True, exist_ok=True)
    rpc.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(tmp)
    with Listener(family='AF_UNIX') as listener:
        listener_bytes = len(os.fsencode(listener.address))
    context = zmq.Context()
    socket = context.socket(zmq.PAIR)
    ipc = str(rpc / str(uuid4()))
    try:
        socket.bind('ipc://' + ipc)
    finally:
        socket.close(linger=0)
        context.term()
    assert listener_bytes == expected['multiprocessing_listener_bytes']
    assert len(os.fsencode(ipc)) == expected['vllm_uuid_bytes']
    print(json.dumps({'ipc_bind_preflight': 'passed', **expected}), flush=True)


if __name__ == '__main__':
    main()
