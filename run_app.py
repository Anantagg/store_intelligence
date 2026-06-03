#!/usr/bin/env python3
"""Uvicorn launcher for Store Intelligence API v2."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
