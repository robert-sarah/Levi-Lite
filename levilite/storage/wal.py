from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from levilite.storage.dbfile import DBFile


WAL_MAGIC = b"WAL1"
REC_FMT = "<4sI"  # magic, payload_len
REC_HDR = struct.calcsize(REC_FMT)


@dataclass(frozen=True)
class WalRecord:
    key: str
    value: bytes


class Wal:
    """
    Write-Ahead Log (WAL) MVP:
    - Append des PUT (key/value) avant application dans DBFile.
    - Au démarrage, rejoue dans DBFile puis tronque le WAL.

    Encodage:
    [magic][payload_len][payload]
    payload = [key_len][key][val_len][val]
    """

    def __init__(self, path: str, fp) -> None:
        self.path = path
        self._fp = fp

    @classmethod
    def open(cls, path: str) -> "Wal":
        fp = open(path, "a+b")
        return cls(path, fp)

    def close(self) -> None:
        self._fp.flush()
        self._fp.close()

    def append_put(self, key: str, value: bytes) -> None:
        k = key.encode("utf-8")
        payload = struct.pack("<I", len(k)) + k + struct.pack("<I", len(value)) + value
        rec = struct.pack(REC_FMT, WAL_MAGIC, len(payload)) + payload
        self._fp.seek(0, os.SEEK_END)
        self._fp.write(rec)
        self._fp.flush()

    def _iter_records(self) -> list[WalRecord]:
        self._fp.seek(0)
        out: list[WalRecord] = []
        while True:
            hdr = self._fp.read(REC_HDR)
            if not hdr:
                break
            magic, plen = struct.unpack(REC_FMT, hdr)
            if magic != WAL_MAGIC:
                raise ValueError("corrupt WAL")
            payload = self._fp.read(plen)
            key_len = struct.unpack("<I", payload[:4])[0]
            p = 4
            key = payload[p : p + key_len].decode("utf-8")
            p += key_len
            val_len = struct.unpack("<I", payload[p : p + 4])[0]
            p += 4
            val = payload[p : p + val_len]
            out.append(WalRecord(key=key, value=val))
        return out

    def recover_into(self, db: DBFile) -> None:
        records = self._iter_records()
        if not records:
            return
        for r in records:
            db.kv_put(r.key, r.value)
        self._truncate()

    def _truncate(self) -> None:
        self._fp.close()
        open(self.path, "wb").close()
        self._fp = open(self.path, "a+b")


