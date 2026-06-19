"""Receives dropped paths via HTTP POST and hands off to the router."""

import logging
import os

from fastapi import BackgroundTasks, HTTPException
from pydantic import BaseModel

from sortilege.librarian import router

logger = logging.getLogger(__name__)


class IntakeRequest(BaseModel):
    paths: list[str]


def handle_intake(req: IntakeRequest, background_tasks: BackgroundTasks) -> dict:
    valid: list[str] = []
    rejected: list[str] = []

    for path in req.paths:
        try:
            if os.path.exists(path) and os.access(path, os.R_OK):
                valid.append(path)
            else:
                rejected.append(path)
        except OSError:
            rejected.append(path)

    if rejected:
        logger.warning("Intake rejected %d unreadable paths", len(rejected))

    if not valid:
        raise HTTPException(status_code=422, detail="No readable paths provided")

    background_tasks.add_task(router.process_batch, valid)
    return {"accepted": len(valid), "rejected": len(rejected)}
