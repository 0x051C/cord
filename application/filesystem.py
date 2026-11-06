"""
File access used by the pipeline: a local directory tree or an SMB share.

On Windows a UNC path (``\\\\server\\share\\...``) also works with the local
implementation, which is what the old "fall back to ``os``" behaviour relied on.
"""

import ntpath
import os
import shutil
from typing import IO, Protocol

from application.logging_setup import validation_logger


class FileSystem(Protocol):
    def join(self, *parts: str) -> str: ...
    def listdir(self, path: str) -> list[str]: ...
    def exists(self, path: str) -> bool: ...
    def makedirs(self, path: str) -> None: ...
    def rename(self, src: str, dst: str) -> None: ...
    def open(self, path: str, mode: str = "r", encoding: str | None = None, newline: str | None = None) -> IO: ...
    def upload(self, local_path: str, path: str) -> None: ...


class LocalFileSystem:
    def join(self, *parts: str) -> str:
        return os.path.join(*parts)

    def listdir(self, path: str) -> list[str]:
        return sorted(os.listdir(path))

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def makedirs(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)

    def rename(self, src: str, dst: str) -> None:
        os.replace(src, dst)

    def open(self, path, mode="r", encoding=None, newline=None):
        return open(path, mode=mode, encoding=encoding, newline=newline)

    def upload(self, local_path: str, path: str) -> None:
        shutil.copyfile(local_path, path)


class SMBFileSystem:
    def __init__(self, **client_config):
        import smbclient
        import smbclient.path
        import smbclient.shutil

        self._smb = smbclient
        smbclient.ClientConfig(**client_config)

    def join(self, *parts: str) -> str:
        return ntpath.join(*parts)

    def listdir(self, path: str) -> list[str]:
        return sorted(self._smb.listdir(path))

    def exists(self, path: str) -> bool:
        return self._smb.path.exists(path)

    def makedirs(self, path: str) -> None:
        self._smb.makedirs(path, exist_ok=True)

    def rename(self, src: str, dst: str) -> None:
        self._smb.replace(src, dst)

    def open(self, path, mode="r", encoding=None, newline=None):
        return self._smb.open_file(path, mode=mode, encoding=encoding, newline=newline)

    def upload(self, local_path: str, path: str) -> None:
        self._smb.shutil.copyfile(local_path, path)


def build_filesystem(settings) -> FileSystem:
    kind = str(settings.get("filesystem", "smb")).lower()
    if kind == "local":
        return LocalFileSystem()
    if kind != "smb":
        raise ValueError(f"Unknown filesystem setting: {kind!r} (expected 'smb' or 'local')")
    try:
        return SMBFileSystem(
            encrypt=True,
            auth_protocol=settings.get("smb_auth_protocol", "kerberos"),
            domain_controller=settings.get("smb_domain_controller"),
        )
    except Exception as e:  # e.g. kerberos is not available on this machine
        validation_logger.warning(f"SMB client could not be configured -> falling back to OS file access: {e}")
        return LocalFileSystem()
