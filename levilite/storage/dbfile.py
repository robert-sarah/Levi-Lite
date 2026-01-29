from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from typing import Dict, Optional


MAGIC = b"LLT1"
HEADER_FMT = "<4sI"  # magic, json_header_len
HEADER_SIZE = struct.calcsize(HEADER_FMT)
HEADER_REGION_SIZE = 4096  # zone réservée pour éviter de déplacer les offsets


@dataclass
class _Header:
    kv_index: Dict[str, int]  # key -> offset in file


class DBFile:
    """
    Very small “DB container” for the MVP.

    Format (MVP):
    [HEADER_REGION(4096 bytes)][KV_BLOBS...]

    - HEADER_REGION contains:
      - HEADER: magic + JSON length
      - HEADER_JSON: {"kv_index": {"key": offset, ...}}
      - padding up to 4096 bytes
    - KV_BLOB: [key_len][key][val_len][val] (u32 LE)
    """

    def __init__(self, path: str, fp) -> None:
        self.path = path
        self._fp = fp
        self._header = _Header(kv_index={})

    @classmethod
    def open(cls, path: str) -> "DBFile":
        exists = os.path.exists(path)
        fp = open(path, "r+b" if exists else "w+b")
        db = cls(path, fp)
        if not exists or os.path.getsize(path) == 0:
            db._init_file()
        else:
            db._read_header()
        return db

    def close(self) -> None:
        self._fp.flush()
        self._fp.close()

    def _init_file(self) -> None:
        self._fp.seek(0)
        self._fp.write(b"\x00" * HEADER_REGION_SIZE)
        self._fp.flush()
        self._write_header()

    def _read_header(self) -> None:
        self._fp.seek(0)
        head = self._fp.read(HEADER_SIZE)
        magic, jlen = struct.unpack(HEADER_FMT, head)
        if magic != MAGIC:
            raise ValueError("invalid DB file (bad magic)")
        if jlen > (HEADER_REGION_SIZE - HEADER_SIZE):
            raise ValueError("invalid DB file (header too large)")
        j = self._fp.read(jlen)
        obj = json.loads(j.decode("utf-8")) if jlen else {"kv_index": {}}
        self._header = _Header(kv_index=obj.get("kv_index", {}))

    def _write_header(self) -> None:
        obj = {"kv_index": self._header.kv_index}
        j = json.dumps(obj).encode("utf-8")
        if len(j) > (HEADER_REGION_SIZE - HEADER_SIZE):
            raise ValueError("catalog header too large for MVP format")
        self._fp.seek(0)
        self._fp.write(struct.pack(HEADER_FMT, MAGIC, len(j)))
        self._fp.write(j)
        pad_len = HEADER_REGION_SIZE - (HEADER_SIZE + len(j))
        if pad_len > 0:
            self._fp.write(b"\x00" * pad_len)
        self._fp.flush()

    def kv_get(self, key: str) -> Optional[bytes]:
        off = self._header.kv_index.get(key)
        if off is None:
            return None
        self._fp.seek(off)
        key_len = struct.unpack("<I", self._fp.read(4))[0]
        _key = self._fp.read(key_len).decode("utf-8")
        if _key != key:
            raise ValueError("corrupt kv index")
        val_len = struct.unpack("<I", self._fp.read(4))[0]
        return self._fp.read(val_len)

    def kv_put(self, key: str, value: bytes) -> None:
        self._fp.seek(0, os.SEEK_END)
        off = self._fp.tell()
        if off < HEADER_REGION_SIZE:
            off = HEADER_REGION_SIZE
            self._fp.seek(off)
        k = key.encode("utf-8")
        self._fp.write(struct.pack("<I", len(k)))
        self._fp.write(k)
        self._fp.write(struct.pack("<I", len(value)))
        self._fp.write(value)
        self._fp.flush()
        self._header.kv_index[key] = off
        self._write_header()


