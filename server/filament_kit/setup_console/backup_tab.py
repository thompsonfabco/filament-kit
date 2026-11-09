"""Backups on the Settings tab: list, download as a zip, back up now, keep-days, and restore from an uploaded zip.
A backup holds every secret of the kit, so each of these takes the setup code; a trusted computer's cookie stands in for
it, as for every other change (the user's choice, 2026-11-09).

    POST backups/list {code}                     the backups in /var/backups/filament-kit, newest first
    POST backups/download {code, name}           one of them, as the standard zip (a nightly tar.gz is turned into one)
    POST backups/keep {code, days}               how many days the nightly backup keeps (the helper's op backup_keep)
    POST restore/upload  (the zip as the body; X-Setup-Code)   kept in the state folder and checked: its summary
    POST restore/forget {code}                   drop an uploaded zip
Back up now is the job `backup`, the restore the job `restore` with {confirm: "restore"}.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

import anyio
from starlette.responses import FileResponse, StreamingResponse

from .. import backup, config

MAX_UPLOAD = 2 * 2**30


def _entry(e: backup.Entry) -> dict:
    return {"name": e.name, "download": e.download, "size": e.size, "kind": e.kind,
            "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(e.at))}


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    w = lambda fn: page.guard(fn, write=True)  # noqa: E731

    async def listing(request, body):
        def run() -> dict:
            return {"backups": [_entry(e) for e in backup.listing()], "keep_days": backup.keep_days(config.load()),
                    "folder": str(backup.backups_dir())}
        return await anyio.to_thread.run_sync(run)

    async def download(request, body):
        name = body.get("name")
        found = next((e for e in await anyio.to_thread.run_sync(backup.listing) if e.name == name), None)
        if found is None:
            raise Refused(404, "no such backup")
        page.audit(request, f"backup {found.name} downloaded")
        path = backup.backups_dir() / found.name
        headers = {"Content-Disposition": f'attachment; filename="{found.download}"'}
        if found.kind != "daily":
            return FileResponse(path, media_type="application/zip", headers=headers)

        def convert():
            tmp = tempfile.TemporaryFile()
            try:
                backup.from_daily(path, tmp)
            except Exception:
                tmp.close()
                raise
            tmp.seek(0)
            return tmp
        tmp = await anyio.to_thread.run_sync(convert)

        def chunks():
            try:
                while data := tmp.read(2**20):
                    yield data
            finally:
                tmp.close()
        return StreamingResponse(chunks(), media_type="application/zip", headers=headers)

    async def keep(request, body):
        r = await page._helper({"op": "backup_keep", "code": body["code"], "days": body.get("days")})
        page.audit(request, f"backups kept for {r['days']} days")
        return {"ok": True, "days": r["days"]}

    async def upload_zip(request, body):
        dest = backup.uploaded()
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_UPLOAD:
            raise Refused(413, "the backup is larger than the page takes; copy it to the server and run: "
                               "sudo filament-kit restore <file>")
        await anyio.to_thread.run_sync(lambda: shutil.rmtree(dest.parent, ignore_errors=True))
        await anyio.to_thread.run_sync(lambda: dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True))
        part = dest.with_name("backup.zip.part")
        n = 0
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                async for chunk in request.stream():
                    n += len(chunk)
                    if n > MAX_UPLOAD:
                        raise Refused(413, "the backup is larger than the page takes; copy it to the server and run: "
                                           "sudo filament-kit restore <file>")
                    await anyio.to_thread.run_sync(fh.write, chunk)
            os.replace(part, dest)

            def check() -> dict:
                m = backup.verify(dest)
                why = backup.refusal(m)
                if why:
                    raise Refused(409, why)
                return m.summary() | {"other_host": bool(m.host) and m.host != backup.host(),
                                      "replaces_data": (config.paths().etc / "config.json").exists()}
            summary = await anyio.to_thread.run_sync(check)
        except backup.BackupError as e:
            await anyio.to_thread.run_sync(lambda: shutil.rmtree(dest.parent, ignore_errors=True))
            raise Refused(400, f"{e}") from None
        except BaseException:
            await anyio.to_thread.run_sync(lambda: shutil.rmtree(dest.parent, ignore_errors=True))
            raise
        page.audit(request, "backup uploaded for a restore")
        return {"ok": True, **summary}

    async def forget(request, body):
        await anyio.to_thread.run_sync(lambda: shutil.rmtree(backup.uploaded().parent, ignore_errors=True))
        return {"ok": True}

    return [("/backups/list", w(listing), "POST"), ("/backups/download", w(download), "POST"),
            ("/backups/keep", page.guard(keep, write="helper"), "POST"),
            ("/restore/upload", page.guard(upload_zip, write=True, raw=True), "POST"),
            ("/restore/forget", w(forget), "POST")]
